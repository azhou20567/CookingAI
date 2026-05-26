from django.shortcuts import render, redirect
from .forms import youtubeLinkForm
from django.http import JsonResponse
from .ai_assistants import CookingAIAssistant
import json

#https://www.youtube.com/watch?v=mhDJNfV7hjk

def youtube_form_view(request):
    if request.method == 'POST':
        form = youtubeLinkForm(request.POST)
        if form.is_valid():
            youtube_url = form.cleaned_data['youtube_link']
            video_id = youtube_url.split('v=')[1].split('&')[0]
            return redirect('recipe_result', video_id=video_id)
    else:
        form = youtubeLinkForm()
    return render(request, 'cookingai/youtube_form.html', {'form': form})

def home_view(request):
    form = youtubeLinkForm()
    return render(request, 'cookingai/home.html', {'form': form})

def recipe_result_view(request, video_id):
    assistant = CookingAIAssistant()
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    recipe = assistant.generate_recipe(youtube_url)
    return render(request, 'cookingai/recipe_result.html', {
        'recipe': recipe,
        'youtube_url': youtube_url
    })