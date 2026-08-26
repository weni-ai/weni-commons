#!/usr/bin/env python3
"""Merge one endpoint into the consolidated CX API document.

Every gateway endpoint of every repository is published from a single OpenAPI
document. That document is edited by people, so a generator may not rewrite it:
this script performs the narrow, mechanical part of the merge instead.

What it guarantees:

  - only the path the fragment carries is inserted or replaced. Every other
    endpoint keeps its bytes, including prose someone reworded by hand.
  - the ``## Index`` section of ``info.description`` is derived from ``paths``,
    so it can never disagree with what the document documents. The prose around
    it is left alone.
  - the shared ``security`` array and ``components`` block come from
    ``assets/gateway-components.json``. A divergence is an error, never a
    silent overwrite.
  - re-running with an unchanged fragment leaves the file, and the manifest
    timestamp, untouched.

Which repository a path came from is recorded in a sidecar manifest rather than
in the document, so nothing internal leaks into what VTEX publishes.

Usage:
  merge.py --fragment FILE --alias ALIAS --repo REPO [--inventory-version N]
  merge.py --extract ALIAS_OR_PATH
  merge.py --list [--json]
  merge.py --remove ALIAS
  merge.py --reindex

Options:
  --doc PATH        consolidated document (default: output.path from config.json)
  --manifest PATH   sidecar manifest (default: output.manifest from config.json)
  --slug SLUG       Developer Portal slug used by index links
  --title TITLE     info.title, used only when creating the document
  --dry-run         report what would change, write nothing

Exit codes:
  0  done (or, with --dry-run, nothing prevented it)
  1  refused: a conflict a person has to settle
  2  bad usage or unreadable input
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
TOP_LEVEL_ORDER = ("openapi", "info", "servers", "tags", "paths", "security", "components")
COMPONENT_SECTIONS = ("securitySchemes", "parameters", "headers", "schemas", "responses", "requestBodies", "examples")
INDEX_HEADING = "## Index"
MANIFEST_VERSION = 1

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "assets" / "config.json"
SHARED_PATH = SKILL_DIR / "assets" / "gateway-components.json"


def note(message: str) -> None:
    print(f"merge.py: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    print(f"merge.py: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path, what: str) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        die(f"no {what} at {path}", 2)
    except json.JSONDecodeError as error:
        die(f"{what} at {path} is not valid JSON: {error}", 2)
    return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------- document


def methods_of(path_item: dict) -> list[str]:
    return [method for method in HTTP_METHODS if method in path_item]


def ordered_document(doc: dict) -> dict:
    ordered = {key: doc[key] for key in TOP_LEVEL_ORDER if key in doc}
    ordered.update({key: value for key, value in doc.items() if key not in ordered})
    return ordered


def new_document(config: dict, title: str) -> dict:
    return {
        "openapi": config.get("openapi_version", "3.0.0"),
        "info": {
            "version": "1.0.0",
            "title": title,
            "description": f"{title}.\n\n{INDEX_HEADING}\n",
        },
        "servers": config.get("servers", []),
        "tags": [],
        "paths": {},
    }


def merge_shared(doc: dict, shared: dict) -> list[str]:
    """Apply the shared security and components block. Conflicts are errors."""
    changes: list[str] = []

    security = shared.get("security")
    if security is not None:
        if "security" not in doc:
            doc["security"] = security
            changes.append("security")
        elif doc["security"] != security:
            die(
                "the document's top-level `security` differs from "
                "assets/gateway-components.json. Revert the edit, or update the asset "
                "so every document agrees."
            )

    incoming = shared.get("components") or {}
    if not incoming:
        return changes

    components = doc.setdefault("components", {})
    for section, entries in incoming.items():
        target = components.setdefault(section, {})
        for name, value in entries.items():
            if name not in target:
                target[name] = value
                changes.append(f"components.{section}.{name}")
            elif target[name] != value:
                die(
                    f"components.{section}.{name} in the document differs from "
                    "assets/gateway-components.json. Shared components are identical "
                    "everywhere by design: revert the edit, or change the asset."
                )
    return changes


def merge_fragment_components(doc: dict, fragment: dict) -> list[str]:
    """Carry components a fragment introduces, so its $refs resolve."""
    incoming = fragment.get("components") or {}
    changes: list[str] = []
    if not incoming:
        return changes

    components = doc.setdefault("components", {})
    for section, entries in incoming.items():
        target = components.setdefault(section, {})
        for name, value in entries.items():
            if name not in target:
                target[name] = value
                changes.append(f"components.{section}.{name}")
            elif target[name] != value:
                die(
                    f"the fragment redefines components.{section}.{name} with a "
                    "different value. Shared components may not be forked per "
                    "endpoint: reuse the existing one or give yours another name."
                )
    return changes


def merge_tags(doc: dict, fragment: dict, path_item: dict) -> list[str]:
    """Union the tags an operation references into the top-level array."""
    declared = {
        entry["name"]: entry
        for entry in fragment.get("tags", [])
        if isinstance(entry, dict) and entry.get("name")
    }
    referenced: list[str] = []
    for method in methods_of(path_item):
        for name in path_item[method].get("tags", []):
            if name not in referenced:
                referenced.append(name)

    tags = doc.setdefault("tags", [])
    known = {entry.get("name") for entry in tags if isinstance(entry, dict)}
    added: list[str] = []
    for name in referenced:
        if name in known:
            continue
        tags.append(declared.get(name, {"name": name}))
        known.add(name)
        added.append(name)
    return added


def prune_tags(doc: dict) -> list[str]:
    """Drop top-level tags no operation references any more."""
    referenced: set[str] = set()
    for path_item in doc.get("paths", {}).values():
        for method in methods_of(path_item):
            referenced.update(path_item[method].get("tags", []))

    tags = doc.get("tags", [])
    kept = [entry for entry in tags if entry.get("name") in referenced]
    removed = [entry.get("name") for entry in tags if entry.get("name") not in referenced]
    doc["tags"] = kept
    return removed


# ---------------------------------------------------------------------- index


def build_index(doc: dict, slug: str) -> list[str]:
    """The index the Portal turns into anchors, grouped by tag as VTEX does."""
    base = f"https://developers.vtex.com/docs/api-reference/{slug}"
    groups: dict[str, list[str]] = {}

    for path, path_item in doc.get("paths", {}).items():
        anchor_path = path.replace("{", "-").replace("}", "-")
        for method in methods_of(path_item):
            operation = path_item[method]
            tag = (operation.get("tags") or ["Endpoints"])[0]
            summary = (operation.get("summary") or "").strip() or f"{method.upper()} {path}"
            link = f"{base}#{method}-{anchor_path}"
            groups.setdefault(tag, []).append(f"- `{method.upper()}` [{summary}]({link})")

    lines = [INDEX_HEADING]
    for tag, entries in groups.items():
        lines.append("")
        lines.append(f"### {tag}")
        lines.extend(entries)
    return lines


def replace_index(description: str, index_lines: list[str]) -> str:
    """Swap the index section, leaving every other line of the overview alone."""
    lines = description.split("\n")

    start = next((i for i, line in enumerate(lines) if line.strip() == INDEX_HEADING), None)
    if start is None:
        # No index yet: it belongs after the opening prose, before the first
        # section, which is where VTEX's own documents put it.
        start = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
        end = start
    else:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )

    prefix = lines[:start]
    while prefix and not prefix[-1].strip():
        prefix.pop()
    suffix = lines[end:]
    while suffix and not suffix[0].strip():
        suffix.pop(0)

    result = list(prefix)
    if prefix:
        result.append("")
    result.extend(index_lines)
    if suffix:
        result.append("")
        result.extend(suffix)
    return "\n".join(result)


# ------------------------------------------------------------------- manifest


def load_manifest(path: Path, doc_path: Path) -> dict:
    if not path.exists():
        return {"version": MANIFEST_VERSION, "document": doc_path.name, "endpoints": {}}
    manifest = read_json(path, "manifest")
    manifest.setdefault("version", MANIFEST_VERSION)
    manifest.setdefault("document", doc_path.name)
    manifest.setdefault("endpoints", {})
    return manifest


def sorted_endpoints(manifest: dict) -> dict:
    endpoints = manifest.get("endpoints", {})
    return {alias: endpoints[alias] for alias in sorted(endpoints)}


# ------------------------------------------------------------------ resolving


def resolve_paths(args, config: dict) -> tuple[Path, Path]:
    output = config.get("output", {})
    doc = Path(args.doc) if args.doc else Path(output.get("path", "docs/openapi/VTEX - CX API.json"))
    if args.manifest:
        manifest = Path(args.manifest)
    elif args.doc:
        manifest = doc.parent / ".weni-openapi.manifest.json"
    else:
        manifest = Path(output.get("manifest", ".weni-openapi.manifest.json"))
    return doc, manifest


def load_document(doc_path: Path, config: dict, title: str, create: bool) -> tuple[dict, bool]:
    if doc_path.exists():
        return read_json(doc_path, "consolidated document"), False
    if not create:
        die(f"no consolidated document at {doc_path}", 2)
    note(f"creating {doc_path}")
    return new_document(config, title), True


# ------------------------------------------------------------------- commands


def cmd_merge(args, config: dict, shared: dict) -> int:
    fragment = read_json(Path(args.fragment), "fragment")
    paths = fragment.get("paths") or {}
    if len(paths) != 1:
        die(
            f"the fragment declares {len(paths)} paths; it must declare exactly one. "
            "One alias is one route: merge them one at a time so a failure can never "
            "half-apply.",
            2,
        )

    path, path_item = next(iter(paths.items()))
    if not path.startswith("/"):
        die(f"path `{path}` does not start with a slash", 2)
    if not methods_of(path_item):
        die(f"path `{path}` declares no HTTP method", 2)

    doc_path, manifest_path = resolve_paths(args, config)
    title = args.title or config.get("output", {}).get("title", "VTEX CX API")
    slug = args.slug or config.get("output", {}).get("portal_slug", "cx-api")

    doc, created = load_document(doc_path, config, title, create=True)
    manifest = load_manifest(manifest_path, doc_path)
    endpoints = manifest["endpoints"]

    owner = next(
        (
            alias
            for alias, entry in endpoints.items()
            if entry.get("public_path") == path and alias != args.alias
        ),
        None,
    )
    if owner:
        die(
            f"`{path}` is already documented under alias `{owner}` "
            f"(from {endpoints[owner].get('repo', 'an unknown repository')}). "
            "Two aliases cannot own one path: fix the decorator, or merge under "
            "that alias."
        )

    doc_paths = doc.setdefault("paths", {})
    previous = endpoints.get(args.alias, {}).get("public_path")
    renamed = None
    if previous and previous != path and previous in doc_paths:
        renamed = previous
        del doc_paths[previous]

    existing = doc_paths.get(path)
    unchanged = existing == path_item and renamed is None

    # Assigning an existing key keeps its position, so a regenerated endpoint
    # stays where it was and the diff covers only its own block.
    doc_paths[path] = path_item

    tags_added = merge_tags(doc, fragment, path_item)
    component_changes = merge_shared(doc, shared) + merge_fragment_components(doc, fragment)
    tags_removed = prune_tags(doc) if renamed else []

    info = doc.setdefault("info", {})
    description = info.get("description") or f"{title}.\n"
    info["description"] = replace_index(description, build_index(doc, slug))

    entry = dict(endpoints.get(args.alias, {}))
    entry["repo"] = args.repo
    entry["public_path"] = path
    entry["methods"] = methods_of(path_item)
    if args.inventory_version is not None:
        entry["inventory_version"] = args.inventory_version
    # A no-op run must not churn the timestamp, or "nothing changed" stops being
    # observable in a diff.
    if not unchanged or "generated_at" not in entry:
        entry["generated_at"] = now()
    endpoints[args.alias] = entry
    manifest["endpoints"] = sorted_endpoints(manifest)

    verb = "created" if created else ("unchanged" if unchanged else ("replaced" if existing else "added"))
    note(f"{verb}: {path} [{', '.join(m.upper() for m in methods_of(path_item))}] as `{args.alias}` from {args.repo}")
    if renamed:
        note(f"path moved: {renamed} -> {path}")
    if tags_added:
        note(f"tags added: {', '.join(tags_added)}")
    if tags_removed:
        note(f"tags pruned: {', '.join(tags_removed)}")
    if component_changes:
        note(f"shared block applied: {', '.join(component_changes)}")

    if args.dry_run:
        note("dry run: nothing written")
        return 0

    write_json(doc_path, ordered_document(doc))
    write_json(manifest_path, manifest)
    note(f"wrote {doc_path}")
    note(f"wrote {manifest_path}")
    return 0


def cmd_extract(args, config: dict) -> int:
    doc_path, manifest_path = resolve_paths(args, config)
    doc, _ = load_document(doc_path, config, "", create=False)
    manifest = load_manifest(manifest_path, doc_path)

    target = args.extract
    path = manifest["endpoints"].get(target, {}).get("public_path") or target

    path_item = doc.get("paths", {}).get(path)
    if path_item is None:
        note(f"`{target}` is not documented yet")
        print(json.dumps({"paths": {}, "tags": []}, indent=2, ensure_ascii=False))
        return 0

    referenced: list[str] = []
    for method in methods_of(path_item):
        for name in path_item[method].get("tags", []):
            if name not in referenced:
                referenced.append(name)
    tags = [entry for entry in doc.get("tags", []) if entry.get("name") in referenced]

    note(f"extracted {path} from {doc_path}")
    print(json.dumps({"paths": {path: path_item}, "tags": tags}, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args, config: dict) -> int:
    doc_path, manifest_path = resolve_paths(args, config)
    doc, _ = load_document(doc_path, config, "", create=False)
    manifest = load_manifest(manifest_path, doc_path)
    endpoints = manifest["endpoints"]

    by_path = {entry.get("public_path"): (alias, entry) for alias, entry in endpoints.items()}
    rows = []
    for path, path_item in doc.get("paths", {}).items():
        alias, entry = by_path.get(path, ("?", {}))
        rows.append(
            {
                "alias": alias,
                "path": path,
                "methods": [method.upper() for method in methods_of(path_item)],
                "repo": entry.get("repo", "?"),
                "generated_at": entry.get("generated_at", ""),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print("no endpoints documented yet")
        return 0

    width = max(len(row["alias"]) for row in rows)
    for row in rows:
        methods = ",".join(row["methods"])
        print(f"{row['alias']:<{width}}  {row['path']:<32} {methods:<12} {row['repo']}")

    orphans = [alias for alias, entry in endpoints.items() if entry.get("public_path") not in doc.get("paths", {})]
    if orphans:
        note(f"manifest entries with no path in the document: {', '.join(orphans)}")
    return 0


def cmd_reindex(args, config: dict) -> int:
    """Rebuild the index alone, for when summaries or the slug changed."""
    doc_path, _ = resolve_paths(args, config)
    doc, _ = load_document(doc_path, config, "", create=False)
    slug = args.slug or config.get("output", {}).get("portal_slug", "cx-api")

    info = doc.setdefault("info", {})
    before = info.get("description", "")
    after = replace_index(before, build_index(doc, slug))
    info["description"] = after

    if before == after:
        note("index already matches the document")
        return 0
    if args.dry_run:
        note("dry run: the index would change, nothing written")
        return 0

    write_json(doc_path, ordered_document(doc))
    note(f"index rebuilt in {doc_path}")
    return 0


def cmd_remove(args, config: dict) -> int:
    doc_path, manifest_path = resolve_paths(args, config)
    doc, _ = load_document(doc_path, config, "", create=False)
    manifest = load_manifest(manifest_path, doc_path)
    slug = args.slug or config.get("output", {}).get("portal_slug", "cx-api")

    alias = args.remove
    entry = manifest["endpoints"].get(alias)
    if entry is None:
        die(f"alias `{alias}` is not in {manifest_path}", 2)

    path = entry.get("public_path")
    if path in doc.get("paths", {}):
        del doc["paths"][path]
        note(f"removed {path} (`{alias}`)")
    else:
        note(f"`{alias}` had no path in the document; clearing its manifest entry")

    del manifest["endpoints"][alias]
    removed_tags = prune_tags(doc)
    info = doc.setdefault("info", {})
    info["description"] = replace_index(info.get("description", ""), build_index(doc, slug))

    if removed_tags:
        note(f"tags pruned: {', '.join(removed_tags)}")
    if args.dry_run:
        note("dry run: nothing written")
        return 0

    write_json(doc_path, ordered_document(doc))
    write_json(manifest_path, manifest)
    note(f"wrote {doc_path}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--doc")
    parser.add_argument("--manifest")
    parser.add_argument("--fragment")
    parser.add_argument("--alias")
    parser.add_argument("--repo")
    parser.add_argument("--inventory-version", type=int, dest="inventory_version")
    parser.add_argument("--extract")
    parser.add_argument("--remove")
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--slug")
    parser.add_argument("--title")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("-h", "--help", action="store_true", dest="help")
    args = parser.parse_args(argv)

    if args.help:
        print(__doc__)
        return 0

    config = read_json(CONFIG_PATH, "skill config")

    if args.fragment:
        if not args.alias or not args.repo:
            die("--fragment needs both --alias and --repo", 2)
        return cmd_merge(args, config, read_json(SHARED_PATH, "shared components"))
    if args.extract:
        return cmd_extract(args, config)
    if args.remove:
        return cmd_remove(args, config)
    if args.reindex:
        return cmd_reindex(args, config)
    if args.list:
        return cmd_list(args, config)

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
