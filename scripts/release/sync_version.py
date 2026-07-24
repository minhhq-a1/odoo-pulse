"""Synchronize project version across metadata manifests."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

JSON_TARGETS = {
    "manifest.json": [("version",)],
    "server.json": [("version",), ("packages", 0, "version")],
    ".claude-plugin/plugin.json": [("version",)],
}


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def set_path(payload: dict, path: tuple, value: str) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def rendered_files(root: Path) -> dict[Path, str]:
    wanted = project_version(root)
    rendered = {}
    for relative, paths in JSON_TARGETS.items():
        path = root / relative
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        for key_path in paths:
            set_path(payload, key_path, wanted)
        rendered[path] = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    drift = []
    root = args.root.resolve()
    for path, rendered in rendered_files(root).items():
        if path.read_text() == rendered:
            continue
        drift.append(path)
        if not args.check:
            path.write_text(rendered)
    if drift:
        for path in drift:
            print(path.relative_to(root))
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
