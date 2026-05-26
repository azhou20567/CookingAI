import re

from django import forms

_YOUTUBE_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:youtube|youtu|youtube-nocookie)\.(?:com|be)/'
    r'(?:watch\?v=|embed/|v/|shorts/|.+\?v=)?'
    r'(?P<video_id>[A-Za-z0-9_-]{11})'
)


def extract_video_id(url: str) -> str | None:
    match = _YOUTUBE_URL_RE.match(url)
    return match.group('video_id') if match else None


class YoutubeLinkForm(forms.Form):
    youtube_link = forms.URLField(
        label='YouTube Video URL',
        widget=forms.URLInput(attrs={
            'placeholder': 'https://www.youtube.com/watch?v=...',
            'class': 'form-control',
        }),
    )

    def clean_youtube_link(self):
        url = self.cleaned_data['youtube_link']
        video_id = extract_video_id(url)
        if video_id is None:
            raise forms.ValidationError('Please enter a valid YouTube URL')
        self.cleaned_data['video_id'] = video_id
        return url
