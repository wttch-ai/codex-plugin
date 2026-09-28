#!/usr/bin/env python3
"""发现并直接执行 JEV 决策。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


BUILTIN_DECISION_ROOT = Path(__file__).resolve().parents[2] / "skills" / "jev-gate" / "decisions"
PROJECT_DECISION_ROOT = Path("jev_decisions")
DEFAULT_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


def decision_files(cwd: Path | None = None) -> list[Path]:
    """返回内置和当前项目的 JEV 决策，项目同名文件优先。"""
    project_root = (cwd or Path.cwd()) / PROJECT_DECISION_ROOT
    paths: dict[str, Path] = {path.stem: path for path in BUILTIN_DECISION_ROOT.glob("*.yml")}
    paths.update({path.stem: path for path in project_root.glob("*.yml")})
    return sorted(paths.values(), key=lambda path: path.stem)


def load_decision(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"JEV 决策格式无效：{path}")
    questions = data.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise ValueError(f"JEV 决策缺少 questions：{path}")
    for name, question in questions.items():
        if not isinstance(question, dict):
            raise ValueError(f"JEV 问题格式无效：{name}")
        if question.get("type") not in {"choice", "noul", "score"}:
            raise ValueError(f"JEV 问题类型无效：{name}")
        if not isinstance(question.get("instructions"), str):
            raise ValueError(f"JEV 问题缺少 instructions：{name}")
        if not question.get("criteria"):
            raise ValueError(f"JEV 问题缺少 criteria：{name}")
    return data


def resolve(name: str, cwd: Path | None = None) -> Path:
    candidate = Path(name)
    if candidate.is_file():
        return candidate.resolve()
    for path in decision_files(cwd):
        if path.stem == name or path.name == name:
            return path
    raise FileNotFoundError(f"JEV 决策不存在：{name}")


def run(decision: Path, request_input: dict) -> int:
    definition = load_decision(decision)
    state = request_input.get("state")
    if not isinstance(state, str):
        raise ValueError("JEV 输入必须包含字符串字段 state")
    payload = {
        "model": definition.get("model", "typesafe/jev-1.13"),
        "state": state,
        "questions": definition["questions"],
    }
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未设置 OPENROUTER_API_KEY")
    request = Request(
        os.environ.get("JEV_OPENROUTER_DECISIONS_URL", DEFAULT_ENDPOINT),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=float(os.environ.get("JEV_OPENROUTER_TIMEOUT", "60"))) as response:
            print(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"JEV 请求失败：{exc}") from exc
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("name")
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps([
            {
                "name": path.stem,
                "file": str(path),
                "group": load_decision(path).get("group", ""),
                "source": "builtin" if BUILTIN_DECISION_ROOT in path.parents else "project",
            }
            for path in decision_files()
        ], ensure_ascii=False, indent=2))
        return 0
    request_input = json.load(sys.stdin)
    if not isinstance(request_input, dict):
        raise ValueError("JEV 输入必须是 JSON 对象")
    return run(resolve(args.name), request_input)


if __name__ == "__main__":
    raise SystemExit(main())
