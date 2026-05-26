import os
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase
from django.urls import reverse

from recipes.forms import YoutubeLinkForm, extract_video_id
from recipes.generator import (
    AnthropicRecipeGenerator,
    FakeRecipeGenerator,
    GeneratedRecipe,
    GenerationFailed,
    TranscriptUnavailable,
    default_generator,
)
from recipes.models import Recipe
from recipes.views import home_view, recipe_result_view, youtube_form_view


VALID_ID = 'mhDJNfV7hjk'


class ExtractVideoIdTests(TestCase):
    def test_standard_watch_url(self):
        self.assertEqual(extract_video_id(f'https://www.youtube.com/watch?v={VALID_ID}'), VALID_ID)

    def test_short_youtu_be_url(self):
        self.assertEqual(extract_video_id(f'https://youtu.be/{VALID_ID}'), VALID_ID)

    def test_embed_url(self):
        self.assertEqual(extract_video_id(f'https://www.youtube.com/embed/{VALID_ID}'), VALID_ID)

    def test_shorts_url(self):
        self.assertEqual(extract_video_id(f'https://www.youtube.com/shorts/{VALID_ID}'), VALID_ID)

    def test_url_with_extra_params(self):
        self.assertEqual(extract_video_id(f'https://www.youtube.com/watch?v={VALID_ID}&t=42s'), VALID_ID)

    def test_no_protocol(self):
        self.assertEqual(extract_video_id(f'youtube.com/watch?v={VALID_ID}'), VALID_ID)

    def test_invalid_url(self):
        self.assertIsNone(extract_video_id('https://example.com/video'))

    def test_empty_string(self):
        self.assertIsNone(extract_video_id(''))

    def test_rejects_invalid_id_characters(self):
        # 11 chars but contains a '$' which is not valid in YouTube IDs
        self.assertIsNone(extract_video_id('https://www.youtube.com/watch?v=abc$def1234'))


class YoutubeLinkFormTests(TestCase):
    def test_valid_form_exposes_video_id(self):
        form = YoutubeLinkForm({'youtube_link': f'https://www.youtube.com/watch?v={VALID_ID}'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['video_id'], VALID_ID)

    def test_invalid_url_fails_validation(self):
        form = YoutubeLinkForm({'youtube_link': 'https://example.com/foo'})
        self.assertFalse(form.is_valid())
        self.assertIn('youtube_link', form.errors)

    def test_non_url_fails_validation(self):
        form = YoutubeLinkForm({'youtube_link': 'not-a-url'})
        self.assertFalse(form.is_valid())


class RecipeModelTests(TestCase):
    def test_str_uses_title(self):
        r = Recipe(video_id=VALID_ID, title='Pasta', payload={})
        self.assertEqual(str(r), 'Pasta')

    def test_str_falls_back_to_video_id(self):
        r = Recipe(video_id=VALID_ID, title='', payload={})
        self.assertEqual(str(r), VALID_ID)

    def test_youtube_url_property(self):
        r = Recipe(video_id=VALID_ID, payload={})
        self.assertEqual(r.youtube_url, f'https://www.youtube.com/watch?v={VALID_ID}')

    def test_default_ordering_is_newest_first(self):
        older = Recipe.objects.create(video_id='aaaaaaaaaaa', payload={})
        newer = Recipe.objects.create(video_id='bbbbbbbbbbb', payload={})
        self.assertEqual(list(Recipe.objects.all()), [newer, older])


class FakeRecipeGeneratorTests(TestCase):
    def test_default_returns_canned_recipe(self):
        gen = FakeRecipeGenerator()
        result = gen.generate(VALID_ID)
        self.assertIsInstance(result, GeneratedRecipe)
        self.assertEqual(result.video_id, VALID_ID)
        self.assertEqual(result.title, 'Fake Test Recipe')

    def test_custom_payload_used(self):
        payload = {
            'data': {'title': 'Custom', 'source': '', 'servings': '1', 'prep_time': '', 'cook_time': '', 'cuisine': ''},
            'ingredients': [], 'instructions': [], 'notes': {},
        }
        gen = FakeRecipeGenerator(payload=payload)
        result = gen.generate(VALID_ID)
        self.assertEqual(result.title, 'Custom')
        self.assertEqual(result.payload, payload)

    def test_raises_when_configured(self):
        gen = FakeRecipeGenerator(raises=TranscriptUnavailable('nope'))
        with self.assertRaises(TranscriptUnavailable):
            gen.generate(VALID_ID)


class HomeViewTests(TestCase):
    # Tests that render templates call views directly via RequestFactory rather
    # than self.client. Reason: Django's test client instruments template
    # rendering by calling copy.copy() on the Context, which breaks under
    # Python 3.14 + Django 5.1 (Context.__copy__ assumes the parent copy
    # supports attribute assignment, which 3.14 no longer guarantees).
    def test_renders_form(self):
        request = RequestFactory().get(reverse('home'))
        response = home_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn('youtube_link', response.content.decode())


class YoutubeFormViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_renders_form(self):
        response = youtube_form_view(self.factory.get(reverse('youtube_form')))
        self.assertEqual(response.status_code, 200)

    def test_post_valid_redirects_to_result(self):
        # Redirects don't render templates, so the test client works here.
        response = self.client.post(
            reverse('youtube_form'),
            {'youtube_link': f'https://www.youtube.com/watch?v={VALID_ID}'},
        )
        self.assertRedirects(
            response,
            reverse('recipe_result', args=[VALID_ID]),
            fetch_redirect_response=False,
        )

    def test_post_invalid_rerenders_form_with_error(self):
        request = self.factory.post(
            reverse('youtube_form'),
            {'youtube_link': 'https://example.com/foo'},
        )
        response = youtube_form_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn('valid YouTube URL', response.content.decode())


class RecipeResultViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        return self.factory.get(f'/results/{VALID_ID}/')

    def test_cache_hit_skips_generator(self):
        Recipe.objects.create(
            video_id=VALID_ID,
            title='Cached',
            payload={'data': {'title': 'Cached'}, 'ingredients': [], 'instructions': [], 'notes': {}},
        )
        mock_gen = Mock()

        response = recipe_result_view(self._request(), VALID_ID, generator=mock_gen)

        self.assertEqual(response.status_code, 200)
        mock_gen.generate.assert_not_called()

    def test_cache_miss_calls_generator_and_persists(self):
        self.assertFalse(Recipe.objects.filter(video_id=VALID_ID).exists())
        fake = FakeRecipeGenerator()

        response = recipe_result_view(self._request(), VALID_ID, generator=fake)

        self.assertEqual(response.status_code, 200)
        recipe = Recipe.objects.get(video_id=VALID_ID)
        self.assertEqual(recipe.title, 'Fake Test Recipe')
        self.assertEqual(recipe.payload, FakeRecipeGenerator.DEFAULT_PAYLOAD)

    def test_transcript_unavailable_renders_error_422(self):
        fake = FakeRecipeGenerator(raises=TranscriptUnavailable('no captions'))

        response = recipe_result_view(self._request(), VALID_ID, generator=fake)

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'Transcript unavailable', status_code=422)
        self.assertFalse(Recipe.objects.filter(video_id=VALID_ID).exists())

    def test_generation_failed_renders_error_502(self):
        fake = FakeRecipeGenerator(raises=GenerationFailed('openai down'))

        response = recipe_result_view(self._request(), VALID_ID, generator=fake)

        self.assertEqual(response.status_code, 502)
        self.assertContains(response, 'Recipe generation failed', status_code=502)
        self.assertFalse(Recipe.objects.filter(video_id=VALID_ID).exists())

    def test_default_generator_used_when_no_argument_passed(self):
        """With USE_FAKE_GENERATOR=true, hitting /results/<id>/ uses the fake
        adapter automatically — no `generator` kwarg needed. This is the path
        the live runserver exercises when started without an OpenAI key.
        """
        env_overrides = {'USE_FAKE_GENERATOR': 'true', 'ANTHROPIC_API_KEY': ''}
        with patch.dict(os.environ, env_overrides, clear=False):
            response = recipe_result_view(self._request(), VALID_ID)

        self.assertEqual(response.status_code, 200)
        recipe = Recipe.objects.get(video_id=VALID_ID)
        self.assertEqual(recipe.title, 'Fake Test Recipe')

    def test_race_recipe_created_during_generation_does_not_crash(self):
        """Simulates a concurrent request that wins the create race.

        At the time our view does its initial cache lookup there is no Recipe.
        Mid-generation a sibling request persists one with the same video_id.
        Our `get_or_create` must absorb the unique-constraint collision
        instead of raising IntegrityError.
        """
        racing_payload = {
            'data': {'title': 'Racing'}, 'ingredients': [], 'instructions': [], 'notes': {},
        }

        class RacingGenerator:
            def generate(inner_self, video_id):
                Recipe.objects.create(video_id=video_id, title='Racing', payload=racing_payload)
                return GeneratedRecipe(video_id=video_id, title='Ours', payload=FakeRecipeGenerator.DEFAULT_PAYLOAD)

        response = recipe_result_view(self._request(), VALID_ID, generator=RacingGenerator())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Recipe.objects.filter(video_id=VALID_ID).count(), 1)
        # The racing-request's row wins — get_or_create returned the existing one
        self.assertEqual(Recipe.objects.get(video_id=VALID_ID).title, 'Racing')


class DefaultGeneratorTests(TestCase):
    """Verify default_generator()'s dispatch on environment variables.

    These cover the wiring that lets the site run locally without OpenAI.
    """

    def test_use_fake_flag_returns_fake_generator(self):
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': 'true', 'ANTHROPIC_API_KEY': ''}, clear=False):
            gen = default_generator()
        self.assertIsInstance(gen, FakeRecipeGenerator)

    def test_use_fake_flag_is_case_insensitive(self):
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': 'TRUE', 'ANTHROPIC_API_KEY': ''}, clear=False):
            gen = default_generator()
        self.assertIsInstance(gen, FakeRecipeGenerator)

    def test_api_key_set_returns_anthropic_generator(self):
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': '', 'ANTHROPIC_API_KEY': 'sk-ant-test'}, clear=False):
            gen = default_generator()
        self.assertIsInstance(gen, AnthropicRecipeGenerator)

    def test_fake_flag_wins_over_real_key(self):
        # Both set: fake flag takes precedence so devs can shadow prod creds locally.
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': 'true', 'ANTHROPIC_API_KEY': 'sk-ant-test'}, clear=False):
            gen = default_generator()
        self.assertIsInstance(gen, FakeRecipeGenerator)

    def test_no_config_raises_generation_failed(self):
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': '', 'ANTHROPIC_API_KEY': ''}, clear=False):
            with self.assertRaises(GenerationFailed):
                default_generator()


class LocalDevSmokeTests(TestCase):
    """End-to-end walk of the local-run flow: home -> submit -> result.

    Mirrors what a developer does after `python manage.py runserver` with
    USE_FAKE_GENERATOR=true: visit /, paste any YouTube URL, see a recipe.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_full_flow_with_fake_generator(self):
        with patch.dict(os.environ, {'USE_FAKE_GENERATOR': 'true', 'ANTHROPIC_API_KEY': ''}, clear=False):
            home_response = home_view(self.factory.get(reverse('home')))
            self.assertEqual(home_response.status_code, 200)
            self.assertIn('youtube_link', home_response.content.decode())

            submit_response = youtube_form_view(self.factory.post(
                reverse('youtube_form'),
                {'youtube_link': f'https://www.youtube.com/watch?v={VALID_ID}'},
            ))
            self.assertEqual(submit_response.status_code, 302)
            self.assertEqual(submit_response.url, reverse('recipe_result', args=[VALID_ID]))

            # No generator kwarg — exercises default_generator() against the env flag.
            result_response = recipe_result_view(
                self.factory.get(submit_response.url),
                VALID_ID,
            )
            self.assertEqual(result_response.status_code, 200)
            self.assertIn('Fake Test Recipe', result_response.content.decode())
            self.assertTrue(Recipe.objects.filter(video_id=VALID_ID).exists())
