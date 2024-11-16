"""
MapService - Service for generating and managing project documentation map
"""
import os
from datetime import datetime
from typing import Dict, List, Tuple
from services.base_service import BaseService
from anthropic import Anthropic
from utils.logger import Logger
from utils.model_router import ModelProvider

class MapService(BaseService):
    """Manages project documentation mapping and size monitoring"""

    def __init__(self, _):  # Keep parameter for compatibility but don't use it
        """Initialize with minimal dependencies"""
        self.logger = Logger()
        self.map_file = "map.md"
        self.size_limits = {
            'warning': 6000,  # Tokens triggering warning (6k)
            'error': 12000    # Tokens triggering error (12k)
        }
        # Initialize Anthropic client for tokenization
        self.anthropic = Anthropic()

    def generate_map(self) -> bool:
        """Generate project map file with enhanced debugging"""
        try:
            self.logger.log("[MapService] Starting map generation", 'debug')
        
            # Scan directory
            tree_content, warnings, total_tokens = self._scan_directory(os.getcwd())
        
            self.logger.log(f"Scan complete - Total tokens: {total_tokens}", 'debug')
        
            # Format and write map content
            map_content = self._format_map_content(tree_content, warnings)
        
            success = self._write_map_file(map_content)
        
            self.logger.log(f"Map write result: {success}", 'debug')
        
            return success
        
        except Exception as e:
            import traceback
            self.logger.log(f"Map generation error: {str(e)}\n{traceback.format_exc()}", 'critical')
            return False

    def _scan_directory(self, path: str, prefix: str = "") -> Tuple[List[str], List[str], int]:
        """Scan directory recursively and return tree structure, warnings and total tokens"""
        try:
            tree_lines = []
            warnings = []
            total_tokens = 0

            # Get active team from TeamService
            try:
                from services import init_services
                services = init_services(None)
                team_service = services['team_service']
                active_team = team_service.get_active_team()
                active_team_id = active_team.get('id') if active_team else None
            except Exception as e:
                self.logger.log(f"Error getting active team: {str(e)}", 'warning')
                active_team_id = None

            # Load ignore patterns from both .gitignore and .aiderignore
            ignore_patterns = [
                '.aider*',  # Explicitly ignore all .aider files
                '.git/',
                '__pycache__/',
                'node_modules/',
                '.env',
                '*.pyc',
                '*.log'
            ]

            # Add pattern to ignore all team folders except active team
            if active_team_id:
                # Ignore all team_ folders except the active one
                for item in os.listdir(os.getcwd()):
                    if item.startswith('team_') and not item.endswith(active_team_id):
                        ignore_patterns.append(f"{item}/")
            else:
                # If no active team, ignore all team_ folders
                ignore_patterns.append('team_*/')
        
            # Add patterns from .gitignore and .aiderignore
            for ignore_file in ['.gitignore', '.aiderignore']:
                ignore_path = os.path.join(os.getcwd(), ignore_file)
                if os.path.exists(ignore_path):
                    try:
                        with open(ignore_path, 'r', encoding='utf-8') as f:
                            patterns = [
                                line.strip() for line in f.readlines()
                                if line.strip() and not line.startswith('#')
                            ]
                            ignore_patterns.extend(patterns)
                    except Exception as e:
                        self.logger.log(f"Error reading {ignore_file}: {str(e)}", 'warning')

            # Create PathSpec for pattern matching
            from pathspec import PathSpec
            from pathspec.patterns import GitWildMatchPattern
            spec = PathSpec.from_lines(GitWildMatchPattern, ignore_patterns)

            # Get and sort directory contents
            items = sorted(os.listdir(path))
        
            # Define tracked file extensions
            tracked_extensions = {
                '.md', '.txt', '.py', '.js', '.html', '.css', '.json', 
                '.yaml', '.yml', '.sh', '.bat', '.ps1', '.java', '.cpp', 
                '.h', '.c', '.cs', '.php', '.rb', '.go', '.rs', '.ts'
            }
        
            for i, item in enumerate(items):
                is_last = i == len(items) - 1
                current_prefix = prefix + ("└── " if is_last else "├── ")
                full_path = os.path.join(path, item)
                rel_path = os.path.relpath(full_path, os.getcwd())

                # Skip if matches ignore patterns - don't even add to tree
                if spec.match_file(rel_path):
                    continue
            
                if os.path.isdir(full_path):
                    # Skip certain directories
                    if item in {'__pycache__', 'node_modules', '.git', '.idea', 'venv',
                              '.pytest_cache', '__pycache__', '.mypy_cache'}:
                        continue
                        
                    tree_lines.append(f"{current_prefix}📁 {item}/")
                    sub_prefix = prefix + ("    " if is_last else "│   ")
                    sub_tree, sub_warnings, sub_tokens = self._scan_directory(full_path, sub_prefix)
                
                    if sub_tree:
                        tree_lines.extend(sub_tree)
                        warnings.extend(sub_warnings)
                        total_tokens += sub_tokens
                    else:
                        tree_lines.pop()
                
                elif any(item.endswith(ext) for ext in tracked_extensions):
                    # Double check that file isn't ignored before counting tokens
                    if not spec.match_file(rel_path):
                        try:
                            token_count = self._count_tokens(full_path)
                            total_tokens += token_count
                            status_icon = self._get_status_icon(token_count)
                        
                            size_k = token_count / 1000
                            tree_lines.append(
                                f"{current_prefix}📄 {item} ({size_k:.1f}k tokens) {status_icon}"
                            )
                        
                            warning = self._check_file_size(item, token_count)
                            if warning:
                                warnings.append(warning)
                        except Exception as e:
                            self.logger.log(f"Error processing file {item}: {str(e)}", 'warning')
                    else:
                        # File matches ignore pattern - add to tree but don't count tokens
                        tree_lines.append(f"{current_prefix}📄 {item} (ignored)")
                        
            return tree_lines, warnings, total_tokens
            
        except Exception as e:
            self.logger.log(f"Error scanning directory: {str(e)}", 'error')
            return [], [], 0

    def _count_tokens(self, file_path: str) -> int:
        """Count number of tokens in a file using current model's tokenizer"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Get ModelRouter for token counting
            from services import init_services
            services = init_services(None)
            model_router = services['model_router']
            
            # Use appropriate tokenizer based on provider
            if model_router.current_provider == ModelProvider.ANTHROPIC:
                return len(model_router.clients['anthropic'].count_tokens(content))
            elif model_router.current_provider == ModelProvider.OPENAI:
                import tiktoken
                encoding = tiktoken.encoding_for_model(model_router.current_model)
                return len(encoding.encode(content))
            else:
                # Fallback estimation
                return len(content.split()) * 1.3
                
        except Exception as e:
            self.logger.log(f"Error counting tokens in {file_path}: {str(e)}", 'error')
            return 0

    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored in map"""
        ignore_patterns = [
            '.git/',
            '__pycache__/',
            'node_modules/',
            '.env',
            '.aider*',
            '*.pyc',
            '*.log'
        ]
        
        for pattern in ignore_patterns:
            if pattern in file_path:
                return True
        return False

    def _get_status_icon(self, token_count: int) -> str:
        """Get status icon based on token count"""
        if token_count > self.size_limits['error']:
            return "🔴"
        elif token_count > self.size_limits['warning']:
            return "⚠️"
        return "✓"

    def _check_file_size(self, filename: str, token_count: int) -> str:
        """Generate warning message if file exceeds size limits"""
        if token_count > self.size_limits['error']:
            return f"🔴 {filename} needs consolidation (>{self.size_limits['error']/1000:.1f}k tokens)"
        elif token_count > self.size_limits['warning']:
            return f"⚠️ {filename} approaching limit (>{self.size_limits['warning']/1000:.1f}k tokens)"
        return ""

    def _format_agent_info(self, agent_name: str, weight: float, agent_type: str) -> str:
        """Format agent information for map display"""
        type_icons = {
            'aider': '🔧',
            'research': '🔍'
        }
        icon = type_icons.get(agent_type, '❓')
        return f"{icon} {agent_name} (type: {agent_type}, weight: {weight:.2f})"

    def _format_map_content(self, tree_content: List[str], warnings: List[str]) -> str:
        """Format complete map content"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
            content = [
                "# Project Map (READONLY FILE)",
                "\nCe document est une carte dynamique du projet qui est automatiquement mise à jour.",
                f"\nGenerated: {timestamp}\n",
                "\n## Document Tree",
                "📁 Project"
            ]
        
            content.extend(tree_content)
        
            if warnings:
                content.extend([
                    "\n## Warnings",
                    *warnings
                ])
            
            return "\n".join(content)
        
        except Exception as e:
            self.logger.log(f"Error formatting map content: {str(e)}", 'error')
            return ""

    def _write_map_file(self, content: str) -> bool:
        """Write content to map file with atomic write"""
        try:
            # Écrire d'abord dans un fichier temporaire
            temp_file = f"{self.map_file}.tmp"
            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())  # Force l'écriture sur le disque
                    
                # Renommage atomique
                os.replace(temp_file, self.map_file)
                
                self.logger.log("Map file updated successfully", 'debug')
                return True
                
            finally:
                # Nettoyer le fichier temporaire si il existe encore
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                        
        except Exception as e:
            self.logger.log(f"Error writing map file: {str(e)}", 'error')
            return False

    def _ensure_map_file_writeable(self) -> bool:
        """Ensure map file is writable"""
        try:
            map_path = os.path.join(os.getcwd(), self.map_file)
            
            # Create file if it doesn't exist
            if not os.path.exists(map_path):
                try:
                    with open(map_path, 'w', encoding='utf-8') as f:
                        f.write("# Project Map\n\nInitial map generation.")
                    self.logger.log("Created new map file", 'info')
                    return True
                except Exception as create_error:
                    self.logger.log(f"Error creating map file: {str(create_error)}", 'error')
                    return False
            
            # Remove read-only attribute
            import stat
            try:
                current_permissions = os.stat(map_path).st_mode
                os.chmod(map_path, current_permissions | stat.S_IWRITE)
                self.logger.log("Removed read-only attribute from map file", 'debug')
                return True
            except Exception as perm_error:
                self.logger.log(f"Error modifying map file permissions: {str(perm_error)}", 'error')
                return False
            
        except Exception as e:
            self.logger.log(f"Error ensuring map file writability: {str(e)}", 'error')
            return False

    def update_map(self) -> bool:
        """Update map after file changes with comprehensive logging"""
        try:
            # Ensure map file is writable first
            if not self._ensure_map_file_writeable():
                self.logger.log("Could not make map file writable", 'error')
                return False
            
            # Rest of the existing update_map method...
            self.logger.log("Starting comprehensive map update", 'debug')
            
            # Validate mission directory
            mission_dir = os.getcwd()
            if not os.path.exists(mission_dir):
                self.logger.log(f"Mission directory not found: {mission_dir}", 'error')
                return False
            
            # Ensure map file can be written
            map_path = os.path.join(mission_dir, self.map_file)
            try:
                # Check write permissions
                if os.path.exists(map_path) and not os.access(map_path, os.W_OK):
                    self.logger.log(f"Map file not writable: {map_path}", 'error')
                    return False
            except Exception as perm_error:
                self.logger.log(f"Permission check error: {str(perm_error)}", 'error')
                return False
            
            # Vérifier si le fichier existe et est accessible en écriture
            if os.path.exists(self.map_file):
                # Sauvegarder la dernière modification
                last_modified = os.path.getmtime(self.map_file)
            else:
                last_modified = 0

            # Generate map with comprehensive error handling
            success = self.generate_map()
            
            if success:
                # Vérifier que le fichier a bien été mis à jour
                try:
                    new_modified = os.path.getmtime(self.map_file)
                    if new_modified <= last_modified:
                        self.logger.log("Map file not updated - forcing regeneration", 'warning')
                        # Forcer une nouvelle génération
                        success = self.generate_map()
                except Exception as check_error:
                    self.logger.log(f"Error checking map update: {str(check_error)}", 'error')
                    success = False
            
            if success:
                self.logger.log("Map successfully updated", 'info')
            else:
                self.logger.log("Map update failed", 'warning')
            
            return success
        
        except Exception as e:
            import traceback
            self.logger.log(f"Comprehensive map update error: {str(e)}\n{traceback.format_exc()}", 'critical')
            return False

    def get_map_content(self) -> str:
        """Get current map content"""
        try:
            if os.path.exists(self.map_file):
                with open(self.map_file, 'r', encoding='utf-8') as f:
                    return f.read()
            return ""
        except Exception as e:
            self.logger.log(f"Error reading map file: {str(e)}", 'error')
            return ""
