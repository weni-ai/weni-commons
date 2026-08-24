# weni-api-gateway (Cursor plugin)

Generates the OpenAPI 3.0 schema that the VTEX Developer Portal publishes, for
Django REST endpoints exposed through the Weni API Gateway.

The plugin ships one skill, `weni-openapi`, invoked as `/weni-openapi`.

## Why a plugin

The generator has to run in the repository that owns the endpoints (flows,
billing, insights), not here. A plugin is installed once per user or per team
and its skills are then available in every workspace, so no service repository
has to vendor a copy of the playbook.

It lives in this repository because its correctness is tied to the inventory
schema produced by `weni_commons.openapi` — the two are versioned together.

## How it works

Generation is split in two, and the split is the whole point:

| Layer | Produced by | Answers |
| --- | --- | --- |
| Inventory | `python manage.py api_gateway_inventory` | Which endpoints are public, at which URL, with which methods, carrying which fields |
| Documentation | the `weni-openapi` skill | What each endpoint means, and what a realistic payload looks like |

The inventory is read from Django's URL resolver and the DRF serializers, so
the agent never guesses which endpoints exist or what shape they return. It
only writes the prose that no amount of introspection can produce.

## Install

For development, symlink it and reload Cursor:

```bash
ln -s "$(pwd)/plugins/weni-api-gateway" ~/.cursor/plugins/local/weni-api-gateway
```

Then run **Developer: Reload Window**.

For the team, add this repository to the organization marketplace
(Dashboard, then Plugins) and install `weni-api-gateway` from **Customize**.

## Layout

```text
plugins/weni-api-gateway/
├── .cursor-plugin/plugin.json
└── skills/weni-openapi/
    ├── SKILL.md                       workflow
    ├── reference.md                   VTEX standards and Spectral traps
    ├── assets/config.json             servers, output paths, canonical examples
    ├── assets/openapi-template.json   document skeleton
    ├── assets/gateway-components.json shared security, parameters, errors
    └── scripts/validate.sh            Spectral lint against the VTEX ruleset
```
