"""
ProductionAgent - Agent responsible for content creation and implementation.

Key responsibilities:
- Creates and updates content based on specifications
- Implements changes requested by management
- Maintains content quality and consistency 
- Responds to evaluation feedback

Workflow:
1. Monitors specifications and management directives
2. Creates/updates content sections as needed
3. Validates content against requirements
4. Maintains document structure integrity
"""
from parallagon_agent import ParallagonAgent
from search_replace import SearchReplace
import anthropic
import re
from datetime import datetime
from functools import wraps

from functools import wraps

def error_handler(func):
    """Decorator for handling errors in agent methods"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            self.logger(f"[{self.__class__.__name__}] ❌ Error: {str(e)}")
            import traceback
            self.logger(traceback.format_exc())
            return args[0].get('production', '') if args else ''
    return wrapper

class ProductionAgent(ParallagonAgent):
    """Agent handling code production and implementation"""
    
    def __init__(self, config):
        super().__init__(config)
        self.client = anthropic.Anthropic(api_key=config["anthropic_api_key"])
        self.logger = config.get("logger", print)

    def determine_actions(self) -> None:
        """
        Analyze requirements and implement needed content changes.
        
        Process:
        1. Reviews specifications and management directives
        2. Identifies required content updates
        3. Implements changes while maintaining quality
        4. Validates changes against requirements
        5. Updates content sections atomically
        """
        try:
            self.logger(f"[{self.__class__.__name__}] Début de l'analyse...")

            # Extraire les sections existantes avec leur contenu complet
            existing_content = {}
            current_section = None
            current_lines = []
            
            for line in self.current_content.split('\n'):
                if line.startswith('# '):
                    if current_section:
                        existing_content[current_section] = {
                            'content': '\n'.join(current_lines[1:]).strip(),  # Exclure la ligne de titre
                            'full': '\n'.join(current_lines)  # Contenu complet avec titre
                        }
                    current_section = line[2:].strip()
                    current_lines = [line]
                else:
                    current_lines.append(line)
                    
            if current_section:
                existing_content[current_section] = {
                    'content': '\n'.join(current_lines[1:]).strip(),
                    'full': '\n'.join(current_lines)
                }

            # Obtenir les suggestions du LLM
            context = {
                "production": self.current_content,
                "other_files": self.other_files
            }
            
            response = self._get_llm_response(context)
            
            # Extraire les suggestions du LLM
            new_sections = {}
            current_section = None
            current_lines = []
            
            for line in response.split('\n'):
                if line.startswith('# '):
                    if current_section:
                        new_sections[current_section] = '\n'.join(current_lines[1:]).strip()
                    current_section = line[2:].strip()
                    current_lines = [line]
                else:
                    current_lines.append(line)
                    
            if current_section:
                new_sections[current_section] = '\n'.join(current_lines[1:]).strip()

            # Fusionner en ne modifiant que les sections vides
            final_sections = []
            
            for section in existing_content:
                if (existing_content[section]['content'].strip() == '' or 
                    existing_content[section]['content'].strip() == '[En attente de contenu]'):
                    # Section vide ou avec placeholder - utiliser nouvelle suggestion
                    if section in new_sections:
                        final_sections.append(f"# {section}\n{new_sections[section]}")
                    else:
                        final_sections.append(existing_content[section]['full'])
                else:
                    # Section avec contenu existant - préserver
                    final_sections.append(existing_content[section]['full'])

            # Mettre à jour le contenu
            self.new_content = '\n\n'.join(final_sections)
            if self.new_content != self.current_content:
                self.update()
                self.logger(f"[{self.__class__.__name__}] ✓ Contenu mis à jour en préservant l'existant")
            else:
                self.logger(f"[{self.__class__.__name__}] Aucune modification nécessaire")
                
        except Exception as e:
            self.logger(f"[{self.__class__.__name__}] ❌ Erreur lors de l'analyse: {str(e)}")
            import traceback
            self.logger(traceback.format_exc())

    def _get_llm_response(self, context: dict) -> str:
        """
        Get LLM response for content creation and updates.
        
        Process:
        1. Analyzes current content and requirements
        2. Generates appropriate content updates
        3. Ensures content quality and consistency
        4. Validates response format
        
        Args:
            context: Current content state and requirements
            
        Returns:
            str: Validated content updates
        """
        """
        Get LLM response for content creation and updates.
        
        Process:
        1. Analyzes current content and requirements
        2. Generates appropriate content updates
        3. Ensures content quality and consistency
        4. Validates response format
        
        Args:
            context: Current content state and requirements
            
        Returns:
            str: Validated content updates
        """
        try:
            self.logger(f"[{self.__class__.__name__}] Calling LLM API...")
            
            prompt = self._build_prompt(context)
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text
            
            # Si le LLM indique qu'aucun changement n'est nécessaire
            if content.strip() == "NO_CHANGES":
                self.logger(f"[{self.__class__.__name__}] No changes needed")
                return context['production']
                
            return content
                
        except Exception as e:
            self.logger(f"[{self.__class__.__name__}] Error calling LLM: {str(e)}")
            import traceback
            self.logger(traceback.format_exc())
            return context['production']

    def _extract_section(self, content: str, section_name: str) -> str:
        """
        Extract content of a specific management section.
        
        Used for:
        - Isolating current directives
        - Accessing task lists
        - Retrieving action history
        
        Args:
            content: Full management content
            section_name: Name of section to extract
            
        Returns:
            str: Content of specified section
        """
        pattern = f"# {section_name}\n(.*?)(?=\n#|$)"
        matches = list(re.finditer(pattern, content, re.DOTALL))
        
        if len(matches) == 0:
            print(f"[{self.__class__.__name__}] Section '{section_name}' not found")
            return ""
        elif len(matches) > 1:
            print(f"[{self.__class__.__name__}] Warning: Multiple '{section_name}' sections found, using first one")
            
        return matches[0].group(1).strip()

    def _format_other_files(self, files: dict) -> str:
        """
        Format other files content for production context.
        
        Organizes:
        - Specifications requirements
        - Management directives
        - Evaluation feedback
        - Related content references
        
        Args:
            files: Dictionary of file contents
            
        Returns:
            str: Formatted context for content decisions
        """
        """
        Format other files content for production context.
        
        Organizes:
        - Specifications requirements
        - Management directives
        - Evaluation feedback
        - Related content references
        
        Args:
            files: Dictionary of file contents
            
        Returns:
            str: Formatted context for content decisions
        """
        result = []
        for file_path, content in files.items():
            result.append(f"=== {file_path} ===\n{content}\n")
        return "\n".join(result)

    def _build_prompt(self, context: dict) -> str:
        """
        Build prompt for content creation and updates.
        
        Includes:
        - Current content state
        - Required changes and updates
        - Quality requirements
        - Format specifications
        - Content guidelines
        
        Args:
            context: Current project state
            
        Returns:
            str: Content creation/update prompt
        """
        """
        Build prompt for content creation and updates.
        
        Includes:
        - Current content state
        - Required changes and updates
        - Quality requirements
        - Format specifications
        - Content guidelines
        
        Args:
            context: Current project state
            
        Returns:
            str: Content creation/update prompt
        """
        return f"""Vous êtes le ProductionAgent, responsable UNIQUEMENT du contenu des sections.

IMPORTANT - VOS LIMITES :
- Vous ne pouvez PAS créer de nouvelles sections
- Vous ne pouvez PAS supprimer de sections existantes
- Vous ne pouvez PAS modifier la structure du document
- Vous pouvez UNIQUEMENT remplir et mettre à jour le contenu des sections existantes

Contexte actuel :
{self._format_other_files(context['other_files'])}

Votre rôle :
1. Analyser les sections existantes et leurs contraintes
2. Créer ou mettre à jour le contenu pour respecter ces contraintes
3. Assurer la cohérence du contenu entre les sections
4. Répondre aux demandes de modifications du ManagementAgent

Pour chaque section :
1. Vérifiez les contraintes définies
2. Produisez un contenu qui :
   - Répond précisément aux exigences
   - Respecte le format demandé
   - S'intègre logiquement dans l'ensemble
   - Est clair et bien structuré

Format de réponse :
- Conservez EXACTEMENT la structure existante
- Modifiez UNIQUEMENT le contenu entre les titres
- Respectez la hiérarchie des sections
- Ne créez PAS de nouvelles sections

Si une section nécessite une modification structurelle :
- NE LA FAITES PAS vous-même
- Signalez-le au ManagementAgent qui coordonnera avec le SpecificationsAgent

Retournez soit :
1. "NO_CHANGES" si aucune modification n'est nécessaire
2. Le contenu mis à jour en respectant strictement la structure existante"""
    def _extract_sections(self, content: str) -> dict:
        """
        Extract sections from content while preserving hierarchy.
        
        Used for:
        - Maintaining document structure
        - Processing section-specific updates
        - Preserving content organization
        
        Args:
            content: Full document content
            
        Returns:
            dict: Mapping of section names to content
        """
        """
        Extract sections from content while preserving hierarchy.
        
        Used for:
        - Maintaining document structure
        - Processing section-specific updates
        - Preserving content organization
        
        Args:
            content: Full document content
            
        Returns:
            dict: Mapping of section names to content
        """
        sections = {}
        current_section = None
        current_content = []
        
        for line in content.split('\n'):
            if line.startswith('# '):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = line.strip()
                current_content = []
            else:
                current_content.append(line)
                
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()
            
        return sections
