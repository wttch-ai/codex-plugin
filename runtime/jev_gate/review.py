#!/usr/bin/env python3
"""调用配置的 OpenRouter 模型处理 JEV 审查规则。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def review(rule: dict[str, Any], event: dict[str, Any]) -> tuple[bool, str]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("JEV_OPENROUTER_MODEL", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    if not model:
        raise RuntimeError("JEV_OPENROUTER_MODEL is not set")

    base_url = os.environ.get(
        "JEV_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    timeout = float(os.environ.get("JEV_OPENROUTER_TIMEOUT", "20"))
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
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}: {detail}") from exc

    content = payload["choices"][0]["message"]["content"]
    result = json.loads(content)
    decision = str(result.get("decision", "")).lower()
    reason = str(result.get("reason", "JEV 未返回原因。"))
    if decision not in {"allow", "deny"}:
        raise RuntimeError("JEV decision must be allow or deny")
    return decision == "allow", reason
