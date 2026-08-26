# weni-api-gateway (Cursor plugin)

Generates the OpenAPI 3.0 schema that the VTEX Developer Portal publishes, for
Django REST endpoints exposed through the Weni API Gateway.

The plugin ships one skill, `weni-openapi`. Run it from the service repository
(the one with `manage.py`); the optional argument is the gateway alias:

```text
/weni-openapi
```

```text
/weni-openapi channels
```

The inventory always covers every exposed endpoint. The alias, when given,
narrows only the generated schema.

After editing a generated file by hand, re-check it without regenerating:

```text
/weni-openapi validate docs/openapi/channels.openapi.json
```

That mode only lints and repairs what Spectral rejects. It never rebuilds the
document, and it never overwrites content you added or reworded.

Output is always **one file per endpoint**, named after the alias
(`docs/openapi/channels.openapi.json`). There is no whole-service schema: run it
without an alias and you get one file per exposed endpoint, not one big one.

## Install

### For yourself, from this checkout

```bash
ln -sfn "$(pwd)/plugins/weni-api-gateway" ~/.cursor/plugins/local/weni-api-gateway
```

Then run **Developer: Reload Window** and type `/weni-openapi` in chat.

`~/.cursor/plugins/local` is Cursor's documented path for developing a plugin,
so use it while editing the skill. It is not a way to distribute one: it needs
every person to have this repository checked out at a path they maintain
themselves.

If the plugin does not appear, install the skill directly instead — same files,
one less layer:

```bash
ln -sfn "$(pwd)/plugins/weni-api-gateway/skills/weni-openapi" ~/.cursor/skills/weni-openapi
```

Cursor documents `~/.cursor/skills/` as a skill root but says nothing about
symlinked skill directories, so if it fails to load, copy instead of linking
(`cp -R`) and re-sync after each change.

### For the whole company

Use a **team marketplace**: Dashboard → Plugins → Add Marketplace → Import from
Repo, pointing at this repository. Set the plugin's installation mode to
**Required** so every member gets it and nobody has to install anything, and
enable **Auto Refresh** so pushes to the tracked branch propagate. Access can be
scoped with Organization Groups. Teams plans get one marketplace, Enterprise
unlimited; on Enterprise only admins can add one.

### For a single service repository

Committing the skill needs no distribution mechanism at all — anyone who clones
the service gets it:

```bash
cp -R plugins/weni-api-gateway/skills/weni-openapi <service>/.cursor/skills/weni-openapi
```

The cost is duplication: the skill then lives in several repositories and will
drift. Reasonable as a bridge until the marketplace exists.

## Requirements

- The target repository needs `weni_commons` in `INSTALLED_APPS` and
  `KONG_URL_PREFIX` configured, at a version that ships the
  `api_gateway_inventory` command. Older releases still work if you keep a local
  `weni-commons` checkout — `scripts/inventory.sh` falls back to it.
- Spectral validation uses the ruleset bundled in the skill
  (`assets/spectral/spectral.yml`). The first run installs Node LTS into
  `~/.cache/weni-openapi` if PATH has no Node 18+, then `npm ci` into
  `assets/spectral/node_modules`. A checkout of `openapi-schemas` is not
  required.
- macOS and Linux. On Windows, use WSL: the scripts look for `bin/python` inside
  virtualenvs, not `Scripts/`.

## Layout

```text
plugins/weni-api-gateway/
├── .cursor-plugin/plugin.json
└── skills/weni-openapi/
    ├── SKILL.md
    ├── reference.md
    ├── assets/
    │   └── spectral/          VTEX ruleset snapshot + pinned Spectral CLI
    ├── scripts/inventory.sh   builds the route inventory in a service repo
    └── scripts/validate.sh    Spectral lint against the bundled ruleset
```
