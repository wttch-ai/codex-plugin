"""同步刷新插件清单与 README 中的 SNOPSHOT 调试版本号。

脚本只维护当前仓库约定的两个版本位置，并保留文件原有换行风格，避免提交时
产生与版本更新无关的整文件差异。
"""

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
    """通过 Git 获取当前仓库根目录，避免依赖脚本启动位置。"""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def read_preserving_newlines(path: Path) -> str:
    """读取 UTF-8 文本，同时禁止 Python 自动转换换行符。"""
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_preserving_newlines(path: Path, content: str) -> None:
    """按传入内容原样写回换行符，保持仓库既有文件格式。"""
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def next_snapshot_version(current: str, now: datetime) -> str:
    """生成严格递增的下一个 SNOPSHOT 版本。

    已是快照版本时保留 SemVer 核心；稳定版本则提升 patch。若调用时间不晚于
    现有快照时间，至少推进一秒，保证连续提交也得到不同版本。
    """
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
    """以清单版本为准，同时更新 plugin.json 与 README 并返回新旧版本。"""
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
    # 用受控正则替换文本而非重新序列化 JSON，避免改变清单缩进和字段顺序。
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
    """解析仓库路径和测试可注入的确定性时间戳。"""
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
    """执行版本同步并输出适合提交日志展示的新旧版本。"""
    args = parse_args()
    root = args.root.resolve() if args.root else repository_root()
    old_version, new_version = update_versions(root, args.timestamp or datetime.now())
    print(f"snapshot version: {old_version} -> {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
