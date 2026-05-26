from django.core.management.base import BaseCommand, CommandError

from recipes.generator import GeneratorError, default_generator
from recipes.models import Recipe
from recipes.views import EXAMPLE_VIDEO_IDS


class Command(BaseCommand):
    help = (
        'Generate and cache recipes for the home-page featured examples. '
        'Idempotent: skips video IDs already in the DB unless --force is passed.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-generate even if a Recipe with that video_id already exists.',
        )

    def handle(self, *args, **options):
        generator = default_generator()
        force = options['force']

        for video_id in EXAMPLE_VIDEO_IDS:
            exists = Recipe.objects.filter(video_id=video_id).exists()
            if exists and not force:
                self.stdout.write(f'  skip {video_id} (already cached)')
                continue

            self.stdout.write(f'  generating {video_id} ...', ending='')
            self.stdout.flush()
            try:
                generated = generator.generate(video_id)
            except GeneratorError as e:
                raise CommandError(f'failed for {video_id}: {e}') from e

            if exists:
                Recipe.objects.filter(video_id=video_id).delete()

            Recipe.objects.create(
                video_id=generated.video_id,
                title=generated.title,
                payload=generated.payload,
            )
            self.stdout.write(self.style.SUCCESS(f' ok: {generated.title}'))

        self.stdout.write(self.style.SUCCESS('Done.'))
