# weni-api-gateway (Cursor plugin)

Generates the OpenAPI 3.0 schema that the VTEX Developer Portal publishes, for
Django REST endpoints exposed through the Weni API Gateway.

The plugin ships one skill, `weni-openapi`. Run it from the **connect**
workspace, naming the repository that owns the endpoint and, optionally, the
gateway alias:

```text
/weni-openapi flows whatsapp_flows
```

```text
/weni-openapi flows
```

The first argument is the repository the inventory is built in — a bare name is
enough, the checkout is found next to the workspace. The inventory always covers
every exposed endpoint of that repository; the alias narrows only what gets
documented.

After editing the document by hand, re-check it without regenerating:

```text
/weni-openapi validate
```

That mode only lints and repairs what Spectral rejects. It never rebuilds the
document, and it never overwrites content you added or reworded.

## One document

Output is always the same file: `docs/openapi/VTEX - CX API.json` in connect,
holding every gateway endpoint of every repository, one key under `paths` per
alias. It is the file that gets published to `openapi-schemas`, which is
organised the same way — one product-level API per JSON, many endpoints inside.

The agent never writes that file. It writes a one-path fragment, and
`scripts/merge.py` merges it: one path inserted or replaced, the tag unioned, the
shared components applied, the `## Index` section of the overview rebuilt from
`paths`, and the owning repository recorded in
`docs/openapi/.weni-openapi.manifest.json`. Every other endpoint keeps its bytes,
so a run scoped to one alias cannot damage prose someone wrote for another.

```bash
scripts/merge.py --list                  what is documented, and from where
scripts/merge.py --extract <alias>       what the document says today
scripts/merge.py --remove <alias>        drop one that lost its decorator
scripts/merge.py --reindex               rebuild the index alone
```

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

### Committed into connect

Since the skill only ever runs in one workspace, committing it there needs no
distribution mechanism at all — anyone who clones connect gets it:

```bash
cp -R plugins/weni-api-gateway/skills/weni-openapi <connect>/.cursor/skills/weni-openapi
```

The cost is duplication: the skill then lives in two repositories and will
drift. Reasonable as a bridge until the marketplace exists.

## Requirements

- The workspace is connect, which owns `docs/openapi/VTEX - CX API.json`. The
  service repository you name is expected next to it, or passed as a path.
- The service repository needs `weni_commons` in `INSTALLED_APPS` and
  `KONG_URL_PREFIX` configured, at a version that ships the
  `api_gateway_inventory` command. Older releases still work if you keep a local
  `weni-commons` checkout — `scripts/inventory.sh` falls back to it.
- `merge.py` needs Python 3.9+ and nothing else: standard library only.
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
    ├── scripts/merge.py       merges one endpoint into the consolidated document
    └── scripts/validate.sh    Spectral lint against the bundled ruleset
```
