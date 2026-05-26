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


class GlobalUsage(models.Model):
    """Total successful Anthropic-incurring generations within a given period.

    Hard cap that stops the app from making API calls once the monthly limit is
    reached. Per-IP rate limits are a softer defense (defeatable by IP rotation);
    this is the floor that bounds the bill regardless.
    """
    period_key = models.CharField(max_length=20, unique=True)  # "YYYY-MM"
    count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_key']

    def __str__(self):
        return f'{self.period_key}: {self.count}'
