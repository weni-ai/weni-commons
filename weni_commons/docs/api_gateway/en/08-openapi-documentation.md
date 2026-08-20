# 08 — OpenAPI documentation

Exposing an endpoint on the gateway is half the work. The other half is
documenting it on the
[VTEX Developer Portal](https://developers.vtex.com/docs/api-reference), which
publishes **OpenAPI 3.0** schemas versioned in the
[openapi-schemas](https://github.com/vtex/openapi-schemas) repository.

Writing those schemas by hand is expensive and does not scale: a single list
endpoint runs past 300 lines of JSON, under style rules a linter rejects at the
slightest deviation. And the cost repeats for every service that joins the
gateway.

## The idea: separate what is verifiable from what is prose

Generation is split in two layers, and that split is the whole point.

| Layer | Produced by | Answers |
|---|---|---|
| Inventory | `python manage.py api_gateway_inventory` | Which endpoints are public, at which URL, with which methods, carrying which fields |
| Documentation | the `weni-openapi` skill, in Cursor | What each endpoint means, and what a realistic payload looks like |

The inventory is read from Django's URL resolver and the DRF serializers. The
answers that **cannot be wrong** — the public path, the allowed methods, the
field names and types — are not inferred by a model, they are extracted from the
code the gateway actually serves.

What is left for the prose layer is exactly what no introspection can produce:
what each field means, the operation summary and a plausible example.

One practical consequence: the automation does not depend on docstrings. The
flows views carry rich ones, but that is a flows peculiarity — the other
repositories have none, and the automation has to work in all of them.

## The `api_gateway_inventory` command

It ships with `weni_commons`, so it only needs `weni_commons` in
`INSTALLED_APPS` and `KONG_URL_PREFIX` configured — the same preconditions as
`kong_sync`.

```bash
python manage.py api_gateway_inventory --out .openapi/inventory.json
```

It makes no network call and writes nothing to Kong: it walks the URL resolver,
finds the views decorated with `@api_gateway_expose` and describes each one.

| Flag | Effect |
|---|---|
| `--out` | Writes to the given path; without it the JSON goes to stdout |
| `--service` | Restricts to one Kong service; every service by default, since a repository may expose views to more than one |
| `--suffix` | URL suffix used during discovery, same as `kong_sync` |
| `--indent` | JSON indentation; `0` produces compact output |
| `--fail-on-warnings` | Exits with an error when warnings are reported, useful in CI |

With `--out`, the summary goes to stderr so stdout stays a clean JSON stream and
the command can be piped.

### What each route carries

Beyond the public path and the methods, each route carries the view's file and
line, the read and write serializers with every field typed, the pagination, the
filters, the permission and authentication classes, and the path parameters
already typed from the Django converter.

Introspection is always best-effort and never fails the command. A serializer
that cannot be instantiated degrades to its declared fields, and a field that
cannot be classified is marked `unresolved` rather than given a wrong type.

### The warnings are the most useful part

The inventory does not silently fill in what it could not settle — it reports it.
Two warnings deserve attention because they point at real problems.

`missing_alias` means the route is only reachable under the service prefix, so it
has no customer-facing URL yet. Those routes are not documented.

`method_mismatch` means the view implements methods the gateway blocks. That is
the case of `ContactsEndpoint` in flows: it implements `GET`, `POST` and
`DELETE`, but the decorator only allows `GET`. Documenting `POST` would publish a
`405`.

The others are `no_serializer`, `serializer_declared_only`, `unresolved_fields`
and `duplicate_route_name`. What to do about each is in the skill's
`reference.md`.

## The `weni-api-gateway` plugin

Generation runs in the repository that owns the endpoints, not in
`weni-commons`. That is why it is distributed as a Cursor plugin: install it once
and the skill is available in every workspace, without each service having to
vendor a copy of the playbook.

The plugin lives in this repository, under `plugins/weni-api-gateway/`, because
its correctness is tied to the inventory format — the two are versioned
together.

To install it for development, from the `weni-commons` root:

```bash
ln -s "$(pwd)/plugins/weni-api-gateway" ~/.cursor/plugins/local/weni-api-gateway
```

Then reload the Cursor window. For the team, add this repository to the
organization marketplace and install the plugin from **Customize**.

With the plugin installed, in the service repository:

```text
/weni-openapi
```

The skill builds the inventory, reads the code behind each route, assembles the
document from the templates, writes the prose and validates it.

### Validating with the real Spectral

`openapi-schemas` carries VTEX's ruleset in `.spectral.yml`, with two custom
JavaScript functions. The skill runs the **real Spectral CLI** against it:

```bash
scripts/validate.sh docs/openapi/flows.openapi.json
```

The script locates the `openapi-schemas` checkout — or takes the path from
`OPENAPI_SCHEMAS_REPO` — and runs the linter from inside it so the custom
functions resolve. The loop is: read the violations, fix the content, run again,
until it is clean. The rule is to fix the content, never to weaken it to silence
a rule.

The difference in approach is worth noting: VTEX's own flow *simulates* Spectral
through an MCP server. Running the real linter is more reliable, and costs
nothing.

## Pilot result

The pilot ran over the two routes flows exposes today, `/contacts` and
`/channels`. The generated document passed Spectral **with no findings at any
severity on the first run** — for comparison, schemas already published by VTEX
report errors under that same ruleset.

The manual work landed exactly where the layer split predicted: reading the
bodies of the seven `SerializerMethodField` in `ContactReadSerializer`, whose
shape is not introspectable, and finding two query parameters (`order_by` and
`reverse`) that the pagination class reads directly.

The pilot also found a bug: a `DictField` was described as an array, because in
DRF it also has a `child` attribute. It was fixed and covered by a test.

## What stays a human decision

The automation does not decide three things, and they remain open:

1. **Whether the public base includes `/api/v1`.** The configured server is
   `https://cx.vtex.com/api/v1`, while Kong registers flat paths such as
   `/contacts`. That is only consistent if the edge maps `/api/v1/contacts` to
   Kong's `/contacts`. It needs confirmation from infrastructure.
2. **The published title and file name.** The Portal derives its URL slug from
   them, so it is a technical writer's call.
3. **One schema or several.** Whether each service publishes its own or all of
   them compose a single gateway schema. Until that is settled, the command
   generates one file per service, which keeps both options open.

## Next steps

- To understand how a service joins the gateway, and therefore what becomes a
  documentable endpoint: [05 — Installing on a service](05-installation.md).
- To understand `@api_gateway_expose` and `alias`, which define the public path:
  [04 — weni-commons reference](04-weni-commons-reference.md).
