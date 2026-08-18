# 05 — Installing on a service

This guide covers what to do to put a new service on the gateway. The concrete
values for each environment live in the Rancher secrets; what follows is what each
variable means, the format it expects, and what breaks when it is wrong.

## Before you start

Three things must exist on the infrastructure side, and none of them is created by
the code in this repository:

- **Kong** running in DB mode, with the Admin API reachable from inside the
  cluster.
- The **session-token table in DynamoDB**, and a credential granting the service
  read access to it.
- The service's **Redis**, which usually already exists.

You also need to decide two names, which become the service's identity on the
gateway and should not change afterwards:

- the service **prefix** on the gateway (`/billing`, for example);
- the **Kong service name** (`billing-service`, for example).

## Step 1 — Install the package

```bash
poetry add weni-commons
```

And register the app, which Django needs in order to find the management
commands:

```python
INSTALLED_APPS = [
    ...
    "weni_commons",
]
```

## Step 2 — Configure the settings

The block below is the recommended approach: with everything in `settings.py`, the
commands run with no flags at all. Each value comes from an environment variable,
which is what the Rancher secrets fill in.

```python
# Kong API Gateway (weni_commons.kong) — used by kong_sync and kong_ensure_service
KONG_ADMIN_URL = env.str("KONG_ADMIN_URL")
KONG_URL_PREFIX = env.str("KONG_URL_PREFIX")
KONG_SERVICE = env.str("KONG_SERVICE")
KONG_SERVICE_URL = env.str("KONG_SERVICE_URL")

# Session tokens (weni_commons.auth.SessionTokenAuthentication)
WENI_SESSION_TOKEN_DYNAMODB_TABLE = env.str("WENI_SESSION_TOKEN_DYNAMODB_TABLE")
WENI_SESSION_TOKEN_DYNAMODB_REGION = env.str("WENI_SESSION_TOKEN_DYNAMODB_REGION")
WENI_SESSION_TOKEN_MAX_REDIS_TTL = env.int("WENI_SESSION_TOKEN_MAX_REDIS_TTL")
WENI_SESSION_TOKEN_REDIS_ALIAS = env.str("WENI_SESSION_TOKEN_REDIS_ALIAS")

# Connect project authorization (weni_commons.auth.ConnectProjectAuthorization)
WENI_CONNECT_API_URL = env.str("WENI_CONNECT_API_URL")
WENI_CONNECT_AUTHORIZATION_TIMEOUT = env.int("WENI_CONNECT_AUTHORIZATION_TIMEOUT")
```

### Kong variables

| Variable | Format | Impact |
|---|---|---|
| `KONG_ADMIN_URL` | URL with scheme, pointing at the Admin API (port `8001` by convention). Must start with `http://` or `https://`, and is usually an in-cluster address | This is where the commands write to Kong. Empty or without a scheme, the commands fail with an explicit message. It defaults to `http://localhost:8001`, which is only useful for local development |
| `KONG_URL_PREFIX` | Path starting with `/`, a single segment, such as `/billing` | Defines the prefix of the public paths, the block route name (`billing-default-block`), and the route ownership tag (`prefix-billing`). Changing it after syncing leaves the old routes without the correct tag |
| `KONG_SERVICE` | Kong service name, such as `billing-service` | It is the sync target and the prune scope. **It has no default**: without it the command fails, and that is deliberate, because an implicit value could delete another service's routes |
| `KONG_SERVICE_URL` | URL with scheme for the service, where Kong forwards requests | It is the real traffic destination. Pointing it at the wrong environment is the gateway's most treacherous failure, because Kong answers normally, only from the wrong backend. See [troubleshooting](07-troubleshooting.md) |

### Session-token variables

| Variable | Format | Impact |
|---|---|---|
| `WENI_SESSION_TOKEN_DYNAMODB_TABLE` | The table **name**, not the ARN | This is the table queried on a cache miss. With an ARN instead of a name, every validation fails and the client gets a `403` with no explanation. Empty, the repository becomes a no-op and only Redis is consulted |
| `WENI_SESSION_TOKEN_DYNAMODB_REGION` | AWS region, such as `sa-east-1` | Must be the region where the table lives. A wrong region behaves like a nonexistent table |
| `WENI_SESSION_TOKEN_MAX_REDIS_TTL` | Integer, in seconds | Ceiling for the local cache. A high value reduces DynamoDB lookups but widens the window in which an invalidated token is still accepted; a low value does the opposite |
| `WENI_SESSION_TOKEN_REDIS_ALIAS` | Name of an alias declared in `CACHES` | Picks which Redis connection caches the tokens. A nonexistent alias makes validation fail, and the failure surfaces as a `403` |

### Connect variables

These two are only needed by services that will use
`ConnectProjectAuthorization`. A service that resolves permission through its own
models can leave them out.

| Variable | Format | Impact |
|---|---|---|
| `WENI_CONNECT_API_URL` | Connect base URL, with scheme and no trailing slash | This is where the user's role is resolved. **When empty, the permission denies every request** — the failure is closed, not open |
| `WENI_CONNECT_AUTHORIZATION_TIMEOUT` | Integer, in seconds (default 5) | Timeout for the Connect lookup. Since the timeout happens in the request path, a high value propagates Connect slowness into the service; on timeout, the request is denied |

## Step 3 — Register the authentication

```python
from weni_commons.auth import SessionTokenAuthentication


class MyView(APIView):
    authentication_classes = [SessionTokenAuthentication]
    permission_classes = [IsProjectContributor]
```

Or globally, if the service wants to accept session tokens across the whole API:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "weni_commons.auth.SessionTokenAuthentication",
    ],
}
```

On services with legacy authentication, add `SessionTokenAuthentication` to the
list alongside the existing classes. It returns `None` when the header is not a
valid `Bearer`, so the other classes are still evaluated normally.

The permission is the service's choice, and both options are in
[03 — Authentication](03-authentication.md#authenticating-is-not-authorizing).
Worth repeating that with no permission class at all, the endpoint accepts any
valid token from any project — authentication does not check access.

## Step 4 — Declare the public endpoints

```python
from weni_commons.kong import api_gateway_expose


@api_gateway_expose(alias="invoices", methods=["GET"], service="billing-service")
class InvoicesEndpoint(APIView):
    ...
```

Two recommendations:

- **Always** pass `service=` explicitly. The default is `"flows-service"`, and
  forgetting the parameter registers the route on the Flows service.
- Choose the `alias` carefully, because it is global: two services with the same
  alias collide, and the last one to sync keeps the route.

## Step 5 — Create the service in Kong

Once, at onboarding:

```bash
python manage.py kong_ensure_service
```

This creates the service pointing at `KONG_SERVICE_URL` and the block route, which
is what makes everything that was not exposed answer `403`. The command is
idempotent, so re-running is safe — in fact that is how you fix a
`KONG_SERVICE_URL` that was wrong.

## Step 6 — Sync the routes

Start with the plan, to see what would happen:

```bash
python manage.py kong_sync --dry-run
```

Then apply:

```bash
python manage.py kong_sync
```

In steady state this command runs automatically on every deploy, through Argo
Workflows — see [06 — Deployment](06-deploy-argo-workflows.md).

## Verification checklist

After configuring, confirm in this order. The order matters: each item rules out a
layer, so a failure points straight at the culprit.

1. **The configuration reached the application.** In the service shell:

   ```python
   from django.conf import settings
   settings.KONG_ADMIN_URL, settings.KONG_SERVICE, settings.KONG_URL_PREFIX
   settings.KONG_SERVICE_URL
   settings.WENI_SESSION_TOKEN_DYNAMODB_TABLE
   ```

   Confirm in particular that `KONG_SERVICE_URL` points at **this** environment and
   that the table is a name, not an ARN.

2. **The service can read the DynamoDB table.** With a valid token at hand:

   ```python
   from weni_commons.auth import DynamoDBSessionTokenRepository
   DynamoDBSessionTokenRepository().get("<token>")
   ```

   The return should be a dict with `project`, `user`, and `expire_at`. `None`
   means a nonexistent token, the wrong table, the wrong region, or a credential
   without permission.

3. **The full validation works.**

   ```python
   from weni_commons.auth import ValidateSessionTokenUseCase
   ValidateSessionTokenUseCase().execute("<token>")
   ```

   It should return a `SessionContext`. If step 2 worked and this one does not, the
   problem is in Redis (wrong alias or unavailable connection).

4. **The sync plan is correct.** `python manage.py kong_sync --dry-run` should list
   the expected endpoints and no surprise deletions.

5. **The end-to-end call answers.** Through the gateway address, with the token in
   the `Authorization: Bearer` header. If this step fails after the first four
   passed, the problem is between Kong and the service — start with
   [troubleshooting](07-troubleshooting.md).

6. **Default-deny is active.** Call a path that was **not** exposed and confirm the
   answer is `403` with `"Route not authorized by the gateway"`. If a normal API
   response comes back, the block route does not exist or does not cover the
   prefix.
