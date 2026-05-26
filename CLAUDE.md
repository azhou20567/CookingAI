# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CookingAI is a Django 5.1 web app that turns a YouTube cooking video into a structured JSON recipe. The user submits a YouTube URL; the backend pulls the transcript via `youtube_transcript_api` and asks Anthropic's Claude (`claude-opus-4-7`, adaptive thinking) to convert it into a recipe with ingredients, steps, and notes, which is then rendered with Bootstrap. Generated recipes are cached in the database keyed by `video_id`, so repeat requests don't re-hit the API.

## Running the app

All `manage.py` commands run from the inner `cookingai/` directory (the one that contains `manage.py`), not the repo root:

```powershell
cd cookingai
python manage.py migrate           # apply migrations (recipes app)
python manage.py runserver         # dev server at http://127.0.0.1:8000/
python manage.py createsuperuser   # for /admin/
```

Install dependencies with `pip install -r requirements.txt` (from the repo root). `youtube-transcript-api` is pinned to `>=1.0,<2.0`; the v1.x API is `YouTubeTranscriptApi().fetch(video_id).to_raw_data()` (instance method, not class method). v0.x crashes against YouTube's current response format with `xml.etree.ElementTree.ParseError` so do not downgrade.

### Local dev without an Anthropic key

Set `USE_FAKE_GENERATOR=true` in `cookingai/.env`. `default_generator()` will return `FakeRecipeGenerator` instead of the Anthropic adapter, so submitting any YouTube URL produces a canned recipe and lets you click through the whole UI offline. The flag takes precedence over `ANTHROPIC_API_KEY` — convenient when shadowing prod creds while developing.

## Configuration

`cookingai/.env` (loaded by `python-dotenv` from `settings.py`) holds:

- **`SECRET_KEY`** (required) — Django will refuse to start without it (intentional, `os.environ['SECRET_KEY']`).
- **`ANTHROPIC_API_KEY`** (required for generation only) — read lazily inside `default_generator()`. Tests and `manage.py migrate` run fine without it; only an actual cache-miss request will raise `GenerationFailed('ANTHROPIC_API_KEY is not configured')`.
- **`MONTHLY_GENERATION_CAP`** (optional, default `30`) — hard upper bound on successful generations per calendar month across all IPs. Stops the app from making any further Anthropic calls once hit. Counted in the `GlobalUsage` model so it survives worker restarts. Anthropic has no organization-level hard spend cap, so this is the bill-floor — at ~$0.15 worst-case per generation, 30 ≈ $5/mo.
- **`DEBUG`** (optional, default `true`) — set to `false` for prod.
- **`ALLOWED_HOSTS`** (optional, default `127.0.0.1,localhost`) — comma-separated.

For prod deploys: set `DEBUG=false`, set `ALLOWED_HOSTS=yourdomain.com`, run `python manage.py collectstatic` (writes to `cookingai/staticfiles/`, gitignored).

## Architecture

Two packages live under `cookingai/`:

- **`cookingai/`** — Django project package: `settings.py`, root `urls.py`, asgi/wsgi. No app code.
- **`recipes/`** — the only Django app. Holds `models.py` (`Recipe`), `views.py`, `forms.py`, `urls.py`, `admin.py`, the AI `generator.py`, templates, and static files.

### Request flow

1. Root `urls.py` includes `recipes.urls`, which routes `/` → `home_view`, `/youtube/` → `youtube_form_view`, `/results/<video_id>/` → `recipe_result_view`.
2. `YoutubeLinkForm.clean_youtube_link` runs the regex and stores the extracted `video_id` on `cleaned_data['video_id']` — **single source of truth for ID extraction**. The view never parses the URL itself.
3. `recipe_result_view` does **read-through caching**: looks up `Recipe.objects.get(video_id=...)`, and on a miss calls the injected `RecipeGenerator`, persists the result, then renders.
4. Generator errors are mapped to a user-visible `recipes/error.html` (HTTP 422 for transcript issues, 502 for OpenAI/JSON failures) — not raw tracebacks.

### The generator seam (`recipes/generator.py`)

`RecipeGenerator` is a `Protocol` with one method: `generate(video_id) -> GeneratedRecipe`. Two adapters satisfy it:

- `AnthropicRecipeGenerator` — fetches transcript, calls `client.messages.parse()` on `claude-opus-4-7` with `thinking={'type': 'adaptive'}` and `output_format=RecipeSchema` (a Pydantic class). The Pydantic schema is enforced server-side by Anthropic's structured-outputs feature, so the response is guaranteed to match the shape the template expects. Raises `TranscriptUnavailable` or `GenerationFailed` on known error modes.
- `FakeRecipeGenerator` — returns a canned recipe (or raises a configured exception) for tests and offline dev. **Do not mock Anthropic in tests; inject this instead.**

`recipe_result_view` takes `generator` as a kwarg defaulting to `default_generator()`. Tests should pass a `FakeRecipeGenerator()` to exercise the view without network.

Both errors derive from `GeneratorError`. If you add a new failure mode, raise a new subclass and add a branch to the view's `except` chain — don't swallow exceptions in the generator.

**Why Pydantic instead of a hand-rolled validator.** The previous OpenAI implementation called `chat.completions.create(response_format='json_object')`, which only guaranteed *parseable JSON* — the schema was described in the prompt and checked at runtime by a `validate_payload` function. The Anthropic implementation uses `messages.parse()` with `output_format=RecipeSchema`, which enforces the full schema at the API level. The runtime validator is gone; the schema in `generator.py` is the single source of truth.

**Model defaults.** `claude-opus-4-7` with `thinking={'type': 'adaptive'}` — per the claude-api skill discipline, never downgrade the model for cost without an explicit user instruction. If you want a cheaper variant, ask the user before switching.

**Timeouts.** Anthropic client uses a 120s timeout (Opus + adaptive thinking can take longer than OpenAI's gpt-4o-mini). `YouTubeTranscriptApi.fetch` still has no native timeout in v1.x, so `_fetch_transcript` runs it in a `ThreadPoolExecutor` and bails out at 30s — the worker thread is intentionally not joined on timeout (leaks until the HTTP call returns) since wedging the request thread is worse.

**Transcript errors.** `_fetch_transcript` catches `CouldNotRetrieveTranscript`, the base class for every v1.x transcript failure (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, RequestBlocked, IpBlocked, AgeRestricted, etc.). All map to `TranscriptUnavailable` → 422 in the view.

**Cache writes use `get_or_create`.** Two concurrent requests for the same `video_id` both miss the cache and both call OpenAI; whichever finishes first wins, the loser's `get_or_create` returns the existing row instead of crashing on the `unique=True` constraint.

**Two-layer abuse defense.** Per-IP rate limit (`django-ratelimit`, 3/day) plus a global monthly cap (`GlobalUsage` model) checked in `recipe_result_view` before generation. The cap is incremented only on outcomes that actually burn API tokens — successful generation OR `GenerationFailed` (the LLM call happened but returned garbage). `TranscriptUnavailable` is a local failure (transcript fetch), so it doesn't count. Both defenses live in the cache-miss path; cached recipes bypass them entirely.

### Recipe model

`Recipe(video_id unique, title, payload JSONField, created_at)`. The full LLM JSON output lives in `payload`; the template (`recipe_result.html`) reads `recipe.payload` (passed as `recipe` in the context). `title` is denormalized for admin display.

### Templates and static files

All templates extend `recipes/templates/recipes/base.html`, which provides only `<head>` (with `{% block title %}` and `{% block head_extra %}`) and a `{% block body %}` — pages bring their own chrome. The landing page (`home.html`) links its own stylesheet at `recipes/static/recipes/home.css`. Utility pages (`youtube_form.html`, `recipe_result.html`, `error.html`) pull Bootstrap from a CDN in `head_extra`.

Static files are served via Django's app-dir finder (`django.contrib.staticfiles` + `STATIC_URL = 'static/'`); no `STATICFILES_DIRS` is configured because everything lives under `recipes/static/`.

## Tests

```powershell
cd cookingai
python manage.py test recipes        # whole suite
python manage.py test recipes.tests.RecipeResultViewTests.test_cache_hit_skips_generator   # one test
```

The suite lives in `cookingai/recipes/tests.py`. It exercises the view directly with `RequestFactory` (not the test client) so it can inject a `FakeRecipeGenerator` via the view's `generator` kwarg — the URL dispatcher does not pass it. To test error paths, construct `FakeRecipeGenerator(raises=TranscriptUnavailable(...))` or `(raises=GenerationFailed(...))`. Do not mock the Anthropic SDK — that bypasses the seam.

The `test/` directory at the repo root is **not** Django tests — it contains two unrelated scratch scripts (`AITest.mjs`, `webscraper.py`) that predate the Django app.
