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

Generation does not run in the repository that owns the endpoint. It runs in
**connect**, because that is where the published document lives: a single
`docs/openapi/VTEX - CX API.json` holding every gateway endpoint of every
repository. `openapi-schemas` is organised that way — each `VTEX - *.json` is a
product-level API with many endpoints, often coming from several code
repositories — and one document is also the only way to have one source of
truth.

It is distributed as a Cursor plugin so the skill is available without each
service vendoring a copy of the playbook.

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

With the plugin installed, open the **connect** workspace and run it in the
Cursor chat, naming the repository that owns the endpoint and the alias it
carries on the gateway:

```text
/weni-openapi flows whatsapp_flows
```

The first argument is the repository the skill boots Django in; a bare name is
enough, since the checkout is found next to the workspace. Drop the second and
every exposed endpoint of that repository is documented.

The inventory always covers **every** endpoint the decorator exposes — it is
cheap, and it shows the developer what else is there. The alias narrows only what
gets documented. The inventory itself is written into connect's `.openapi/`
directory, which is gitignored, so documenting `flows` leaves nothing behind in
`flows`.

### Merging instead of writing

The agent never writes the consolidated document. It writes a fragment carrying
the single path it was asked about, and `scripts/merge.py` merges that fragment:

```bash
scripts/merge.py --fragment .openapi/whatsapp_flows.fragment.json \
                 --alias whatsapp_flows --repo flows
```

The script inserts or replaces exactly one path, unions the tag, applies the
shared `security` and `components` block, rebuilds the `## Index` section of the
overview from `paths`, and records in
`docs/openapi/.weni-openapi.manifest.json` which repository the alias came from —
provenance stays in a sidecar, out of what VTEX publishes.

Everything else in the document keeps its bytes. That is the property that makes
this safe at forty endpoints: prose someone edited by hand last month cannot be
damaged by a run scoped to a different alias, and re-running with an unchanged
fragment produces no diff at all.

Conflicts are refusals, never overwrites. Two aliases claiming one path, or a
shared component edited in place, exit non-zero and ask a person to settle it.

The other subcommands: `--extract <alias>` prints what the document already says
about an alias, which is how a regeneration preserves prose; `--list` shows every
documented alias with its repository; `--remove` drops one that lost its
decorator; `--reindex` rebuilds the index alone, after summaries or the Portal
slug change.

### Re-validating a hand-edited file

After generation it is common to adjust the file — fix a description, add a
field, change an example. To confirm it is still publishable, without
regenerating anything:

```text
/weni-openapi validate
```

That mode does two things only: run Spectral, and repair whatever it rejects
with the smallest edit each rule requires, until it is clean. It does **not**
build the inventory, does **not** regenerate the document, and does **not**
undo what you wrote. If the only way to silence a rule were to delete your
content, the skill stops and asks. And if something in the file looks
inconsistent with the code, it reports that as an observation instead of
touching it.

Without a file argument it lints the consolidated document, which is the case
that matters. Pass a path only for some other file.

If no route carries the alias you asked for, the skill stops and lists the
aliases that exist rather than documenting the one whose name looked close.

That is the whole interface. The skill builds the inventory itself, through
`scripts/inventory.sh --repo <repository>`, which resolves whatever the command
needs to boot Django: it finds the checkout, picks the virtualenv interpreter,
points at the GDAL and GEOS libraries PostGIS projects require on macOS, and
falls back to a local checkout via `PYTHONPATH` when the installed
`weni-commons` predates the command.

It then reads the code behind each route, assembles the fragment from the
templates, writes the prose, merges and validates. The developer does not run
two commands — they run the skill.

The scripts run on macOS and Linux. On Windows, use WSL: virtualenv detection
looks for `bin/python`, not `Scripts/`.

### Validating with the real Spectral

The skill ships a copy of VTEX's ruleset at `assets/spectral/spectral.yml`,
including the two custom JavaScript functions. On the first run, if PATH has no
Node 18+, `validate.sh` downloads a Node LTS into `~/.cache/weni-openapi` — no
`sudo`, no system install — and then `npm ci`s the Spectral CLI into
`assets/spectral/node_modules` (gitignored). Later runs reuse both.

```bash
scripts/validate.sh "docs/openapi/VTEX - CX API.json"
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

The pilot ran over the routes flows exposes today: `/contacts`, `/channels` and
`/events`, all three now in `VTEX - CX API.json`. The generated documents passed
Spectral **with no findings at any severity on the first run** — for comparison,
schemas already published by VTEX report errors under that same ruleset.

The manual work landed exactly where the layer split predicted: reading the
bodies of the seven `SerializerMethodField` in `ContactReadSerializer`, whose
shape is not introspectable, and finding two query parameters (`order_by` and
`reverse`) that the pagination class reads directly.

The pilot also found a bug: a `DictField` was described as an array, because in
DRF it also has a `child` attribute. It was fixed and covered by a test.

## Publishing

The document is versioned in connect and reviewed like code. Publishing is a
separate, human step: copy `docs/openapi/VTEX - CX API.json` into an
[openapi-schemas](https://github.com/vtex/openapi-schemas) checkout under the
same name, confirm its entry exists in that repository's `config.json`, and open
a pull request there. The manifest stays behind — it is ours, not VTEX's.

## What stays a human decision

The automation does not decide two things, and they remain open:

1. **Whether the public base includes `/api/v1`.** The configured server is
   `https://cx.vtex.com/api/v1`, while Kong registers flat paths such as
   `/contacts`. That is only consistent if the edge maps `/api/v1/contacts` to
   Kong's `/contacts`. It needs confirmation from infrastructure.
2. **The Portal slug.** The file name is settled — `VTEX - CX API.json` — but the
   slug the Portal derives from it is a technical writer's call, and every link
   in the index depends on it. The skill assumes `cx-api`; if it changes, one
   `merge.py --reindex` rewrites every link.

A third question is now settled: the Portal publishes **one reference per API**,
so every gateway endpoint of every repository goes into the same document.

## Next steps

- To understand how a service joins the gateway, and therefore what becomes a
  documentable endpoint: [05 — Installing on a service](05-installation.md).
- To understand `@api_gateway_expose` and `alias`, which define the public path:
  [04 — weni-commons reference](04-weni-commons-reference.md).
