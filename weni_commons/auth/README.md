# Authentication and Permissions

A single DRF authentication class, `WeniAuthentication`, accepts **two token
formats** through one entry point:

- **JWT** — App IO / inter-module tokens signed with `JWT_PUBLIC_KEY`. The
  signed payload carries tenant claims (`project_uuid`, `vtex_account`), which
  are **immutable** — request values never override them.
- **Keycloak (OIDC)** — the existing browser/session flow, used as a fallback.
  Tenant scope is **resolved from the request** using a standardized set of
  keys and locations (see below).

Either way, the tenant scope is resolved once, at authentication time, and
placed on `request.auth`. **Views must read it exclusively from `self.auth`**
(never from the serializer or the raw request) so every endpoint behaves
consistently and a future permission class can validate project access in a
uniform way.

## Request flow

1. Client sends a token in `X-Weni-Auth` (App IO / inter-module JWT) or
   `Authorization: Bearer <token>` (Keycloak session from the browser).
2. `WeniAuthentication` tries to validate the token as a Weni JWT first. If it
   is not a Weni JWT (invalid signature / not ours), it falls back to Keycloak.
   An expired Weni JWT fails hard — it does **not** fall back.
3. Either way it stores a `WeniAuthContext` on `request.auth` (a DRF attribute,
   not an HTTP header) before the view runs.

## Standardized tenant resolution (Keycloak)

For Keycloak callers the tenant is looked up from the request, in this order:

1. URL keyword arguments (`request.resolver_match.kwargs`)
2. Query parameters
3. Headers
4. Request body

Keys are matched **case-insensitively, ignoring `-` and `_`**, so a single
canonical key also accepts its variants:

| Field | Accepted keys (and variants) |
|---|---|
| `project_uuid` | `project_uuid`, `project-uuid`, `projectUuid`, `project` |
| `vtex_account` | `vtex_account`, `vtex-account`, `vtexAccount` |

Endpoints that expose these values under other names must be refactored to one
of the standard keys. For JWT callers this resolution is skipped entirely — the
values come from the signed token.

## Configuration

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "weni_commons.auth.WeniAuthentication",
    ],
}

JWT_PUBLIC_KEY = env.str("JWT_PUBLIC_KEY", default="")          # validates Weni JWTs
OIDC_DRF_AUTH_BACKEND = "my_project.auth.KeycloakOIDCBackend"    # Keycloak fallback
```

Both settings are optional and independent: configure only `OIDC_DRF_AUTH_BACKEND`
to keep the current Keycloak-only behavior, and add `JWT_PUBLIC_KEY` when you
want to also accept inter-module JWTs.

## Reading auth data in a view

The `WeniAuthViewMixin` exposes the context. Tenant scope is already resolved,
so the view reads it directly from `self.auth` — the same code works for JWT and
Keycloak callers, with no branching.

**Accessing a tenant field means it is required in that context**: it returns
the value or raises `403` when absent. Use the `has_*` flags when the field is
optional:

```python
from rest_framework.views import APIView
from weni_commons.auth import WeniAuthentication, WeniAuthViewMixin


class MyView(WeniAuthViewMixin, APIView):
    authentication_classes = [WeniAuthentication]

    def post(self, request):
        vtex_account = self.auth.vtex_account       # 403 if missing (required here)
        email = self.user_email                     # from token; from request for internal Keycloak
        internal = self.is_internal                 # service-to-service caller?

        if self.auth.has_project_uuid:              # optional access
            project_uuid = self.auth.project_uuid
        ...
```

This is the single, Pythonic access style: there is no separate "get or raise"
method — accessing the attribute *is* the enforcement, so the library validates
presence for you instead of each view testing for `None` by hand.

**Without the mixin** — plain helpers return `None` instead of raising, for code
that must not fail on absence:

```python
from weni_commons.auth import (
    get_project_uuid,
    get_vtex_account,
    get_user_email,
    is_internal_request,
)

project_uuid = get_project_uuid(request)   # None when unresolved
vtex_account = get_vtex_account(request)
email = get_user_email(request)
internal = is_internal_request(request)
```

> Do **not** read tenant scope from `serializer.validated_data` or from the raw
> request. Always go through `self.auth` / the helpers, so the value is the one
> validated by the library.

## Reading the context (`request.auth`)

Everything is read from `request.auth` (a `WeniAuthContext`) — not an HTTP header:

| Attribute | Type | Description |
|---|---|---|
| `is_jwt` | `bool` | `True` when authenticated with a Weni JWT |
| `is_keycloak` | `bool` | `True` when authenticated with Keycloak |
| `project_uuid` | `str` | Resolved project UUID; **raises 403** when accessed while absent |
| `vtex_account` | `str` | Resolved VTEX account; **raises 403** when accessed while absent |
| `has_project_uuid` | `bool` | Whether a project UUID is available (no raise) |
| `has_vtex_account` | `bool` | Whether a VTEX account is available (no raise) |
| `account_id` | `str` | Optional account identity claim; **raises 400** (`ValidationError`) when accessed while absent |
| `has_account_id` | `bool` | Whether an account id is available (no raise) |
| `user_email` | `Optional[str]` | Authenticated principal's email. From the token, except for internal Keycloak callers, where it is the acting user resolved from the request (`user` / `user_email`) |
| `is_internal` | `bool` | Service-to-service caller |
| `token_type` | `str` | `"jwt"` or `"keycloak"` |
| `raw_payload` | `Optional[dict]` | Raw decoded claims |

For JWT callers the token must carry at least one of `project_uuid` /
`vtex_account` (enforced at authentication). For Keycloak callers a missing
tenant is allowed (identity-only access) — the `403` only happens if a view
actually accesses the missing field.

`account_id` is an **optional identity claim**, not tenant scope: it is read
only from the token (never from request body/params, to avoid spoofing) and is
not required to authenticate. Because a route that needs it but does not receive
it is a *malformed request* rather than an authorization failure, accessing
`self.auth.account_id` while absent raises `ValidationError` (**HTTP 400**),
whereas `project_uuid` / `vtex_account` raise `PermissionDenied` (**403**). Use
`self.auth.has_account_id` for optional access:

```python
account_id = self.auth.account_id          # 400 if the route requires it and it is missing

if self.auth.has_account_id:               # optional
    account_id = self.auth.account_id
```

## Call examples — JWT vs Keycloak

The **view code is the same** for both token types (`self.auth.vtex_account`).
What changes is how the request arrives and where the tenant comes from.

**JWT (App IO / inter-module)** — token in `X-Weni-Auth`, tenant in the signed
payload; the request body does not carry the tenant:

```http
POST /api/webchat/activate/
X-Weni-Auth: eyJhbGciOiJSUzI1NiIs...
Content-Type: application/json

{"app_uuid": "..."}
```

```jsonc
// decoded JWT payload — tenant and account_id come from the token, not the body
{ "vtex_account": "mystore", "account_id": "acc-123", "user_email": "user@weni.ai" }
```

Result: `self.auth.is_jwt is True`, `self.auth.vtex_account == "mystore"`,
`self.auth.account_id == "acc-123"`.

**Keycloak (browser/session)** — token in `Authorization: Bearer`, tenant taken
from the request in a standardized location (any of the forms below is valid):

```http
# query param
POST /api/webchat/activate/?vtex_account=mystore
Authorization: Bearer <keycloak-access-token>
```

```http
# URL kwarg
POST /api/mystore/webchat/activate/
Authorization: Bearer <keycloak-access-token>
```

```http
# header
POST /api/webchat/activate/
Authorization: Bearer <keycloak-access-token>
Vtex-Account: mystore
```

```http
# body
POST /api/webchat/activate/
Authorization: Bearer <keycloak-access-token>
Content-Type: application/json

{"vtex_account": "mystore", "app_uuid": "..."}
```

Result: `self.auth.is_keycloak is True`, `self.auth.vtex_account == "mystore"`
(resolved from the request), `self.auth.user_email` from the Keycloak token.
For **internal** Keycloak callers the token identifies the service account, so
`self.auth.user_email` is instead the acting user resolved from the request
(`user` / `user_email`), falling back to the token only when the request omits
it.

Note: `account_id` is **not** resolved from the request for Keycloak callers —
it comes only from the token claims (`account_id` / `accountId`). A body/query
`account_id` is ignored, so `self.auth.account_id` raises `400` unless the claim
is present.

## When it is not a good fit

- **Identity-only JWT calls** — a Weni JWT **must** carry at least one of
  `project_uuid` / `vtex_account`; a token with neither is rejected at
  authentication. If you need a pure identity inter-module call (no tenant),
  this authenticator is not the right tool.
- **Keycloak routes that require a tenant it never receives** — Keycloak
  identity-only requests authenticate fine, but the moment a view accesses
  `self.auth.project_uuid` / `self.auth.vtex_account` and the value is absent,
  it raises `403`. To block before the view, read the field only inside
  `if self.auth.has_*`.
- **Non-standard tenant keys** — values sent under keys outside the accepted set
  (e.g. `?p=...`, `?store=...`) are **not** resolved. Refactor the endpoint to a
  standard key instead of widening the resolver.
- **Reading tenant from the serializer/body directly** — bypasses the library's
  validation and breaks the standardization. Always go through `self.auth`.

## Permissions

Composable DRF permission classes are provided:

- `IsWeniAuthenticated` — request carries a valid `WeniAuthContext`.
- `CanCommunicateInternally` — internal service-to-service caller.
- `HasProjectPermission` — contributor/moderator level, resolved via an injected
  `UserPermissionsServiceInterface`.

```python
permission_classes = [IsWeniAuthenticated]
```

When a route requires a tenant, read it via `self.auth.project_uuid` /
`self.auth.vtex_account` (raises `403` when absent) rather than a dedicated
permission class.

## Required Django settings

- `JWT_PUBLIC_KEY`: public key used to validate App IO / inter-module JWTs
- `OIDC_DRF_AUTH_BACKEND`: import path to the Keycloak OIDC backend class
