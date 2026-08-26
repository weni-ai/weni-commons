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
| Inventory | `api_gateway_inventory`, a `weni_commons` management command | Which endpoints are public, at which URL, with which methods, carrying which fields |
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
`kong_sync`. Since Django discovers commands from installed apps, no service has
to implement it: upgrading the library is what makes it appear, exactly like
`kong_sync`.

```bash
python manage.py api_gateway_inventory --out .openapi/inventory.json
```

In practice you never run this by hand — the skill runs it for you (see
[The plugin](#the-weni-api-gateway-plugin)). It is documented here because it is
useful in CI and when debugging.

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

Then reload the Cursor window. That path is for developing the skill, not for
distributing it: it requires everyone to have this repository cloned. For the
team, use an **organization marketplace** (Dashboard → Plugins → Add Marketplace
→ Import from Repo) with the plugin set to **Required**, which installs it for
every member with no action on their part, and **Auto Refresh** on so fixes
propagate.

With the plugin installed, open the service repository and run it in the Cursor
chat:

```text
/weni-openapi
```

The repository is the current workspace — the one with `manage.py`. Its name is
not an argument.

To document a single endpoint, pass the alias it carries on the gateway:

```text
/weni-openapi channels
```

The inventory still covers **every** endpoint the decorator exposes — it is
cheap, and it shows the developer what else is there. The alias narrows only the
generated schema, which lands in `docs/openapi/channels.openapi.json`.

### Re-validating a hand-edited file

After generation it is common to adjust the file — fix a description, add a
field, change an example. To confirm it is still publishable, without
regenerating anything:

```text
/weni-openapi validate docs/openapi/channels.openapi.json
```

That mode does two things only: run Spectral, and repair whatever it rejects
with the smallest edit each rule requires, until it is clean. It does **not**
build the inventory, does **not** regenerate the document, and does **not**
undo what you wrote. If the only way to silence a rule were to delete your
content, the skill stops and asks. And if something in the file looks
inconsistent with the code, it reports that as an observation instead of
touching it.

Output is always **one file per endpoint**, named after the alias. There is no
whole-service schema: running without an alias produces one file per exposed
endpoint, not one big one. The reason is isolation — regenerating one endpoint
never touches the others, and prose someone edited by hand in one file is never
at risk from a run scoped to a different alias. If the decision later is to
publish a single schema, merging files is mechanical while splitting a
hand-edited one is not.

If no route carries that alias, the skill stops and lists the aliases that exist
rather than documenting the one whose name looked close.

That is the whole interface. The skill builds the inventory itself, through
`scripts/inventory.sh` in the current directory, which resolves whatever the
command needs to boot Django: it picks the virtualenv interpreter, points at the
GDAL and GEOS libraries PostGIS projects require on macOS, and falls back to a
local checkout via `PYTHONPATH` when the installed `weni-commons` predates the
command.

It then reads the code behind each route, assembles the document from the
templates, writes the prose and validates it. The developer does not run two
commands — they run the skill.

The scripts run on macOS and Linux. On Windows, use WSL: virtualenv detection
looks for `bin/python`, not `Scripts/`.

### Validating with the real Spectral

The skill ships a copy of VTEX's ruleset at `assets/spectral/spectral.yml`,
including the two custom JavaScript functions. On the first run, if PATH has no
Node 18+, `validate.sh` downloads a Node LTS into `~/.cache/weni-openapi` — no
`sudo`, no system install — and then `npm ci`s the Spectral CLI into
`assets/spectral/node_modules` (gitignored). Later runs reuse both.

```bash
scripts/validate.sh docs/openapi/channels.openapi.json
```

The loop is: read the violations, fix the content, run again, until it is
clean. The rule is to fix the content, never to weaken it to silence a rule.
The ruleset is a snapshot: if the Portal changes the rules, re-copy from
[openapi-schemas](https://github.com/vtex/openapi-schemas); do not edit the
copy to silence violations.

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
3. **How the Portal groups the endpoints.** Whether each endpoint becomes its own
   reference or several are published together. It does not change what the skill
   generates: always one file per endpoint. Merging files later is mechanical,
   while splitting a hand-edited one is not.

## Next steps

- To understand how a service joins the gateway, and therefore what becomes a
  documentable endpoint: [05 — Installing on a service](05-installation.md).
- To understand `@api_gateway_expose` and `alias`, which define the public path:
  [04 — weni-commons reference](04-weni-commons-reference.md).
