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

## Invocation

Two modes.

```text
/weni-openapi [alias]                       generate
/weni-openapi validate <file> [<file> ...]   lint an existing file and fix it
```

| Invocation | Mode | Meaning |
| --- | --- | --- |
| `/weni-openapi` | generate | Document every documentable route in the current workspace. |
| `/weni-openapi channels` | generate | Document only the route whose gateway alias is `channels`. |
| `/weni-openapi validate docs/openapi/channels.openapi.json` | validate | Lint a file the developer edited, fix what the linter rejects, keep their content. |

`validate` as the first token always means the validate mode, never an alias.
With no file after it, ask which file — do not guess, and do not fall back to
generating. Follow [Validate mode](#validate-mode) and ignore the generation
workflow entirely.

In generate mode the skill runs in the service repository — the workspace that
has `manage.py` and `weni_commons` in `INSTALLED_APPS`. Do not take a repository
name as an argument, and do not look for a sibling checkout. If `manage.py` is
missing from the current directory, say so and stop.

**One file per endpoint, always.** Each alias gets its own schema file, named
after the alias. There is no whole-service schema: documenting three aliases
means writing three files, each with a single path. This holds whether or not
the developer passed an alias — the alias changes how many files you write, never
whether they are split.

**The alias narrows the output, never the inventory.** Always build the full
inventory, then document only what is in scope. An inventory of every exposed
endpoint is cheap and shows the developer what else exists.

A single token is always the alias, never a repository. `/weni-openapi channels`
documents `channels` in the current workspace. `/weni-openapi` documents every
documentable route in the current workspace.

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

## Validate mode

For a file a person has edited by hand. The job is narrow: prove it is still
publishable, and repair only what the linter rejects. Nothing here generates
documentation.

Do not build the inventory. Do not regenerate the document. Do not restore
anything from a previous version of the file. The developer's copy is the
current truth.

1. **Resolve the file.** It must exist and parse as JSON. Report and stop if it
   does not. With several files, handle each independently and lint each on its
   own — a clean sibling says nothing about the file next to it.
2. **Lint it.**

   ```bash
   scripts/validate.sh <file>
   ```

3. **If there are no findings, change nothing.** Say it is clean and stop. Do
   not reword prose, reorder keys, reformat, or "improve" anything you were not
   asked about. A clean file that you edited anyway is a regression.
4. **If there are findings, fix each one with the smallest edit that satisfies
   the rule**, then lint again. Loop until zero errors and zero warnings. If the
   same rule keeps failing after three attempts, stop and report the rule, the
   location and what you tried.
5. **Report.** See below.

### What you may and may not touch

Edit only the nodes Spectral names in its findings, and only as much as the rule
requires. Concretely:

| Finding | Smallest fix |
| --- | --- |
| `must-end-descriptions-with-period` | Add the period. Do not rewrite the sentence. |
| `properties-description`, `parameters-description` | Write the missing description, in the voice the rest of the file already uses. |
| `status-code-descriptions-format` | Correct the casing, e.g. `ok.` to `OK`. |
| `array-items`, `response-body-items-type` | Add the missing `items` or `type`, matching what the example shows. |
| `must-include-response-examples` | Add an example consistent with the schema, reusing `canonical_examples` from `config.json`. |
| `response-body-objects-arrays-example` | Move the example to the content-type level; keep its values. |

Hard limits:

- **Never delete a path, method, field, enum value or example the developer
  added** in order to make a rule pass. If the only way to satisfy a rule is to
  remove their content, stop and ask.
- **Never revert their wording** because you would have phrased it differently.
  Their prose outranks anything generated.
- Ground rule 6 still applies: fix the content, never weaken it to silence a
  rule.
- If something looks factually wrong against the code — a path, method or field
  that the gateway does not serve — **report it as an observation and leave it
  alone**. Verifying that is generate mode's job, and only if they ask for it.

### Report

- the file, and the Spectral result before and after
- every fix, as `rule → location → what you changed`
- anything you deliberately left, with the reason
- observations you did not act on, such as content that looks inconsistent with
  the code

If the file was already clean, say so in one line. Do not pad the report.

## Workflow

Everything below is generate mode.

Copy this checklist and keep it updated as you go:

```text
- [ ] 1. Build the inventory
- [ ] 2. Settle the scope
- [ ] 3. Read the code behind each route
- [ ] 4. Assemble the document
- [ ] 5. Write the prose
- [ ] 6. Lint with Spectral until clean
- [ ] 7. Report the gaps
```

### 1. Build the inventory

Run it yourself — the developer should only have to invoke this skill:

```bash
scripts/inventory.sh
```

Run it from the current workspace, with no repository argument. The alias, if
the developer gave one, is not passed here — the inventory always covers every
exposed endpoint, and filtering happens in step 2.

The script boots Django in the current workspace and runs
`manage.py api_gateway_inventory`, resolving on its own what the command needs:
the virtualenv interpreter, the GDAL and GEOS paths that PostGIS projects need
on macOS, and a local `weni-commons` checkout when the installed release
predates the command. It prints the inventory path on stdout and the route and
warning summary on stderr.

Useful flags, all optional: `--out`, `--service`, `--url-prefix`,
`--weni-commons`, `--python`. Do not pass a repository name.

Do not ask the user to run the command, and never fall back to grepping for
`@api_gateway_expose` — a hand-rolled list is exactly the guesswork the
inventory exists to remove. If the script exits non-zero, report what it said
and stop:

| Message | What it means |
| --- | --- |
| `no manage.py in ...` | The current workspace is not the service repository. Stop and say so. |
| `the installed weni-commons has no api_gateway_inventory command` | No local checkout was found either. The repository needs a newer `weni-commons`. |
| `--url-prefix is required` | `KONG_URL_PREFIX` is missing from the service settings. Ask, then pass `--url-prefix`. |

Check `inventory_version` against `inventory.supported_versions` in
`config.json`. If it is higher, the inventory carries fields this skill does not
know about: continue, but say so in the final report.

### 2. Settle the scope

Summarize what the inventory found before writing anything: the routes, their
public paths and methods, and the warnings.

**With an alias.** Select the route whose `alias` equals it, exactly, and
document only that one. The scope is already explicit, so do not ask for
confirmation — say which route you matched and move on. Other routes still get
mentioned in the summary, so the developer sees what exists, but nothing else is
documented.

If no route carries that alias, stop. List the aliases the inventory does carry
and ask which one was meant. Never document a neighbouring route because its
name looked close.

**Without an alias.** Every route that is not flagged `missing_alias` is in
scope, each producing its own file. List them and confirm before writing, since
this is the expensive path: three routes means three documents to write and lint.

Either way, skip every route flagged `missing_alias` — it has no public URL yet.
List those under gaps.

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

Write one document per alias in scope, to `output.directory` /
`output.filename_template` from `config.json`, where the slug is the alias. So
`/weni-openapi channels` writes `docs/openapi/channels.openapi.json`, and
`/weni-openapi` with three exposed aliases writes three files. Never combine
aliases into one document, and never name a file after the service.

Each file is self-contained and holds exactly one key under `paths`:

- `info.title` and the `info.description` index cover only that endpoint. Do not
  advertise paths the file does not document.
- `tags` declares only that endpoint's tag.
- `components` is the shared block merged verbatim, identical in every file. The
  security scheme and error responses are the same everywhere, and the ruleset
  allows unused components, so do not trim it per file.

The reason for the split: regenerating one endpoint must not touch the others,
and a person's edits to one file must never be at risk from a run scoped to a
different alias.

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

The script bootstraps whatever it needs. Do not ask the user to install Node
or to run npm: if PATH has no Node 18+, it downloads Node LTS into
`~/.cache/weni-openapi` (not the system prefix, not this repository), then
`npm ci` installs `@stoplight/spectral-cli` into `assets/spectral/node_modules`,
which is gitignored. Set `SPECTRAL_FORMAT=json` when you want to parse the
output.

Do not point at an `openapi-schemas` checkout — the skill does not need one to
lint. That repository is only the destination when a human publishes.

Lint every file you wrote, and take each to zero on its own — a clean sibling
says nothing about the file next to it.

Loop: read the violations, fix the content, run again. Stop only at zero
errors. Warnings should also be zero; report any you deliberately leave, with
the reason.

If the same rule keeps failing after three attempts, stop looping and report it
with the rule name, the location and what you tried.

### 7. Report the gaps

Close with a short report covering:

- the scope: the current repository, and the alias when one was given
- the files written, one per alias, with their paths
- routes documented, and routes skipped with the reason
- the other aliases the inventory found but the scope excluded, so the developer
  knows what is still undocumented
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
