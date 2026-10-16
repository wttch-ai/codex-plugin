from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


SNAPSHOT_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)-SNOPSHOT-"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})$"
)
STABLE_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)(?:\+[0-9A-Za-z.-]+)?$"
)
MANIFEST_VERSION_RE = re.compile(
    r'^(?P<prefix>\s*"version"\s*:\s*")[^"]+(?P<suffix>"\s*,?\s*)$',
    re.MULTILINE,
)
README_VERSION_RE = re.compile(
    r"^(?P<prefix>- 当前版本：`)[^`]+(?P<suffix>`\s*)$", re.MULTILINE
)


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def read_preserving_newlines(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_preserving_newlines(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def next_snapshot_version(current: str, now: datetime) -> str:
    snapshot = SNAPSHOT_RE.fullmatch(current)
    if snapshot:
        core = ".".join(
            (snapshot.group("major"), snapshot.group("minor"), snapshot.group("patch"))
        )
        previous = datetime.strptime(snapshot.group("timestamp"), "%Y-%m-%dT%H-%M-%S")
        if now <= previous:
            now = previous + timedelta(seconds=1)
    else:
        stable = STABLE_RE.fullmatch(current)
        if not stable:
            raise ValueError(f"unsupported plugin version: {current}")
        core = ".".join(
            (
                stable.group("major"),
                stable.group("minor"),
                str(int(stable.group("patch")) + 1),
            )
        )

    return f"{core}-SNOPSHOT-{now.strftime('%Y-%m-%dT%H-%M-%S')}"


def update_versions(root: Path, now: datetime) -> tuple[str, str]:
    manifest_path = root / ".codex-plugin" / "plugin.json"
    readme_path = root / "README.md"
    if not manifest_path.is_file() or not readme_path.is_file():
        raise FileNotFoundError(
            "repository must contain .codex-plugin/plugin.json and README.md"
        )

    manifest_text = read_preserving_newlines(manifest_path)
    readme_text = read_preserving_newlines(readme_path)
    manifest = json.loads(manifest_text)
    current = manifest.get("version")
    if not isinstance(current, str):
        raise ValueError("plugin manifest version must be a string")

    new_version = next_snapshot_version(current, now.replace(microsecond=0))
    updated_manifest, manifest_count = MANIFEST_VERSION_RE.subn(
        rf"\g<prefix>{new_version}\g<suffix>", manifest_text
    )
    updated_readme, readme_count = README_VERSION_RE.subn(
        rf"\g<prefix>{new_version}\g<suffix>", readme_text
    )
    if manifest_count != 1:
        raise ValueError("expected exactly one manifest version field")
    if readme_count != 1:
        raise ValueError("expected exactly one README current-version line")

    write_preserving_newlines(manifest_path, updated_manifest)
    write_preserving_newlines(readme_path, updated_readme)
    return current, new_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh this repository's SemVer-compatible SNOPSHOT version."
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Repository root; defaults to the current Git repository.",
    )
    parser.add_argument(
        "--timestamp",
        type=lambda value: datetime.strptime(value, "%Y-%m-%dT%H-%M-%S"),
        help="Deterministic local timestamp, primarily for tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve() if args.root else repository_root()
    old_version, new_version = update_versions(root, args.timestamp or datetime.now())
    print(f"snapshot version: {old_version} -> {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
