# 03 — Authentication

## The session token

The gateway uses a single kind of credential: the **session token**, an opaque
hash issued by Connect and bound to a project.

It is generated with `secrets.token_urlsafe(32)`, so it is a random 43-character
string with no internal structure. Unlike a JWT, it carries no information at
all: anyone who wants to know which project it belongs to has to query the store.
That is on purpose, because it is what makes immediate invalidation possible —
just remove the item from the store, something you cannot do with a
self-contained, signed token.

### Issuing

```bash
curl -s -G "${CONNECT_BASE_URL}/v2/projects/${PROJECT_UUID}/get-token" \
  -H "Authorization: Bearer ${KEYCLOAK_TOKEN}" \
  --data-urlencode "duration=7600"
```

```json
{ "hash": "xATi0rFElmBXmd7FyXgWB-rx7glo2ejmhNui9eItsB4" }
```

This call is authenticated with the Keycloak token of the logged-in session, and
Connect only issues the hash if the user is authorized on the requested project —
otherwise it answers `404`. The `duration` parameter is required, in seconds, and
is validated against `SESSION_TOKEN_MIN_DURATION` and
`SESSION_TOKEN_MAX_DURATION` in Connect's settings; out of range, the answer is
`400`.

On issuance, Connect writes the token to DynamoDB and warms its own Redis. Worth
noting that this warm-up only helps Connect: each service has its own Redis, so a
client's first call to a different service always reads from DynamoDB.

### Using

```http
GET /contacts?limit=10
Authorization: Bearer xATi0rFElmBXmd7FyXgWB-rx7glo2ejmhNui9eItsB4
```

The scheme is always `Bearer`. A legacy API token, in the `Token` scheme, still
works on the services that already accepted it, but it is not the gateway flow.

### Invalidating

```http
POST /v2/projects/{project_uuid}/invalidate-session-token
Authorization: Bearer <session token>

{ "hash": "<token to invalidate>" }
```

This endpoint is authenticated with the session token itself, and Connect checks
that the token being invalidated belongs to the same project as the token that
authenticated the call — if it does not, it answers `403`.

## How the service validates the token

Validation is done by `SessionTokenAuthentication`, in
`weni_commons/auth/authentication.py`, a DRF authentication class. The path is:

```mermaid
flowchart TD
    Start[Request arrives] --> Header{"Authorization header<br/>with Bearer scheme?"}
    Header -->|no| Skip["Returns None,<br/>and the next authentication class takes over"]
    Header -->|yes| Cache["Look up the auth:session-token:hash key in Redis"]
    Cache -->|hit| Ok[Authenticated]
    Cache -->|miss| Dynamo["get_item on DynamoDB by token_hash"]
    Dynamo -->|not found| Skip
    Dynamo -->|found| Ttl{"Still within validity?"}
    Ttl -->|no| Skip
    Ttl -->|yes| Warm[Warm Redis] --> Ok
```

Two behaviors deserve attention:

- **A validation failure returns `None`, not an error.** When the token is
  missing, invalid, expired, or when the store lookup fails, the class returns
  `None`, which makes DRF move on to the next configured authentication class.
  This is deliberate: a misconfigured DynamoDB or Redis must not turn into a
  `500` across the whole API, and services with legacy authentication keep
  working alongside it. The side effect is that an infrastructure failure shows
  up to the client as a `403` rather than a server error — which is what makes
  [troubleshooting](07-troubleshooting.md) that `403` less obvious than it looks.
- **The cache has a time ceiling.** The Redis TTL is
  `min(token time remaining, WENI_SESSION_TOKEN_MAX_REDIS_TTL)`. A 24-hour token
  is not cached for 24 hours: it is periodically reloaded from DynamoDB, which
  bounds the window in which an invalidated token would still be accepted by a
  service that already had it cached.

## What lands on the request

After a successful authentication, the view finds:

| Attribute | Contents |
|---|---|
| `request.user` | `SessionUser`, with an `email` attribute |
| `request.auth` | `SessionContext(project, user, expire_at)` |
| `request.project_uuid` | the UUID of the project the token belongs to |

`SessionUser` is not a Django user: it only exposes `email`, `is_authenticated`,
and `is_anonymous`. That is enough for DRF to consider the request
authenticated, and it is intentional that it is nothing more — `weni-commons`
cannot assume the service has a user model, let alone which one.

## Authenticating is not authorizing

This split is the most important design decision in this part of the system.

`SessionTokenAuthentication` answers two questions only: **is this token valid?**
and **which project and user does it belong to?** It does not check whether the
user may access that project, and it does not check whether the token's project
is the project the view is operating on.

The reason is that this check has no single shape. Some services have an
organization model, others have nothing like it; some need role levels, others
only membership. Putting that logic in authentication would force `weni-commons`
to assume a data model that does not exist in every service.

So the split is: **authentication proves identity, permission decides access.**
Each service picks how to implement the permission, and there are two ready
paths.

### Path 1 — ask Connect

For services without their own organization model, `weni-commons` ships
`ConnectProjectAuthorization`, an abstract permission class in
`weni_commons/auth/connect.py`. It queries Connect and yields the user's role on
the project:

```http
GET {WENI_CONNECT_API_URL}/v2/projects/{project_uuid}/authorization
Authorization: <the same header that arrived on the request>
```

What the base class does: confirms the request is authenticated, reads
`request.project_uuid`, forwards the `Authorization` header to Connect, stores the
returned role on `request.project_authorization`, and delegates the final decision
to the service. What the service does: implement `has_required_role`.

```python
from weni_commons.auth import ConnectProjectAuthorization


class IsProjectContributor(ConnectProjectAuthorization):
    def has_required_role(self, request, view, role: int) -> bool:
        return role >= CONTRIBUTOR


class MyView(APIView):
    authentication_classes = [SessionTokenAuthentication]
    permission_classes = [IsProjectContributor]
```

`has_required_role` is abstract on purpose: without an implementation it raises
`NotImplementedError`, because there is no default access level that would be
safe for every case.

Every failure path denies access: no `project_uuid`, no `Authorization` header,
Connect down, a non-`200` response, or unexpected JSON — the result is always
deny. That includes an empty `WENI_CONNECT_API_URL`: an incomplete configuration
blocks everything rather than allowing everything.

### Path 2 — reuse the permissions the service already has

Services with an organization model and mature permission rules may prefer to
translate the session token into their own objects and keep the permissions they
already have. That is what Flows does in `_resolve_session_user`, in
`temba/api/v2/views_base.py`: from `request.project_uuid` it resolves the `Org`,
finds the Django user by the `SessionUser` email, confirms that user belongs to
the org, and replaces `request.user`. From there the existing permission classes
work unchanged.

The upside is not duplicating permission rules; the cost is a database query per
request, and the service has to mirror users and projects locally.

## DynamoDB

The table is shared across services and has a simple structure:

| Attribute | Type | Contents |
|---|---|---|
| `token_hash` | string | partition key; the token hash |
| `project` | string | project UUID |
| `user` | string | email of the user who generated the token |
| `expire_at` | string | expiration timestamp, in ISO 8601 |
| `ttl` | number | the same `expire_at` as epoch, for DynamoDB native TTL |

`ttl` is what makes DynamoDB delete expired items on its own. It exists alongside
`expire_at` because native TTL requires a numeric epoch attribute, while the
validation in code compares the ISO timestamp.

The repository (`DynamoDBSessionTokenRepository`) tolerates an unconfigured
table: if the table name is empty, every operation becomes a no-op and validation
falls back to Redis only. That allows shipping the code before the table exists,
but in production it is a configuration that does not work for real clients,
because each service has a different Redis from the one Connect warmed.

One detail that has bitten us before: the setting expects the table **name**, not
the ARN. See [troubleshooting](07-troubleshooting.md).

## Next steps

- Code and command details: [04 — Reference](04-weni-commons-reference.md).
- How to configure all of this in a service:
  [05 — Installation](05-installation.md).
