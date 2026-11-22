"""One-shot: pull device punches from ZKTECO_BRIDGE_URL into this database."""

from django.core.management.base import BaseCommand

from attendance.bridge_pull import pull_once


class Command(BaseCommand):
    help = "Pull attendance rows from the configured zkteco-bridge into CheckIn punches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=None,
            help="Only ingest punches from the last N days (default: settings).",
        )

    def handle(self, *args, **options):
        stats = pull_once(lookback_days=options.get("lookback_days"))
        self.stdout.write(
            self.style.SUCCESS(
                "fetched={fetched} recorded={recorded} skipped={skipped} errors={errors}".format(
                    **stats
                )
            )
        )
