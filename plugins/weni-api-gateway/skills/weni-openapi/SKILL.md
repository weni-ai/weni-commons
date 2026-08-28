# Weni OpenAPI generation

Maintain the OpenAPI 3.0 document the VTEX Developer Portal publishes for the
endpoints Weni exposes through the API Gateway. There is one such document, it
lives in this workspace, and every repository behind the gateway is documented
in it.

All paths below are relative to this skill's directory (the one holding this
file). Read `assets/config.json` first — it holds the server URL, the path of
the consolidated document and the canonical example values.

## Invocation

Two modes.

```text
/weni-openapi <repository> [alias]      generate, then merge into the document
/weni-openapi validate [file]           lint an existing file and fix it
```

| Invocation | Mode | Meaning |
| --- | --- | --- |
| `/weni-openapi flows whatsapp_flows` | generate | Document the `flows` route whose gateway alias is `whatsapp_flows`, and merge it into the consolidated document. |
| `/weni-openapi flows` | generate | Document every documentable route in `flows`, each merged into the same document. |
| `/weni-openapi .` | generate | The service repository is the current workspace, for when connect exposes its own routes. |
| `/weni-openapi validate` | validate | Lint the consolidated document and fix what the linter rejects. |
| `/weni-openapi validate docs/openapi/other.json` | validate | Lint that file instead. |

The first token is always the repository, never an alias. `/weni-openapi
channels` is not a valid invocation: say which repository is missing and ask.
If the token matches an alias in the manifest, name the repository the manifest
records for it and confirm before running.

`validate` as the first token always means the validate mode, never a
repository. With no file after it, use the consolidated document. Follow
[Validate mode](#validate-mode) and ignore the generation workflow entirely.

## The document

One file, named in `output.path`: `docs/openapi/VTEX - CX API.json`. It holds
every gateway endpoint of every repository, one key under `paths` per alias, and
it is what gets published to VTEX. A single source of truth is the whole point
of it, so:

- **Never write a per-endpoint file, and never write inside the service
  repository.** Documenting a `flows` endpoint changes nothing in `flows`.
- **Never edit the document directly** — not with an editor, not with a patch.
  Every change goes through `scripts/merge.py`, which cannot damage the
  endpoints you were not asked about.
- Which repository each alias came from is recorded in
  `docs/openapi/.weni-openapi.manifest.json`, next to the document. Internal
  provenance stays out of what VTEX publishes.

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
7. **The endpoints you were not asked about are untouchable.** Their prose,
   examples and ordering survive your run unchanged. That is what makes running
   this skill safe once forty endpoints are in one file.

## Validate mode

For a file a person has edited by hand — usually the consolidated document. The
job is narrow: prove it is still publishable, and repair only what the linter
rejects. Nothing here generates documentation.

Do not build the inventory. Do not regenerate anything. Do not restore anything
from a previous version of the file. The developer's copy is the current truth.

1. **Resolve the file.** With no argument, use `output.path` from
   `config.json`. It must exist and parse as JSON. Report and stop if it does
   not. With several files, handle each independently and lint each on its own.
2. **Lint it.**

   ```bash
   scripts/validate.sh "<file>"
   ```

3. **If there are no findings, change nothing.** Say it is clean and stop. Do
   not reword prose, reorder keys, reformat, or "improve" anything you were not
   asked about. A clean file that you edited anyway is a regression.
4. **If there are findings, fix each one with the smallest edit that satisfies
   the rule**, then lint again. Loop until zero errors and zero warnings. If the
   same rule keeps failing after three attempts, stop and report the rule, the
   location and what you tried.
5. **Report.** See below.

Validate mode is the one place where editing the consolidated document by hand
is expected, because the developer asked for exactly that. Even here, touch only
the nodes Spectral names.

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
- Leave the `## Index` section of `info.description` alone. It is derived from
  `paths` by `scripts/merge.py`; hand-editing it only creates a diff the next
  merge undoes.
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
- [ ] 1. Check the workspace and resolve the repository
- [ ] 2. Build the inventory
- [ ] 3. Settle the scope
- [ ] 4. Read the code behind each route
- [ ] 5. Recover what is already documented
- [ ] 6. Assemble the fragment
- [ ] 7. Write the prose
- [ ] 8. Merge into the document
- [ ] 9. Lint until clean
- [ ] 10. Report the gaps
```

### 1. Check the workspace and resolve the repository

The skill runs where the document lives — the connect workspace. Confirm it
before anything else: either `docs/openapi/VTEX - CX API.json` exists, or the
current directory holds `manage.py` and the `connect` package (the document has
not been created yet). If neither is true, stop and say the skill runs in the
connect workspace, not in the service repository.

Then take the first argument as the repository. It may be a bare name
(`flows`), a path, or `.` for the current workspace; step 2 resolves it. Do not
infer it from the alias, and do not fall back to the current workspace when it
is missing.

### 2. Build the inventory

Run it yourself — the developer should only have to invoke this skill:

```bash
scripts/inventory.sh --repo <repository> --out "$PWD/.openapi/<repo>.inventory.json"
```

Keep `--out` inside this workspace, as `inventory.out_template` in
`config.json` says. Documenting `flows` must leave no artifact in `flows`.

The alias, if the developer gave one, is not passed here — the inventory always
covers every exposed endpoint of that repository, and filtering happens in
step 3.

The script boots Django in the target repository and runs
`manage.py api_gateway_inventory`, resolving on its own what the command needs:
the repository (by name, searched next to this workspace), the virtualenv
interpreter, the GDAL and GEOS paths that PostGIS projects need on macOS, and a
local `weni-commons` checkout when the installed release predates the command.
It prints the inventory path on stdout and the route and warning summary on
stderr.

Other useful flags, all optional: `--service`, `--url-prefix`,
`--weni-commons`, `--python`.

Do not ask the user to run the command, and never fall back to grepping for
`@api_gateway_expose` — a hand-rolled list is exactly the guesswork the
inventory exists to remove. If the script exits non-zero, report what it said
and stop:

| Message | What it means |
| --- | --- |
| `could not find a repository named ...` | The checkout is not next to this workspace. Ask for its path and pass `--repo /path/to/service`. |
| `no manage.py in ...` | That directory is not a Django project. Stop and say so. |
| `the installed weni-commons has no api_gateway_inventory command` | No local checkout was found either. The service repository needs a newer `weni-commons`. |
| A Python traceback while Django boots, pointing inside `site-packages/weni_commons` | The installed release is broken, not just old — a pre-release built mid-merge, for instance. Retry once with `--weni-commons /path/to/weni-commons`, which shadows it, and say in the report that the installed package needs reinstalling. |
| `--url-prefix is required` | `KONG_URL_PREFIX` is missing from the service settings. Ask, then pass `--url-prefix`. |

Check `inventory_version` against `inventory.supported_versions` in
`config.json`. If it is higher, the inventory carries fields this skill does not
know about: continue, but say so in the final report.

### 3. Settle the scope

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
scope. List them and confirm before writing, since this is the expensive path:
three routes means three fragments to write, merge and lint.

Either way, skip every route flagged `missing_alias` — it has no public URL yet.
List those under gaps.

Also run

```bash
scripts/merge.py --list
```

so you know which aliases the document already carries, and from which
repository. An alias in scope that is already there is an update, not an
addition.

### 4. Read the code behind each route

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

### 5. Recover what is already documented

```bash
scripts/merge.py --extract <alias> > .openapi/<alias>.previous.json
```

The output is a fragment: the path block as the document has it today, plus its
tag. Empty `paths` means the alias is new.

When it is not empty, treat this run as a diff, not a rewrite. For every
operation still present with the same fields, keep the existing `summary`,
`description` and `example` untouched — a person may have edited them, and that
work outranks anything generated. Change only what the inventory changed: new or
removed methods, and fields that were added, removed or retyped. State in the
report what you preserved and what you rewrote.

### 6. Assemble the fragment

One fragment per alias, written to `.openapi/<alias>.fragment.json` in this
workspace. It carries exactly two keys:

```json
{
  "paths": { "<public_path>": { "<method>": { } } },
  "tags": [{ "name": "<Alias in sentence case>" }]
}
```

Nothing else. No `info`, no `servers`, no `components`: `merge.py` applies
`assets/gateway-components.json` itself, and the document's overview belongs to
whoever wrote it. Exactly one key under `paths` — the merge refuses more,
because one alias is one route.

Use `assets/openapi-template.json` for the shape of an operation, and reference
the shared components by `$ref` as it does (`#/components/parameters/Accept`,
`#/components/responses/Forbidden` and so on). They are guaranteed to exist in
the document after the merge.

Mapping from inventory to fragment:

| Inventory | OpenAPI |
| --- | --- |
| `public_path` | the key under `paths` |
| `gateway_methods` | operations on that path, lowercased |
| `path_params` | `parameters` with `in: path`, `required: true` |
| `pagination.query_params` | `parameters` with `in: query` |
| `serializers.read.fields` | success response schema |
| `serializers.write.fields` | request body schema for POST, PUT and PATCH |
| `alias` in sentence case | operation `tags`, and the fragment's `tags` entry |

Field-level translation rules and the tag conventions are in
[reference.md](reference.md).

### 7. Write the prose

This is the part introspection cannot do: summaries, descriptions, the
`## Permissions` block and realistic examples. Follow
[reference.md](reference.md) — it carries the VTEX content standards and the
Spectral rules that punish each mistake.

Use the values in `canonical_examples` from `config.json` rather than inventing
new ones, so regenerating produces no example churn.

Two things you do not write here:

- **The `## Index` section of `info.description`.** `merge.py` derives it from
  `paths` and your operation summaries.
- **Conventions shared by several endpoints** (pagination, date formats,
  authentication). Those live once in the document's overview. If your endpoint
  needs one that is missing, say so in the report and propose the wording; do
  not append a private copy to your operation description.

### 8. Merge into the document

```bash
scripts/merge.py --fragment .openapi/<alias>.fragment.json \
                 --alias <alias> --repo <repository> --inventory-version <n>
```

That inserts or replaces one path, unions the tag, applies the shared
components, rewrites the index and updates the manifest. Everything else in the
document keeps its bytes. Add `--dry-run` first if you want to see what it would
do.

Exit 1 is a conflict a person has to settle — two aliases claiming one path, or
a shared component that was edited in place. Report what it said and stop; do
not work around it by editing the document yourself. Ground rule 7 has no
exceptions here: hand-editing a forty-endpoint file to satisfy one endpoint is
how the other thirty-nine get damaged.

### 9. Lint until clean

```bash
scripts/validate.sh "docs/openapi/VTEX - CX API.json"
```

The script bootstraps whatever it needs. Do not ask the user to install Node
or to run npm: if PATH has no Node 18+, it downloads Node LTS into
`~/.cache/weni-openapi` (not the system prefix, not this repository), then
`npm ci` installs `@stoplight/spectral-cli` into `assets/spectral/node_modules`,
which is gitignored. Set `SPECTRAL_FORMAT=json` when you want to parse the
output.

Do not point at an `openapi-schemas` checkout — the skill does not need one to
lint. That repository is only the destination when a human publishes.

Spectral lints the whole document, so read the locations before fixing
anything:

- **Findings inside the path you merged** are yours. Fix the fragment, merge
  again, lint again. Never patch the document to paper over a bad fragment, or
  the next regeneration reintroduces the finding.
- **Findings in another endpoint** were already there. Report them with their
  rule and location and leave them alone unless the developer asks — that
  endpoint may be mid-edit, and it is not in your scope.

Loop until your path is at zero errors and zero warnings. If the same rule keeps
failing after three attempts, stop and report the rule, the location and what
you tried.

### 10. Report the gaps

Close with a short report covering:

- the scope: the repository, and the alias when one was given
- what the merge did: the path added or replaced, the tag, and the index entry
- routes documented, and routes skipped with the reason
- the other aliases the inventory found but the scope excluded, so the developer
  knows what is still undocumented
- every inventory warning, and what you did about it
- fields whose meaning or example you had to infer, so a reviewer can check them
- the Spectral result, separating your path from pre-existing findings
- decisions that need a human: see the open questions in
  [reference.md](reference.md)

Do not create extra markdown files for this. The report goes in the reply.

## Publishing

The document lives in this repository, reviewed like code. Publishing to the
Developer Portal is a separate, human step: copy it into the `openapi-schemas`
checkout under `output.publish_filename` (`VTEX - CX API.json`), make sure its
entry exists in that repository's `config.json`, and open a pull request there.

Confirm the published title and the Portal slug (`output.portal_slug`, which the
index links depend on) with a technical writer before the first publication.
