import os
import json
import time
import sys
import random
import threading
import signal
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
import traceback
from utils.logger import Logger
from utils.path_manager import PathManager
from utils.exceptions import ServiceError
from services.agent_service import AgentService
from agents.base.agent_base import AgentBase

# Known Aider initialization error patterns
AIDER_INIT_ERRORS = [
    "Can't initialize prompt toolkit",
    "No Windows console found", 
    "aider.chat/docs/troubleshooting/edit-errors.html"
]

class TeamService:
    """Service simplifié pour la gestion des équipes en CLI"""
    
    def __init__(self, _):  # Keep parameter for compatibility but don't use it
        """Initialize with minimal dependencies"""
        self.logger = Logger()
        self.agent_service = AgentService(None)
        self.predefined_teams = self._load_predefined_teams()
        self.max_concurrent_agents = 3  # Maximum concurrent agents
        self._agent_queue = Queue()  # Agent queue
        self._active_agents = set()  # Active agents tracking
        self._team_lock = threading.Lock()

    def _load_predefined_teams(self) -> List[Dict]:
        """Load team configurations from teams/ directory"""
        teams = []
        
        try:
            # Get KinOS installation directory - it's where this team_service.py file is located
            kinos_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            teams_dir = os.path.join(kinos_root, "teams")
            
            # Scan teams directory
            if not os.path.exists(teams_dir):
                print(f"\nTeams directory not found: {teams_dir}")
                return []
                
            # List teams directory contents (sans affichage)
            for item in os.listdir(teams_dir):
                config_path = os.path.join(teams_dir, item, "config.json")
                    
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            team_config = json.load(f)
                                
                        # Validate required fields
                        if 'id' not in team_config:
                            team_config['id'] = item
                                
                        if 'name' not in team_config:
                            team_config['name'] = item.replace('_', ' ').title()
                                
                        if 'agents' not in team_config:
                            print(f"No agents defined in {config_path}")
                            continue
                                
                        teams.append(team_config)
                        print(f"Loaded team configuration: {team_config['id']}")
                            
                    except Exception as e:
                        print(f"Error loading team config {config_path}: {str(e)}")
                        continue

            if not teams:
                print("\nNo team configurations found")
                # Add default team as fallback
                teams.append({
                    'id': 'default',
                    'name': 'Default Team',
                    'agents': ['specifications', 'management', 'evaluation']
                })
                
            return teams
            
        except Exception as e:
            print(f"\nError loading team configurations: {str(e)}")
            return [{
                'id': 'default',
                'name': 'Default Team',
                'agents': ['specifications', 'management', 'evaluation']
            }]

    def _normalize_agent_names(self, team_agents: List[str]) -> List[str]:
        """Normalize agent names"""
        normalized = []
        for agent in team_agents:
            norm_name = agent.lower().replace('agent', '').strip()
            normalized.append(norm_name)
        return normalized

    def _normalize_team_id(self, team_id: str) -> str:
        """Normalize team ID to handle different separator styles"""
        # Convert to lowercase and replace underscores and spaces with hyphens
        normalized = team_id.lower().replace('_', '-').replace(' ', '-')
        return normalized

    def start_team(self, team_id: str, base_path: Optional[str] = None) -> Dict[str, Any]:
        """Start team in current/specified directory"""
        started_agents = []  # Track started agents
        original_sigint_handler = signal.getsignal(signal.SIGINT)  # Save original handler
        
        try:
            # Temporarily disable Ctrl+C
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            
            mission_dir = base_path or os.getcwd()
            
            # Normalize the requested team ID
            normalized_id = self._normalize_team_id(team_id)
            
            # Find team with normalized ID comparison
            team = next(
                (t for t in self.predefined_teams 
                 if self._normalize_team_id(t['id']) == normalized_id),
                None
            )
            
            if not team:
                available_teams = [t['id'] for t in self.predefined_teams]
                self.logger.log(
                    f"Team {team_id} not found. Available teams: {available_teams}",
                    'error'
                )
                raise ValueError(f"Team {team_id} not found")

            # Get services once and reuse
            from services import init_services
            services = init_services(None)
            phase_service = services['phase_service']
            map_service = services['map_service']
            
            print(f"[DEBUG] Services initialized - phase_service id: {id(phase_service)}")

            # Generate map first to get token count
            map_service.generate_map()
            
            # Get phase status info directly from phase service
            phase_status = phase_service.get_status_info()
            
            # Log phase status with EXACT values from phase_status
            self.logger.log(
                f"Current phase: {phase_status['phase']}\n"
                f"Total tokens: {phase_status['total_tokens']:,}\n"
                f"Usage: {phase_status['usage_percent']:.1f}%\n"
                f"Status: {phase_status['status_message']}\n"
                f"Headroom: {phase_status['headroom']:,} tokens", 
                'info'
            )

            # Filter and weight agents based on phase
            filtered_agents = self._filter_agents_by_phase(team['agents'], phase_status['phase'])
            
            if not filtered_agents:
                self.logger.log(
                    f"No agents available for phase {phase_status['phase']}. "
                    f"Original agents: {[a['name'] if isinstance(a, dict) else a for a in team['agents']]}", 
                    'warning'
                )
                return {
                    'team_id': team['id'],
                    'mission_dir': mission_dir,
                    'agents': [],
                    'phase': phase_status['phase'],
                    'status': 'no_agents_for_phase'
                }

            # Convert string agent names to dict format with weights
            normalized_agents = []
            phase_config = team.get('phase_config', {}).get(phase_status['phase'].lower(), {})
            phase_agents = {a['name']: a.get('weight', 0.5) for a in phase_config.get('active_agents', [])}
            
            for agent in filtered_agents:
                if isinstance(agent, dict):
                    # Keep existing dict format but override weight if in phase config
                    agent_copy = agent.copy()
                    if agent['name'] in phase_agents:
                        agent_copy['weight'] = phase_agents[agent['name']]
                    normalized_agents.append(agent_copy)
                else:
                    # Convert string to dict with weight from phase config or default
                    normalized_agents.append({
                        'name': agent,
                        'type': 'aider',  # default type
                        'weight': phase_agents.get(agent, 0.5)
                    })

            # Initialize filtered agents with error handling
            try:
                config = {'mission_dir': mission_dir}
                self.agent_service.init_agents(config, filtered_agents)
            except Exception as init_error:
                self.logger.log(f"Error initializing agents: {str(init_error)}", 'error')
                return {
                    'team_id': team['id'],
                    'mission_dir': mission_dir,
                    'agents': [],
                    'phase': phase_status['phase'],
                    'status': 'initialization_failed'
                }

            # Randomize agent order
            random_agents = filtered_agents.copy()
            random.shuffle(random_agents)

            # Create thread pool with error handling
            with ThreadPoolExecutor(max_workers=self.max_concurrent_agents) as executor:
                # Function to start an agent with better error handling
                def start_agent(agent_name: str) -> bool:
                    try:
                        self.logger.log(f"Starting agent: {agent_name}", 'info')
                        # Ignore known Aider initialization errors
                        try:
                            success = self.agent_service.toggle_agent(agent_name, 'start', mission_dir)
                            if success:
                                with self._team_lock:
                                    started_agents.append(agent_name)
                            return success
                        except Exception as e:
                            error_msg = str(e)
                            if not any(err in error_msg for err in AIDER_INIT_ERRORS):
                                self.logger.log(f"Error starting agent {agent_name}: {str(e)}", 'error')
                            return False
                    except Exception as e:
                        self.logger.log(f"Critical error starting agent {agent_name}: {str(e)}", 'error')
                        return False

                # Submit initial batch of agents with error handling
                futures = []
                initial_batch = random_agents[:self.max_concurrent_agents]
                remaining_agents = random_agents[self.max_concurrent_agents:]

                for agent_config in initial_batch:
                    try:
                        # Extract agent name from config dict
                        agent_name = agent_config['name'] if isinstance(agent_config, dict) else agent_config
                        
                        futures.append(executor.submit(start_agent, agent_name))
                        time.sleep(5)  # Wait 5 seconds between each initial agent
                    except Exception as e:
                        self.logger.log(f"Error submitting agent {agent_config}: {str(e)}", 'error')

                # Process results and add new agents as others complete
                while futures or remaining_agents:
                    try:
                        # Wait for an agent to complete
                        done, futures = concurrent.futures.wait(
                            futures,
                            return_when=concurrent.futures.FIRST_COMPLETED,
                            timeout=10  # Add timeout to prevent hanging
                        )

                        # For each completed agent
                        for future in done:
                            try:
                                success = future.result(timeout=5)  # Add timeout for result retrieval
                                if success and remaining_agents:
                                    # Get next agent config and extract name
                                    next_agent = remaining_agents.pop(0)
                                    agent_name = next_agent['name'] if isinstance(next_agent, dict) else next_agent
                                    
                                    futures.add(executor.submit(start_agent, agent_name))
                                    time.sleep(5)  # Wait 5 seconds before starting next agent
                            except Exception as e:
                                self.logger.log(f"Error processing agent result: {str(e)}", 'error')
                    except Exception as e:
                        self.logger.log(f"Error in agent processing loop: {str(e)}", 'error')
                        break

            return {
                'team_id': team['id'],
                'mission_dir': mission_dir,
                'agents': started_agents,
                'phase': phase_status['phase'],
                'status': 'started' if started_agents else 'failed'
            }

        except Exception as e:
            self.logger.log(f"Error starting team: {str(e)}", 'error')
            # Stop any started agents in reverse order
            for agent_name in reversed(started_agents):
                try:
                    self.agent_service.toggle_agent(agent_name, 'stop', mission_dir)
                except Exception as cleanup_error:
                    self.logger.log(f"Error stopping agent {agent_name}: {str(cleanup_error)}", 'error')
            raise
            
        finally:
            # Restore original Ctrl+C handler
            signal.signal(signal.SIGINT, original_sigint_handler)

    def get_available_teams(self) -> List[Dict[str, Any]]:
        """Get list of available teams"""
        try:
            teams = [
                {
                    'id': team['id'],
                    'name': team['name'],
                    'agents': team['agents'],
                    'status': 'available'
                }
                for team in self.predefined_teams
            ]
            
            self.logger.log(f"Retrieved {len(teams)} available teams", 'info')
            return teams
        except Exception as e:
            self.logger.log(f"Error getting available teams: {str(e)}", 'error')
            raise ServiceError(f"Failed to get teams: {str(e)}")

    def launch_team(self, team_id: str, base_path: Optional[str] = None) -> Dict[str, Any]:
        """Launch a team in the specified directory"""
        try:
            # Use current directory if not specified
            mission_dir = base_path or os.getcwd()
            
            self.logger.log(f"Starting team {team_id} in {mission_dir}")

            # Validate team exists
            team = next((t for t in self.predefined_teams if t['id'] == team_id), None)
            if not team:
                raise ValueError(f"Team {team_id} not found")

            # Initialize agents
            config = {'mission_dir': mission_dir}
            self.agent_service.init_agents(config, team['agents'])

            # Start each agent
            for agent_name in team['agents']:
                try:
                    self.agent_service.toggle_agent(agent_name, 'start', mission_dir)
                    self.logger.log(f"Started agent {agent_name}")
                    time.sleep(5)
                except Exception as e:
                    self.logger.log(f"Error starting agent {agent_name}: {str(e)}", 'error')

            return {
                'team_id': team_id,
                'mission_dir': mission_dir,
                'agents': team['agents']
            }

        except Exception as e:
            self.logger.log(f"Error starting team: {str(e)}", 'error')
            raise


    def _calculate_team_metrics(self, team: Dict[str, Any], agent_status: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate performance metrics for a team"""
        try:
            if not agent_status:
                return {}

            total_agents = len(team['agents'])
            metrics = {
                'efficiency': self._calculate_efficiency(agent_status),
                'health': self._calculate_health_score(agent_status),
                'agent_stats': {
                    'total': total_agents,
                    'active': sum(1 for status in agent_status.values() if status['running']),
                    'healthy': sum(1 for status in agent_status.values() if status['health']['is_healthy'])
                }
            }

            return metrics

        except Exception as e:
            self.logger.log(f"Error calculating team metrics: {str(e)}", 'error')
            return {}

    def _calculate_efficiency(self, agent_status: Dict[str, Any]) -> float:
        """Calculate team efficiency score"""
        if not agent_status:
            return 0.0
        
        weights = {
            'health': 0.4,
            'activity': 0.3,
            'response_time': 0.2,
            'resource_usage': 0.1
        }
        
        scores = {
            'health': self._calculate_health_score(agent_status),
        }
        
        return sum(score * weights[metric] for metric, score in scores.items())

    def cleanup(self) -> None:
        """Clean up team service resources"""
        try:
            self.agent_service.stop_all_agents()
            self.teams.clear()
            self.active_team = None
        except Exception as e:
            self.logger.log(f"Error in cleanup: {str(e)}", 'error')


    def _run_agent_wrapper(self, agent_name: str, agent: 'AgentBase') -> None:
        """
        Wrapper pour exécuter un agent dans un thread avec gestion des erreurs
        
        Args:
            agent_name: Nom de l'agent
            agent: Instance de l'agent
        """
        try:
            self.log_message(f"🔄 Agent {agent_name} starting run loop", 'info')
            agent.run()  # Appel effectif de la méthode run()
        except Exception as e:
            self.log_message(
                f"💥 Agent {agent_name} crashed:\n"
                f"Error: {str(e)}\n"
                f"Traceback: {traceback.format_exc()}", 
                'error'
            )

    def _calculate_health_score(self, agent_status: Dict[str, Any]) -> float:
        """Calculate overall health score for the team"""
        try:
            if not agent_status:
                return 0.0

            total_score = 0
            for status in agent_status.values():
                if status['health']['is_healthy']:
                    total_score += 1
                else:
                    # Penalize based on consecutive no changes
                    penalty = min(status['health']['consecutive_no_changes'] * 0.1, 0.5)
                    total_score += (1 - penalty)

            return total_score / len(agent_status)

        except Exception as e:
            self.logger.log(f"Error calculating health score: {str(e)}", 'error')
            return 0.0
    def _filter_agents_by_phase(self, agents: List[Union[str, Dict]], phase: str) -> List[Dict]:
        """Filter and configure agents based on current phase"""
        try:
            # Get team configuration for the phase
            active_team = None
            for team in self.predefined_teams:
                if any(isinstance(a, dict) and a['name'] in [ag['name'] if isinstance(ag, dict) else ag for ag in agents] 
                      for a in team.get('agents', [])):
                    active_team = team
                    break

            if not active_team:
                # Return default configuration if no matching team
                return [{'name': a, 'type': 'aider', 'weight': 0.5} if isinstance(a, str) else a 
                       for a in agents]

            # Get phase configuration
            phase_config = active_team.get('phase_config', {}).get(phase.lower(), {})
            active_agents = phase_config.get('active_agents', [])

            if not active_agents:
                # Use default weights if no phase-specific config
                return [{'name': a, 'type': 'aider', 'weight': 0.5} if isinstance(a, str) else a 
                       for a in agents]

            # Build filtered and configured agents list
            filtered_agents = []
            phase_weights = {a['name']: a.get('weight', 0.5) for a in active_agents}

            for agent in agents:
                agent_name = agent['name'] if isinstance(agent, dict) else agent
                if agent_name in phase_weights:
                    # Create or update agent configuration
                    agent_config = agent.copy() if isinstance(agent, dict) else {'name': agent}
                    agent_config.update({
                        'type': agent_config.get('type', 'aider'),
                        'weight': phase_weights[agent_name]
                    })
                    filtered_agents.append(agent_config)

            self.logger.log(
                f"Filtered agents for phase {phase}:\n" +
                "\n".join(f"- {a['name']} (type: {a['type']}, weight: {a['weight']:.2f})" 
                         for a in filtered_agents),
                'debug'
            )

            return filtered_agents

        except Exception as e:
            self.logger.log(f"Error filtering agents: {str(e)}", 'error')
            return [{'name': a, 'type': 'aider', 'weight': 0.5} if isinstance(a, str) else a 
                    for a in agents]
