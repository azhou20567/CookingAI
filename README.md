# CookingAI

CookingAI is an AI-powered web application that converts YouTube cooking videos into structured, easy-to-follow recipes. It extracts video transcripts and uses Claude AI to generate ingredients, cooking instructions, and helpful notes.

## Features

- **AI Recipe Generation:** Converts YouTube cooking videos into organized recipes using Anthropic Claude.
- **Transcript Extraction:** Retrieves video transcripts automatically.
- **Structured Recipes:** Displays ingredients, step-by-step instructions, and cooking notes.
- **Recipe Caching:** Stores previously generated recipes to avoid redundant API calls.
- **Rate Limiting:** Limits API usage to control costs and prevent abuse.

## Tech Stack

- **Backend:** Python, Django
- **Frontend:** HTML, CSS, Bootstrap
- **AI:** Anthropic Claude API
- **Database:** Django ORM
- **Integrations:** YouTube Transcript API

## Getting Started

1. Clone the repository:
   ```bash
   git clone https://github.com/azhou20567/CookingAI.git
   cd CookingAI
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create `cookingai/.env` and configure:
   ```env
   SECRET_KEY=your-django-secret-key
   ANTHROPIC_API_KEY=your-api-key
   ```

4. Start the application:
   ```bash
   cd cookingai
   python manage.py migrate
   python manage.py runserver
   ```

5. Visit `http://127.0.0.1:8000/` in your browser.

For local testing without an API key, set `USE_FAKE_GENERATOR=true` in your `.env` file.

## Future Improvements

- Recipe search and filtering
- User accounts and saved recipes
- Recipe customization based on dietary preferences
