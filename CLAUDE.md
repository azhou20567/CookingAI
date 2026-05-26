# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CookingAI is a Django 5.1 web app that turns a YouTube cooking video into a structured JSON recipe. The user submits a YouTube URL; the backend pulls the transcript via `youtube_transcript_api` and asks OpenAI (`gpt-4o-mini`) to convert it into a recipe with ingredients, steps, and notes, which is then rendered with Bootstrap. Generated recipes are cached in the database keyed by `video_id`, so repeat requests don't re-hit OpenAI.

## Running the app

All `manage.py` commands run from the inner `cookingai/` directory (the one that contains `manage.py`), not the repo root:

```powershell
cd cookingai
python manage.py migrate           # apply migrations (recipes app)
python manage.py runserver         # dev server at http://127.0.0.1:8000/
python manage.py createsuperuser   # for /admin/
```

Install dependencies with `pip install -r requirements.txt` (from the repo root). `youtube-transcript-api` is pinned to `<1.0` because the code uses the v0.x `YouTubeTranscriptApi.get_transcript(...)` class-method API.

## Configuration

`cookingai/.env` (loaded by `python-dotenv` from `settings.py`) holds:

- **`SECRET_KEY`** (required) — Django will refuse to start without it (intentional, `os.environ['SECRET_KEY']`).
- **`OPENAI_API_KEY`** (required for generation only) — read lazily inside `default_generator()`. Tests and `manage.py migrate` run fine without it; only an actual cache-miss request will raise `GenerationFailed('OPENAI_API_KEY is not configured')`.
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

- `OpenAIRecipeGenerator` — fetches transcript, calls OpenAI with `response_format=json_object`, validates the payload shape via `validate_payload`, raises `TranscriptUnavailable` or `GenerationFailed` on known error modes.
- `FakeRecipeGenerator` — returns a canned recipe (or raises a configured exception) for tests and offline dev. **Do not mock OpenAI in tests; inject this instead.**

`recipe_result_view` takes `generator` as a kwarg defaulting to `default_generator()`. Tests should pass a `FakeRecipeGenerator()` to exercise the view without network.

Both errors derive from `GeneratorError`. If you add a new failure mode, raise a new subclass and add a branch to the view's `except` chain — don't swallow exceptions in the generator.

**Timeouts.** OpenAI is configured with a 30s timeout. `YouTubeTranscriptApi.get_transcript` has no native timeout in v0.x, so `_fetch_transcript` runs it in a `ThreadPoolExecutor` and bails out at 30s — the worker thread is intentionally not joined on timeout (leaks until the HTTP call returns) since wedging the request thread is worse. If you upgrade to `youtube-transcript-api>=1.0` you can replace this with native timeout config.

**Cache writes use `get_or_create`.** Two concurrent requests for the same `video_id` both miss the cache and both call OpenAI; whichever finishes first wins, the loser's `get_or_create` returns the existing row instead of crashing on the `unique=True` constraint.

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

The suite lives in `cookingai/recipes/tests.py`. It exercises the view directly with `RequestFactory` (not the test client) so it can inject a `FakeRecipeGenerator` via the view's `generator` kwarg — the URL dispatcher does not pass it. To test error paths, construct `FakeRecipeGenerator(raises=TranscriptUnavailable(...))` or `(raises=GenerationFailed(...))`. Do not mock the OpenAI SDK — that bypasses the seam.

The `test/` directory at the repo root is **not** Django tests — it contains two unrelated scratch scripts (`AITest.mjs`, `webscraper.py`) that predate the Django app.
