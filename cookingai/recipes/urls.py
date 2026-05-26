from django.urls import path

from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('youtube/', views.youtube_form_view, name='youtube_form'),
    path('results/<str:video_id>/', views.recipe_result_view, name='recipe_result'),
]
