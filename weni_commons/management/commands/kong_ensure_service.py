"""
Management command: kong_ensure_service

Registers a Kong Service and its default-block catch-all route (403) via the
Admin API. Idempotent — safe to re-run. Does not modify allow-routes created
by ``kong_sync`` / ``@api_gateway_expose``.

Configuration:
    KONG_ADMIN_URL, KONG_SERVICE, KONG_SERVICE_URL and KONG_URL_PREFIX are read
    from the host project's Django settings first, then from the environment. A
    command-line flag overrides both.

Required setup:
    - Add "weni_commons" to INSTALLED_APPS so Django discovers this command.

Usage:
    # Using Django settings (recommended)
    #   KONG_ADMIN_URL = "http://kong-admin:8001"
    #   KONG_SERVICE = "billing-service"
    #   KONG_SERVICE_URL = "https://billing.stg.cloud.weni.ai"
    #   KONG_URL_PREFIX = "/billing"
    python manage.py kong_ensure_service

    # Using environment variables
    KONG_ADMIN_URL=http://kong-admin:8001 \\
    KONG_SERVICE=billing-service \\
    KONG_SERVICE_URL=https://billing.stg.cloud.weni.ai \\
    KONG_URL_PREFIX=/billing \\
    python manage.py kong_ensure_service

    # Passing arguments explicitly
    python manage.py kong_ensure_service \\
      --kong-addr http://localhost:8001 \\
      --service billing-service \\
      --url https://billing.stg.cloud.weni.ai \\
      --url-prefix /billing

    # Preview without applying
    python manage.py kong_ensure_service --dry-run
"""
from django.core.management.base import BaseCommand, CommandError

from weni_commons.kong.config import resolve_config
from weni_commons.kong.service import (
    DEFAULT_BLOCK_MESSAGE,
    DEFAULT_BLOCK_STATUS,
    ensure_default_block,
    ensure_service,
)


class Command(BaseCommand):
    help = (
        "Ensure a Kong service and its default-block (403) route exist "
        "via the Admin API"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--kong-addr",
            default=resolve_config("KONG_ADMIN_URL", "http://localhost:8001"),
            help="Kong Admin API base URL (setting/env: KONG_ADMIN_URL)",
        )
        parser.add_argument(
            "--service",
            default=resolve_config("KONG_SERVICE"),
            help="Kong service name, e.g. billing-service (setting/env: KONG_SERVICE)",
        )
        parser.add_argument(
            "--url",
            default=resolve_config("KONG_SERVICE_URL"),
            help="Upstream service URL (setting/env: KONG_SERVICE_URL)",
        )
        parser.add_argument(
            "--url-prefix",
            default=resolve_config("KONG_URL_PREFIX"),
            help="Gateway path prefix, e.g. /billing (setting/env: KONG_URL_PREFIX)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without calling the Admin API",
        )

    def handle(self, *args, **options):
        service = (options["service"] or "").strip()
        if not service:
            raise CommandError(
                "--service is required, or set KONG_SERVICE in your Django settings "
                "or environment"
            )

        url = (options["url"] or "").strip()
        if not url:
            raise CommandError(
                "--url is required, or set KONG_SERVICE_URL in your Django settings "
                "or environment"
            )
        if not url.startswith(("http://", "https://")):
            raise CommandError(
                "KONG_SERVICE_URL / --url must start with http:// or https:// "
                f"(got: {url!r})"
            )

        url_prefix = (options["url_prefix"] or "").strip()
        if not url_prefix:
            raise CommandError(
                "--url-prefix is required, or set KONG_URL_PREFIX in your Django "
                "settings or environment"
            )
        if not url_prefix.startswith("/"):
            url_prefix = "/" + url_prefix

        kong_addr = (options["kong_addr"] or "").strip()
        if not options["dry_run"]:
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

        prefix = "/" + url_prefix.strip("/")
        route_name = f"{prefix.strip('/')}-default-block"

        if options["dry_run"]:
            self.stdout.write("\nDry run — would ensure:\n")
            self.stdout.write(f"  service     {service}")
            self.stdout.write(f"  upstream    {url.rstrip('/')}")
            self.stdout.write(f"  block route {route_name}")
            self.stdout.write(f"  block path  {prefix}")
            self.stdout.write(
                f"  plugin      request-termination "
                f"({DEFAULT_BLOCK_STATUS}: {DEFAULT_BLOCK_MESSAGE!r})"
            )
            self.stdout.write("")
            return

        self.stdout.write(
            f"Ensuring service {service!r} at {kong_addr} "
            f"(prefix: {prefix}) ...\n"
        )

        ensure_service(admin_url=kong_addr, name=service, url=url)
        self.stdout.write(f"  service  {service}")

        block_name = ensure_default_block(
            admin_url=kong_addr,
            service=service,
            url_prefix=url_prefix,
        )
        self.stdout.write(f"  block    {block_name} -> {prefix}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Service {service!r} and default-block are ready. "
                "Run kong_sync to register @api_gateway_expose allow-routes."
            )
        )
