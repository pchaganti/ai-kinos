import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from utils.decorators import safe_operation
from utils.exceptions import ServiceError
from services.base_service import BaseService
from utils.path_manager import PathManager

class NotificationService(BaseService):
    def __init__(self, web_instance):
        super().__init__(web_instance)
        self.notifications_queue = []
        self.content_cache = {}
        self.last_modified = {}
        self.last_content = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_notifications = 0
        
    def _format_notification(self, message: str, panel: str, flash: bool = False) -> dict:
        """Centralized notification formatting"""
        return {
            'type': 'info',
            'message': message,
            'panel': panel,
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'flash': flash,
            'id': len(self.notifications_queue),
            'websocket_url': '/ws/notifications'  # Use relative path
        }
        
    @safe_operation()
    def check_content_updates(self) -> None:
        """Check for content updates in all monitored files"""
        try:
            current_content = {}
            # Ne vérifier que les fichiers qui existent physiquement
            for file_name, path in self.web_instance.file_paths.items():
                if os.path.exists(path):
                    content = self.web_instance.file_manager.read_file(file_name)
                    if content is not None:
                        current_content[file_name] = content

            for file_name, content in current_content.items():
                if content is None:
                    continue
                    
                if (file_name not in self.last_content or 
                    content != self.last_content[file_name]):
                    self.handle_content_change(
                        file_name, 
                        content,
                        panel_name=file_name.split('.')[0].capitalize()
                    )
                    self.last_content[file_name] = content

        except Exception as e:
            self.logger.log(f"Error checking content updates: {str(e)}", 'error')
            raise ServiceError(f"Failed to check content updates: {str(e)}")

    @safe_operation()
    def _handle_file_change(self, file_path: str, content: str) -> None:
        """Gestion centralisée des changements de fichiers"""
        try:
            if not self._validate_path(file_path):
                return
                
            if content and content.strip():
                self.content_cache[file_path] = content
                self.last_modified[file_path] = time.time()
                
            self._notify_change(file_path)
            
        except Exception as e:
            self.logger.log(f"Error handling file change: {str(e)}", 'error')

    def handle_content_change(self, file_path: str, content: str, 
                            panel_name: str = None, flash: bool = False) -> bool:
        """Handle content change notifications with cache metrics"""
        try:
            start_time = time.time()
            self._validate_input(file_path=file_path, content=content)
            self._log_operation('handle_content_change', 
                              file_path=file_path, 
                              panel_name=panel_name,
                              flash=flash)
                              
            # Track cache performance
            if file_path in self.content_cache:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            
            # Handle file change using centralized method
            self._handle_file_change(file_path, content)
            
            # Create notification
            if not panel_name:
                panel_name = os.path.splitext(os.path.basename(file_path))[0].capitalize()
            
            notification = {
                'type': 'info',
                'message': f'Content updated in {panel_name}',
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'panel': panel_name,
                'status': os.path.basename(file_path),
                'operation': 'flash_tab' if flash else 'update',
                'id': len(self.notifications_queue),
                'flash': flash
            }
            
            self.notifications_queue.append(notification)
            return True
            
        except Exception as e:
            return self._handle_error('handle_content_change', e, False)

    @safe_operation()
    def get_notifications(self) -> List[Dict[str, Any]]:
        """Get and clear pending notifications with metrics"""
        try:
            self._log_operation('get_notifications')
            current_time = datetime.now()
            self.total_notifications += len(self.notifications_queue)
            
            # Log cache performance metrics periodically
            if self.total_notifications % 100 == 0:
                total_cache_ops = self.cache_hits + self.cache_misses
                hit_rate = (self.cache_hits / total_cache_ops * 100) if total_cache_ops > 0 else 0
                self.logger.log(
                    f"Cache performance - Hits: {self.cache_hits}, "
                    f"Misses: {self.cache_misses}, "
                    f"Hit rate: {hit_rate:.1f}%",
                    'info'
                )
            
            # Filter notifications from last 3 seconds
            recent_notifications = []
            for n in self.notifications_queue:
                try:
                    notif_time = datetime.strptime(n['timestamp'], "%H:%M:%S")
                    notif_datetime = current_time.replace(
                        hour=notif_time.hour,
                        minute=notif_time.minute,
                        second=notif_time.second
                    )
                    
                    if (current_time - notif_datetime).total_seconds() <= 3:
                        recent_notifications.append(n)
                except ValueError as e:
                    self.logger.log(f"Invalid timestamp format in notification: {e}", 'error')
                    continue

            # Clear the queue after filtering
            self.notifications_queue.clear()
            
            return recent_notifications
        except Exception as e:
            return self._handle_error('get_notifications', e, [])
            
    def create_mission_file(self, file_name: str, initial_content: str = "") -> bool:
        """Create a new mission file on demand"""
        try:
            if not self.current_mission:
                return False
                
            # Use PathManager for mission path
            file_path = os.path.join(
                PathManager.get_mission_path(self.current_mission),
                file_name
            )
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(initial_content)
                
            # Add to tracked files
            base_name = os.path.splitext(file_name)[0]
            self.file_paths[base_name] = file_name
            
            return True
            
        except Exception as e:
            self.logger.log(f"Error creating file {file_name}: {str(e)}", 'error')
            return False

    def cleanup(self):
        """Cleanup notification service resources"""
        try:
            self._log_operation('cleanup')
            self.notifications_queue.clear()
            self.content_cache.clear()
            self.last_modified.clear()
            self.last_content.clear()
        except Exception as e:
            self._handle_error('cleanup', e)
