from django.contrib import admin

from .models import Recipe


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('title', 'video_id', 'created_at')
    search_fields = ('title', 'video_id')
    readonly_fields = ('created_at',)
