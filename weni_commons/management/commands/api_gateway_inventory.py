"""
Management command: api_gateway_inventory

Emits a JSON inventory of every endpoint this service exposes through the API
Gateway: public path, allowed methods, the view behind it and the DRF
serializers that shape its payloads.

It is the deterministic input for OpenAPI generation. The generator reads this
file to know *which* endpoints exist and *what* they carry, so documentation
can never drift into endpoints that are not exposed, or miss ones that are.

Nothing is written to Kong and no network call is made — the inventory is built
from the URL resolver alone, so it is safe to run anywhere the project imports.

Configuration:
    KONG_URL_PREFIX is read from Django settings first, then the environment;
    --url-prefix overrides both. It is required, because a route without an
    alias is only reachable under that prefix.

Usage:
    # Print to stdout
    python manage.py api_gateway_inventory

    # Write to a file for the OpenAPI generator to read
    python manage.py api_gateway_inventory --out .openapi/inventory.json

    # Only the routes exposed to one Kong service
    python manage.py api_gateway_inventory --service flows-service

    # Fail the run when discovery reports problems (useful in CI)
    python manage.py api_gateway_inventory --fail-on-warnings
"""
import json
import os
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from weni_commons.kong.config import resolve_config
from weni_commons.openapi.inventory import build_inventory


class Command(BaseCommand):
    help = "Emit a JSON inventory of @api_gateway_expose endpoints for OpenAPI generation"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url-prefix",
            default=resolve_config("KONG_URL_PREFIX"),
            help="Gateway path prefix for this service, e.g. /flows "
            "(setting/env: KONG_URL_PREFIX)",
        )
        parser.add_argument(
            "--service",
            default=None,
            help="Only routes exposed to this Kong service (default: every service, "
            "since a repository may expose views to more than one)",
        )
        parser.add_argument(
            "--suffix",
            default=".json",
            help="URL suffix used to filter routes (default: .json)",
        )
        parser.add_argument(
            "--out",
            default=None,
            help="Write the inventory to this path instead of stdout",
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=2,
            help="JSON indentation (default: 2, use 0 for compact)",
        )
        parser.add_argument(
            "--fail-on-warnings",
            action="store_true",
            help="Exit with an error when discovery reports warnings",
        )

    def handle(self, *args, **options):
        url_prefix = (options["url_prefix"] or "").strip()
        if not url_prefix:
            raise CommandError(
                "--url-prefix is required, or set KONG_URL_PREFIX in your Django "
                "settings or environment"
            )

        # discover_routes reads this from the environment; keep both paths in sync.
        os.environ["KONG_URL_PREFIX"] = url_prefix

        # Importing the root URL conf imports every view, which is what triggers
        # the @api_gateway_expose decorators.
        import_module(settings.ROOT_URLCONF)

        inventory = build_inventory(
            url_prefix=url_prefix,
            suffix=options["suffix"],
            service=options["service"],
        )

        indent = options["indent"] or None
        payload = json.dumps(inventory, indent=indent, sort_keys=False, default=str)

        out = options["out"]
        if out:
            directory = os.path.dirname(os.path.abspath(out))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(out, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            self._report(inventory, out)
        else:
            self.stdout.write(payload)

        warnings = inventory["warnings"]
        if warnings and options["fail_on_warnings"]:
            raise CommandError(
                f"{len(warnings)} warning(s) reported — see the inventory for details"
            )

    def _report(self, inventory, out):
        """Summarize to stderr so stdout stays a clean JSON stream when piped."""
        routes = inventory["routes"]
        self.stderr.write(
            f"Wrote {inventory['route_count']} route(s) to {out} "
            f"(prefix: {inventory['url_prefix']})"
        )
        for route in routes:
            methods = ",".join(route["gateway_methods"])
            self.stderr.write(
                f"  {route['public_path']:<40} {methods:<12} {route['view']['class']}"
            )

        warnings = inventory["warnings"]
        if not warnings:
            return
        self.stderr.write("")
        self.stderr.write(self.style.WARNING(f"{len(warnings)} warning(s):"))
        for warning in warnings:
            self.stderr.write(f"  [{warning['code']}] {warning['message']}")
