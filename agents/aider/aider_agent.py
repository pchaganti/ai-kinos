"""
AiderAgent - Core implementation of Aider-based agent functionality
"""
import os
import time
import subprocess
import traceback
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List
from utils.logger import Logger
from utils.exceptions import AgentError
from agents.base.agent_base import AgentBase
from agents.aider.command_builder import AiderCommandBuilder
from agents.aider.output_parser import AiderOutputParser
from agents.utils.encoding import configure_encoding
from agents.utils.path_utils import validate_paths, get_relative_path, PathManager
from agents.utils.rate_limiter import RateLimiter

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
        super().__init__(config)
        
        # Configure UTF-8 encoding
        configure_encoding()
        
        # Initialize components
        self.command_builder = AiderCommandBuilder()
        self.output_parser = AiderOutputParser(self.logger)
        self.rate_limiter = RateLimiter(
            max_requests=50,
            time_window=60
        )
        
        # Store original directory
        self.original_dir = os.getcwd()
        
        # Initialize state
        self._init_state()
        
        # Validate paths
        if not validate_paths(self.mission_dir):
            raise ValueError(f"Invalid mission directory: {self.mission_dir}")

    def _run_aider(self, prompt: str) -> Optional[str]:
        """Execute Aider with given prompt"""
        attempt = 1
        max_attempts = 5
        
        while attempt <= max_attempts:
            try:
                if not self._check_rate_limit():
                    return None
                    
                return self._execute_aider_command(prompt)
                    
            except Exception as e:
                error_str = str(e).lower()
                # Detect Anthropic rate limit errors
                if any(msg in error_str for msg in ['rate limit', 'too many requests', '429']):
                    if attempt < max_attempts:
                        wait_time = min(30 * attempt, 300)  # Max 5 min wait
                        self.logger.log(f"Rate limit hit. Waiting {wait_time}s (attempt {attempt}/{max_attempts})", 'warning')
                        time.sleep(wait_time)
                        attempt += 1
                        continue
                        
                self.logger.log(f"Error running Aider: {str(e)}\n{traceback.format_exc()}", 'error')
                return None

    def _check_rate_limit(self) -> bool:
        """Check rate limiting and wait if needed"""
        if not self.rate_limiter.should_allow_request():
            wait_time = self.rate_limiter.get_wait_time()
            self.logger.log(f"Rate limit reached. Waiting {wait_time:.1f}s", 'warning')
            return False
        return True

    def _execute_aider_command(self, prompt: str) -> Optional[str]:
        """Build and execute Aider command with proper directory handling"""
        original_dir = os.getcwd()
        try:
            os.chdir(self.mission_dir)
            
            cmd = self._build_command(prompt)
            process = self._run_process(cmd)
            result = self._handle_process_output(process)
            
            # Update rate limit metrics on success
            if result:
                self.rate_limiter.record_request()
                
            return result
            
        finally:
            os.chdir(original_dir)

    def _build_command(self, prompt: str) -> List[str]:
        """Build Aider command with current configuration"""
        return self.command_builder.build_command(
            prompt=prompt,
            files=list(self.mission_files.keys())
        )

    def _run_process(self, cmd: List[str]) -> subprocess.Popen:
        """Execute Aider process with proper environment"""
        return self.command_builder.execute_command(cmd)

    def _handle_process_output(self, process: subprocess.Popen) -> Optional[str]:
        """Parse and handle process output with error checking"""
        try:
            result = self.output_parser.parse_output(process)
            
            if result:
                # Update map after successful changes
                from services import init_services
                services = init_services(None)
                services['map_service'].update_map()
                
            return result
            
        except Exception as e:
            self.logger.log(f"Error handling process output: {str(e)}", 'error')
            return None

    def list_files(self) -> None:
        """List all text files in mission directory"""
        try:
            if not os.path.exists(self.mission_dir):
                self.logger.log("Mission directory not found", 'error')
                self.mission_files = {}
                return

            # Get ignore patterns
            ignore_patterns = self.command_builder.get_ignore_patterns(
                self.mission_dir
            )
            
            # List files
            text_files = {}
            for root, _, files in os.walk(self.mission_dir):
                for file in files:
                    if file.endswith(('.md', '.txt', '.py', '.js')):
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, self.mission_dir)
                        
                        # Skip ignored files
                        if any(pattern in rel_path for pattern in ignore_patterns):
                            continue
                            
                        text_files[file_path] = os.path.getmtime(file_path)
            
            self.mission_files = text_files
            
        except Exception as e:
            self.logger.log(f"Error listing files: {str(e)}", 'error')
            self.mission_files = {}

    def cleanup(self):
        """Cleanup agent resources"""
        try:
            # Stop agent if running
            if self.running:
                self.stop()
            
            # Restore original directory
            if hasattr(self, 'original_dir'):
                try:
                    os.chdir(self.original_dir)
                except Exception as e:
                    self.logger.log(f"Error restoring directory: {str(e)}", 'error')
            
            # Clear caches
            self._prompt_cache.clear()
            self.mission_files.clear()
            
            # Base cleanup
            super().cleanup()
            
        except Exception as e:
            self.logger.log(f"Error in cleanup: {str(e)}", 'error')
    def _log_commit_message(self, line: str):
        """Log commit message with appropriate icon"""
        COMMIT_ICONS = {
            'feat': '✨', 'fix': '🐛', 'docs': '📚', 'style': '💎',
            'refactor': '♻️', 'perf': '⚡️', 'test': '🧪', 'build': '📦',
            'ci': '🔄', 'chore': '🔧', 'revert': '⏪', 'merge': '🔗',
            'update': '📝', 'add': '➕', 'remove': '➖', 'move': '🚚',
            'cleanup': '🧹', 'format': '🎨', 'optimize': '🚀'
        }
        
        try:
            parts = line.split()
            commit_hash = parts[1]
            message = ' '.join(parts[2:])
            
            # Detect commit type
            commit_type = next((t for t in COMMIT_ICONS if message.lower().startswith(f"{t}:")), None)
            icon = COMMIT_ICONS.get(commit_type, '🔨')
            
            self.logger.log(f"{icon} {commit_hash}: {message}", 'success')
            
        except Exception as e:
            self.logger.log(f"Error parsing commit message: {str(e)}", 'error')
            self.logger.log(line, 'info')

    def _log_output_line(self, line: str):
        """Log output line with appropriate level"""
        lower_line = line.lower()
        if any(err in lower_line for err in ['error', 'exception', 'failed']):
            self.logger.log(line, 'error')
        else:
            self.logger.log(line, 'info')
