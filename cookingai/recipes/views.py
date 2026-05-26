import os
from datetime import datetime, timezone

from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone as django_tz
from django_ratelimit.core import is_ratelimited

from .forms import YoutubeLinkForm
from .generator import (
    GeneratorError,
    RecipeGenerator,
    TranscriptUnavailable,
    default_generator,
)
from .models import GlobalUsage, Recipe


# Video IDs surfaced in the home page's "Featured Examples" section.
# Seed them with `python manage.py seed_examples`.
EXAMPLE_VIDEO_IDS = ['2eCuSkRthq8', 'M8eeWdpqGo0', 'F2ENkOF3fMQ']

# Per-IP rate limit on new generation. Cached recipes (the 3 examples plus
# anything previously generated) bypass this entirely — only API-cost-incurring
# work counts.
GENERATION_RATE = '3/d'

# Hard monthly cap on total successful generations across all IPs. At
# ~$0.15 worst-case per call, the default of 30 keeps the bill under ~$5/mo.
# Anthropic has no organization-level spend cap, so this is the bill-floor.
MONTHLY_GENERATION_CAP = int(os.environ.get('MONTHLY_GENERATION_CAP', '30'))


def _client_ip_key(group, request):
    """Return the originating client IP, accounting for Render's reverse proxy.

    Render rewrites X-Forwarded-For to put the client IP first. Falling back to
    REMOTE_ADDR keeps local dev working (RequestFactory and runserver set it
    directly). An attacker can spoof X-Forwarded-For from the open internet, so
    this is not authentication-grade — the real defense is the Anthropic spend
    cap. Rate limiting just keeps honest traffic honest.
    """
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def ratelimited(request, exception=None):
    """Friendly 429 page when a visitor exceeds the per-IP generation limit."""
    return render(request, 'recipes/ratelimited.html', {
        'rate': GENERATION_RATE,
    }, status=429)


def budget_exhausted(request):
    """Friendly 503 page when the global monthly generation cap is hit."""
    return render(request, 'recipes/budget_exhausted.html', {
        'cap': MONTHLY_GENERATION_CAP,
    }, status=503)


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m')


def _global_usage_within_cap() -> bool:
    usage = GlobalUsage.objects.filter(period_key=_current_period()).first()
    return (usage.count if usage else 0) < MONTHLY_GENERATION_CAP


def _increment_global_usage() -> None:
    """Atomically bump this month's generation counter.

    Two-query implementation (get_or_create + F-expression update) so the
    increment is race-safe on both SQLite and Postgres without needing
    select_for_update — SQLite doesn't support row-level locks.
    """
    period = _current_period()
    GlobalUsage.objects.get_or_create(period_key=period)
    GlobalUsage.objects.filter(period_key=period).update(
        count=F('count') + 1,
        updated_at=django_tz.now(),
    )


def home_view(request):
    by_id = {r.video_id: r for r in Recipe.objects.filter(video_id__in=EXAMPLE_VIDEO_IDS)}
    examples = [by_id[vid] for vid in EXAMPLE_VIDEO_IDS if vid in by_id]
    return render(request, 'recipes/home.html', {
        'form': YoutubeLinkForm(),
        'examples': examples,
    })


def youtube_form_view(request):
    if request.method == 'POST':
        form = YoutubeLinkForm(request.POST)
        if form.is_valid():
            video_id = form.cleaned_data['video_id']
            return redirect('recipe_result', video_id=video_id)
    else:
        form = YoutubeLinkForm()
    return render(request, 'recipes/youtube_form.html', {'form': form})


def recipe_result_view(request, video_id, generator: RecipeGenerator | None = None):
    """Return cached recipe for video_id, or generate-and-save on cache miss.

    `generator` is injectable for tests; production uses `default_generator()`.
    Rate limit is checked only on cache miss — cached recipes are free to serve.
    """
    try:
        recipe = Recipe.objects.get(video_id=video_id)
    except Recipe.DoesNotExist:
        # Global cap first — defends the API bill even if per-IP rate limiting is bypassed.
        if not _global_usage_within_cap():
            return budget_exhausted(request)
        if is_ratelimited(
            request,
            group='recipe_generation',
            key=_client_ip_key,
            rate=GENERATION_RATE,
            increment=True,
        ):
            return ratelimited(request)
        try:
            generated = (generator or default_generator()).generate(video_id)
        except TranscriptUnavailable as e:
            # No Anthropic call happened — transcript fetch failed locally. Don't count.
            return render(request, 'recipes/error.html', {
                'heading': 'Transcript unavailable',
                'detail': 'This video does not have captions we can read. Try a different video.',
                'cause': str(e),
            }, status=422)
        except GeneratorError as e:
            # Anthropic call likely happened (and cost tokens), even though it failed.
            _increment_global_usage()
            return render(request, 'recipes/error.html', {
                'heading': 'Recipe generation failed',
                'detail': 'Something went wrong while generating the recipe. Please try again.',
                'cause': str(e),
            }, status=502)

        _increment_global_usage()
        recipe, _ = Recipe.objects.get_or_create(
            video_id=generated.video_id,
            defaults={'title': generated.title, 'payload': generated.payload},
        )

    return render(request, 'recipes/recipe_result.html', {
        'recipe': recipe.payload,
        'youtube_url': recipe.youtube_url,
    })
