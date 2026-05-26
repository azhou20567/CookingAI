from django.db import models


class Recipe(models.Model):
    video_id = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255, blank=True)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title or self.video_id

    @property
    def youtube_url(self):
        return f'https://www.youtube.com/watch?v={self.video_id}'
