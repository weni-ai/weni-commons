---
name: weni-openapi
description: Generates and updates VTEX Developer Portal OpenAPI 3.0 schemas for Django REST endpoints exposed through the Weni API Gateway, using a deterministic route inventory from weni-commons plus the view and serializer source. Use when documenting gateway endpoints, producing or refreshing a "VTEX - *.json" schema for the openapi-schemas repository, or when the user mentions the Developer Portal, api_gateway_expose or api_gateway_inventory.
disable-model-invocation: true
---

# Weni OpenAPI generation

Produce the OpenAPI 3.0 schema the VTEX Developer Portal publishes, for the
endpoints this repository exposes through the Weni API Gateway.

All paths below are relative to this skill's directory (the one holding this
file). Read `assets/config.json` first — it holds the server URL, output paths
and the canonical example values.

## Ground rules

These are what keep generated documentation truthful. Do not negotiate them.

1. **The inventory decides which endpoints exist.** Never document a path or
   method absent from it, and never silently drop one that is present. The
   inventory is built from Django's URL resolver, so it is what the gateway
   actually serves.
2. **Document `gateway_methods`, never `view_methods`.** A view may implement
   POST while Kong only allows GET; documenting POST would publish a 405.
3. **Field names and types come from the serializer descriptors**, not from
   reading a payload example or guessing from the field name.
4. **Routes with a `missing_alias` warning are not documented.** They are only
   reachable under the service prefix, so they have no public URL yet. Report
   them instead.
5. **Docstrings are a hint, never the source.** Most repositories have none.
   When one exists, verify every claim against the code before using it.
6. **Never weaken content to silence Spectral.** Fix the content.

## Workflow

Copy this checklist and keep it updated as you go:

```text
- [ ] 1. Build the inventory
- [ ] 2. Agree on the scope
- [ ] 3. Read the code behind each route
- [ ] 4. Assemble the document
- [ ] 5. Write the prose
- [ ] 6. Lint with Spectral until clean
- [ ] 7. Report the gaps
```

### 1. Build the inventory

Run the command from `config.json` at the repository root:

```bash
python manage.py api_gateway_inventory --out .openapi/inventory.json
```

It needs `KONG_URL_PREFIX` in Django settings or the environment, and
`weni_commons` in `INSTALLED_APPS`. If the command does not exist, the installed
`weni-commons` predates it — say so and stop rather than falling back to
grepping for decorators.

Check `inventory_version` against `inventory.supported_versions` in
`config.json`. If it is higher, the inventory carries fields this skill does not
know about: continue, but say so in the final report.

### 2. Agree on the scope

Summarize what the inventory found before writing anything: the routes, their
public paths and methods, and the warnings. Then confirm the scope — all
documentable routes, or a subset.

Skip every route flagged `missing_alias`. List them under gaps.

### 3. Read the code behind each route

For each route in scope, read the source the inventory points at:

- `view.file` at `view.line` — the handler, its status codes, its error
  branches, and query parameters read manually from `request.query_params`
  (these never appear in a serializer)
- `serializers.read.file` and `serializers.write.file` — what the fields mean
- `pagination.query_params`, plus the source of `pagination.class` — a paginator
  that overrides `get_ordering` often reads its own query parameters, and those
  are invisible to introspection
- `filters` — filter backends, which imply query parameters

What to extract, per method: success status code and body, the query and path
parameters, the request body for write methods, and the error responses the code
can actually produce.

Resolve `unresolved` fields here. A `SerializerMethodField` needs its method
read; an unmapped field class needs its definition read. If the shape is still
unclear, ask instead of inventing one.

### 4. Assemble the document

Start from `assets/openapi-template.json` and merge
`assets/gateway-components.json` verbatim — its `security` array and its
`components` (security scheme, `Accept` / `Content-Type` parameters, shared
error responses) are already Spectral-clean.

Mapping from inventory to document:

| Inventory | OpenAPI |
| --- | --- |
| `public_path` | key under `paths` |
| `gateway_methods` | operations on that path, lowercased |
| `path_params` | `parameters` with `in: path`, `required: true` |
| `pagination.query_params` | `parameters` with `in: query` |
| `serializers.read.fields` | success response schema |
| `serializers.write.fields` | request body schema for POST, PUT and PATCH |
| `alias` in sentence case | operation `tags` |

Write to `output.directory` / `output.filename_template` from `config.json`.

Field-level translation rules, the `info.description` overview, and the tag
conventions are in [reference.md](reference.md).

### 5. Write the prose

This is the part introspection cannot do: summaries, descriptions, the
`## Permissions` block and realistic examples. Follow
[reference.md](reference.md) — it carries the VTEX content standards and the
Spectral rules that punish each mistake.

Use the values in `canonical_examples` from `config.json` rather than inventing
new ones, so regenerating produces no example churn.

**Updating an existing schema.** If the output file already exists, treat this
as a diff, not a rewrite. Load it, and for every operation still present with
the same fields, keep the existing `summary`, `description` and `example`
untouched — a person may have edited them, and that work outranks anything
generated. Change only what the inventory changed: new or removed paths and
methods, and fields that were added, removed or retyped. State in the report
what you preserved and what you rewrote.

### 6. Lint with Spectral until clean

```bash
scripts/validate.sh docs/openapi/<file>.json
```

The script runs the real Spectral CLI against VTEX's own ruleset in the
`openapi-schemas` repository. Point it there with `OPENAPI_SCHEMAS_REPO` when it
cannot find the checkout. Set `SPECTRAL_FORMAT=json` when you want to parse the
output.

Loop: read the violations, fix the content, run again. Stop only at zero
errors. Warnings should also be zero; report any you deliberately leave, with
the reason.

If the same rule keeps failing after three attempts, stop looping and report it
with the rule name, the location and what you tried.

### 7. Report the gaps

Close with a short report covering:

- routes documented, and routes skipped with the reason
- every inventory warning, and what you did about it
- fields whose meaning or example you had to infer, so a reviewer can check them
- the final Spectral result
- decisions that need a human: see the open questions in
  [reference.md](reference.md)

Do not create extra markdown files for this. The report goes in the reply.

## Publishing

The generated file lives in this repository, versioned with the code that
produced it. Publishing to the Developer Portal is a separate, human step: copy
it into the `openapi-schemas` checkout under
`output.publish_filename_template` and open a pull request there.

Confirm the published title and file name with a technical writer before the
first publication — the Portal derives its URL slug from them.
