"""Synchronize project version across metadata manifests.

`pyproject.toml` holds the canonical PEP 440 version. Each ecosystem manifest
receives the representation it actually accepts: MCPB, the Claude plugin, and
the MCP server descriptor use SemVer, while the PyPI package entry inside
`server.json` keeps the canonical PEP 440 string.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from release_contract import release_identity

try:  # Python 3.11+ ships tomllib; 3.10 needs the tomli backport.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover - actionable operator error
        raise SystemExit(
            "Reading pyproject.toml on Python 3.10 requires the tomli "
            "backport. Install it with: pip install -e \".[dev]\""
        ) from None

PYPROJECT = "pyproject.toml"

JSON_TARGETS = {
    "manifest.json": [("semver", ("version",))],
    "server.json": [
        ("semver", ("version",)),
        ("python", ("packages", 0, "version")),
    ],
    ".claude-plugin/plugin.json": [("semver", ("version",))],
}


class MissingTargetError(RuntimeError):
    """A required release metadata target is absent."""


class MalformedTargetError(RuntimeError):
    """A required release metadata target has no version field to update."""


def require(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.exists():
        raise MissingTargetError(f"Missing required release target: {relative}")
    return path


def project_version(root: Path) -> str:
    path = require(root, PYPROJECT)
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    try:
        return payload["project"]["version"]
    except (KeyError, TypeError) as error:
        raise MalformedTargetError(
            f"Cannot read project.version from {PYPROJECT}: the release target "
            f"does not expose that field"
        ) from error


def set_path(payload: dict, path: tuple, value: str) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def rendered_files(root: Path) -> dict[Path, str]:
    identity = release_identity(project_version(root))
    representations = {
        "semver": identity.semver_version,
        "python": identity.python_version,
    }
    rendered = {}
    for relative, targets in JSON_TARGETS.items():
        path = require(root, relative)
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise MalformedTargetError(
                f"Cannot parse {relative}: {error}"
            ) from error
        for representation, key_path in targets:
            try:
                set_path(payload, key_path, representations[representation])
            except (KeyError, IndexError, TypeError) as error:
                location = ".".join(str(key) for key in key_path)
                raise MalformedTargetError(
                    f"Cannot update {location} in {relative}: the release target "
                    f"does not expose that field"
                ) from error
        rendered[path] = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        rendered = rendered_files(root)
    except (
        MissingTargetError,
        MalformedTargetError,
        ValueError,
        OSError,
        KeyError,
        IndexError,
    ) as error:
        print(error, file=sys.stderr)
        return 1
    drift = []
    for path, text in rendered.items():
        if path.read_text() == text:
            continue
        drift.append(path)
        if not args.check:
            path.write_text(text)
    if drift:
        for path in drift:
            print(path.relative_to(root))
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
