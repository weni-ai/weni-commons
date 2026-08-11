"""
Management command: kong_sync

Discovers all views decorated with @api_gateway_expose in the project's URL
configuration and registers them as routes in Kong via the Admin API.

Supports APIView classes, DRF ViewSets (``callback.cls``), and method-level
decorators on ``@action`` / ``list`` / ``retrieve``.

Without alias, client URLs keep the service prefix:
    {KONG_URL_PREFIX}/api/v2/contacts.json   e.g. /flows/api/v2/contacts.json

With ``alias`` on @api_gateway_expose, three public paths are registered:
    /{alias}                                 e.g. /events          (flat)
    {KONG_URL_PREFIX}/{alias}                e.g. /flows/events    (compat)
    {KONG_URL_PREFIX}/api/v2/....json        e.g. /flows/api/v2/…  (compat)

Detail ViewSet routes use Kong regex paths (e.g. ``(?<pk>[^/]+)``). Alias may
include the same placeholders: ``alias="dashboards/{pk}/widgets"``.

The Kong route for an alias is named ``allow-{alias}`` and is last-writer-wins:
another service that syncs the same alias overwrites service + upstream.

Upstream rewrite:
    - Static paths → request-transformer ``replace.uri``
    - Parameterized paths → pre-function (strip prefix or rewrite captures)

The sync reconciles instead of rewriting everything: the Kong state is read in
bulk and only the routes that are missing or divergent are written. Routes this
service exposed before and no longer decorates are deleted (prune), which is on
by default — pass --no-prune to keep them.

Configuration:
    KONG_URL_PREFIX, KONG_SERVICE and KONG_ADMIN_URL are read from the host
    project's Django settings first, then from the environment. A command-line
    flag overrides both. KONG_URL_PREFIX and KONG_SERVICE are required;
    KONG_ADMIN_URL falls back to http://localhost:8001.

Required setup:
    - Add "weni_commons" to INSTALLED_APPS so Django discovers this command.
    - KONG_ADMIN_URL must be reachable, including for --dry-run, since the plan
      is computed against the live Kong state.

Usage:
    # Using Django settings (recommended)
    #   KONG_URL_PREFIX = "/flows"
    #   KONG_SERVICE = "flows-service"
    #   KONG_ADMIN_URL = "http://kong-admin:8001"
    python manage.py kong_sync

    # Using environment variables
    KONG_URL_PREFIX=/flows KONG_SERVICE=flows-service \\
    KONG_ADMIN_URL=http://kong-admin:8001 python manage.py kong_sync

    # Passing arguments explicitly
    python manage.py kong_sync --url-prefix /flows --service flows-service \\
      --kong-addr http://localhost:8001

    # Preview without applying
    python manage.py kong_sync --dry-run

    # Keep orphan routes in Kong
    python manage.py kong_sync --no-prune

    # Confirm a prune above the safety threshold
    python manage.py kong_sync --force-prune
"""
import os
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from weni_commons.kong.config import resolve_config
from weni_commons.kong.sync import PruneLimitExceeded, discover_routes, sync_to_kong


class Command(BaseCommand):
    help = "Sync @api_gateway_expose views to Kong API Gateway via the Admin API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--kong-addr",
            default=resolve_config("KONG_ADMIN_URL", "http://localhost:8001"),
            help="Kong Admin API base URL (setting/env: KONG_ADMIN_URL)",
        )
        parser.add_argument(
            "--service",
            default=resolve_config("KONG_SERVICE"),
            help="Kong service name to attach routes to (setting/env: KONG_SERVICE)",
        )
        parser.add_argument(
            "--url-prefix",
            default=resolve_config("KONG_URL_PREFIX"),
            help="Gateway path prefix for this service, e.g. /flows "
            "(setting/env: KONG_URL_PREFIX)",
        )
        parser.add_argument(
            "--suffix",
            default=".json",
            help="URL suffix used to filter routes (default: .json)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the plan against the live Kong state without writing",
        )
        parser.add_argument(
            "--no-prune",
            dest="prune",
            action="store_false",
            default=True,
            help="Keep routes that are no longer decorated (prune is on by default)",
        )
        parser.add_argument(
            "--force-prune",
            action="store_true",
            help="Confirm a prune that exceeds the safety threshold",
        )

    def handle(self, *args, **options):
        url_prefix = (options["url_prefix"] or "").strip()
        if not url_prefix:
            raise CommandError(
                "--url-prefix is required, or set KONG_URL_PREFIX in your Django "
                "settings or environment"
            )

        # No default on purpose: prune deletes routes attached to this service,
        # so an implicit value could reach another service's routes.
        service = (options["service"] or "").strip()
        if not service:
            raise CommandError(
                "--service is required, or set KONG_SERVICE in your Django settings "
                "or environment"
            )
        options["service"] = service

        # Required for --dry-run too: the plan is diffed against the live state.
        kong_addr = (options["kong_addr"] or "").strip()
        if not kong_addr:
            raise CommandError(
                "--kong-addr is required, or set KONG_ADMIN_URL in your Django settings "
                "or environment (it is currently empty — check that the KONG_ADMIN_URL "
                "secret is configured)"
            )
        if not kong_addr.startswith(("http://", "https://")):
            raise CommandError(
                "KONG_ADMIN_URL must start with http:// or https:// "
                f"(got: {kong_addr!r}). Example: http://kong-admin.example.com:8001"
            )
        options["kong_addr"] = kong_addr

        # Ensure the env is set so discover_routes() can read it
        os.environ["KONG_URL_PREFIX"] = url_prefix

        # Importing the root URL conf causes all views to be imported,
        # which triggers every @api_gateway_expose decorator in the project.
        import_module(settings.ROOT_URLCONF)

        routes = discover_routes(suffix=options["suffix"])

        if not routes:
            self.stdout.write(self.style.WARNING("No @api_gateway_expose routes found."))
            return

        dry_run = options["dry_run"]
        prune = options["prune"]

        self.stdout.write(
            f"{'Planning' if dry_run else 'Syncing'} {len(routes)} route(s) with "
            f"{options['kong_addr']} (service: {options['service']}, "
            f"prune: {'on' if prune else 'off'}) ...\n"
        )

        try:
            created, updated, skipped, deleted = sync_to_kong(
                admin_url=options["kong_addr"],
                service=options["service"],
                routes=routes,
                prune=prune,
                force_prune=options["force_prune"],
                dry_run=dry_run,
            )
        except PruneLimitExceeded as exc:
            raise CommandError(str(exc)) from exc

        by_name = {route["name"]: route for route in routes}
        create_label, update_label, skip_label, delete_label = (
            ("create", "update", "skip", "delete")
            if dry_run
            else ("created", "updated", "skipped", "deleted")
        )

        for label, names in ((create_label, created), (update_label, updated)):
            for name in names:
                route = by_name[name]
                self.stdout.write(
                    f"  {label:<8} {name:<50} gateway={route['paths']}  "
                    f"upstream={route['upstream_uri']}  {route['methods']}  "
                    f"rewrite={route.get('rewrite_mode', 'static_uri')}"
                )

        if dry_run:
            for name in skipped:
                self.stdout.write(f"  {skip_label:<8} {name}")

        for name in deleted:
            self.stdout.write(f"  {delete_label:<8} {name}")

        self.stdout.write("")
        summary = (
            f"{len(created)} created, {len(updated)} updated, "
            f"{len(skipped)} unchanged, {len(deleted)} deleted."
        )
        self.stdout.write(
            self.style.SUCCESS(f"{'Dry run.' if dry_run else 'Done.'} {summary}")
        )
