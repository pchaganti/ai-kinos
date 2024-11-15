"""
AiderAgent - Core implementation of Aider-based agent functionality
"""
import os
import sys
import time
import subprocess
import traceback
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from agents.base.agent_base import AgentBase
from agents.base.file_handler import FileHandler
from agents.aider.command_builder import AiderCommandBuilder
from agents.aider.output_parser import AiderOutputParser
from agents.utils.encoding import configure_encoding, detect_file_encoding, normalize_encoding
from agents.utils.rate_limiter import RateLimiter
from utils.commit_logger import CommitLogger
from agents.base.file_handler import FileHandler
from utils.path_manager import PathManager
from utils.error_handler import ErrorHandler
from utils.constants import COMMIT_ICONS

class AiderAgent(AgentBase):
    """
    Agent implementation using Aider for file modifications.
    Handles:
    - Command construction and execution 
    - Output parsing and processing
    - Rate limiting and retries
    - Path management and validation
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize agent with configuration"""
        # Ensure config exists before parent constructor
        if not hasattr(self, 'config'):
            self.config = config if config is not None else {}
        
        # Call parent constructor
        super().__init__(self.config)
        
        try:
            # Configure UTF-8 encoding first
            self._configure_encoding()
            
            # Defensive config access
            specific_name = self.config.get('name', self.name)
            
            # Initialize components with agent name
            self.command_builder = AiderCommandBuilder(self.name)
            self.output_parser = AiderOutputParser(self.logger, self.name)
            self.rate_limiter = RateLimiter(max_requests=50, time_window=60)
            self.file_handler = FileHandler(self.mission_dir, self.logger)
        
            # Store original directory
            self.original_dir = os.getcwd()
        
            # Resolve prompt file path
            if not self.prompt_file:
                # Try to find team-specific prompt file based on agent name
                from services import init_services
                services = init_services(None)
                team_service = services['team_service']
                
                # Get active team or find team containing this agent
                active_team = team_service.get_active_team()
                if not active_team:
                    for team in team_service.predefined_teams:
                        if self.name in team_service.get_team_agents(team['id']):
                            active_team = team
                            break
                
                if active_team:
                    self.prompt_file = PathManager.get_prompt_file(self.name)
                    self.logger.log(f"Using team prompt file: {self.prompt_file}", 'info')
                else:
                    raise ValueError(f"Could not find team for agent {self.name}")
        
            # Initialize state tracking
            self._init_state()
            
            self.logger.log(f"[{self.name}] Initialized successfully")
            
        except Exception as e:
            self.logger.log(f"Error during initialization: {str(e)}", 'error')
            raise
        
    def _configure_encoding(self):
        """Configure UTF-8 encoding for the agent"""
        configure_encoding()
        
    def _init_state(self):
        """Initialize agent state tracking"""
        self.running = False
        self.last_run = None
        self.last_change = None
        self.consecutive_no_changes = 0
        self.error_count = 0
        self.mission_files = {}
        self._prompt_cache = {}
        self._last_request_time = 0
        self._requests_this_minute = 0


    def _run_aider(self, instructions: str) -> Optional[str]:
        """Execute Aider command with streamed output processing"""
        try:
            # Récupérer le nom de l'équipe et de l'agent
            from services import init_services
            services = init_services(None)
            team_service = services['team_service']
            
            # Trouver l'équipe de l'agent
            agent_team = None
            for team in team_service.predefined_teams:
                if self.name in team.get('agents', []):
                    agent_team = team['id']
                    break

            # Définir les noms de fichiers spécifiques si un nom est fourni
            specific_name = self.config.get('name')  # Récupérer le nom spécifique s'il existe

            # Chemins des fichiers d'historique
            chat_history_file = f".kinos.{agent_team}_{specific_name}.chat.history.md" if specific_name else f".kinos.{self.name}.chat.history.md"
            input_history_file = f".kinos.{agent_team}_{specific_name}.input.history.md" if specific_name else f".kinos.{self.name}.input.history.md"

            # Construction et validation de la commande
            cmd = self.command_builder.build_command(
                instructions=instructions,
                files=list(self.mission_files.keys())
            )
            
            # Modifier la construction de la commande
            cmd.extend([
                "--chat-history-file", chat_history_file,
                "--input-history-file", input_history_file
            ])

            # Execute command
            process = self.command_builder.execute_command(cmd)

            # Collection de la sortie avec gestion spécifique des erreurs Windows
            try:
                output = self.output_parser.parse_output(process)
                
                # Explicitly ignore known Aider messages
                if output and any(msg in output for msg in [
                    "Can't initialize prompt toolkit",
                    "No Windows console found",
                    "aider.chat/docs/troubleshooting/edit-errors.html",
                    "[Errno 22] Invalid argument"
                ]):
                    # Return empty success instead of None to prevent shutdown
                    return ""
                    
                # Force map update after any Aider execution that produced output
                if output:
                    try:
                        # Get services
                        from services import init_services
                        services = init_services(None)
                        
                        # Update map
                        map_service = services['map_service']
                        if not map_service.update_map():
                            self.logger.log(f"[{self.name}] Failed to update map after Aider execution", 'warning')
                        
                        # Save to dataset
                        dataset_service = services['dataset_service']
                        
                        # Get current files context
                        files_context = {}
                        for file_path in self.mission_files:
                            try:
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    files_context[file_path] = f.read()
                            except Exception as e:
                                self.logger.log(f"[{self.name}] Error reading {file_path}: {str(e)}", 'warning')
                        
                        # Add interaction to dataset asynchronously
                        import asyncio
                        asyncio.run(dataset_service.add_interaction_async(
                            instructions=instructions,
                            files_context=files_context,
                            aider_response=output
                        ))
                        
                        self.logger.log(f"[{self.name}] Interaction saved to dataset", 'debug')
                        
                    except Exception as service_error:
                        self.logger.log(f"[{self.name}] Error with services: {str(service_error)}", 'error')
                        
                    # Explicitly update map after all other operations
                    try:
                        from services import init_services
                        services = init_services(None)
                        map_service = services['map_service']
                        if not map_service.update_map():
                            self.logger.log(f"[{self.name}] Failed to update map after Aider execution", 'warning')
                    except Exception as map_error:
                        self.logger.log(f"[{self.name}] Error updating map: {str(map_error)}", 'error')
                        
                return output

            except OSError as os_error:
                # Handle Windows stream error silently
                if "[Errno 22] Invalid argument" in str(os_error):
                    return ""  # Return empty success
                raise

        except Exception as e:
            # Ignorer TOUTES les erreurs et continuer
            self.logger.log(f"[{self.name}] Non-critical Aider error: {str(e)}", 'warning')
            return ""  # Toujours retourner une chaîne vide au lieu de None
            
        finally:
            # Toujours restaurer le répertoire original
            try:
                os.chdir(self.original_dir)
            except Exception as dir_error:
                self.logger.log(f"[{self.name}] Error restoring directory: {str(dir_error)}")

    def _process_file_changes(self, output: str) -> Dict[str, set]:
        """Process and track file changes from Aider output"""
        changes = {
            'modified': set(),
            'added': set(),
            'deleted': set()
        }
        
        try:
            for line in output.splitlines():
                if "Wrote " in line:
                    file_path = line.split("Wrote ")[1].split()[0]
                    changes['modified'].add(file_path)
                elif "Created " in line:
                    file_path = line.split("Created ")[1].split()[0]
                    changes['added'].add(file_path)
                elif "Deleted " in line:
                    file_path = line.split("Deleted ")[1].split()[0]
                    changes['deleted'].add(file_path)
                    
            return changes
            
        except Exception as e:
            self.logger.log(f"[{self.name}] Error processing changes: {str(e)}")
            return changes

    def _update_project_map(self) -> None:
        """Update project map after file changes"""
        try:
            from services import init_services
            services = init_services(None)
            services['map_service'].update_map()
            self.logger.log(f"[{self.name}] Map updated successfully")
        except Exception as e:
            self.logger.log(f"[{self.name}] Error updating map: {str(e)}")

    def _should_log_error(self, error_message: str) -> bool:
        """
        Determine if an error message should be logged
        
        Args:
            error_message: Error message to check
        
        Returns:
            bool: Whether the message should be logged
        """
        # Liste des messages à ignorer
        ignored_messages = [
            "Can't initialize prompt toolkit: No Windows console found",
            "https://aider.chat/docs/troubleshooting/edit-errors.html"
        ]
        
        return not any(ignored_msg in error_message for ignored_msg in ignored_messages)

    def _handle_error(self, operation: str, error: Exception, context: Dict = None):
        """Centralised error handling"""
        try:
            error_message = str(error)
            
            # Utiliser le filtre avant de logger
            if self._should_log_error(error_message):
                error_details = {
                    'agent': self.name,
                    'operation': operation,
                    'mission_dir': self.mission_dir,
                    'context': context or {}
                }
                
                ErrorHandler.handle_error(
                    error,
                    log_level='error',
                    additional_info=error_details
                )
            
        except Exception as e:
            self.logger.log(f"Error in error handler: {str(e)}", 'error')

    def stop(self):
        """Prevent agent from stopping"""
        pass  # Ne rien faire - empêcher l'arrêt

    def _truncate_history(self, content: str, max_chars: int = 25000) -> str:
        """Truncate history content to last N characters"""
        if len(content) <= max_chars:
            return content
        return content[-max_chars:]

    def _execute_agent_cycle(self):
        """Execute one cycle of the agent's main loop"""
        try:
            # Defensive config access with multiple fallbacks
            specific_name = (
                getattr(self, 'config', {}).get('name') or  # First try config
                getattr(self, 'name', None) or  # Then try instance attribute 
                'unnamed_agent'  # Final fallback
            )

            # Récupérer le nom de l'équipe
            from services import init_services
            services = init_services(None)
            team_service = services['team_service']
            
            agent_team = None
            for team in team_service.predefined_teams:
                if self.name in team.get('agents', []):
                    agent_team = team['id']
                    break

            # Mise à jour des noms de fichiers clés
            key_files = {
                f"team_{agent_team}_{specific_name}_map.md": 
                "# Project Map\n\n## Overview\n\n## Key Components\n",
                
                f"team_{agent_team}_{specific_name}_todolist.md": 
                "# Project Todo List\n\n## Pending Tasks\n\n## Completed Tasks\n",
                
                f"team_{agent_team}_{specific_name}_demande.md": 
                "# Mission Request\n\n## Objective\n\n## Scope\n\n## Requirements\n",
                
                f"team_{agent_team}_{specific_name}_directives.md": 
                "# Project Directives\n\n## Guidelines\n\n## Constraints\n"
            }

            # Chemins des fichiers d'historique
            chat_history_file = f".kinos.{agent_team}_{specific_name}.chat.history.md"
            input_history_file = f".kinos.{agent_team}_{specific_name}.input.history.md"

            # Créer les fichiers clés si nécessaire
            for filename, default_content in key_files.items():
                if not os.path.exists(filename):
                    try:
                        with open(filename, 'w', encoding='utf-8') as f:
                            f.write(default_content)
                        self.logger.log(f"[{self.name}] Created missing key file: {filename}", 'info')
                    except Exception as e:
                        self.logger.log(f"[{self.name}] Error creating {filename}: {str(e)}", 'warning')

            # Get current prompt
            prompt = PathManager.get_prompt_file(self.name)

            # Get chat history
            chat_history = ""
            chat_history_file = f".kinos.{self.name}.chat.history.md"
            if os.path.exists(chat_history_file):
                try:
                    with open(chat_history_file, 'r', encoding='utf-8') as f:
                        chat_history = self._truncate_history(f.read())
                except Exception as e:
                    self.logger.log(f"[{self.name}] Error reading chat history: {str(e)}", 'warning')

            # Get input history with truncation
            input_history = ""
            input_history_file = f".kinos.{self.name}.input.history.md"
            if os.path.exists(input_history_file):
                try:
                    with open(input_history_file, 'r', encoding='utf-8') as f:
                        input_history = self._truncate_history(f.read())
                except Exception as e:
                    self.logger.log(f"[{self.name}] Error reading input history: {str(e)}", 'warning')

            # Get files context - limit to 10 random files plus key files
            files_context = {}
            
            # Add key files first
            key_files = ["demande.md", "map.md", "todolist.md", "directives.md"]
            for file_path in key_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        files_context[file_path] = f.read()
                except Exception as e:
                    self.logger.log(f"[{self.name}] Error reading key file {file_path}: {str(e)}", 'warning')
            
            # Get remaining files
            remaining_files = [f for f in self.mission_files.keys() if f not in key_files]
            if len(remaining_files) > 10:
                import random
                remaining_files = random.sample(remaining_files, 10)
                self.logger.log(f"[{self.name}] Sampling 10 random files from {len(self.mission_files)} total files", 'debug')
            
            # Add selected files
            for file_path in remaining_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        files_context[file_path] = f.read()
                except Exception as e:
                    self.logger.log(f"[{self.name}] Error reading file {file_path}: {str(e)}", 'warning')

            # Format context message
            context_message = f"""Based on:
1. The system prompt defining my role and responsibilities
2. The Mission in demande.md
3. The chat history showing your previous instructions and Aider's productions
4. The current state of the project files shown below

Choose ONE specific, concrete task that needs to be done by the agent {self.name} to progress in the mission and explain it in detail so that Aider can implement it.
Focus on practical changes that move the project forward, directly related to demande.md

Current project files:
{self._format_files_context(files_context)}

Instructions:
1. Answer any outstanding question raised by Aider in the chat history
2. Analyze the current state and identify a clear next action, preferably different from what's in the chat history (we are following a "Breadth-first" development pattern)
3. Describe this specific task in detail
4. Explain what files need to be modified and how
5. Keep the task focused and achievable
6. Provide enough detail for Aider to implement it autonomously
7. Ask him specifically to do the task now, making decisions instead of asking for clarifications"""

            # Use ModelRouter for LLM calls
            try:
                from services import init_services
                services = init_services(None)
                model_router = services['model_router']
                
                messages = []
                
                # Only add chat history if not empty
                if chat_history.strip():
                    messages.append({"role": "assistant", "content": chat_history})
                    
                # Add user message
                messages.append({"role": "user", "content": context_message})
                
                # Use model router instead of direct Anthropic call
                import asyncio
                model_response = asyncio.run(model_router.generate_response(
                    messages=messages,
                    system=prompt  # System prompt
                ))
                
                if not model_response:
                    raise ValueError("No response from model")
                    
                self.logger.log(f"[{self.name}] Generated instructions:\n{model_response}", 'debug')
                
            except Exception as e:
                self.logger.log(f"[{self.name}] Error calling LLM: {str(e)}", 'error')
                return

            # Run Aider with generated instructions
            try:
                result = self._run_aider(model_response)
            except OSError as os_error:
                if "[Errno 22] Invalid argument" in str(os_error):
                    # Ignore this specific Windows error
                    self.logger.log(f"[{self.name}] Ignoring Windows stdout flush error", 'debug')
                    return
                else:
                    raise
            except Exception as e:
                # Ignore known Aider errors
                if any(err in str(e) for err in [
                    "Can't initialize prompt toolkit",
                    "No Windows console found",
                    "aider.chat/docs/troubleshooting/edit-errors.html"
                ]):
                    return
                raise

            # Update state based on result
            self.last_run = datetime.now()
            if result:
                self.last_change = datetime.now()
                self.consecutive_no_changes = 0
            else:
                self.consecutive_no_changes += 1

        except Exception as e:
            self.logger.log(
                f"[{self.name}] 💥 Comprehensive error in agent cycle:\n"
                f"Type: {type(e)}\n"
                f"Error: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}",
                'critical'
            )

    def run(self):
        """Execute one iteration of the agent's task"""
        try:
            self.logger.log(f"[{self.name}] 🔄 Starting agent iteration", 'debug')
        
            # Validate mission directory
            if not os.path.exists(self.mission_dir):
                self.logger.log(f"[{self.name}] ❌ Mission directory not found")
                return

            # Update file list
            self.list_files()
    
            # Call _execute_agent_cycle instead of execute_mission
            result = self._execute_agent_cycle()
    
            # Update state based on result
            self.last_run = datetime.now()
            if result:
                self.last_change = datetime.now()
                self.consecutive_no_changes = 0
            else:
                self.consecutive_no_changes += 1

        except Exception as e:
            # Ignore known benign Aider errors
            if any(err in str(e) for err in [
                "Can't initialize prompt toolkit",
                "No Windows console found",
                "aider.chat/docs/troubleshooting/edit-errors.html",
                "[Errno 22] Invalid argument"
            ]):
                pass  # Do not stop the agent
            else:
                self.logger.log(f"[{self.name}] Error in run: {str(e)}", 'error')

    def _format_files_context(self, files_context: Dict[str, str]) -> str:
        """
        Format files context into a readable string with clear file boundaries
        
        Args:
            files_context: Dictionary mapping filenames to content
            
        Returns:
            str: Formatted string with file content blocks
        """
        formatted = []
        for filename, content in files_context.items():
            # Get relative path for cleaner output
            rel_path = os.path.relpath(filename, self.mission_dir)
            formatted.append(f"File: {rel_path}\n```\n{content}\n```\n")
        return "\n".join(formatted)

    def _build_prompt(self, context: dict = None) -> str:
        """
        Build the complete prompt with context.
        
        Args:
            context (dict, optional): Additional context to include in prompt
            
        Returns:
            str: Complete formatted prompt
        """
        try:
            # Get base prompt content
            prompt_content = self.get_prompt()
            if not prompt_content:
                raise ValueError("No prompt content available")
                
            # If no context provided, return base prompt
            if not context:
                return prompt_content
                
            # Format mission files info
            files_info = self._format_mission_files(context)
            
            # Add agent status info
            status_info = {
                'last_run': self.last_run.isoformat() if self.last_run else 'Never',
                'last_change': self.last_change.isoformat() if self.last_change else 'Never',
                'consecutive_no_changes': self.consecutive_no_changes,
                'current_interval': self.calculate_dynamic_interval()
            }
            
            # Combine all context
            full_context = {
                'files': files_info,
                'status': status_info,
                **context  # Include any additional context
            }
            
            # Format prompt with context
            return prompt_content.format(**full_context)
            
        except Exception as e:
            self.logger(f"Error building prompt: {str(e)}")
            return self.prompt  # Fallback to default prompt
        
    def _handle_output_line(self, line: str) -> None:
        """
        Process a single line of Aider output
        
        Args:
            line: Output line to process
        """
        try:
            # Skip empty lines
            if not line.strip():
                return
                
            # Parse different line types
            if "Wrote " in line:
                self._handle_file_modification(line)
            elif "Commit" in line:
                self._handle_commit_message(line)
            elif self._is_error_message(line):
                self._handle_error_message(line)
            else:
                # Log regular output
                self.logger.log(f"[{self.name}] 📝 {line}", 'debug')
                
        except Exception as e:
            self.logger.log(f"[{self.name}] Error processing output line: {str(e)}")

    def _handle_file_modification(self, line: str) -> None:
        """
        Handle file modification output
        
        Args:
            line: Output line containing file modification
        """
        try:
            file_path = line.split("Wrote ")[1].split()[0]
            self.logger.log(f"[{self.name}] ✍️ Modified: {file_path}", 'info')
            
            # Track modification
            if hasattr(self, 'modified_files'):
                self.modified_files.add(file_path)
                
        except Exception as e:
            self.logger.log(f"[{self.name}] Error handling file modification: {str(e)}")

    def _handle_commit_message(self, line: str) -> None:
        """
        Handle commit message output
        
        Args:
            line: Output line containing commit message
        """
        try:
            # Extract commit hash and message
            parts = line.split()
            commit_hash = parts[1]
            message = ' '.join(parts[2:])
            
            # Detect commit type
            commit_type = None
            for known_type in self.output_parser.COMMIT_ICONS:
                if message.lower().startswith(f"{known_type}:"):
                    commit_type = known_type
                    message = message[len(known_type)+1:].strip()
                    break
                    
            # Get icon and log
            icon = self.output_parser.COMMIT_ICONS.get(commit_type, '🔨')
            self.logger.log(f"[{self.name}] {icon} {commit_hash}: {message}", 'success')
            
        except Exception as e:
            self.logger.log(f"[{self.name}] Error handling commit message: {str(e)}")

    def _handle_error_message(self, line: str) -> None:
        """
        Handle error message output
        
        Args:
            line: Output line containing error
        """
        self.logger.log(f"[{self.name}] ❌ {line}", 'error')
        self.error_count += 1

    def _is_error_message(self, line: str) -> bool:
        """
        Check if line contains error message
        
        Args:
            line: Output line to check
            
        Returns:
            bool: True if line contains error
        """
        # Documentation links should not be treated as errors
        if "documentation:" in line.lower():
            return False
            
        error_indicators = [
            'error',
            'exception', 
            'failed',
            'can\'t initialize',
            'fatal:',
            'permission denied'
        ]
        return any(indicator in line.lower() for indicator in error_indicators)

    def list_files(self) -> None:
        """List and track files that this agent should monitor"""
        try:
            # Use FileHandler to list files in mission directory
            file_handler = FileHandler(self.mission_dir, self.logger)
            self.mission_files = file_handler.list_files()
                
        except Exception as e:
            self.logger.log(
                f"[{self.name}] Error listing files: {str(e)}", 
                'error'
            )
