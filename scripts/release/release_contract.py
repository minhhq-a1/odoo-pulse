"""Canonical release identity, tag parity, and Docker alias expectations.

`pyproject.toml` is the single source of truth for the release version. This
module derives every other ecosystem's representation from it so no publication
step invents its own mapping.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

try:  # Python 3.11+ ships tomllib; 3.10 needs the tomli backport.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:rc(?P<rc>[1-9]\d*))?$"
)


@dataclass(frozen=True)
class ReleaseIdentity:
    python_version: str
    semver_version: str
    tag: str
    prerelease: bool


def release_identity(value: str) -> ReleaseIdentity:
    match = VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(
            f"Unsupported release version {value!r}; expected stable X.Y.Z or RC X.Y.ZrcN"
        )
    rc = match.group("rc")
    semver = value if rc is None else value.removesuffix(f"rc{rc}") + f"-rc.{rc}"
    return ReleaseIdentity(value, semver, f"v{value}", rc is not None)


def validate_tag(tag: str, identity: ReleaseIdentity) -> None:
    if tag != identity.tag:
        raise ValueError(
            f"Release tag {tag!r} does not match project version "
            f"{identity.python_version!r}; expected {identity.tag!r}"
        )


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def write_github_output(path: Path, identity: ReleaseIdentity) -> None:
    values = {
        "version": identity.python_version,
        "semver_version": identity.semver_version,
        "tag": identity.tag,
        "prerelease": str(identity.prerelease).lower(),
    }
    with path.open("a") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in values.items()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Release identity contract")
    commands = parser.add_subparsers(dest="command", required=True)
    identity = commands.add_parser(
        "identity", help="Resolve and validate the release identity for a tag"
    )
    identity.add_argument("--root", type=Path, required=True)
    identity.add_argument("--tag", required=True)
    identity.add_argument("--github-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identity = release_identity(project_version(args.root.resolve()))
        validate_tag(args.tag, identity)
    except (ValueError, OSError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.github_output is not None:
        write_github_output(args.github_output, identity)
    else:
        print(
            json.dumps(
                {
                    "version": identity.python_version,
                    "semver_version": identity.semver_version,
                    "tag": identity.tag,
                    "prerelease": identity.prerelease,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
