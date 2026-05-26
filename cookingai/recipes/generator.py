import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI, OpenAIError
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

OPENAI_TIMEOUT_S = 30.0
TRANSCRIPT_TIMEOUT_S = 30.0


class GeneratorError(Exception):
    """Base class for recipe generation failures the view should surface to users."""


class TranscriptUnavailable(GeneratorError):
    """The video has no usable transcript (private, disabled, missing captions)."""


class GenerationFailed(GeneratorError):
    """The LLM call failed or returned output that could not be parsed."""


@dataclass(frozen=True)
class GeneratedRecipe:
    video_id: str
    title: str
    payload: dict


class RecipeGenerator(Protocol):
    def generate(self, video_id: str) -> GeneratedRecipe: ...


def validate_payload(payload: object) -> None:
    """Raise GenerationFailed if the LLM JSON doesn't match the shape the template needs."""
    if not isinstance(payload, dict):
        raise GenerationFailed('payload is not a JSON object')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise GenerationFailed('payload.data is missing or not an object')
    if not data.get('title'):
        raise GenerationFailed('payload.data.title is missing or empty')
    if not isinstance(payload.get('ingredients'), list):
        raise GenerationFailed('payload.ingredients is missing or not a list')
    if not isinstance(payload.get('instructions'), list):
        raise GenerationFailed('payload.instructions is missing or not a list')


_PROMPT_TEMPLATE = """\
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
        {{"name": "[ingredient name]", "amount": "[quantity]", "unit": "[measurement unit]", "notes": "[optional preparation notes]"}}
    ],
    "instructions": [
        {{"step": [step number], "description": "[detailed cooking instruction]", "tips": "[optional tips or variations]"}}
    ],
    "notes": {{
        "serving_suggestions": "[how to serve the dish]",
        "storage": "[storage instructions]",
        "variations": "[optional ingredient substitutions or variations]"
    }}
}}

Transcript:
{transcript}
"""

_SYSTEM_PROMPT = (
    "You are an expert cooking assistant specializing in analyzing and creating recipes. "
    "Generate recipe ideas based on user input and video transcripts, including ingredients, "
    "measurements, cooking methods, and tips. "
    "Please ensure the output is in JSON format, with clear structure and no additional text."
)


def _fetch_transcript(video_id: str, timeout: float = TRANSCRIPT_TIMEOUT_S) -> list:
    """Fetch a YouTube transcript with a hard timeout.

    youtube-transcript-api v0.x has no native timeout option. We run the call
    in a worker thread and bail out after `timeout` seconds. The worker thread
    is intentionally not joined on timeout — it leaks until the underlying
    HTTP call returns, but that is preferable to wedging the request thread.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(YouTubeTranscriptApi.get_transcript, video_id)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as e:
            raise TranscriptUnavailable(f'Transcript fetch timed out after {timeout}s') from e
    finally:
        executor.shutdown(wait=False)


class OpenAIRecipeGenerator:
    def __init__(self, api_key: str, model: str = 'gpt-4o-mini', timeout: float = OPENAI_TIMEOUT_S):
        self._client = OpenAI(api_key=api_key, timeout=timeout)
        self._model = model

    def generate(self, video_id: str) -> GeneratedRecipe:
        try:
            transcript_entries = _fetch_transcript(video_id)
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
            raise TranscriptUnavailable(str(e)) from e

        transcript_text = ' '.join(entry['text'] for entry in transcript_entries)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {'role': 'system', 'content': _SYSTEM_PROMPT},
                    {'role': 'user', 'content': _PROMPT_TEMPLATE.format(transcript=transcript_text)},
                ],
                temperature=0.7,
                response_format={'type': 'json_object'},
                max_tokens=1500,
            )
        except OpenAIError as e:
            raise GenerationFailed(f'OpenAI request failed: {e}') from e

        raw = response.choices[0].message.content
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise GenerationFailed(f'Model returned non-JSON output: {e}') from e

        validate_payload(payload)
        title = payload['data']['title']
        return GeneratedRecipe(video_id=video_id, title=title, payload=payload)


class FakeRecipeGenerator:
    """Returns a canned recipe. For tests and local dev without API calls."""

    DEFAULT_PAYLOAD = {
        'data': {
            'title': 'Fake Test Recipe',
            'source': 'fake://test',
            'servings': '2',
            'prep_time': '5 min',
            'cook_time': '10 min',
            'cuisine': 'Test',
        },
        'ingredients': [
            {'name': 'flour', 'amount': '1', 'unit': 'cup', 'notes': ''},
        ],
        'instructions': [
            {'step': 1, 'description': 'Mix everything.', 'tips': ''},
        ],
        'notes': {
            'serving_suggestions': 'Serve immediately.',
            'storage': 'Refrigerate.',
            'variations': '',
        },
    }

    def __init__(self, payload: dict | None = None, raises: Exception | None = None):
        self._payload = payload or self.DEFAULT_PAYLOAD
        self._raises = raises

    def generate(self, video_id: str) -> GeneratedRecipe:
        if self._raises is not None:
            raise self._raises
        return GeneratedRecipe(
            video_id=video_id,
            title=self._payload['data']['title'],
            payload=self._payload,
        )


def default_generator() -> RecipeGenerator:
    """Production wiring: read API key from the environment and return an OpenAI-backed generator.

    Read lazily so that running `manage.py migrate` / tests does not require the key to be set.
    """
    import os
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        raise GenerationFailed('OPENAI_API_KEY is not configured')
    return OpenAIRecipeGenerator(api_key=api_key)
