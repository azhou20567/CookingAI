from django.contrib import admin

from .models import GlobalUsage, Recipe


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('title', 'video_id', 'created_at')
    search_fields = ('title', 'video_id')
    readonly_fields = ('created_at',)


@admin.register(GlobalUsage)
class GlobalUsageAdmin(admin.ModelAdmin):
    list_display = ('period_key', 'count', 'updated_at')
    readonly_fields = ('period_key', 'updated_at')
