"""
ResearchAgent - Agent for automated research using Perplexity API
"""
# Defensive import strategy for os
import sys
import importlib
import traceback

# Try multiple import strategies
def import_os():
    try:
        import os
        return os
    except ImportError:
        try:
            import posixpath as os
            return os
        except ImportError:
            # Fallback to a minimal path handling
            class MinimalOSPath:
                @staticmethod
                def join(*args):
                    return '/'.join(str(arg).replace('\\', '/') for arg in args)
                
                @staticmethod
                def path():
                    return MinimalOSPath()
                
                def exists(self, path):
                    try:
                        with open(path, 'r'):
                            return True
                    except IOError:
                        return False
            
            return MinimalOSPath()

# Import os with fallback
os = import_os()

# Rest of the imports
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

# Project-specific imports
from agents.aider.aider_agent import AiderAgent
from utils.perplexity_client import PerplexityClient
from utils.logger import Logger
from utils.path_manager import PathManager

class ResearchAgent(AiderAgent):
    """
    Agent that performs automated research using Perplexity API.
    
    Workflow:
    1. Extract research questions/topics from content
    2. Generate and execute relevant Perplexity queries
    3. Save and organize research data
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize research agent"""
        # Ensure os is available before using it
        if not hasattr(os, 'path'):
            raise ImportError("Could not import a valid path module")

        # Call parent constructor first
        super().__init__(config)
        
        # Initialize research-specific attributes
        self.data_dir = os.path.join(self.mission_dir, "research_data")
        
        # Ensure data directory exists
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except Exception as e:
            self.logger.log(f"Error creating research data directory: {str(e)}", 'error')
        
        self.research_log = os.path.join(self.data_dir, "research_log.jsonl")
        self.query_cache = {}
        
        # Load environment variables and initialize Perplexity client
        from dotenv import load_dotenv
        load_dotenv()
        
        perplexity_api_key = os.environ.get('PERPLEXITY_API_KEY')
        if not perplexity_api_key:
            raise ValueError("PERPLEXITY_API_KEY not found in .env file")
            
        self.perplexity_client = PerplexityClient(api_key=perplexity_api_key)
        
        # Load API configuration
        self.api_config = self._load_api_config()

    def _extract_research_topics(self, content: str) -> List[str]:
        """Extract research topics using Claude"""
        try:
            from anthropic import Anthropic
            client = Anthropic()
            
            prompt = f"""Analyze the following content and identify ONE claim or question that need research and references:

{content}

List the specific topic or claim that need references.
Focus on factual claims, statistics, or technical concepts that should be supported by sources.
Give some context explanation.
"""
            
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract text from response correctly
            topics = response.content[0].text
            
            # TODO: Ajouter la réponse dans le fichier de chat 
            
            self.logger.log(f"[{self.name}] Research topics : {topics}", 'info')
            return [topics]  # Return as list since code expects list
            
        except Exception as e:
            self.logger.log(f"Error extracting topics: {str(e)}", 'error')
            return []

    def _generate_query(self, topic: str) -> str:
        """Generate an optimized Perplexity query for a topic"""
        try:
            from anthropic import Anthropic
            client = Anthropic()
            
            prompt = f"""Convert this research topic into an optimized search query for Perplexity for finding academic/reliable sources:

Topic: {topic}

Generate a single search query that:
1. Is in natural language
2. Uses relevant academic/technical terms
3. Is focused and specific
4. Give the context and goal of the research

Return ONLY the query text, nothing else."""

            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            
            query = response.content[0].text.strip()
            self.logger.log(f"Generated query: {query}", 'debug')

            # TODO: Ajouter la réponse dans le fichier de chat 
            return query
            
        except Exception as e:
            self.logger.log(f"Error generating query: {str(e)}", 'error')
            return topic

    def _execute_query(self, query: str) -> Optional[Dict[str, Any]]:
        """Execute query using Perplexity API"""
        try:
            # Check cache first
            if query in self.query_cache:
                self.logger.log(f"Using cached results for: {query}", 'debug')
                return self.query_cache[query]
                
            # Execute query
            results = self.perplexity_client.execute_query(query)
            
            if results:
                # Cache results
                self.query_cache[query] = results
                self._save_research_data(query, results)

                # Log the response
                self.logger.log(f"[{self.name}] Perplexity response: {results['response']}", 'info')
                
                # Save to chat history
                chat_history_file = f".aider.{self.name}.chat.history.md"
                try:
                    with open(chat_history_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n\n--- {datetime.now().isoformat()} ---\n")
                        f.write(f"**Perplexity Query:**\n{query}\n\n")
                        f.write(f"**Perplexity Response:**\n{results['response']}\n")
                except Exception as e:
                    self.logger.log(f"Error saving Perplexity response to chat: {str(e)}", 'warning')
                
            return results
            
        except Exception as e:
            self.logger.log(f"Error executing query: {str(e)}", 'error')
            return None

    def _load_api_config(self) -> Dict[str, Any]:
        """Load Perplexity API configuration"""
        try:
            config_path = os.path.join(PathManager.get_config_path(), "perplexity_config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.logger.log(f"Error loading API config: {str(e)}", 'error')
            return {}

    def _save_research_data(self, query: str, results: Dict[str, Any]) -> bool:
        """Save research results to disk"""
        try:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'query': query,
                'results': results
            }
            
            with open(self.research_log, 'a', encoding='utf-8') as f:
                json.dump(entry, f)
                f.write('\n')
                
            return True
            
        except Exception as e:
            self.logger.log(f"Error saving research data: {str(e)}", 'error')
            return False

    def _format_research_results(self, results: List[Dict[str, Any]]) -> str:
        """Format research results for Aider prompt"""
        formatted = []
        
        for result in results:
            formatted.append(f"Topic: {result['topic']}\n")
            formatted.append(f"Query: {result['query']}\n")
            formatted.append("Findings:\n")
            formatted.append(self._format_findings(result['results']))
            formatted.append("\n---\n")
            
        return "\n".join(formatted)

    def _format_findings(self, results: Dict[str, Any]) -> str:
        """Format query results into readable findings"""
        findings = []
        
        for item in results.get('results', []):
            findings.append(f"- {item['title']}")
            findings.append(f"  Source: {item['url']}")
            findings.append(f"  Summary: {item['summary']}\n")
            
        return "\n".join(findings)

    def execute_mission(self, prompt: str) -> Optional[str]:
        """Execute research mission with topic extraction and single Perplexity query"""
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

            # Step 1: Extract research topics using Claude
            topics = self._extract_research_topics(content)

            # Step 2: Generate optimized query using Claude
            query = self._generate_query(topics[0])  # Use first/main topic
            
            # Execute single query to Perplexity
            results = self.perplexity_client.execute_query(query)
            if not results:
                self.logger.log(f"[{self.name}] No research results found", 'info')
                return None

            # Create Aider prompt
            aider_prompt = f"""Based on the research results below, update the relevant files to add appropriate references and citations.

Research Topic: {topics[0]}
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
                    f.write(f"**Research Topic:**\n{topics[0]}\n\n")
                    f.write(f"**Research Query:**\n{query}\n\n")
                    f.write(f"**Research Results:**\n{results['response']}\n\n")
                    f.write(f"**Aider Prompt:**\n{aider_prompt}\n")
            except Exception as e:
                self.logger.log(f"Error saving research chat history: {str(e)}", 'warning')

            return super()._run_aider(aider_prompt)
            
        except Exception as e:
            self.logger.log(f"Error in research mission: {str(e)}", 'error')
            return None

    def run(self):
        """Main execution loop for research agent"""
        try:
            self.logger.log(f"[{self.name}] 🚀 Starting research agent run loop", 'info')
            
            self.running = True
            while self.running:
                try:
                    # Validate mission directory
                    if not os.path.exists(self.mission_dir):
                        self.logger.log(f"[{self.name}] ❌ Mission directory not found")
                        time.sleep(60)
                        continue

                    # Update file list
                    self.list_files()
                    
                    # Get current prompt
                    prompt = self.get_prompt()
                    if not prompt:
                        self.logger.log(f"[{self.name}] ⚠️ No prompt available")
                        time.sleep(60)
                        continue
                    
                    # Execute research mission instead of normal Aider execution
                    result = self.execute_mission(prompt)
                    
                    # Update state based on result
                    self.last_run = datetime.now()
                    if result:
                        self.last_change = datetime.now()
                        self.consecutive_no_changes = 0
                    else:
                        self.consecutive_no_changes += 1
                    
                except Exception as loop_error:
                    self.logger.log(
                        f"[{self.name}] CRITICAL: Comprehensive error in run method:\n"
                        f"Type: {type(loop_error)}\n"
                        f"Error: {str(loop_error)}\n"
                        f"Traceback: {traceback.format_exc()}",
                        'critical'
                    )
                    self._handle_error('run_loop', loop_error)
                    time.sleep(5)  # Brief pause before retrying

            self.logger.log(f"[{self.name}] Run loop ended")
            
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
                self.logger.log(f"[{self.name}] Critical error in run: {str(e)}", 'error')
                self.running = False
            
        finally:
            # Ensure cleanup happens
            self.cleanup()

    def cleanup(self):
        """Cleanup research agent resources"""
        # Keep existing implementation...

    def _format_research_results(self, results: List[Dict[str, Any]]) -> str:
        """Format research results for Aider prompt"""
        # Keep existing implementation...

    def _format_findings(self, results: Dict[str, Any]) -> str:
        """Format query results into readable findings"""
        # Keep existing implementation...
