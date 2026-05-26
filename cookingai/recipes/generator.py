from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Protocol

import anthropic
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi, CouldNotRetrieveTranscript

ANTHROPIC_TIMEOUT_S = 120.0
TRANSCRIPT_TIMEOUT_S = 30.0


class GeneratorError(Exception):
    """Base class for recipe generation failures the view should surface to users."""


class TranscriptUnavailable(GeneratorError):
    """The video has no usable transcript (private, disabled, missing captions)."""


class GenerationFailed(GeneratorError):
    """The LLM call failed or returned output that could not be parsed."""


# ---- Recipe schema (Pydantic) ---------------------------------------------
# The Anthropic API enforces this schema server-side via output_format on
# messages.parse(), so we don't need a runtime validate_payload anymore.
# The template reads recipe.data.title, recipe.ingredients, etc., so the
# JSON shape from model_dump() is the source of truth for the rendered page.

class RecipeData(BaseModel):
    title: str
    source: str = ''
    servings: str = ''
    prep_time: str = ''
    cook_time: str = ''
    cuisine: str = ''


class Ingredient(BaseModel):
    name: str
    amount: str = ''
    unit: str = ''
    notes: str = ''


class Instruction(BaseModel):
    step: int
    description: str
    tips: str = ''


class RecipeNotes(BaseModel):
    serving_suggestions: str = ''
    storage: str = ''
    variations: str = ''


class RecipeSchema(BaseModel):
    data: RecipeData
    ingredients: list[Ingredient]
    instructions: list[Instruction]
    notes: RecipeNotes


@dataclass(frozen=True)
class GeneratedRecipe:
    video_id: str
    title: str
    payload: dict


class RecipeGenerator(Protocol):
    def generate(self, video_id: str) -> GeneratedRecipe: ...


_SYSTEM_PROMPT = (
    'You are an expert cooking assistant. Given a YouTube cooking-video transcript, '
    'extract a structured recipe: ingredients with measurements, ordered cooking '
    'instructions, and useful notes (serving, storage, variations). When the transcript '
    'is ambiguous about quantities or timing, infer reasonable defaults from culinary '
    'context rather than leaving fields empty.'
)


def _fetch_transcript(video_id: str, timeout: float = TRANSCRIPT_TIMEOUT_S) -> list[dict]:
    """Fetch a YouTube transcript with a hard timeout.

    youtube-transcript-api v1.x has no native request timeout, so we run the
    call in a worker thread and bail out after `timeout` seconds. The worker
    thread is intentionally not joined on timeout — it leaks until the
    underlying HTTP call returns, but that is preferable to wedging the
    request thread.
    """
    def _run() -> list[dict]:
        return YouTubeTranscriptApi().fetch(video_id).to_raw_data()

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_run)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as e:
            raise TranscriptUnavailable(f'Transcript fetch timed out after {timeout}s') from e
    finally:
        executor.shutdown(wait=False)


class AnthropicRecipeGenerator:
    def __init__(self, api_key: str, model: str = 'claude-opus-4-7', timeout: float = ANTHROPIC_TIMEOUT_S):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._model = model

    def generate(self, video_id: str) -> GeneratedRecipe:
        try:
            transcript_entries = _fetch_transcript(video_id)
        except CouldNotRetrieveTranscript as e:
            raise TranscriptUnavailable(str(e)) from e

        transcript_text = ' '.join(entry['text'] for entry in transcript_entries)
        user_prompt = f'Generate a recipe from this video transcript:\n\n{transcript_text}'

        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=16000,
                thinking={'type': 'adaptive'},
                system=_SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': user_prompt}],
                output_format=RecipeSchema,
            )
        except anthropic.APIError as e:
            raise GenerationFailed(f'Anthropic request failed: {e}') from e

        if response.parsed_output is None:
            raise GenerationFailed('Model did not return parseable output')

        recipe = response.parsed_output
        if not recipe.data.title.strip():
            raise GenerationFailed('Model returned an empty recipe title')

        return GeneratedRecipe(
            video_id=video_id,
            title=recipe.data.title,
            payload=recipe.model_dump(),
        )


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
    """Pick an adapter based on environment.

    - `USE_FAKE_GENERATOR=true` -> FakeRecipeGenerator (lets you run the site
      end-to-end locally without an Anthropic key).
    - `ANTHROPIC_API_KEY` set -> AnthropicRecipeGenerator (normal production path).
    - Neither -> raise GenerationFailed so the view returns a 502.

    Read lazily so `manage.py migrate` / tests don't require any of this.
    """
    import os
    if os.environ.get('USE_FAKE_GENERATOR', '').lower() == 'true':
        return FakeRecipeGenerator()
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        raise GenerationFailed(
            'ANTHROPIC_API_KEY is not configured. '
            'Set it in cookingai/.env, or set USE_FAKE_GENERATOR=true for local dev.'
        )
    return AnthropicRecipeGenerator(api_key=api_key)
