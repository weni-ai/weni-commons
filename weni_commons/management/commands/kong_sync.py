"""
Management command: kong_sync

Discovers all views decorated with @kong_expose in the project's URL
configuration and registers them as routes in Kong via the Admin API.

Required setup:
    - Add "weni_commons" to INSTALLED_APPS so Django discovers this command.
    - Set KONG_URL_PREFIX in the environment (e.g. /flows, /nexus).

Usage:
    # Using environment variables (recommended for CI/CD)
    KONG_URL_PREFIX=/flows KONG_ADMIN_URL=http://kong-admin:8001 python manage.py kong_sync

    # Passing arguments explicitly
    python manage.py kong_sync --url-prefix /flows --kong-addr http://localhost:8001

    # Preview without applying
    python manage.py kong_sync --dry-run
"""
import os
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from weni_commons.kong.sync import discover_routes, sync_to_kong


class Command(BaseCommand):
    help = "Sync @kong_expose views to Kong API Gateway via the Admin API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--kong-addr",
            default=os.environ.get("KONG_ADMIN_URL", "http://localhost:8001"),
            help="Kong Admin API base URL (env: KONG_ADMIN_URL)",
        )
        parser.add_argument(
            "--service",
            default=os.environ.get("KONG_SERVICE", "flows-service"),
            help="Kong service name to attach routes to (env: KONG_SERVICE)",
        )
        parser.add_argument(
            "--url-prefix",
            default=os.environ.get("KONG_URL_PREFIX"),
            help="Gateway path prefix for this service, e.g. /flows (env: KONG_URL_PREFIX)",
        )
        parser.add_argument(
            "--suffix",
            default=".json",
            help="URL suffix used to filter routes (default: .json)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Discover and list routes without registering them in Kong",
        )

    def handle(self, *args, **options):
        url_prefix = options["url_prefix"]
        if not url_prefix:
            raise CommandError(
                "--url-prefix is required, or set the KONG_URL_PREFIX environment variable"
            )

        # Ensure the env is set so discover_routes() can read it
        os.environ["KONG_URL_PREFIX"] = url_prefix

        # Importing the root URL conf causes all views to be imported,
        # which triggers every @kong_expose decorator in the project.
        import_module(settings.ROOT_URLCONF)

        routes = discover_routes(suffix=options["suffix"])

        if not routes:
            self.stdout.write(self.style.WARNING("No @kong_expose routes found."))
            return

        if options["dry_run"]:
            self.stdout.write(f"\nDry run — {len(routes)} route(s) discovered:\n")
            for route in routes:
                self.stdout.write(
                    f"  {route['name']:<50} {route['paths']}  {route['methods']}"
                )
            self.stdout.write("")
            return

        self.stdout.write(
            f"Syncing {len(routes)} route(s) to {options['kong_addr']} "
            f"(service: {options['service']}) ...\n"
        )

        created = sync_to_kong(
            admin_url=options["kong_addr"],
            service=options["service"],
            routes=routes,
        )

        skipped = len(routes) - len(created)

        for name in created:
            self.stdout.write(f"  created  {name}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {len(created)} created, {skipped} already existed."
            )
        )
