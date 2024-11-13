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

from services import init_services

class TeamService:
    """Service simplifié pour la gestion des équipes en CLI"""
    
    def __init__(self, _):  # Keep parameter for compatibility but don't use it
        """Initialize with minimal dependencies"""
        self.logger = Logger()
        self.agent_service = AgentService(None)
        self.predefined_teams = self._load_predefined_teams()
        self.max_concurrent_agents = 3  # Maximum concurrent agents
        self._agent_queue = Queue()  # Agent queue
        self._active_agents = []  # List for active agents
        self._waiting_agents = []  # List for waiting agents
        self._started_agents = []  # List for started agents
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
    
    def _manage_agent_collections(self, agent_name: str, action: str) -> None:
        """Helper to safely manage agent collections"""
        try:
            if action == 'start':
                if agent_name not in self._active_agents:
                    self._active_agents.append(agent_name)
                if agent_name not in self._started_agents:
                    self._started_agents.append(agent_name)
                if agent_name in self._waiting_agents:
                    self._waiting_agents.remove(agent_name)
            elif action == 'stop':
                if agent_name in self._active_agents:
                    self._active_agents.remove(agent_name)
                if agent_name not in self._waiting_agents:
                    self._waiting_agents.append(agent_name)
        except Exception as e:
            self.logger.log(f"Error managing agent collections: {str(e)}", 'error')

    def _start_agent(self, agent_name: str) -> bool:
        """Start a single agent with error handling"""
        try:
            self.logger.log(f"Starting agent {agent_name}", 'info')
            
            # Ignore known Aider initialization errors
            try:
                success = self.agent_service.toggle_agent(agent_name, 'start')
                if success:
                    self._manage_agent_collections(agent_name, 'start')
                return success
                
            except Exception as e:
                error_msg = str(e)
                # Liste des erreurs connues d'Aider à ignorer
                known_errors = [
                    "Can't initialize prompt toolkit",
                    "No Windows console found",
                    "aider.chat/docs/troubleshooting/edit-errors.html",
                    "[Errno 22] Invalid argument"  # Erreur Windows spécifique
                ]
                
                if not any(err in error_msg for err in known_errors):
                    self.logger.log(f"Error starting agent {agent_name}: {error_msg}", 'error')
                return False
                
        except Exception as e:
            self.logger.log(f"Critical error starting agent {agent_name}: {str(e)}", 'error')
            return False

    def _normalize_team_id(self, team_id: str) -> str:
        """Normalize team ID to handle different separator styles"""
        # Convert to lowercase and replace underscores and spaces with hyphens
        normalized = team_id.lower().replace('_', '-').replace(' ', '-')
        return normalized

    def start_team(self, team_id: str, base_path: Optional[str] = None) -> Dict[str, Any]:
        """Start a team with enhanced tracking and metrics"""
        metrics = TeamMetrics(
            start_time=datetime.now(),
            total_agents=0  # Will be updated after filtering
        )
        
        agent_states: Dict[str, AgentState] = {}
        
        try:
            # Get and validate team config
            team_config = TeamConfig.from_dict(self._get_team_config(team_id))
            if not team_config:
                raise TeamStartupError("Team not found", team_id)
                
            valid, error = team_config.validate()
            if not valid:
                raise TeamStartupError(error, team_id)

            # Setup and validate mission directory
            mission_dir = base_path or os.getcwd()
            
            # Initialize services and get phase
            phase_status = self._initialize_services(mission_dir)
            
            # Filter agents for current phase
            filtered_agents = self._get_phase_filtered_agents(team_config, phase_status['phase'])
            metrics.total_agents = len(filtered_agents)
            
            # Initialize agent states
            for agent in filtered_agents:
                agent_name = agent['name'] if isinstance(agent, dict) else agent
                agent_states[agent_name] = AgentState(name=agent_name)
            
            # Start agents with enhanced tracking
            startup_result = self._start_agents_with_tracking(
                filtered_agents,
                agent_states,
                metrics,
                mission_dir
            )
            
            return {
                'team_id': team_config.id,
                'mission_dir': mission_dir,
                'phase': phase_status['phase'],
                'metrics': metrics.to_dict(),
                'agent_states': {
                    name: state.__dict__ 
                    for name, state in agent_states.items()
                },
                'status': 'started' if metrics.success_rate > 0.5 else 'failed'
            }
            
        except TeamStartupError as e:
            return e.to_dict()
        except Exception as e:
            error = TeamStartupError(
                str(e), 
                team_id,
                {'type': type(e).__name__, 'traceback': traceback.format_exc()}
            )
            return error.to_dict()

        try:
            # Temporarily disable Ctrl+C
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            
            # Setup mission directory
            mission_dir = base_path or os.getcwd()
            
            # Get team configuration
            team = self._get_team_config(team_id)
            if not team:
                return self._build_error_response(team_id, "Team not found")

            # Initialize phase and map services
            phase_status = self._initialize_services(mission_dir)
            
            # Get and filter agents for current phase
            filtered_agents = self._get_phase_filtered_agents(team, phase_status['phase'])
            if not filtered_agents:
                return self._build_phase_response(team_id, mission_dir, phase_status['phase'])

            # Initialize agents
            if not self._initialize_agents(mission_dir, filtered_agents):
                return self._build_error_response(team_id, "Agent initialization failed")

            # Randomize agent order for startup
            random_agents = filtered_agents.copy()
            random.shuffle(random_agents)

            # Start agents with thread pool
            futures = []
            startup_result = self._start_agents_with_pool(
                filtered_agents,
                active_agents,
                waiting_agents,
                started_agents
            )

            # Process completed agents with started_agents list
            self._process_completed_agents(
                futures,
                active_agents,
                waiting_agents,
                random_agents,
                started_agents
            )

            return {
                'team_id': team['id'],
                'mission_dir': mission_dir,
                'agents': started_agents,
                'phase': phase_status['phase'],
                'status': 'started' if started_agents else 'failed'
            }

        except Exception as e:
            self.logger.log(f"Error starting team: {str(e)}", 'error')
            self._cleanup_started_agents(started_agents, mission_dir)
            raise

        finally:
            # Restore original Ctrl+C handler
            signal.signal(signal.SIGINT, original_sigint_handler)

    def get_team_status(self, team_id: str) -> Dict[str, Any]:
        """Get comprehensive team status"""
        try:
            team_config = self._get_team_config(team_id)
            if not team_config:
                return {'status': 'not_found', 'team_id': team_id}
                
            agent_status = {}
            for agent in team_config.agents:
                agent_name = agent['name'] if isinstance(agent, dict) else agent
                status = self.agent_service.get_agent_status(agent_name)
                agent_status[agent_name] = status
                
            return {
                'team_id': team_id,
                'status': 'active' if any(s['running'] for s in agent_status.values()) else 'inactive',
                'agents': agent_status,
                'last_update': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'team_id': team_id,
                'error': str(e)
            }

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
    def _get_team_config(self, team_id: str) -> Optional[Dict]:
        """Get team configuration by ID"""
        normalized_id = self._normalize_team_id(team_id)
        return next(
            (t for t in self.predefined_teams 
             if self._normalize_team_id(t['id']) == normalized_id),
            None
        )

    def _initialize_services(self, mission_dir: str) -> Dict[str, Any]:
        """Initialize required services"""
        services = init_services(None)
        map_service = services['map_service']
        phase_service = services['phase_service']
        
        # Generate map to get token count
        map_service.generate_map()
        
        return phase_service.get_status_info()

    def _get_phase_filtered_agents(self, team: Dict, phase: str) -> List[Dict]:
        """Get filtered agents for current phase"""
        filtered_agents = self._filter_agents_by_phase(team['agents'], phase)
        if not filtered_agents:
            self.logger.log(
                f"No agents available for phase {phase}",
                'warning'
            )
        return filtered_agents

    def _initialize_agents(self, mission_dir: str, agents: List[Dict]) -> bool:
        """Initialize agent configurations"""
        try:
            config = {'mission_dir': mission_dir}
            self.agent_service.init_agents(config, agents)
            return True
        except Exception as e:
            self.logger.log(f"Error initializing agents: {str(e)}", 'error')
            return False

    def _start_agents_with_pool(
        self,
        filtered_agents: List[Dict],
        active_agents: List[str],
        waiting_agents: List[str],
        started_agents: List[str]
    ) -> bool:
        """Start agents using thread pool"""
        # Randomize agent order
        random_agents = filtered_agents.copy()
        random.shuffle(random_agents)

        # Initialize waiting agents list
        waiting_agents.extend(
            agent['name'] if isinstance(agent, dict) else agent 
            for agent in random_agents
        )

        with ThreadPoolExecutor(max_workers=self.max_concurrent_agents) as executor:
            futures = []
            
            while waiting_agents or active_agents:
                # Calculate available slots
                available_slots = self.max_concurrent_agents - len(active_agents)

                if available_slots > 0 and waiting_agents:
                    self._start_new_agents(
                        executor,
                        waiting_agents,
                        active_agents,
                        started_agents,
                        available_slots,
                        futures
                    )

                # Wait for completions
                self._process_completed_agents(
                    futures,
                    active_agents,
                    waiting_agents,
                    random_agents
                )

                time.sleep(1)

        return True

    def _start_new_agents(
        self,
        executor: ThreadPoolExecutor,
        waiting_agents: List[str],
        active_agents: List[str],
        started_agents: List[str],
        available_slots: int,
        futures: List
    ) -> None:
        """Start new agents from waiting list"""
        agents_to_start = random.sample(
            waiting_agents,
            min(available_slots, len(waiting_agents))
        )
        
        for agent_name in agents_to_start:
            waiting_agents.remove(agent_name)
            future = executor.submit(self._start_agent, agent_name)
            futures.append(future)
            active_agents.append(agent_name)
            if agent_name not in started_agents:
                started_agents.append(agent_name)
            time.sleep(5)

    def _process_completed_agents(
        self,
        futures: List,
        active_agents: List[str],
        waiting_agents: List[str],
        random_agents: List[Dict],
        started_agents: List[str]
    ) -> None:
        """Process completed agent futures"""
        done, futures = concurrent.futures.wait(
            futures,
            return_when=concurrent.futures.FIRST_COMPLETED,
            timeout=10
        )

        for future in done:
            try:
                success = future.result(timeout=5)
                completed_agent = next(
                    agent for agent in active_agents
                    if agent in [a['name'] if isinstance(a, dict) else a 
                               for a in random_agents]
                )
                active_agents.remove(completed_agent)
                if completed_agent not in started_agents:
                    waiting_agents.append(completed_agent)
            except Exception as e:
                self.logger.log(f"Error processing agent result: {str(e)}", 'error')

    def _build_error_response(self, team_id: str, error: str) -> Dict[str, Any]:
        """Build error response dictionary"""
        return {
            'team_id': team_id,
            'mission_dir': None,
            'agents': [],
            'phase': None,
            'status': 'error',
            'error': error
        }

    def _build_phase_response(self, team_id: str, mission_dir: str, phase: str) -> Dict[str, Any]:
        """Build phase-specific response dictionary"""
        return {
            'team_id': team_id,
            'mission_dir': mission_dir,
            'agents': [],
            'phase': phase,
            'status': 'no_agents_for_phase'
        }

    def _cleanup_started_agents(self, started_agents: List[str], mission_dir: str) -> None:
        """Clean up agents on error"""
        for agent_name in reversed(started_agents):
            try:
                self.agent_service.toggle_agent(agent_name, 'stop', mission_dir)
            except Exception as cleanup_error:
                self.logger.log(f"Error stopping agent {agent_name}: {str(cleanup_error)}", 'error')
