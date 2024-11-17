import os
import time
import threading
import traceback
import json
import random
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from utils.exceptions import AgentError
from agents.base.agent_state import AgentState
import importlib
import inspect
from agents.base.agent_base import AgentBase
from agents.aider.aider_agent import AiderAgent
from agents.base.agent_base import AgentBase as BaseAgent
from utils.path_manager import PathManager
from utils.validators import validate_agent_name
from utils.logger import Logger
import sys

class AgentService:
    def _normalize_agent_names(self, team_agents: List[str]) -> List[str]:
        """Normalise les noms d'agents pour correspondre aux conventions"""
        normalized = []
        for agent in team_agents:
            # Supprimer 'Agent' et normaliser
            norm_name = agent.lower().replace('agent', '').strip()
            normalized.append(norm_name)
        return normalized


    def __init__(self, _):  # Keep parameter for compatibility but don't use it
        self.logger = Logger()
        self.logger.set_level('debug')  # Assurez-vous que le debug est activé
        self.agents = {}
        self.agent_threads = {}
        self._shutting_down = threading.Event()
        self._cleanup_lock = threading.Lock()
        self._shutting_down = threading.Event()  # Add shutdown flag

    def validate_web_instance(self, web_instance):
        """
        Valide et complète une instance web avec des valeurs par défaut
        
        Args:
            web_instance: Instance web à valider
        
        Returns:
            Instance web complétée
        """
        from utils.logger import Logger
        from services.file_manager import FileManager
        from types import SimpleNamespace

        # Si None, créer une instance par défaut
        if web_instance is None:
            web_instance = SimpleNamespace(
                logger=Logger(),
                config={},
                file_manager=FileManager(None)
            )

        # Ajouter des méthodes par défaut si manquantes
        if not hasattr(web_instance, 'logger'):
            self.logger = Logger()
        
        if not hasattr(web_instance, 'log_message'):
            self.log_message = lambda msg, level='info': self.logger.log(msg, level)
        
        if not hasattr(web_instance, 'file_manager'):
            self.file_manager = FileManager(web_instance)

        return web_instance

    def _discover_agents(self) -> List[Dict[str, str]]:
        """Discover available agents by scanning prompts directory"""
        discovered_agents = []
        # Get prompts directory using PathManager
        prompts_dir = PathManager.get_prompts_path()
        
        try:
            # Create prompts directory if it doesn't exist
            if not os.path.exists(prompts_dir):
                os.makedirs(prompts_dir)
                self.log_message("Created prompts directory", 'info')
                return []

            # Get prompts directory using PathManager
            prompts_dir = PathManager.get_prompts_path()
            
            # Scan for .md files in prompts directory
            for file in os.listdir(prompts_dir):
                if file.endswith('.md'):
                    agent_name = file[:-3].lower()  # Remove .md extension
                    agent_class = self._get_agent_class(agent_name)
                    if agent_class:
                        discovered_agents.append({
                            'name': agent_name,
                            'prompt_file': file,
                            'class': agent_class,
                            'status': self._get_agent_status(agent_name)
                        })
                        self.log_message(f"Discovered agent: {agent_name}", 'debug')

            return discovered_agents

        except Exception as e:
            self.log_message(f"Error discovering agents: {str(e)}", 'error')
            return []

    def _get_agent_class(self, agent_type: str):
        """Get the appropriate agent class based on name"""
        try:
            # Import agent classes based on type
            if agent_type.lower() == 'research':
                from agents.research.research_agent import ResearchAgent
                return ResearchAgent
            else:  # Default to AiderAgent
                from agents.aider.aider_agent import AiderAgent
                return AiderAgent
            
        except ImportError as e:
            self.log_message(f"Error importing agent class: {str(e)}", 'error')
            return None

    def init_agents(self, config: Dict[str, Any], team_agents: Optional[List[Union[str, Dict[str, Any]]]] = None) -> None:
        """Initialize agents with minimal configuration"""
        try:
            # If no team_agents provided, load from default team config
            if not team_agents:
                default_team_path = os.path.join(os.getcwd(), "team_default", "config.json")
                try:
                    with open(default_team_path, 'r', encoding='utf-8') as f:
                        default_team = json.load(f)
                    team_agents = default_team.get('agents', [])
                    self.logger.log(f"Loaded default team configuration with {len(team_agents)} agents")
                except Exception as e:
                    self.logger.log(f"Error loading default team config: {str(e)}", 'error')
                    return

            mission_dir = config.get('mission_dir')
            if not mission_dir or not os.path.exists(mission_dir):
                raise ValueError(f"Invalid mission directory: {mission_dir}")

            initialized_agents = {}
            for agent_spec in team_agents:
                try:
                    # Normalize agent specification
                    if isinstance(agent_spec, dict):
                        agent_name = agent_spec['name']
                        agent_type = agent_spec.get('type', 'aider')
                        agent_weight = float(agent_spec.get('weight', 0.5))
                    else:
                        agent_name = agent_spec
                        agent_type = 'aider'
                        agent_weight = 0.5

                    # Construct agent config
                    agent_config = {
                        'name': agent_name,
                        'type': agent_type,
                        'weight': agent_weight,
                        'mission_dir': mission_dir,
                        'prompt_file': os.path.join('prompts', f"{agent_name}.md")
                    }

                    # Create appropriate agent type
                    if agent_type == 'research':
                        from agents.research.research_agent import ResearchAgent
                        agent = ResearchAgent(agent_config)
                    else:
                        from agents.aider.aider_agent import AiderAgent
                        agent = AiderAgent(agent_config)

                    initialized_agents[agent_name] = agent
                    self.logger.log(f"Initialized {agent_type} agent: {agent_name} (weight: {agent_weight})")

                except Exception as e:
                    self.logger.log(f"Error initializing agent {agent_name}: {str(e)}", 'error')

            self.agents = initialized_agents

        except Exception as e:
            self.logger.log(f"Error in agent initialization: {str(e)}", 'error')
            raise

    def _find_agent_prompt(self, agent_name: str, search_paths: List[str]) -> Optional[str]:
        """Diagnostic avancé pour trouver les fichiers de prompt avec logging détaillé"""
        normalized_name = agent_name.lower()
        
        potential_filenames = [
            f"{normalized_name}.md",
            f"{normalized_name}_agent.md", 
            f"agent_{normalized_name}.md",
            f"{normalized_name}.txt"
        ]

        searched_paths = []  # Track all paths searched

        for search_path in search_paths:
            if not os.path.exists(search_path):
                self.log_message(
                    f"Search path does not exist: {search_path}", 
                    'warning'
                )
                continue

            for filename in potential_filenames:
                full_path = os.path.join(search_path, filename)
                searched_paths.append(full_path)
                
                self.logger.log(
                    f"Checking potential prompt file: {full_path}\n"
                    f"File exists: {os.path.exists(full_path)}", 
                    'debug'
                )

                if os.path.exists(full_path):
                    return full_path

        # Log détaillé si aucun fichier n'est trouvé
        self.logger.log(
            f"No prompt file found for agent: {agent_name}\n"
            f"Searched paths: {searched_paths}\n"
            f"Potential filenames: {potential_filenames}", 
            'error'
        )
        return None

    def _read_prompt_file(self, prompt_file: str) -> Optional[str]:
        """
        Lit le contenu d'un fichier prompt avec gestion des erreurs
        
        Args:
            prompt_file: Chemin vers le fichier prompt
            
        Returns:
            str: Contenu du prompt ou None si erreur
        """
        try:
            if not prompt_file or not os.path.exists(prompt_file):
                return None
                
            with open(prompt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if not content.strip():
                self.log_message(
                    f"Empty prompt file: {prompt_file}", 
                    'warning'
                )
                return None
                
            self.log_message(
                f"Successfully read prompt from: {prompt_file}", 
                'debug'
            )
            return content
            
        except Exception as e:
            self.log_message(
                f"Error reading prompt file {prompt_file}: {str(e)}", 
                'error'
            )
            return None

    def _create_default_prompt(self, agent_name: str) -> str:
        """
        Crée un prompt par défaut pour un agent
        
        Args:
            agent_name: Nom de l'agent
            
        Returns:
            str: Prompt par défaut
        """
        default_prompt = f"""# {agent_name.capitalize()} Agent

## MISSION
Define the core mission and purpose of the {agent_name} agent.

## CONTEXT
Provide background information and context for the agent's operations.

## INSTRUCTIONS
Detailed step-by-step instructions for the agent's workflow.

## RULES
- Rule 1: Define key operational rules
- Rule 2: Specify constraints and limitations
- Rule 3: List required behaviors

## CONSTRAINTS
List any specific constraints or limitations.
"""
        
        self.log_message(
            f"Created default prompt for {agent_name}", 
            'info'
        )
        
        return default_prompt

    def _find_prompt_file(self, agent_name: str) -> Optional[str]:
        """Find prompt file for an agent"""
        try:
            # Normalize agent name
            normalized_name = agent_name.lower().replace('agent', '').strip()
            
            # Get project root (where prompts directory is)
            project_root = os.getcwd()
            
            # Possible prompt locations in order of preference
            prompt_locations = [
                os.path.join(project_root, "prompts", f"{normalized_name}.md"),
                os.path.join(project_root, "prompts", "custom", f"{normalized_name}.md"),
                os.path.join(project_root, "prompts", f"{normalized_name}_agent.md")
            ]
            
            # Try each possible location
            for location in prompt_locations:
                if os.path.exists(location):
                    self.logger.log(f"Found prompt for {normalized_name}: {location}", 'debug')
                    return location
            
            self.logger.log(
                f"No prompt file found for {normalized_name}\n"
                f"Searched locations:\n" + "\n".join(prompt_locations),
                'error'
            )
            return None
            
        except Exception as e:
            self.logger.log(f"Error finding prompt for {agent_name}: {str(e)}", 'error')
            return None

    def _create_default_prompt_file(self, agent_name: str) -> Optional[str]:
        """Create a default prompt file if no existing file is found"""
        try:
            # Use custom prompts directory for new files
            custom_prompts_dir = PathManager.get_custom_prompts_path()
            os.makedirs(custom_prompts_dir, exist_ok=True)
            
            # Construct prompt file path
            prompt_path = os.path.join(custom_prompts_dir, f"{agent_name}.md")
            
            # Default prompt template
            default_content = f"""# {agent_name.capitalize()} Agent Prompt

## MISSION
Define the core mission and purpose of the {agent_name} agent.

## CONTEXT
Provide background information and context for the agent's operations.

## INSTRUCTIONS
Detailed step-by-step instructions for the agent's workflow.

## RULES
- Rule 1: 
- Rule 2: 
- Rule 3: 

## CONSTRAINTS
List any specific constraints or limitations.
"""
            
            # Write default prompt file
            with open(prompt_path, 'w', encoding='utf-8') as f:
                f.write(default_content)
            
            self.logger.log(f"Created default prompt file for {agent_name}: {prompt_path}", 'info')
            return prompt_path
        
        except Exception as e:
            self.logger.log(f"Error creating default prompt file for {agent_name}: {str(e)}", 'error')
            return None

    def get_available_agents(self) -> List[str]:
        """Get list of available agent names"""
        # If no agents, try to initialize
        if not self.agents:
            try:
                # Try to get agents from active team or use a default list
                team_agents = None
                try:
                    active_team = self.team_service.active_team
                    team_agents = active_team['agents'] if active_team else None
                except Exception:
                    pass
            
                # Use a comprehensive default list if no team agents
                if not team_agents:
                    team_agents = [
                        'specifications',
                        'management',
                        'evaluation',
                        'chroniqueur',
                        'documentaliste',
                        'duplication',
                        'redacteur',
                        'validation',
                        'production',
                        'testeur'
                    ]
            
                self.init_agents({
                }, team_agents)
            except Exception as e:
                self.log_message(f"Failed to initialize agents: {str(e)}", 'error')
    
        return list(self.agents.keys())

    def run_random_agent(self, team_agents: List[str]):
        """
        Run a random agent from the team based on weights

        Args:
            team_agents: List of agent names from team config
        """
        try:
            # Comprehensive logging for agent selection
            self.logger.log(f"🎲 Selecting agent from team: {team_agents}", 'debug')
            
            # Get current phase first
            from services import init_services
            services = init_services(None)
            
            
            # Get weights from team config
            weights = []
            for agent in team_agents:
                # Try to get weight from team config
                try:
                    from services import init_services
                    services = init_services(None)
                    team_service = services['team_service']
                    active_team = team_service.get_active_team()
                    
                    # Find agent in team config
                    agent_config = None
                    for team_agent in active_team.get('agents', []):
                        if isinstance(team_agent, dict) and team_agent.get('name') == agent:
                            agent_config = team_agent
                            break
                        elif isinstance(team_agent, str) and team_agent == agent:
                            agent_config = {'name': agent, 'weight': 0.5}
                            break
                    
                    # Get weight with fallback
                    weight = agent_config.get('weight', 0.5) if agent_config else 0.5
                    weights.append(weight)
                    
                except Exception:
                    weights.append(0.5)  # Default weight on error
            
            # Calculate normalized weights
            total_weight = sum(weights) if weights else len(team_agents)  # Avoid division by zero
            normalized_weights = [w/total_weight for w in weights]
            
            self.logger.log(
                "Agent Selection Details:\n" +
                "\n".join(f"- {agent}: Weight = {weight:.2f}" 
                          for agent, weight in zip(team_agents, normalized_weights)),
                'debug'
            )
            
            # Select agent with logging
            agent_name = random.choices(team_agents, weights=normalized_weights, k=1)[0]
            self.logger.log(f"🎯 Selected Agent: {agent_name}", 'debug')

            self.logger.log(f"Selected agent: {agent_name}", 'debug')

            # Find the agent configuration in the team config
            agent_config = None
            for team in services['team_service'].team_types:
                for agent in team.get('agents', []):
                    # Handle both string and dictionary agent configurations
                    if isinstance(agent, dict) and agent['name'] == agent_name:
                        agent_config = agent
                        break
                    elif isinstance(agent, str) and agent == agent_name:
                        agent_config = {'name': agent_name}
                        break
                if agent_config:
                    break

            self.logger.log(f"Agent config found: {agent_config}", 'debug')

            # EXPLICIT RESEARCH TYPE FOR SPECIFIC AGENTS
            research_agents = [
                'chercheur', 
                'documentaliste'
            ]
            
            # Determine agent type with fallback and case-insensitive check
            if agent_name.lower() in research_agents:
                agent_type = 'research'
                self.logger.log(f"Agent {agent_name} explicitly set to research type", 'debug')
            elif agent_config and isinstance(agent_config, dict):
                agent_type = agent_config.get('type', 'aider').lower()
                self.logger.log(f"Agent type from config: {agent_type}", 'debug')
            else:
                # Default fallback
                agent_type = 'aider'
                self.logger.log(f"Agent type defaulted to: {agent_type}", 'debug')

            # Normalize agent type
            if agent_type not in ['aider', 'research']:
                agent_type = 'aider'
                self.logger.log(f"Normalized agent type to: {agent_type}", 'debug')

            # Configure agent
            config = {
                'name': agent_name,
                'mission_dir': os.getcwd(),
                'prompt_file': os.path.join('prompts', f"{agent_name}.md"),
                'type': agent_type,  # Explicitly set type from configuration
                'weight': weights.get(agent_name, 0.5)  # Pass weight to agent
            }

            self.logger.log(f"Final agent configuration: {config}", 'debug')

            # Dynamically select agent class
            if agent_type == 'research':
                from agents.research.research_agent import ResearchAgent
                AgentClass = ResearchAgent
                self.logger.log(
                    f"🔍 Explicitly creating ResearchAgent for {agent_name}\n"
                    f"Config: {json.dumps(config, indent=2)}\n"
                    f"Agent Type: {type(AgentClass).__name__}", 
                    'debug'
                )
            else:
                from agents.aider.aider_agent import AiderAgent
                AgentClass = AiderAgent
                self.logger.log(
                    f"🔧 Creating AiderAgent for {agent_name}\n"
                    f"Config: {json.dumps(config, indent=2)}\n"
                    f"Agent Type: {type(AgentClass).__name__}", 
                    'debug'
                )

            # Create and run agent
            agent = AgentClass(config)

            # Add explicit type checking log
            self.logger.log(
                f"Agent instantiated: {agent_name}\n"
                f"Actual Agent Type: {type(agent).__name__}\n"
                f"Expected Type: {AgentClass.__name__}", 
                'debug'
            )
            self.logger.log(
                f"Running {agent_type.upper()} agent {agent_name} "
                f"(weight: {config['weight']:.2f})", 
                'info'
            )
    
            # Add global error tracking
            try:
                agent.run()
            except Exception as agent_error:
                self.logger.log(
                    f"Agent {agent_name} execution error:\n"
                    f"Type: {type(agent_error)}\n"
                    f"Error: {str(agent_error)}\n"
                    f"Traceback: {traceback.format_exc()}",
                    'critical'
                )
                
                # Optional: Attempt recovery or restart
                if hasattr(agent, 'recover_from_error'):
                    agent.recover_from_error()

        except Exception as e:
            self.logger.log(
                f"❌ Comprehensive error running agent:\n"
                f"Type: {type(e)}\n"
                f"Error: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}",
                'error'
            )

    def toggle_agent(self, agent_name: str, action: str, mission_dir: Optional[str] = None) -> bool:
        """Start or stop an agent with improved error handling"""
        try:
            agent_key = agent_name.lower().replace('agent', '').strip()
            
            # Get or create agent
            agent = self.agents.get(agent_key)
            if not agent:
                if action == 'start':
                    # Create new agent configuration
                    agent_config = {
                        'name': agent_name,
                        'type': 'aider',
                        'weight': 0.5,
                        'mission_dir': mission_dir or os.getcwd(),
                        'prompt_file': os.path.join('prompts', f"{agent_name}.md")
                    }
                    
                    # Create agent instance
                    from agents.aider.aider_agent import AiderAgent
                    agent = AiderAgent(agent_config)
                    self.agents[agent_key] = agent
                    self.logger.log(f"Created new agent instance: {agent_name}", 'info')
                else:
                    self.logger.log(f"Agent {agent_name} not found", 'error')
                    return False

            # Update mission directory if provided
            if mission_dir:
                agent.mission_dir = mission_dir

            # Execute action
            if action == 'start':
                if agent.running:
                    self.logger.log(f"Agent {agent_name} already running", 'warning')
                    return True
                    
                try:
                    agent.start()
                    thread = threading.Thread(
                        target=self._run_agent_wrapper,
                        args=(agent_name, agent),
                        daemon=True
                    )
                    self.agent_threads[agent_name] = thread
                    thread.start()
                    
                    # Wait briefly to ensure agent starts properly
                    time.sleep(0.5)
                    
                    if agent.running:
                        self.logger.log(f"Agent {agent_name} started successfully", 'success')
                        return True
                    else:
                        self.logger.log(f"Agent {agent_name} failed to start", 'error')
                        return False
                        
                except Exception as e:
                    # Handle known Aider errors
                    error_msg = str(e)
                    known_errors = [
                        "Can't initialize prompt toolkit",
                        "No Windows console found",
                        "aider.chat/docs/troubleshooting/edit-errors.html",
                        "[Errno 22] Invalid argument"
                    ]
                    
                    if not any(err in error_msg for err in known_errors):
                        self.logger.log(f"Error starting agent {agent_name}: {error_msg}", 'error')
                    return False
                    
            elif action == 'stop':
                if not agent.running:
                    return True
                    
                agent.stop()
                if agent_name in self.agent_threads:
                    thread = self.agent_threads[agent_name]
                    if thread and thread.is_alive():
                        thread.join()
                    del self.agent_threads[agent_name]
                    
                return not agent.running

            return False

        except Exception as e:
            self.logger.log(f"Error in toggle_agent: {str(e)}", 'error')
            return False

    def _cleanup_cache(self, cache_type: str) -> None:
        """Centralized cache cleanup"""
        try:
            cache = self._get_cache(cache_type)
            now = time.time()
            expired = [
                key for key, (_, timestamp) in cache.items()
                if now - timestamp > self.ttl
            ]
            for key in expired:
                self._remove(key, cache_type)
        except Exception as e:
            self.logger.log(f"Cache cleanup error: {str(e)}", 'error')

    def _cleanup_resources(self):
        """Nettoie les ressources"""
        try:
            with self._cleanup_lock:
                # Nettoyer les threads
                for thread in self.agent_threads.values():
                    if thread and thread.is_alive():
                        try:
                            thread.join()
                        except:
                            pass
                            
                self.agent_threads.clear()
                
        except Exception as e:
            self.logger.log(f"Error cleaning up resources: {str(e)}", 'error')

    def start_all_agents(self) -> None:
        """Start all agents"""
        try:
            self.logger.log("Starting agents...")
            
            # Get current directory as mission directory
            mission_dir = os.getcwd()
            
            # Update mission directory for all agents
            for name, agent in self.agents.items():
                agent.mission_dir = mission_dir
                self.logger.log(f"Set mission dir for {name}: {mission_dir}")

            # Start agent threads
            for name, agent in self.agents.items():
                try:
                    self.logger.log(f"Starting agent: {name}")
                    agent.start()
                    
                    thread = threading.Thread(
                        target=self._run_agent_wrapper,
                        args=(name, agent),
                        daemon=True,
                        name=f"Agent-{name}"
                    )
                    
                    self.agent_threads[name] = thread
                    thread.start()
                    
                    self.logger.log(f"Agent {name} started successfully")
                    
                except Exception as e:
                    self.logger.log(f"Failed to start agent {name}: {str(e)}", 'error')

        except Exception as e:
            self.logger.log(f"Error starting agents: {str(e)}", 'error')
            raise

    def stop_all_agents(self) -> None:
        """Stop all agents with proper cleanup"""
        try:
            self._shutting_down.set()
            
            # First set all agents to not running
            for name, agent in self.agents.items():
                try:
                    agent.running = False
                    self.logger.log(f"Marked agent {name} to stop")
                except Exception as e:
                    self.logger.log(f"Error marking agent {name} to stop: {str(e)}", 'error')

            # Then wait for threads to finish
            for name, thread in self.agent_threads.items():
                try:
                    if thread and thread.is_alive():
                        thread.join()
                        self.logger.log(f"Stopped agent thread {name}")
                except Exception as e:
                    self.logger.log(f"Error stopping agent thread {name}: {str(e)}", 'error')

            # Clear thread references
            self.agent_threads.clear()
            
            # Final cleanup
            for agent in self.agents.values():
                try:
                    if hasattr(agent, 'cleanup'):
                        agent.cleanup()
                except Exception as e:
                    self.logger.log(f"Error in agent cleanup: {str(e)}", 'error')

        except Exception as e:
            self.logger.log(f"Error stopping agents: {str(e)}", 'error')
        finally:
            # Force clear references
            self.agents.clear()
            self.agent_threads.clear()

    def _start_monitor_thread(self) -> None:
        """Start the agent monitor thread if not running"""
        if not self.monitor_thread or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(
                target=self._monitor_agents,
                daemon=True,
                name="AgentMonitor"
            )
            self.monitor_thread.start()

    def _calculate_system_health(self, metrics: Dict) -> float:
        """
        Calculate overall system health score from metrics
        
        Args:
            metrics: Dictionary containing system metrics
            
        Returns:
            float: Health score between 0.0 and 1.0
        """
        try:
            # Calculate base health score from agent states
            if metrics['total_agents'] == 0:
                return 0.0
                
            # Weight different factors
            agent_health = metrics['healthy_agents'] / metrics['total_agents']
            active_ratio = metrics['active_agents'] / metrics['total_agents']
            
            # Calculate error rate
            total_operations = (metrics['cache_hits'] + metrics['cache_misses'] + 
                              metrics['file_operations']['reads'] + 
                              metrics['file_operations']['writes'])
            error_rate = metrics['error_count'] / max(total_operations, 1)
            
            # Calculate cache performance
            cache_rate = metrics['cache_hits'] / max(metrics['cache_hits'] + metrics['cache_misses'], 1)
            
            # Weighted average of health indicators
            weights = {
                'agent_health': 0.4,
                'active_ratio': 0.3,
                'error_rate': 0.2,
                'cache_rate': 0.1
            }
            
            health_score = (
                weights['agent_health'] * agent_health +
                weights['active_ratio'] * active_ratio +
                weights['error_rate'] * (1 - error_rate) +  # Invert error rate
                weights['cache_rate'] * cache_rate
            )
            
            return max(0.0, min(1.0, health_score))  # Clamp between 0 and 1
            
        except Exception as e:
            self.log_message(f"Error calculating system health: {str(e)}", 'error')
            return 0.0  # Return 0 on error

    def _handle_system_degradation(self, system_metrics: Dict) -> None:
        """Handle system-wide performance degradation"""
        try:
            # Log detailed metrics
            self.logger.log(
                f"System health degraded. Metrics:\n"
                f"- Active agents: {system_metrics['active_agents']}/{system_metrics['total_agents']}\n"
                f"- Healthy agents: {system_metrics['healthy_agents']}/{system_metrics['total_agents']}\n"
                f"- Error count: {system_metrics['error_count']}\n"
                f"- Cache performance: {system_metrics['cache_hits']}/{system_metrics['cache_hits'] + system_metrics['cache_misses']} hits",
                'warning'
            )

            # Attempt recovery actions
            recovery_actions = []

            # Check for unhealthy agents
            if system_metrics['healthy_agents'] < system_metrics['total_agents']:
                recovery_actions.append("Restarting unhealthy agents")
                for name, agent in self.agents.items():
                    if hasattr(agent, 'is_healthy') and not agent.is_healthy():
                        self._restart_agent(name, agent)

            # Check cache performance
            total_cache_ops = system_metrics['cache_hits'] + system_metrics['cache_misses']
            if total_cache_ops > 0:
                hit_rate = system_metrics['cache_hits'] / total_cache_ops
                if hit_rate < 0.7:  # Less than 70% hit rate
                    recovery_actions.append("Clearing and rebuilding caches")
                    for agent in self.agents.values():
                        if hasattr(agent, '_prompt_cache'):
                            agent._prompt_cache.clear()

            # Log recovery actions
            if recovery_actions:
                self.logger.log(
                    f"Recovery actions taken:\n- " + "\n- ".join(recovery_actions),
                    'info'
                )
            else:
                self.logger.log(
                    "No automatic recovery actions available for current degradation",
                    'warning'
                )

        except Exception as e:
            self.logger.log(
                f"Error handling system degradation: {str(e)}",
                'error'
            )

    def _monitor_agents(self) -> None:
        """Monitor agent status and health with enhanced metrics"""
        while self.running:
            try:
                status_updates = {}
                system_metrics = {
                    'total_agents': len(self.agents),
                    'active_agents': 0,
                    'healthy_agents': 0,
                    'error_count': 0,
                    'cache_hits': 0,
                    'cache_misses': 0,
                    'average_response_time': 0.0,
                    'memory_usage': {},
                    'file_operations': {
                        'reads': 0,
                        'writes': 0,
                        'errors': 0
                    }
                }

                # Monitor each agent
                for name, agent in self.agents.items():
                    try:
                        # Get detailed agent status
                        current_status = self._get_detailed_agent_status(name)
                        
                        # Update system metrics
                        if current_status['running']:
                            system_metrics['active_agents'] += 1
                        if current_status['health']['is_healthy']:
                            system_metrics['healthy_agents'] += 1
                            
                        # Aggregate performance metrics
                        system_metrics['cache_hits'] += current_status['metrics']['cache_hits']
                        system_metrics['cache_misses'] += current_status['metrics']['cache_misses']
                        system_metrics['file_operations']['reads'] += current_status['metrics']['file_reads']
                        system_metrics['file_operations']['writes'] += current_status['metrics']['file_writes']
                        
                        # Check for health issues
                        if not current_status['health']['is_healthy']:
                            self._handle_unhealthy_agent(name, current_status)
                            
                        status_updates[name] = current_status
                        
                    except Exception as agent_error:
                        system_metrics['error_count'] += 1
                        self._handle_agent_error(name, agent_error)

                # Calculate system health score
                health_score = self._calculate_system_health(system_metrics)
                
                # Update global status with metrics
                self._update_global_status(status_updates, system_metrics, health_score)
                
                # Handle system-wide issues
                if health_score < 0.7:  # Below 70% health
                    self._handle_system_degradation(system_metrics)
                    
            except Exception as e:
                self.logger.log(f"Error in monitor loop: {str(e)}", 'error')
            finally:
                time.sleep(30)  # Check every 30 seconds

    def get_agent_status(self, agent_name: str = None) -> Union[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        """Unified method for retrieving agent status"""
        if agent_name:
            # Normalize agent name
            agent_key = agent_name.lower()
            
            # Check if agent exists
            if agent_key not in self.agents:
                return {
                    'running': False,
                    'status': 'not_initialized',
                    'error': f'Agent {agent_name} not found'
                }
            
            agent = self.agents[agent_key]
            return {
                'running': agent.running,
                'status': 'active' if agent.running else 'inactive',
                'last_run': agent.last_run.isoformat() if agent.last_run else None,
                'health': {
                    'is_healthy': agent.is_healthy(),
                    'consecutive_no_changes': getattr(agent, 'consecutive_no_changes', 0)
                }
            }
        
        # Return status for all agents
        return {
            name: {
                'running': agent.running,
                'status': 'active' if agent.running else 'inactive',
                'last_run': agent.last_run.isoformat() if agent.last_run else None,
                'health': {
                    'is_healthy': agent.is_healthy(),
                    'consecutive_no_changes': getattr(agent, 'consecutive_no_changes', 0)
                }
            }
            for name, agent in self.agents.items()
        }

    # Removed _get_agent_status_details method as it's now consolidated

    # Removed _get_agent_status method as it's now consolidated

    def _get_default_agent_status(self, status_type: str = 'default') -> Dict[str, Any]:
        """Generate a default agent status dictionary"""
        status_map = {
            'not_found': {
                'running': False,
                'status': 'not_found',
                'last_run': None,
                'health': {'is_healthy': False, 'consecutive_no_changes': 0}
            },
            'error': {
                'running': False,
                'status': 'error',
                'last_run': None,
                'health': {'is_healthy': False, 'consecutive_no_changes': 0}
            },
            'default': {
                'running': False,
                'status': 'inactive',
                'last_run': None,
                'health': {'is_healthy': True, 'consecutive_no_changes': 0}
            }
        }
        return status_map.get(status_type, status_map['default'])
    def _run_agent_wrapper(self, name: str, agent: 'AgentBase') -> None:
        """Wrapper to execute an agent in a thread with comprehensive error handling"""
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                self.logger.log(f"Starting agent {name} (Attempt {retry_count + 1}/{max_retries})", 'info')
            
                # Capture start time
                start_time = time.time()
            
                # Execute agent run
                result = agent.run()
                
                # Log if no result
                if not result:
                    self.logger.log(f"⚠️ No result from agent {name}", 'warning')
            
                # Log successful run
                run_duration = time.time() - start_time
                self.logger.log(
                    f"Agent {name} completed run "
                    f"(duration: {run_duration:.2f}s)", 
                    'success'
                )
            
                # If successful, break the retry loop
                break
            
            except Exception as e:
                retry_count += 1
            
                # Comprehensive error logging
                self.logger.log(
                    f"Agent {name} error (Attempt {retry_count}/{max_retries}):\n"
                    f"Type: {type(e)}\n"
                    f"Error: {str(e)}\n"
                    f"Traceback: {traceback.format_exc()}",
                    'critical'
                )
            
                # Exponential backoff
                wait_time = min(30, 2 ** retry_count)
                self.logger.log(f"Waiting {wait_time}s before retry", 'warning')
                time.sleep(wait_time)
    
        if retry_count == max_retries:
            self.logger.log(
                f"FATAL: Agent {name} failed after {max_retries} attempts", 
                'critical'
            )

    def _get_detailed_agent_status(self, agent_name: str) -> Dict[str, Any]:
        """Get comprehensive agent status including performance metrics"""
        try:
            agent = self.agents.get(agent_name)
            if not agent:
                return self._get_default_status()

            # Basic status
            status = {
                'running': agent.running,
                'status': 'active' if agent.running else 'inactive',
                'last_run': agent.last_run.isoformat() if agent.last_run else None,
                'last_change': agent.last_change.isoformat() if agent.last_change else None,
                
                # Health metrics
                'health': {
                    'is_healthy': agent.is_healthy(),
                    'consecutive_no_changes': agent.consecutive_no_changes,
                    'current_interval': agent.calculate_dynamic_interval(),
                    'error_rate': self._calculate_error_rate(agent),
                    'response_times': self._get_response_times(agent)
                },
                
                # Performance metrics
                'metrics': {
                    'cache_hits': getattr(agent, 'cache_hits', 0),
                    'cache_misses': getattr(agent, 'cache_misses', 0),
                    'file_reads': getattr(agent, 'file_reads', 0),
                    'file_writes': getattr(agent, 'file_writes', 0),
                    'average_processing_time': self._get_average_processing_time(agent),
                    'memory_usage': self._get_agent_memory_usage(agent)
                },
                
                # Resource utilization
                'resources': {
                    'cpu_usage': self._get_agent_cpu_usage(agent),
                    'memory_usage': self._get_agent_memory_usage(agent),
                    'file_handles': self._get_open_file_handles(agent)
                }
            }

            return status

        except Exception as e:
            self.logger.log(f"Error getting detailed status: {str(e)}", 'error')
            return self._get_default_status()

    def _calculate_error_rate(self, agent) -> float:
        """Calculate error rate for an agent over the last period"""
        try:
            # Get error count from last period (default to 0)
            error_count = getattr(agent, 'error_count', 0)
            total_runs = getattr(agent, 'total_runs', 1)  # Avoid division by zero
            
            # Calculate rate (0.0 to 1.0)
            return error_count / max(total_runs, 1)
            
        except Exception as e:
            self.logger.log(f"Error calculating error rate: {str(e)}", 'error')
            return 0.0

    def _handle_error(self, error_type: str, error: Exception, context: Dict = None) -> None:
        """Centralized error handling for both agent and system errors"""
        try:
            context = context or {}
            agent_name = context.get('agent_name')
            
            # Log the error with context
            self.logger.log(
                f"{error_type} error: {str(error)}\n"
                f"Context: {context}", 
                'error'
            )
            
            if error_type == 'agent':
                if not agent_name or agent_name not in self.agents:
                    return
                    
                agent = self.agents[agent_name]
                agent.error_count = getattr(agent, 'error_count', 0) + 1
                
                # Try recovery for agent errors
                if hasattr(agent, 'recover_from_error'):
                    try:
                        if agent.recover_from_error():
                            self.logger.log(f"Agent {agent_name} recovered successfully", 'info')
                        else:
                            self.logger.log(f"Agent {agent_name} recovery failed", 'warning')
                    except Exception as recovery_error:
                        self.logger.log(f"Recovery error: {str(recovery_error)}", 'error')
                
                # Stop agent if too many errors
                if agent.error_count > 5:
                    self.logger.log(f"Stopping agent {agent_name} due to too many errors", 'warning')
                    agent.stop()
        except Exception as e:
            self.logger.log(f"Error in error handler: {str(e)}", 'error')

    def _get_response_times(self, agent) -> Dict[str, float]:
        """Get agent response time metrics"""
        return {
            'average': getattr(agent, 'avg_response_time', 0.0),
            'min': getattr(agent, 'min_response_time', 0.0),
            'max': getattr(agent, 'max_response_time', 0.0)
        }

    def _get_average_processing_time(self, agent) -> float:
        """Get average processing time for agent operations"""
        return getattr(agent, 'avg_processing_time', 0.0)

    def _get_agent_memory_usage(self, agent) -> Dict[str, int]:
        """Get memory usage metrics for an agent"""
        return {
            'current': getattr(agent, 'current_memory', 0),
            'peak': getattr(agent, 'peak_memory', 0)
        }

    def _get_agent_cpu_usage(self, agent) -> float:
        """Get CPU usage percentage for an agent"""
        return getattr(agent, 'cpu_usage', 0.0)

    def _get_open_file_handles(self, agent) -> int:
        """Get number of open file handles for an agent"""
        return getattr(agent, 'open_files', 0)

    def _get_default_status(self) -> Dict[str, Any]:
        """Get default status structure for agents"""
        return {
            'running': False,
            'status': 'inactive',
            'last_run': None,
            'last_change': None,
            'health': {
                'is_healthy': True,
                'consecutive_no_changes': 0,
                'current_interval': 60,
                'error_rate': 0.0,
                'response_times': {
                    'average': 0.0,
                    'min': 0.0,
                    'max': 0.0
                }
            },
            'metrics': {
                'cache_hits': 0,
                'cache_misses': 0,
                'file_reads': 0,
                'file_writes': 0,
                'average_processing_time': 0.0,
                'memory_usage': {
                    'current': 0,
                    'peak': 0
                }
            },
            'resources': {
                'cpu_usage': 0.0,
                'memory_usage': {
                    'current': 0,
                    'peak': 0
                },
                'file_handles': 0
            }
        }

    def _handle_agent_crash(self, agent_name: str, agent: 'AgentBase') -> None:
        """
        Handle agent crash with recovery attempt
        
        Args:
            agent_name: Name of crashed agent
            agent: Agent instance that crashed
        """
        try:
            self.logger.log(f"Handling crash of agent {agent_name}", 'warning')
            
            # Stop the agent
            agent.stop()
            
            # Wait briefly
            time.sleep(5)
            
            # Try to restart
            try:
                agent.start()
                thread = threading.Thread(
                    target=self._run_agent_wrapper,
                    args=(agent_name, agent),
                    daemon=True,
                    name=f"Agent-{agent_name}"
                )
                self.agent_threads[agent_name] = thread
                thread.start()
                
                self.logger.log(f"Successfully restarted agent {agent_name} after crash", 'success')
                
            except Exception as restart_error:
                self.logger.log(
                    f"Failed to restart agent {agent_name} after crash: {str(restart_error)}", 
                    'error'
                )
                
        except Exception as e:
            self.logger.log(f"Error handling agent crash: {str(e)}", 'error')

    def _restart_agent(self, name: str, agent: 'AgentBase') -> None:
        """Safely restart a single agent"""
        try:
            # Stop the agent
            agent.stop()
            time.sleep(1)  # Brief pause
            
            # Start the agent
            agent.start()
            thread = threading.Thread(
                target=self._run_agent_wrapper,
                args=(name, agent),
                daemon=True,
                name=f"Agent-{name}"
            )
            thread.start()
            
            self.logger.log(f"Successfully restarted agent {name}", 'success')
            
        except Exception as e:
            self.logger.log(f"Error restarting agent {name}: {str(e)}", 'error')

    def _start_agent_with_retry(self, agent_name: str, agent_state: AgentState, max_attempts: int = 3) -> bool:
        """Start agent with retry logic and exponential backoff"""
        
        for attempt in range(max_attempts):
            try:
                self.logger.log(f"Starting agent {agent_name} (attempt {attempt + 1}/{max_attempts})", 'info')
                
                agent_state.mark_active()
                success = self._start_agent(agent_name)
                
                if success:
                    agent_state.mark_completed()
                    self.logger.log(f"Successfully started agent {agent_name}", 'success')
                    return True
                        
                # If failed but can retry
                if agent_state.can_retry:
                    backoff_time = min(30, 2 ** attempt)  # Exponential backoff capped at 30s
                    self.logger.log(
                        f"Retrying agent {agent_name} in {backoff_time}s "
                        f"(Attempt {attempt + 1}/{max_attempts})",
                        'warning'
                    )
                    time.sleep(backoff_time)
                else:
                    agent_state.mark_error(f"Failed after {max_attempts} attempts")
                    return False
                    
            except Exception as e:
                self.logger.log(f"Error starting agent {agent_name}: {str(e)}", 'error')
                agent_state.mark_error(str(e))
                if not agent_state.can_retry:
                    return False
                    
        return False

    def _start_agent(self, agent_name: str) -> bool:
        """Start a single agent with error handling"""
        try:
            self.logger.log(f"Initializing agent: {agent_name}", 'info')
            
            # Ignore known Aider initialization errors
            try:
                success = self.agent_service.toggle_agent(agent_name, 'start')
                if success:
                    self.logger.log(f"Agent {agent_name} started successfully", 'success')
                else:
                    self.logger.log(f"Agent {agent_name} failed to start", 'error')
                return success
                
            except Exception as e:
                error_msg = str(e)
                # List of known Aider errors to ignore
                known_errors = [
                    "Can't initialize prompt toolkit",
                    "No Windows console found",
                    "aider.chat/docs/troubleshooting/edit-errors.html",
                    "[Errno 22] Invalid argument"  # Windows-specific error
                ]
                
                if not any(err in error_msg for err in known_errors):
                    self.logger.log(f"Error starting agent {agent_name}: {error_msg}", 'error')
                return False
                
        except Exception as e:
            self.logger.log(f"Critical error starting agent {agent_name}: {str(e)}", 'error')
            return False

    def _update_global_status(self, status_updates: Dict[str, Dict], system_metrics: Dict, health_score: float) -> None:
        """Update global system status based on agent states"""
        try:
            total_agents = len(status_updates)
            active_agents = sum(1 for status in status_updates.values() if status['running'])
            healthy_agents = sum(1 for status in status_updates.values() 
                               if status['health']['is_healthy'])
            
            system_status = {
                'total_agents': total_agents,
                'active_agents': active_agents,
                'healthy_agents': healthy_agents,
                'system_health': health_score,
                'metrics': system_metrics,
                'timestamp': datetime.now().isoformat(),
                'agents': status_updates
            }
            
            # Log significant changes
            if system_status['system_health'] < 0.8:  # Less than 80% healthy
                self.logger.log(
                    f"System health degraded: {system_status['system_health']:.1%}", 
                    'warning'
                )
                
            # Store status for API access
            self._last_status = system_status
            
        except Exception as e:
            self.logger.log(f"Error updating global status: {str(e)}", 'error')

    def get_prompt(self) -> Optional[str]:
        """Get the current prompt content"""
        try:
            # Use prompt handler to get prompt
            return self.prompt_handler.get_prompt(self.prompt_file)
        except Exception as e:
            self.logger.log(f"Error getting prompt: {str(e)}", 'error')
            return None

    def execute_mission(self, prompt: str) -> Optional[str]:
        """Execute research mission with single query to Perplexity"""
        try:
            self.logger.log(f"[{self.name}] 🔍 Starting research mission", 'debug')
            
            # Get current content
            content = ""
            for file_path in self.mission_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content += f.read() + "\n\n"
                    self.logger.log(f"[{self.name}] Read content from: {file_path}", 'debug')
                except Exception as e:
                    self.logger.log(f"Error reading {file_path}: {str(e)}", 'warning')

            # Execute single query with full content
            results = self.perplexity_client.execute_query(content)
            
            if not results:
                self.logger.log(f"[{self.name}] No research results found", 'info')
                return None

            # Format for Aider
            aider_prompt = f"""Based on the research results below, update the relevant files to add appropriate references and citations.

Research Results:
{results['response']}

Instructions:
1. Insert references at appropriate locations in the text
2. Use a consistent citation format
3. Add a References/Bibliography section if needed
4. Preserve existing content and formatting
5. Only add the new references - don't modify other content

Please proceed with the updates now."""

            # Save to chat history
            chat_history_file = f".aider.{self.name}.chat.history.md"
            try:
                with open(chat_history_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n\n--- {datetime.now().isoformat()} ---\n")
                    f.write(f"**Research Query:**\n{content}\n\n")
                    f.write(f"**Research Results:**\n{results['response']}\n\n")
                    f.write(f"**Aider Prompt:**\n{aider_prompt}\n")
            except Exception as e:
                self.logger.log(f"Error saving research chat history: {str(e)}", 'warning')

            return super()._run_aider(aider_prompt)
            
        except Exception as e:
            self.logger.log(f"Error in research mission: {str(e)}", 'error')
            return None

    def create_agent(self, agent_config: Union[str, Dict[str, Any]]) -> Optional[BaseAgent]:
        """Create an agent instance from configuration"""
        try:
            # Get current team from TeamService
            from services import init_services
            services = init_services(None)
            team_service = services['team_service']
            current_team = team_service.active_team_name

            # Handle string input (agent name)
            if isinstance(agent_config, str):
                agent_name = agent_config
                agent_config = {
                    'name': agent_name,
                    'type': 'aider',
                    'mission_dir': os.getcwd(),
                    'weight': 0.5,
                    'team': current_team  # Add team to config
                }
            else:
                agent_name = agent_config.get('name')
                if not agent_name:
                    raise ValueError("Missing agent name in config")
                # Add team to config if not present
                if 'team' not in agent_config:
                    agent_config['team'] = current_team

            # Get agent class based on type
            agent_type = agent_config.get('type', 'aider')
            agent_class = self._get_agent_class(agent_type)
            if not agent_class:
                raise ValueError(f"Unknown agent type: {agent_type}")

            # Create agent instance
            agent = agent_class(agent_config)
            self.logger.log(f"Created agent: {agent_name} (type: {agent_type})", 'success')
            return agent

        except Exception as e:
            self.logger.log(f"Error creating agent {agent_config}: {str(e)}", 'error')
            return None

    def get_agent_prompt(self, agent_id: str) -> Optional[str]:
        """Get the current prompt for a specific agent"""
        try:
            # Normalize agent name
            agent_name = agent_id.lower()
            
            # Use PathManager for prompts directory
            prompts_dir = PathManager.get_prompts_path()
            
            # Multiple possible prompt file locations
            possible_paths = [
                os.path.join(prompts_dir, f"{agent_name}.md"),
                os.path.join(prompts_dir, "custom", f"{agent_name}.md"),
                os.path.join(prompts_dir, f"{agent_name}_agent.md")
            ]
            
            # Try each possible path
            for prompt_path in possible_paths:
                if os.path.exists(prompt_path):
                    try:
                        with open(prompt_path, 'r', encoding='utf-8') as f:
                            prompt = f.read()
                        
                        # Validate prompt content
                        if prompt and prompt.strip():
                            self.log_message(f"Retrieved prompt from {prompt_path}", 'debug')
                            return prompt
                    except Exception as read_error:
                        self.log_message(f"Error reading prompt file {prompt_path}: {str(read_error)}", 'error')
            
            # If no prompt found, return a default
            default_prompt = f"""# {agent_name.capitalize()} Agent Default Prompt

## MISSION
Provide a default mission for the {agent_name} agent.

## CONTEXT
Default context for agent operations.

## INSTRUCTIONS
Default operational instructions.
"""
            self.log_message(f"Using default prompt for {agent_name}", 'warning')
            return default_prompt
            
        except Exception as e:
            self.log_message(f"Error getting agent prompt: {str(e)}", 'error')
            return None

    def save_agent_prompt(self, agent_id: str, prompt_content: str) -> bool:
        """Save updated prompt for a specific agent"""
        try:
            # Validate input
            if not prompt_content or not prompt_content.strip():
                raise ValueError("Prompt content cannot be empty")
            
            # Normalize agent name
            agent_name = agent_id.lower()
            
            # Use PathManager for custom prompts
            custom_prompts_dir = PathManager.get_custom_prompts_path()
            os.makedirs(custom_prompts_dir, exist_ok=True)
            
            # Construct prompt file path
            prompt_path = os.path.join(custom_prompts_dir, f"{agent_name}.md")
            
            # Write prompt file
            with open(prompt_path, 'w', encoding='utf-8') as f:
                f.write(prompt_content)
            
            # Reload agent if it exists
            if agent_name in self.agents:
                self.reload_agent(agent_name)
            
            self.log_message(f"Saved new prompt for agent {agent_name}", 'success')
            return True
            
        except Exception as e:
            self.log_message(f"Error saving agent prompt: {str(e)}", 'error')
            return False

    def _validate_prompt(self, prompt_content: str) -> bool:
        """Validate prompt content format and requirements"""
        try:
            if not prompt_content or not prompt_content.strip():
                return False
                
            # Vérifier la taille minimale
            if len(prompt_content) < 10:
                return False
                
            # Vérifier la présence d'instructions basiques
            required_elements = [
                "MISSION:",
                "CONTEXT:",
                "INSTRUCTIONS:",
                "RULES:"
            ]
            
            for element in required_elements:
                if element not in prompt_content:
                    self.logger.log(
                        f"Missing required element in prompt: {element}", 
                        'warning'
                    )
                    return False
                    
            return True
            
        except Exception as e:
            self.logger.log(f"Error validating prompt: {str(e)}", 'error')
            return False

    def _backup_prompt(self, agent_name: str) -> bool:
        """Create backup of current prompt before updating"""
        try:
            prompt_file = f"prompts/{agent_name}.md"
            if not os.path.exists(prompt_file):
                return True  # No backup needed
                
            # Create backups directory
            backup_dir = "prompts/backups"
            os.makedirs(backup_dir, exist_ok=True)
            
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"{backup_dir}/{agent_name}_{timestamp}.md"
            
            # Copy current prompt to backup
            import shutil
            shutil.copy2(prompt_file, backup_file)
            
            self.log_message(
                f"Created backup of {agent_name} prompt: {backup_file}", 
                'info'
            )
            return True
            
        except Exception as e:
            self.log_message(f"Error backing up prompt: {str(e)}", 'error')
            return False

    def log_agent_creation(self, agent_name: str, success: bool):
        """Log agent creation events"""
        if success:
            self.logger.log(f"Successfully created agent: {agent_name}", 'success')
        else:
            self.logger.log(f"Failed to create agent: {agent_name}", 'error')

    def log_agent_interaction(self, agent_name: str, prompt: str, response: str, files_context: Optional[Dict[str, str]] = None):
        """
        Log an agent interaction using ChatLogger
        
        Args:
            agent_name: Name of the agent
            prompt: Prompt sent to the agent
            response: Agent's response
            files_context: Optional context of files involved
        """
        try:
            from utils.chat_logger import ChatLogger
            from utils.path_manager import PathManager
            
            # Use current mission directory or a default
            mission_name = os.path.basename(os.getcwd())
            chat_logger = ChatLogger(mission_name)
            
            # Log the interaction
            chat_logger.log_agent_interaction(
                agent_name=agent_name,
                prompt=prompt,
                response=response,
                files_context=files_context or {}
            )
        except Exception as e:
            self.logger.log(f"Error logging agent interaction: {str(e)}", 'error')

    def _load_prompt_template(self, agent_type: str) -> Optional[str]:
        """Load default prompt template for agent type"""
        try:
            template_file = f"templates/prompts/{agent_type}.md"
            if not os.path.exists(template_file):
                return None
                
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            return content
            
        except Exception as e:
            self.log_message(f"Error loading prompt template: {str(e)}", 'error')
            return None

    def _create_default_prompt(self, agent_name: str) -> str:
        """
        Create a default prompt for an agent
        
        Args:
            agent_name: Name of the agent
        
        Returns:
            str: Default prompt content
        """
        return f"""# {agent_name.capitalize()} Agent Default Prompt

## MISSION
Provide a comprehensive mission description for the {agent_name} agent.

## CONTEXT
Describe the operational context and key responsibilities.

## INSTRUCTIONS
1. Define primary objectives
2. Outline key operational guidelines
3. Specify decision-making criteria

## RULES
- Rule 1: Maintain clarity and precision
- Rule 2: Prioritize mission objectives
- Rule 3: Adapt to changing requirements

## CONSTRAINTS
- Adhere to ethical guidelines
- Maintain confidentiality
- Optimize resource utilization
"""
