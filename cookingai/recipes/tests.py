from unittest.mock import Mock

from django.test import RequestFactory, TestCase
from django.urls import reverse

from recipes.forms import YoutubeLinkForm, extract_video_id
from recipes.generator import (
    FakeRecipeGenerator,
    GeneratedRecipe,
    GenerationFailed,
    TranscriptUnavailable,
    validate_payload,
)
from recipes.models import Recipe
from recipes.views import recipe_result_view


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


class ValidatePayloadTests(TestCase):
    def _valid(self):
        return {
            'data': {'title': 'X', 'source': '', 'servings': '', 'prep_time': '', 'cook_time': '', 'cuisine': ''},
            'ingredients': [],
            'instructions': [],
            'notes': {},
        }

    def test_accepts_well_formed_payload(self):
        validate_payload(self._valid())  # does not raise

    def test_rejects_non_dict(self):
        with self.assertRaises(GenerationFailed):
            validate_payload(['not', 'a', 'dict'])

    def test_rejects_missing_data(self):
        payload = self._valid()
        del payload['data']
        with self.assertRaises(GenerationFailed):
            validate_payload(payload)

    def test_rejects_empty_title(self):
        payload = self._valid()
        payload['data']['title'] = ''
        with self.assertRaises(GenerationFailed):
            validate_payload(payload)

    def test_rejects_non_list_ingredients(self):
        payload = self._valid()
        payload['ingredients'] = {'not': 'a list'}
        with self.assertRaises(GenerationFailed):
            validate_payload(payload)

    def test_rejects_non_list_instructions(self):
        payload = self._valid()
        payload['instructions'] = None
        with self.assertRaises(GenerationFailed):
            validate_payload(payload)


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
    def test_renders_form(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'youtube_link')


class YoutubeFormViewTests(TestCase):
    def test_get_renders_form(self):
        response = self.client.get(reverse('youtube_form'))
        self.assertEqual(response.status_code, 200)

    def test_post_valid_redirects_to_result(self):
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
        response = self.client.post(reverse('youtube_form'), {'youtube_link': 'https://example.com/foo'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'valid YouTube URL')


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
