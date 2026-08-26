# Reference: inventory, VTEX standards, Spectral

Detail for the `weni-openapi` skill. Read the section you need rather than the
whole file.

## Reading the inventory

Per-route fields worth knowing:

| Field | Meaning |
| --- | --- |
| `route_name` | Kong route name, e.g. `allow-contacts`. Cross-references what `kong_sync` created. |
| `public_path` | The URL a customer calls, relative to the server URL. This is the key under `paths`. |
| `gateway_methods` | Methods Kong lets through. The only methods to document. |
| `view_methods` | Methods the view implements. For comparison only. |
| `compat_paths` | Prefixed aliases Kong also answers. Internal, never documented. |
| `upstream_path` | The Django path behind the gateway. Never documented. |
| `path_params` | Path parameters with type and format already resolved from the Django converter. |
| `serializers.read` / `.write` | Field descriptors for the response and request bodies. |
| `pagination.query_params` | Query parameter names the paginator reads. |
| `warnings` | What the inventory could not settle for this route. |

### Warning codes and what to do

| Code | Action |
| --- | --- |
| `missing_alias` | Do not document the route. List it under gaps: it needs an `alias` on `@api_gateway_expose` to have a public URL. |
| `method_mismatch` | Document only `gateway_methods`. Report the blocked methods so someone decides whether to widen the decorator. |
| `no_serializer` | Read the view body and derive the payload from what it returns. Say in the report that the shape came from the handler. |
| `serializer_declared_only` | The serializer could not be instantiated, so model-derived fields are missing. Read the serializer and its `meta.model` to complete the field list. |
| `unresolved_fields` | Read the named fields in the source. Never assume `string`. |
| `duplicate_route_name` | Two different views claim the same route. Kong keeps the last. Document that one and report the collision as a bug. |

### Field descriptors to schema

Each descriptor already carries `type` and, when applicable, `format`. Translate
directly, and use the metadata rather than restating it in prose:

- `read_only: true` — response only. Exclude it from the request body schema.
- `write_only: true` — request only. Exclude it from the response schema.
- `required: false` — leave the name out of the schema's `required` array.
- `allow_null: true` — set `"nullable": true`.
- `enum` — copy verbatim.
- `max_length`, `min_length`, `max_value`, `min_value` — copy as the matching
  OpenAPI keywords.
- `help_text` — the starting point for the description, not the final text. It
  is written for developers; rewrite it for customers and end it with a period.
- `type: "array"` — the descriptor's `items` becomes the schema's `items`.
- `type: "object"` with `properties` — a nested object. Inline it; do not create
  a component for it unless the exact same schema appears in several places.
- `truncated: true` — the descriptor stopped at a recursion or depth limit. Read
  the serializer to finish it.

## Content standards

VTEX's full standards live in the `openapi-schemas` repository, at
`.cursor/rules/openapi-standards.mdc`, useful as extra reading. The rules the
linter actually enforces are the snapshot in `assets/spectral/spectral.yml`.
The ones that matter most here:

### Summaries

- Sentence case, no trailing period, three to six words.
- Describe the operation, never the HTTP method. "List contacts", not
  "Get contacts (GET)".
- Enforced by `must-include-operation-summary` and
  `summaries-should-be-in-sentence-case`.

### Descriptions

- What the endpoint does, in one or two sentences, then the `## Permissions`
  section. Use escaped markdown with `\r\n` for line breaks.
- Every property description must end with a period
  (`must-end-descriptions-with-period`) and none may be empty
  (`no-empty-descriptions`).
- Every property and every parameter needs a description
  (`properties-description`, `parameters-description`).
- Write "email", never "e-mail" (`write-email-not-e-mail`).

### Permissions block

VTEX's own template is about License Manager resources, which do not apply to
us. Use this instead, verbatim, at the end of every operation description:

```text
## Permissions

This endpoint requires a session token issued by Weni Connect. The token identifies the user and the project, and the user must have access to that project. Otherwise, the request returns a status code `403` error.
```

The `endpoint-permissions` rule only checks that `## Permissions` is present, so
this satisfies it. Have a technical writer approve the wording before the first
publication.

### Tags

- Sentence case, derived from the alias: `contacts` becomes `Contacts`,
  `contact-groups` becomes `Contact groups`.
- Declare each tag once in the top-level `tags` array and reference it from the
  operations. Enforced by `tags-should-be-in-sentence-case`.

### Status codes

- Descriptions in Title Case, no period: `OK`, `Created`, `No Content`,
  `Not Found`. Enforced by `status-code-descriptions-format`.
- Every response needs both a schema and an example
  (`must-include-response-schemas`, `must-include-response-examples`).
- Only document status codes the code can actually return. The shared error
  responses in `assets/gateway-components.json` cover 401, 403, 404, 429 and
  500; include the ones that apply.

Note on 401 versus 403: when a session token is missing or unknown, DRF answers
403 with `Authentication credentials were not provided.` unless another
authentication class on the view advertises a `WWW-Authenticate` challenge, in
which case it is 401. Check the view's `authentication_classes` in the inventory
before including 401.

### Examples

- At the content-type level, as a sibling of `schema` — never inside individual
  properties. Enforced by `request-example-parallel-to-schema` and
  `response-body-objects-arrays-example`.
- One `example` for a single payload; `examples` (plural, named entries with
  `summary` and `value`) when the schema uses `anyOf` or `oneOf`.
- Values come from `canonical_examples` in `assets/config.json`. Reuse them so
  regeneration produces no diff noise.

### Other Spectral traps

- `array-items` — every `type: array` needs `items` with a `type`.
- `no-chained-refs-in-components` — a component may not `$ref` another component
  that itself contains a `$ref`. Inline instead.
- `use-ref-in-request-and-response-bodies` — `$ref` only for genuinely identical
  schemas, and never for array items.
- `no-empty-titles` — omit `title` rather than leaving it empty.
- `discard-operationid-fields` — do not emit `operationId`.
- Keep string formats such as `date-time` and `uri`.

## The overview in `info.description`

One escaped-markdown document covering, in order: what the API does,
authentication, an index of every endpoint, and any shared conventions such as
pagination.

The index entry format, which the Portal turns into anchors:

```text
\r\n- ``GET`` [List contacts](https://developers.vtex.com/docs/api-reference/{slug}#get-/contacts)
```

Path parameters in the anchor replace `{` and `}` with `-`, so `/things/{id}`
becomes `/things/-id-`. Write the overview last, after `paths` is final, and
make sure every path in scope appears exactly once in both the index and
`paths`. A schema scoped to one alias indexes only that alias — do not advertise
endpoints the file does not document.

## Open questions

Carry these into the report until someone settles them.

1. **Does the public base include `/api/v1`?** `config.json` sets the server to
   `https://cx.vtex.com/api/v1` while Kong registers flat paths such as
   `/contacts`. That is consistent only if the edge maps `/api/v1/contacts` to
   Kong's `/contacts`. Confirm with infrastructure; if the mapping does not
   exist, either the server URL or the Kong paths must change.
2. **Published title and file name.** The Portal derives its URL slug from them,
   and `openapi-schemas/docs/centralized-api-slug-mapping.md` documents how.
   A technical writer decides.
3. **How the Portal groups them.** Whether the Portal publishes one reference per
   endpoint or merges several into one is undecided, and a technical writer
   settles it. It does not change what this skill generates: always one file per
   alias. Merging files later is mechanical, while splitting a hand-edited one
   is not, so the split is the safe default to sit on.
