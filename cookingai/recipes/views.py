from django.shortcuts import redirect, render

from .forms import YoutubeLinkForm
from .generator import (
    GeneratorError,
    RecipeGenerator,
    TranscriptUnavailable,
    default_generator,
)
from .models import Recipe


def home_view(request):
    return render(request, 'recipes/home.html', {'form': YoutubeLinkForm()})


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
    """
    try:
        recipe = Recipe.objects.get(video_id=video_id)
    except Recipe.DoesNotExist:
        try:
            generated = (generator or default_generator()).generate(video_id)
        except TranscriptUnavailable as e:
            return render(request, 'recipes/error.html', {
                'heading': 'Transcript unavailable',
                'detail': 'This video does not have captions we can read. Try a different video.',
                'cause': str(e),
            }, status=422)
        except GeneratorError as e:
            return render(request, 'recipes/error.html', {
                'heading': 'Recipe generation failed',
                'detail': 'Something went wrong while generating the recipe. Please try again.',
                'cause': str(e),
            }, status=502)

        recipe, _ = Recipe.objects.get_or_create(
            video_id=generated.video_id,
            defaults={'title': generated.title, 'payload': generated.payload},
        )

    return render(request, 'recipes/recipe_result.html', {
        'recipe': recipe.payload,
        'youtube_url': recipe.youtube_url,
    })
