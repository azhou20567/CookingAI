# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CookingAI is a Django 5.1 web app that turns a YouTube cooking video into a structured JSON recipe. The user submits a YouTube URL; the backend pulls the transcript via `youtube_transcript_api` and asks OpenAI (`gpt-4o-mini`) to convert it into a recipe with ingredients, steps, and notes, which is then rendered with Bootstrap.

## Running the app

All `manage.py` commands must be run from the inner `cookingai/` directory (the one that contains `manage.py`), not the repo root:

```powershell
cd cookingai
python manage.py runserver        # dev server at http://127.0.0.1:8000/
python manage.py migrate          # apply migrations (SQLite db.sqlite3 is committed)
python manage.py createsuperuser  # for /admin/
```

Install dependencies with `pip install -r requirements.txt` (from the repo root). Note `youtube-transcript-api` is pinned to `<1.0` because the code uses the v0.x `YouTubeTranscriptApi.get_transcript(...)` class-method API, which v1.x removed.

## Required secrets

`settings.py` reads `SECRET_KEY` and `OPENAI_API_KEY` from the environment via `python-dotenv`, loading `cookingai/.env` (i.e. next to `manage.py`) at import time. The file is gitignored and ships with empty values — fill them in locally before running. Missing keys raise `KeyError` on startup (intentional — better than a silent fallback).

## Tests

There is no Django test suite. The `test/` directory at the repo root is **not** Django tests — it contains two unrelated scratch scripts (`AITest.mjs`, `webscraper.py`) that predate the Django app and exist only as references for the OpenAI / transcript-scraping APIs. `python manage.py test` will find nothing.

## Architecture

The project has an unusual layout: the Django **project** and its only **app** are both named `cookingai` and live in the same `cookingai/cookingai/` directory. There is no separate app package — views, forms, templates, URLs, and the AI assistant all live alongside `settings.py`. `INSTALLED_APPS` lists `'cookingai'` as an app even though it's also the project root.

Request flow:

1. `urls.py` routes `/` → `home_view`, `/youtube/` → `youtube_form_view`, `/results/<video_id>/` → `recipe_result_view`.
2. `home.html` posts the URL directly to `/youtube/`. `youtube_form_view` validates with `forms.youtubeLinkForm`, extracts the `v=` parameter as `video_id`, and **redirects** to `/results/<video_id>/`. The video_id parsing in the view is naive (`url.split('v=')[1].split('&')[0]`) and only handles standard `watch?v=...` URLs — the regex in `forms.py` accepts more shapes than the view can handle.
3. `recipe_result_view` instantiates `CookingAIAssistant` and calls `generate_recipe(youtube_url)` **synchronously on the request thread**. This means a page load blocks on both the YouTube transcript fetch and the OpenAI call — expect multi-second response times and HTTP timeouts on long videos.

`ai_assistants.py` subclasses `django_ai_assistant.AIAssistant` but largely bypasses the framework: `generate_recipe` directly instantiates an `openai.OpenAI` client and calls `chat.completions.create` with `response_format={"type": "json_object"}` and a hand-crafted prompt in `_build_prompt`. The `@method_tool` decorator and `youtubeInput` schema are declared but the method is invoked as a plain method, not via the assistant's tool-dispatch loop. If you're modifying recipe generation, edit `_build_prompt` and the response-parsing in `generate_recipe` together — the template (`recipe_result.html`) assumes the exact JSON shape declared in that prompt (`data`, `ingredients[]`, `instructions[]`, `notes`).

## Templates

Templates live in `cookingai/cookingai/templates/cookingai/` and use Bootstrap 5.3 from a CDN. `home.html` is a single ~500-line file containing the entire landing page with inline CSS. Despite the `8136555 frontend basics finishing touches` and `879bc53 added react` commits, **there is no React, no build step, and no `package.json`** — everything is server-rendered Django templates.
