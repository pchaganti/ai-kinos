"""Prompt management and caching"""
import os
from typing import Optional, Dict, Any
from datetime import datetime
from utils.logger import Logger

class PromptHandler:
    """Manages prompt loading and caching"""
    def __init__(self, logger: Logger):
        self.logger = logger
        self._prompt_cache = {}

    def get_prompt(self, prompt_file: str) -> Optional[str]:
        """Get prompt with caching"""
        try:
            if not prompt_file:
                self.logger.log("No prompt file specified", 'error')
                return None

            # Normalize path and check existence
            prompt_path = self._resolve_prompt_path(prompt_file)
            if not prompt_path or not os.path.exists(prompt_path):
                self.logger.log(f"Searched path: {prompt_path}", 'debug')
                return None

            # Check cache first
            mtime = os.path.getmtime(prompt_path)
            if prompt_path in self._prompt_cache:
                cached_time, cached_content = self._prompt_cache[prompt_path]
                if cached_time == mtime:
                    return cached_content

            # Load and cache prompt
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if not content.strip():
                self.logger.log(f"Empty prompt file: {prompt_path}", 'error')
                return None
                
            self._prompt_cache[prompt_path] = (mtime, content)
            self.logger.log(f"Loaded prompt from: {prompt_path}", 'debug')
            return content

        except Exception as e:
            self.logger.log(f"Error getting prompt: {str(e)}", 'error')
            return None

    def save_prompt(self, prompt_file: str, content: str) -> bool:
        """Save prompt with validation"""
        try:
            if not content or not content.strip():
                raise ValueError("Prompt content cannot be empty")

            # Create directory if needed
            os.makedirs(os.path.dirname(prompt_file), exist_ok=True)

            # Write to temp file first
            temp_file = f"{prompt_file}.tmp"
            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.replace(temp_file, prompt_file)

                # Clear cache entry
                if prompt_file in self._prompt_cache:
                    del self._prompt_cache[prompt_file]

                return True

            finally:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass

        except Exception as e:
            self.logger.log(f"Error saving prompt: {str(e)}", 'error')
            return False

    def validate_prompt(self, content: str) -> bool:
        """Validate prompt content format"""
        try:
            if not content or not content.strip():
                return False
                
            # Check minimum size
            if len(content) < 10:
                return False
                
            # Check required sections
            required = ["MISSION:", "CONTEXT:", "INSTRUCTIONS:", "RULES:"]
            for section in required:
                if section not in content:
                    self.logger.log(f"Missing required section: {section}", 'warning')
                    return False
                    
            return True
            
        except Exception as e:
            self.logger.log(f"Error validating prompt: {str(e)}", 'error')
            return False

    def create_backup(self, prompt_file: str) -> bool:
        """Create backup of current prompt"""
        try:
            if not os.path.exists(prompt_file):
                return True
                
            # Create backups directory
            backup_dir = os.path.join(os.path.dirname(prompt_file), "backups")
            os.makedirs(backup_dir, exist_ok=True)
            
            # Generate backup filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(backup_dir, f"{os.path.basename(prompt_file)}_{timestamp}")
            
            # Copy current prompt
            import shutil
            shutil.copy2(prompt_file, backup_file)
            
            self.logger.log(f"Created backup: {backup_file}", 'info')
            return True
            
        except Exception as e:
            self.logger.log(f"Error creating backup: {str(e)}", 'error')
            return False
    def _resolve_prompt_path(self, prompt_file: str) -> Optional[str]:
        """Resolve prompt file path checking multiple locations"""
        try:
            from services import init_services
            from utils.path_manager import PathManager
            
            services = init_services(None)
            team_service = services['team_service']
            
            # Find the team containing this agent
            agent_team = None
            for team in team_service.team_types:
                if any(agent == prompt_file.replace('.md', '') for agent in team.get('agents', [])):
                    agent_team = team['id']
                    break
            
            # If no team found, use a default search strategy
            if not agent_team:
                agent_team = 'default'
            
            # Search paths with priority
            search_paths = [
                # Specific agent prompt in team directory
                os.path.join(PathManager.get_kinos_root(), 'teams', agent_team, f'{prompt_file}'),
                
                # Team-level prompt
                os.path.join(PathManager.get_kinos_root(), 'teams', agent_team, 'prompts', prompt_file),
                
                # Global prompts directory
                os.path.join(PathManager.get_kinos_root(), 'teams', 'prompts', prompt_file),
                
                # Fallback to current directory
                os.path.join(os.getcwd(), prompt_file)
            ]
            
            # Search for existing files
            for path in search_paths:
                if os.path.exists(path):
                    self.logger.log(f"Found prompt at: {path}", 'debug')
                    return path
            
            # Detailed logging if no file found
            self.logger.log(
                f"Prompt not found. Searched paths:\n" + 
                "\n".join(f"- {p}" for p in search_paths), 
                'error'
            )
            return None
            
        except Exception as e:
            self.logger.log(f"Error resolving prompt path: {str(e)}", 'error')
            return None
