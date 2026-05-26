from django import forms
import re

class youtubeLinkForm(forms.Form):
    youtube_link = forms.URLField(
        label='YouTube Video URL',
        widget=forms.URLInput(attrs={
            'placeholder': 'https://www.youtube.com/watch?v=...',
            'class': 'form-control'
        })
    )

    def clean_youtube_link(self):
        url = self.cleaned_data['youtube_link']
        
        # Basic YouTube URL validation
        youtube_regex = (
            r'(https?://)?(www\.)?'
            '(youtube|youtu|youtube-nocookie)\.(com|be)/'
            '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        
        if not re.match(youtube_regex, url):
            raise forms.ValidationError("Please enter a valid YouTube URL")
            
        return url