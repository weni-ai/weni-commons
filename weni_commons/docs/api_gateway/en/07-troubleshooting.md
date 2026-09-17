# 07 — Troubleshooting

The symptoms below are real cases, with the diagnosis that led to the cause in each
one.

## Quick index by symptom

| Symptom | Likely cause |
|---|---|
| `403` with `"Authentication credentials were not provided."` | the token was not recognized by whichever backend answered; start with `KONG_SERVICE_URL` |
| `403` with `"Route not authorized by the gateway"` | the path is not exposed; this is the block route answering |
| `400 Bad Request` when creating a route | Kong schema violation; read the response body |
| `PruneLimitExceeded` | deletion above the volume guard |
| `503` or name resolution failure | the Kong service's upstream |
| Write error on the Admin API | Kong in DB-less mode |
| `404` on `get-token` | user not authorized on the project |
| `200` with HTML instead of JSON | the gateway path did not reach the API endpoint |

## `403` with "Authentication credentials were not provided."

This is the gateway's most confusing symptom, because the message suggests a token
problem, and the token may be perfectly valid.

The root of the confusion is how authentication handles failures:
`SessionTokenAuthentication` returns `None` in any failure scenario — token missing,
invalid, expired, or store unreachable. DRF reads that as "not authenticated" and
answers `403` with this message. In other words, **the message is the same for a
client error and for a server misconfiguration.**

### Real case: `KONG_SERVICE_URL` pointing at another environment

This was the outcome of a long investigation. The symptoms were:

- the token existed in DynamoDB and `ValidateSessionTokenUseCase` returned a
  `SessionContext` normally when run in the staging service shell;
- the call through the gateway answered `403`;
- a direct call to the service pod answered `200`.

The initial conclusion looked like the `Authorization` header being lost between
Kong and the service. It was not. Staging's `KONG_SERVICE_URL` was pointing at the
**production** address, so Kong forwarded the request to the production backend,
which legitimately did not know a staging token.

What confirmed the diagnosis was comparing the response headers: the returned
`content-security-policy` headers were the other environment's. The upstream
latency Kong reported (a high `x-kong-upstream-latency`, in the hundreds of
milliseconds) reinforced that the destination was not the local service.

### How to investigate, in order

1. **Confirm the token in the store**, in the service shell:

   ```python
   from weni_commons.auth import DynamoDBSessionTokenRepository, ValidateSessionTokenUseCase
   DynamoDBSessionTokenRepository().get("<token>")
   ValidateSessionTokenUseCase().execute("<token>")
   ```

   If both calls work, the token and the store are fine, and the problem is not in
   authentication itself.

2. **Confirm where Kong is forwarding to:**

   ```python
   from django.conf import settings
   settings.KONG_SERVICE_URL
   ```

   It must point at **this** environment. Confirm in Kong as well:

   ```bash
   curl -s "${KONG_ADMIN_URL}/services/${KONG_SERVICE}"
   ```

3. **Compare behavior per path.** A direct call to the service answering `200` and a
   call through the gateway answering `403` means the gateway is not delivering to
   the service you are inspecting.

4. **Look at the response headers** for clues about which environment answered:
   `content-security-policy`, `x-kong-upstream-latency`, and `x-kong-request-id`.

If `KONG_SERVICE_URL` was wrong, fix the secret and run `kong_ensure_service` again
— it patches the service URL.

### Other causes of the same `403`

| Cause | How to confirm |
|---|---|
| DynamoDB table configured with an ARN instead of a name | `settings.WENI_SESSION_TOKEN_DYNAMODB_TABLE` must be a plain name |
| Wrong DynamoDB region | the repository's `get()` returns `None` for a token that exists |
| Credential without read permission on the table | `get()` raises an access exception, visible in the service log |
| Nonexistent Redis alias | the repository's `get()` works, but `ValidateSessionTokenUseCase` fails |
| Expired token | `expire_at` in the past; the item may already have been removed by TTL |
| `Token` scheme instead of `Bearer` | the gateway requires `Bearer`; the `Token` scheme belongs to the legacy flow |

## `403` with "Route not authorized by the gateway"

This `403` is different from the previous one: it comes from **Kong**, not from the
service, and it means the path did not match any allow route and fell into the block
route.

Common causes:

- the endpoint does not have the `@api_gateway_expose` decorator;
- the endpoint has the decorator, but `kong_sync` has not run since the deploy;
- the HTTP method used is not in the decorator's `methods` list;
- the called path is not one of the three registered paths (check with
  `kong_sync --dry-run`).

To see what is registered:

```bash
curl -s "${KONG_ADMIN_URL}/services/${KONG_SERVICE}/routes"
```

## `400 Bad Request` when creating or patching a route

```text
requests.exceptions.HTTPError: 400 Client Error: Bad Request for url:
http://kong-kong-admin.kong.svc:8001/services/flows-service/routes
```

A `400` from the Admin API is almost always a **schema violation**, and the status
alone says nothing. The useful information is in the response body, which the
command now includes in the error message precisely because of this case.

The real case: the route ownership tag was generated as `prefix:/flows`, and Kong
rejects `:` inside tags. The format was normalized to `prefix-flows`. If a `400`
shows up today, read the body — it names the rejected field.

## `PruneLimitExceeded`

```text
prune would delete 7 of 9 managed route(s), above the safety limit of 4:
allow-a, allow-b, ... Re-run with --force-prune to confirm.
```

The command deleted nothing. Before forcing it, understand why so many routes went
orphan at once, because the guard exists precisely to catch incomplete discovery:

- the image has a broken import that prevented views from loading;
- `KONG_URL_PREFIX` differs from the one used in previous syncs;
- `KONG_SERVICE` points at the wrong service;
- the sync ran with the wrong image.

Run `kong_sync --dry-run` and review the list. If the deletions are legitimate —
several endpoints really were unpublished in the same release — re-run with
`--force-prune`.

## `503` or name resolution failure

A Kong error reaching the upstream, not a service error. Check that
`KONG_SERVICE_URL` is resolvable and reachable from inside Kong, and that the
service is up. Responses carrying `x-kong-*` headers but none of the service's own
headers mean Kong never managed to talk to the backend.

## Write error on the Admin API

If the Admin API consistently refuses to create or delete resources, check whether
Kong is in **DB mode**. In DB-less mode the Admin API is read-only, and neither
`kong_ensure_service` nor `kong_sync` works.

## `kong_sync` warnings

### Duplicate alias

```text
WARNING discover_routes: duplicate route name 'allow-contacts' — overwriting
previous registration (was upstream /api/v2/contacts.json)
```

Two endpoints of the same service declared the same alias, and only one will be
exposed — the last one found while walking the URLs. Pick distinct aliases.

### No routes found

```text
No @api_gateway_expose routes found.
```

Discovery found nothing. Confirm that the decorated views are actually reachable
from the service's `ROOT_URLCONF`, and that `--suffix` matches the project's URL
pattern (the default is `.json`).

## Token issuance problems

| `get-token` status | Meaning |
|---|---|
| `401` | Keycloak token missing, invalid, or expired |
| `404` | user not authorized on the given `project_uuid` |
| `400` | `duration` outside the range allowed by Connect's settings |

## `200` with HTML instead of JSON

The called path did not reach the API endpoint, and the response is a page. Confirm
the correct public path in the `kong_sync --dry-run` plan and, where applicable, use
the `.json` suffix, which forces a pure JSON response.
