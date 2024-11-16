import sys
import threading
import queue
import time
import random
import argparse
import traceback
from cli.commands.commits import commits
from typing import List, Dict, Optional
import os
import json
from datetime import datetime
from utils.logger import Logger
from services.agent_service import AgentService
from utils.model_router import ModelRouter
from utils.path_manager import PathManager

def load_team_config(team_name: str) -> List[str]:
    """Load agent names from team config"""
    try:
        # Use PathManager to get KinOS root path
        kinos_root = PathManager.get_kinos_root()
        
        config_path = os.path.join(kinos_root, "team_types", team_name, "config.json")
        with open(config_path, 'r') as f:
            config = json.load(f)
            return [agent['name'] if isinstance(agent, dict) else agent 
                   for agent in config.get('agents', [])]
    except Exception as e:
        print(f"Error loading team config: {e}")
        return []

class AgentRunner(threading.Thread):
    """Thread class for running an agent and capturing output"""
    def __init__(self, agent_service: AgentService, team_agents: List[str], 
                 output_queue: queue.Queue, logger: Logger):
        super().__init__(daemon=True)
        self.agent_service = agent_service
        self.team_agents = team_agents  # Liste complète des agents de l'équipe
        self.output_queue = output_queue
        self.logger = logger
        self.running = True
        self.agent_type = 'aider'  # Default type

    def run(self):
        while self.running:
            try:
                # Select random agent
                self.agent_name = random.choice(self.team_agents)
                
                self.logger.log(f"Selected agent for execution: {self.agent_name}", 'debug')
                start_time = datetime.now()
            
                # Initialize agent
                agent = self.agent_service.create_agent(self.agent_name)
                if not agent:
                    self.logger.log(f"Failed to create agent: {self.agent_name}", 'error')
                    time.sleep(5)  # Wait before retrying
                    continue
                    
                # Start agent
                try:
                    agent.start()
                    
                    # Run agent's main loop with timeout
                    max_runtime = 300  # 5 minutes max runtime
                    start = time.time()
                    
                    while time.time() - start < max_runtime:
                        if not agent.running:
                            break
                            
                        try:
                            agent.run()  # Single iteration
                            time.sleep(agent.calculate_dynamic_interval())  # Use dynamic interval
                        except Exception as run_error:
                            self.logger.log(f"Error in agent run: {str(run_error)}", 'error')
                            break
                            
                    duration = (datetime.now() - start_time).total_seconds()
                    
                    # Put completion message in queue
                    self.output_queue.put({
                        'thread_id': threading.get_ident(),
                        'agent_name': self.agent_name,
                        'status': 'completed',
                        'duration': duration,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                except Exception as agent_error:
                    self.logger.log(f"Agent execution error: {str(agent_error)}", 'error')
                    
                finally:
                    # Ensure cleanup
                    try:
                        agent.cleanup()
                    except:
                        pass
                        
                # Wait before starting next agent
                time.sleep(random.uniform(10, 30))
                
            except Exception as e:
                self.output_queue.put({
                    'thread_id': threading.get_ident(),
                    'agent_name': self.agent_name,
                    'status': 'error',
                    'error': str(e),
                    'traceback': traceback.format_exc(),
                    'timestamp': datetime.now().isoformat()
                })
                time.sleep(5)

def initialize_team_structure(team_name: str, specific_name: str = None):
    """
    Initialise la structure de dossiers pour une équipe
    
    Args:
        team_name: Nom de l'équipe
        specific_name: Nom spécifique de l'agent (optionnel)
    """
    logger = Logger()
    
    # Create team directory with "team_" prefix if not already present
    team_dir_name = f"team_{team_name}" if not team_name.startswith("team_") else team_name
    team_dir = os.path.join(os.getcwd(), team_dir_name)
    
    # Create team subdirectories (excluding 'map' since we want map.md in team root)
    subdirs = ['history', 'prompts']
    for subdir in subdirs:
        os.makedirs(os.path.join(team_dir, subdir), exist_ok=True)
    
    # Default files with their content - map.md directly in team directory
    default_files = {
        'map.md': '# Project Map\n\n## Overview\n',  # Place map.md in team root
        'todolist.md': '# Todo List\n\n## Pending Tasks\n',
        'demande.md': '# Mission Request\n\n## Objective\n',
        'directives.md': '# Project Directives\n\n## Guidelines\n'
    }
    
    # Create default files in team directory
    for filename, content in default_files.items():
        file_path = os.path.join(team_dir, filename)
        
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.log(f"Created {filename} in {team_dir_name}", 'info')
    
    # Create .gitignore in team directory
    gitignore_path = os.path.join(team_dir, '.gitignore')
    gitignore_content = """# Ignore Aider and KinOS history files
.aider*
.kinos*
"""
    
    with open(gitignore_path, 'w', encoding='utf-8') as f:
        f.write(gitignore_content)
    logger.log(f"Created .gitignore in {team_dir_name}", 'info')
    
    # Create team config file
    config_path = os.path.join(team_dir, 'config.json')
    
    # Configuration par défaut
    kinos_config = {
        "name": team_name,
        "type": "book_writing",
        "paths": {
            "prompts": os.path.join(team_dir, "prompts"),
            "history": os.path.join(team_dir, "history")
        },
        "created_at": datetime.now().isoformat()
    }
    
    # Write config file
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(kinos_config, f, indent=2)
    
    logger.log(f"Created config.json in {team_dir_name}", 'info')

def run_team_loop(team_name: str, specific_name: str = None):
    """Main team execution loop"""
    logger = Logger()
    logger.log(f"🚀 Starting team loop for: {team_name}", 'debug')
    
    # Initialiser la structure de l'équipe
    initialize_team_structure(team_name, specific_name)

    agent_service = AgentService(None)
    
    # Load team configuration with enhanced logging
    agents = load_team_config(team_name)
    logger.log(f"Loaded {len(agents)} agents: {', '.join(agents)}", 'debug')
    
    if not agents:
        logger.log(f"No agents found for team: {team_name}", 'error')
        return
        
    logger.log(f"Starting team {team_name} with agents: {', '.join(agents)}")
    
    # Create output queue
    output_queue = queue.Queue()
    active_threads: Dict[int, AgentRunner] = {}
    
    logger.log("Entering main loop", 'debug')
    
    try:
        while True:  # Main loop
            logger.log("Checking agent initialization conditions", 'debug')
            
            # Clean up finished threads
            active_threads = {tid: runner for tid, runner in active_threads.items() 
                            if runner.is_alive()}
            
            logger.log(f"Active threads: {len(active_threads)}", 'debug')
            
            # Start new threads if needed
            while len(active_threads) < 3:
                # Select random agent
                agent_name = random.choice(agents)
                
                logger.log(f"Selected agent: {agent_name}", 'debug')
                
                # Start new runner
                runner = AgentRunner(agent_service, agents, output_queue, logger)
                runner.start()
                active_threads[runner.ident] = runner
                logger.log(f"Started new agent runner (total: {len(active_threads)})")
            
            # Process output queue
            try:
                msg = output_queue.get(timeout=0.1)
                logger.log(f"Received message from queue: {msg['status']}", 'warning')
            except queue.Empty:
                pass
            
            time.sleep(0.1)  # Brief sleep to prevent CPU spinning
                
    except KeyboardInterrupt:
        logger.log("Stopping team execution...")
        
        # Stop all threads
        for runner in active_threads.values():
            runner.running = False
            
        # Wait for threads to finish
        for runner in active_threads.values():
            runner.join(timeout=1.0)
            
def run_multi_team_loop(model: Optional[str] = None):
    """
    Run agents across multiple teams with optional model specification
    
    Args:
        model: Optional model to use for all agents
    """
    logger = Logger()
    logger.log("🌐 Starting multi-team agent execution", 'debug')
    
    # Dynamically detect teams in current directory
    current_dir = os.getcwd()
    team_dirs = [d.replace('team_', '') for d in os.listdir(current_dir) if d.startswith('team_')]
    
    # Ensure default team is available
    if 'default' not in team_dirs:
        team_dirs.append('default')
    
    # Initialize services
    from services import init_services
    services = init_services(None)
    
    # Set model if specified
    if model:
        model_router = services['model_router']
        if not model_router.set_model(model):
            logger.log(f"Model {model} not found. Available models:", 'warning')
            for provider, models in model_router.get_available_models().items():
                logger.log(f"{provider}: {', '.join(models)}", 'info')
            return

    team_service = services['team_service']
    agent_service = services['agent_service']
    
    # Create output queue and thread management
    output_queue = queue.Queue()
    active_threads = {}
    
    try:
        while True:
            # Clean up finished threads
            active_threads = {tid: runner for tid, runner in active_threads.items() 
                              if runner.is_alive()}
            
            # Start new threads if needed
            while len(active_threads) < 3:
                # Select random team
                team_name = random.choice(team_dirs)
                
                # Important: Set active team before creating agents
                if not team_service.set_active_team(team_name):
                    logger.log(f"Failed to set active team {team_name}", 'error')
                    continue
                
                # Load team configuration
                team_config = team_service.get_team_config(team_name)
                if not team_config:
                    logger.log(f"Could not load team config for {team_name}", 'warning')
                    continue
                
                # Select random agent from the team
                agents = team_service.get_team_agents(team_name)
                agent_name = random.choice(agents)
                
                logger.log(f"Selected team: {team_name}, Agent: {agent_name}", 'debug')
                
                # Create and start runner
                runner = AgentRunner(agent_service, agents, output_queue, logger)
                runner.start()
                active_threads[runner.ident] = runner
                
                logger.log(f"Started new agent runner (total: {len(active_threads)})")
            
            # Process output queue
            try:
                msg = output_queue.get(timeout=0.1)
                logger.log(f"Received message from queue: {msg['status']}", 'warning')
            except queue.Empty:
                pass
            
            time.sleep(0.1)  # Brief sleep to prevent CPU spinning
                
    except KeyboardInterrupt:
        logger.log("Stopping multi-team execution...")
        
        # Stop all threads
        for runner in active_threads.values():
            runner.running = False
            
        # Wait for threads to finish
        for runner in active_threads.values():
            runner.join(timeout=1.0)

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='KinOS CLI')
    parser.add_argument('command', help='Command to execute')
    parser.add_argument('--name', help='Specific agent or team name for file context')
    parser.add_argument('--model', help='Model to use (e.g. "claude-3-haiku", "gpt-4", etc.)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()

    # Configuration du logger
    logger = Logger()
    if args.verbose:
        logger.set_level('debug')

    # New run command for multi-team execution
    if args.command == "run":
        # Validate model if provided
        if args.model:
            run_multi_team_loop(args.model)
        else:
            run_multi_team_loop()
        return

    # Existing team command logic
    if not args.name:
        logger.log("Error: --name is required", 'error')
        sys.exit(1)

    # Initialiser la structure de l'équipe
    initialize_team_structure(args.command, args.name)

    # If model is specified, update ModelRouter
    if args.model:
        try:
            from services import init_services
            services = init_services(None)
            model_router = services['model_router']
                    
            if not model_router.set_model(args.model):
                logger.log(f"Model {args.model} not found. Available models:", 'warning')
                for provider, models in model_router.get_available_models().items():
                    logger.log(f"{provider}: {', '.join(models)}", 'info')
                return
                        
        except Exception as e:
            logger.log(f"Error setting model: {str(e)}", 'error')
            return

    if args.command == "commits":
        if len(sys.argv) < 3:
            print("Usage: kin commits <generate>")
            return
        if sys.argv[2] == "generate":
            from utils.generate_commit_log import generate_commit_log
            generate_commit_log()
    else:
        # Execute team command
        team_name = args.command
        run_team_loop(team_name, args.name)

if __name__ == "__main__":
    main()
