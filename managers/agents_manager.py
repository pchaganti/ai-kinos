import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from utils.logger import Logger
import openai
from dotenv import load_dotenv

class AgentsManager:
    """Manager class for handling agents and their operations."""
    
    def __init__(self, model="gpt-4o-mini"):
        self.mission_path = None
        self.logger = Logger()
        self.model = model
        load_dotenv()  # Load environment variables
        openai.api_key = os.getenv('OPENAI_API_KEY')
        if not openai.api_key:
            raise ValueError("OpenAI API key not found in environment variables")
        
    async def generate_agents(self, mission_filepath=".aider.mission.md"):
        """
        Generate mission-specific agent prompts in parallel.
        """
        try:
            self.mission_path = mission_filepath
            self.logger.info(f"🚀 Starting agent generation for mission: {mission_filepath}")
            
            if not self._validate_mission_file():
                self.logger.error("❌ Mission file not found!")
                self.logger.info("\n📋 To start KinOS, you must:")
                self.logger.info("   1. Either create a '.aider.mission.md' file in the current folder")
                self.logger.info("   2. Or specify the path to your mission file with --mission")
                self.logger.info("\n💡 Examples:")
                self.logger.info("   kin run agents --generate")
                self.logger.info("   kin run agents --generate --mission path/to/my_mission.md")
                self.logger.info("\n📝 The mission file must contain your project description.")
                raise SystemExit(1)
                
            # List of specific agent types
            agent_types = [
                "specification",
                "management", 
                "redaction",
                "evaluation",
                "deduplication",
                "chroniqueur",
                "redondance",
                "production",
                "chercheur",
                "integration"
            ]
            
            # Create tasks for parallel execution
            tasks = []
            for agent_type in agent_types:
                tasks.append(self._generate_single_agent_async(agent_type))
                
            # Execute all tasks in parallel and wait for completion
            await asyncio.gather(*tasks)
            
        except Exception as e:
            self.logger.error(f"❌ Agent generation failed: {str(e)}")
            raise
            
    def _validate_mission_file(self):
        """
        Validate that mission file exists and is readable.
        
        Returns:
            bool: True if file is valid, False otherwise
        """
        try:
            return os.path.exists(self.mission_path) and os.access(self.mission_path, os.R_OK)
        except Exception as e:
            self.logger.error(f"⚠️ Error validating mission file: {str(e)}")
            return False
        
    async def _generate_single_agent_async(self, agent_name):
        """
        Asynchronous version of _generate_single_agent.
        """
        try:
            # Use ThreadPoolExecutor for CPU-bound operations
            with ThreadPoolExecutor() as pool:
                # Load mission content
                mission_content = await asyncio.get_event_loop().run_in_executor(
                    pool,
                    self._read_mission_content
                )
                
                # Create agent prompt
                prompt = self._create_agent_prompt(agent_name, mission_content)
                self.logger.debug(f"📝 Created prompt for agent: {agent_name}")
                
                # Make GPT call and get response
                agent_config = await asyncio.get_event_loop().run_in_executor(
                    pool,
                    lambda: self._call_gpt(prompt)
                )
                self.logger.debug(f"🤖 Received GPT response for agent: {agent_name}")
                
                # Save agent configuration
                output_path = f".aider.agent.{agent_name}.md"
                await asyncio.get_event_loop().run_in_executor(
                    pool,
                    lambda: self._save_agent_config(output_path, agent_config)
                )
                
                self.logger.success(f"✨ Agent {agent_name} successfully generated")
                
        except Exception as e:
            self.logger.error(f"Failed to generate agent {agent_name}: {str(e)}")
            raise

    def _read_mission_content(self):
        """Helper method to read mission content."""
        with open(self.mission_path, 'r') as f:
            return f.read()

    def _save_agent_config(self, output_path, content):
        """Helper method to save agent configuration."""
        with open(output_path, 'w') as f:
            f.write(content)

    def _create_agent_prompt(self, agent_name, mission_content):
        """
        Create the prompt for GPT to generate a specialized agent configuration.
        
        Args:
            agent_name (str): Name/type of the agent to generate
            mission_content (str): Content of the mission specification file
        
        Returns:
            str: Detailed prompt for agent generation
        """
        # Try to load custom prompt template
        prompt_path = f"prompts/{agent_name}.md"
        custom_prompt = ""
        
        if os.path.exists(prompt_path):
            try:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    custom_prompt = f.read()
                self.logger.info(f"📝 Using custom prompt template for {agent_name}")
            except Exception as e:
                self.logger.warning(f"⚠️ Could not load custom prompt for {agent_name}: {str(e)}")

        # Ensure we're getting the complete mission content
        self.logger.debug(f"Mission content length: {len(mission_content)} characters")
        
        return f"""
# Generate KinOS Agent Configuration

Generate a role definition and plan for the {agent_name} agent that fulfills the mission while following the analysis framework.

## Context Analysis
1. Mission Details
````
{mission_content}
````

2. Analysis Framework
````
{custom_prompt}
````

## Requirements

1. Mission Alignment
   - How agent's role serves mission objectives
   - Critical mission needs to address
   - Mission-specific success criteria

2. Framework Application
   - Apply framework questions to mission context
   - Use framework to structure mission approach
   - Define mission-specific validation points

3. Role Definition
   - Core responsibilities for mission completion
   - Interaction patterns within mission scope
   - Mission-aligned success criteria

4. High-Level Plan
   - Major mission milestones
   - Systematic approach to mission goals
   - Quality standards for mission deliverables

Your output should clearly show how this agent will contribute to mission success through the lens of the analysis framework.

Example Sections:
- Mission Understanding
- Role in Mission Completion
- Framework-Guided Approach
- Key Objectives & Milestones
- Quality Standards
- Success Criteria
"""

    def _call_gpt(self, prompt):
        """
        Make a call to GPT to generate agent configuration.
        
        Args:
            prompt (str): The prepared prompt for GPT
            
        Returns:
            str: Generated agent configuration
            
        Raises:
            Exception: If API call fails
        """
        try:
            client = openai.OpenAI()
            response = client.chat.completions.create(
                model="gpt-4o",  # Using the BIG Omni model!
                messages=[
                    {"role": "system", "content": """
# KinOS Agent Generator

You create strategic role definitions for KinOS agents by applying specialized analysis frameworks.

## Operational Context
- Agent operates through Aider file operations
- Main loop handles all triggers and timing
- Single-step file modifications only
- Directory-based mission scope

## Framework Integration
1. Question Analysis
   - Process each framework section
   - Extract relevant guidelines
   - Apply to current context

2. Role Mapping
   - Map responsibilities to framework sections
   - Align capabilities with framework requirements
   - Define boundaries using framework structure

3. Planning Through Framework
   - Use framework sections as planning guides
   - Ensure comprehensive coverage
   - Maintain framework-aligned validation

## Core Requirements
1. Mission Contribution
   - Framework-guided responsibilities
   - Framework-aligned success metrics
   - Quality standards from framework

2. Team Integration
   - Framework-based coordination
   - Shared objective alignment
   - Quality interdependencies

Remember: 
- Answer framework questions practically
- Keep focus on achievable file operations
- Use framework to structure planning
- Maintain mission alignment
"""},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=4000
            )
            
            # Extract the generated configuration from the response
            config = response.choices[0].message.content
            
            # Log full response for debugging
            self.logger.debug(f"OpenAI Response: {response}")
            
            return config
            
        except Exception as e:
            self.logger.error(f"GPT API call failed. Error: {str(e)}")
            self.logger.error(f"Last response received: {response if 'response' in locals() else 'No response'}")
            raise
