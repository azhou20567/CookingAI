from django_ai_assistant import AIAssistant, method_tool, BaseModel, Field
from openai import OpenAI
from django.conf import settings
import json
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

class CookingAIAssistant(AIAssistant):
    id = "cooking_assistant"
    name = "Cooking Assistant"
    instructions = (
        "You are an expert cooking assistant specializing in analyzing and creating recipes. "
        "Generate recipe ideas based on user input and video transcripts, including ingredients, measurements, cooking methods, and tips. "
        "Please ensure the output is in JSON format, with clear structure and no additional text."
    )
    model = "gpt-4o-mini"

    class youtubeInput(BaseModel):
        link: str = Field(description="Link to YouTube video")

    def __init__(self):
        super().__init__()
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    @method_tool(args_schema=youtubeInput)
    def generate_recipe(self, link: str, **kwargs):
        """
        Generate a recipe based on user's video input using OpenAI's API.
        Returns a detailed recipe with ingredients, tips, and detailed steps.
        """
        input_data = YouTubeTranscriptApi.get_transcript(link.split("v=")[1])

        response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.instructions
                    },
                    {
                        "role": "user",
                        "content": self._build_prompt(input_data)
                    }
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
                max_tokens=1500
            )
            
        plan_json = response.choices[0].message.content
        return json.loads(plan_json)

    
    def _build_prompt(self, input_data: str) -> str:
        prompt = f"""
        Create a recipe based on the following video transcript. The recipe should include a list of ingredients with measurements, cooking methods, and any tips or variations. 
        Ensure the output is in JSON format with clear structure and no additional text.

        
        Output format (JSON):
        {{
            "data": {{
                "title": "[recipe title]",
                "source": "[YouTube video URL or name]",
                "servings": "[number of servings]",
                "prep_time": "[preparation time]",
                "cook_time": "[cooking time]",
                "cuisine": "[type of cuisine]"
            }},
            "ingredients": [
                {{
                    "name": "[ingredient name]",
                    "amount": "[quantity]",
                    "unit": "[measurement unit]",
                    "notes": "[optional preparation notes]"
                }}
            ],
            "instructions": [
                {{
                    "step": [step number],
                    "description": "[detailed cooking instruction]",
                    "tips": "[optional tips or variations]"
                }}
            ],
            "notes": {{
                "serving_suggestions": "[how to serve the dish]",
                "storage": "[storage instructions]",
                "variations": "[optional ingredient substitutions or variations]"
            }}
        }}
        """
        return prompt.strip()