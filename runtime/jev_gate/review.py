#!/usr/bin/env python3
"""调用配置的 OpenRouter 模型处理 JEV 审查规则。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any

from wttch_config import openrouter_api_key


def review(rule: dict[str, Any], event: dict[str, Any]) -> tuple[bool, str]:
    """请求 OpenRouter 审查工具调用，返回是否允许及可展示的原因。

    API Key 优先使用环境变量，未设置时从工具调用工作目录下的
    ``wttch-config.yml`` 读取。模型配置仍只从环境变量读取；策略文件仅描述需要
    判断的操作，避免将凭据写入会提交的策略文件。
    """
    cwd = event.get("cwd")
    # Hook 事件的 cwd 比进程 cwd 更准确；普通 Skill 脚本可直接调用共享读取函数。
    working_directory = (
        Path(cwd).expanduser() if isinstance(cwd, str) and cwd.strip() else None
    )
    # 环境变量优先，使 CI 和临时密钥轮换无需修改本地配置文件。
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip() or openrouter_api_key(
        working_directory
    )
    model = os.environ.get("JEV_OPENROUTER_MODEL", "").strip()
    if not api_key:
        raise RuntimeError(
            "OpenRouter API key is not configured: set OPENROUTER_API_KEY "
            "or <working-directory>/wttch-config.yml openrouter.api_key"
        )
    if not model:
        raise RuntimeError("JEV_OPENROUTER_MODEL is not set")

    base_url = os.environ.get(
        "JEV_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    timeout = float(os.environ.get("JEV_OPENROUTER_TIMEOUT", "20"))
    # temperature 为零并要求 JSON 对象，降低审查结果格式和决策的随机性。
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are JEV, a conservative tool-call policy judge. "
                        "Return one JSON object with keys decision (allow or deny) "
                        "and reason. Do not return markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "policy_instruction": rule.get(
                                "instruction", "Review the action safely."
                            ),
                            "tool_name": event.get("tool_name"),
                            "tool_input": event.get("tool_input"),
                            "cwd": event.get("cwd"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    # HTTP-Referer 和 X-Title 用于 OpenRouter 侧的应用归属识别，不包含用户输入。
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://chatgpt.com/",
            "X-Title": "Wttch JEV Gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # 截断响应正文，既保留远程错误线索，也避免 Hook 消息过长。
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}: {detail}") from exc

    # 键访问故障和非 JSON 内容会抛出异常，随后由 gate.py 的失败策略统一处理。
    content = payload["choices"][0]["message"]["content"]
    result = json.loads(content)
    decision = str(result.get("decision", "")).lower()
    reason = str(result.get("reason", "JEV 未返回原因。"))
    if decision not in {"allow", "deny"}:
        raise RuntimeError("JEV decision must be allow or deny")
    return decision == "allow", reason
