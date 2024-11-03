"""
EvaluationAgent - Agent responsible for quality control and validation
"""
from parallagon_agent import ParallagonAgent
from search_replace import SearchReplace
import re
from datetime import datetime
import anthropic

class EvaluationAgent(ParallagonAgent):
    """Agent handling quality control and validation"""
    
    def __init__(self, config):
        super().__init__(config)
        self.client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

    def determine_actions(self) -> None:
        """
        Analyze current context and determine if validation/evaluation is needed.
        """
        # Prepare context for LLM
        context = {
            "evaluation": self.current_content,
            "other_files": self.other_files
        }
        
        # Get LLM response
        response = self._get_llm_response(context)
        
        if response != self.current_content:
            # Use temporary content for replacements
            temp_content = self.current_content
            sections = ["État Actuel", "Signaux", "Contenu Principal", "Historique"]
            
            for section in sections:
                pattern = f"# {section}\n(.*?)(?=\n#|$)"
                match = re.search(pattern, response, re.DOTALL)
                if not match:
                    print(f"[{self.__class__.__name__}] {section} section not found in LLM response")
                    continue
                    
                new_section_content = match.group(1).strip()
                result = SearchReplace.section_replace(
                    temp_content,
                    section,
                    new_section_content
                )
                if result.success:
                    temp_content = result.new_content
                    
            self.new_content = temp_content
            print(f"[{self.__class__.__name__}] Changes detected:")
            print(f"Old content: {self.current_content[:100]}...")
            print(f"New content: {self.new_content[:100]}...")

    def _get_llm_response(self, context: dict) -> str:
        """Get LLM response for evaluation tasks"""
        try:
            print(f"[{self.__class__.__name__}] Calling LLM API...")  # Debug log
            prompt = f"""You are the Evaluation Agent in the Parallagon framework. Your role is to validate work and maintain evaluation.md.

Current evaluation content:
{context['evaluation']}

Other files content:
{self._format_other_files(context['other_files'])}

Your task:
1. Review work from other agents
2. Validate implementation quality
3. Check for validation requests
4. If needed, provide an updated version of evaluation.md that:
   - Evaluates code quality
   - Validates implementations
   - Provides feedback
   - Approves or requests changes
   - Maintains exact markdown structure

Focus on:
- Code quality standards
- Implementation correctness
- Documentation completeness
- Test coverage
- Performance considerations

If no changes are needed, return the exact current content.
If changes are needed, return the complete updated content.

Important:
- Keep all existing sections
- Maintain same formatting
- Only make necessary changes
- Add timestamps for new history entries
- Be precise in evaluation feedback
"""
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            print(f"[{self.__class__.__name__}] LLM response received")  # Debug log
            return response.content[0].text
        except Exception as e:
            print(f"[{self.__class__.__name__}] Error calling LLM: {str(e)}")  # Error log
            import traceback
            print(traceback.format_exc())
            return context['evaluation']

    def _extract_section(self, content: str, section_name: str) -> str:
        """Extract content of a specific section"""
        pattern = f"# {section_name}\n(.*?)(?=\n#|$)"
        matches = list(re.finditer(pattern, content, re.DOTALL))
        
        if len(matches) == 0:
            print(f"[{self.__class__.__name__}] Section '{section_name}' not found")
            return ""
        elif len(matches) > 1:
            print(f"[{self.__class__.__name__}] Warning: Multiple '{section_name}' sections found, using first one")
            
        return matches[0].group(1).strip()

    def _update_status(self, new_content: str) -> None:
        """Update status if changed"""
        old_status_match = re.search(r'\[status: (\w+)\]', self.current_content)
        new_status_match = re.search(r'\[status: (\w+)\]', new_content)
        
        if (old_status_match and new_status_match and 
            old_status_match.group(1) != new_status_match.group(1)):
            result = SearchReplace.exact_replace(
                self.current_content,
                f"[status: {old_status_match.group(1)}]",
                f"[status: {new_status_match.group(1)}]"
            )
            if result.success:
                self.current_content = result.new_content

    def _format_other_files(self, files: dict) -> str:
        """Format other files content for the prompt"""
        result = []
        for file_path, content in files.items():
            result.append(f"=== {file_path} ===\n{content}\n")
        return "\n".join(result)
