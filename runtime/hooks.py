"""Codex Hook 协议实体。

当前只强制实体化 UserPromptSubmit；其他 Hook 仍由各自处理器保留字典响应，待协议
稳定后再逐步迁移。
"""

from dataclasses import asdict, dataclass, fields
import json
from typing import Any, Literal, Optional, TextIO

from notice import hook_notice


@dataclass
class CommonInput:
    """表示一个钩子事件的上下文输入信息。"""

    session_id: str
    """当前代码会话 ID。子代理挂钩使用父会话 ID。"""

    transcript_path: Optional[str]
    """通往会话记录文件的路径（如有）。"""

    cwd: str
    """会话的工作目录。"""

    hook_event_name: str
    """当前钩子事件名称。"""

    model: str
    """特定代码的扩展。主动模型缺陷。"""


@dataclass
class CommonOutput:
    """SessionStart、PreCompact、PostCompact、UserPromptSubmit、SubagentStop、Stop
    以及 SubagentStart 共享的钩子输出字段。
    """

    continue_: bool = True
    """如果为 False，则将该次钩子运行标记为已停止。
    注意：SubagentStart 接受相同结构，但 `continue=False` 不会停止子代理。
    """

    stop_reason: Optional[str] = None
    """记录为停止的原因。"""

    system_message: Optional[str] = None
    """作为警告显示在 UI 或事件流中。"""

    suppress_output: bool = False
    """目前会被解析，但尚未实现。"""


@dataclass
class UserPromptSubmitInput(CommonInput):
    """经过类型和事件名称校验的 UserPromptSubmit 输入。"""

    hook_event_name: Literal["UserPromptSubmit"]
    """必须是 UserPromptSubmit，避免把其他 Hook 输入误送到本处理链。"""

    turn_id: str
    """特定于 Codex 的扩展。当前活动的 Codex 轮次 ID。"""

    prompt: str
    """用户提示词。"""

    def __post_init__(self) -> None:
        """校验运行时真正依赖的字段，避免错误事件进入提示处理链。"""
        required = {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "model": self.model,
            "turn_id": self.turn_id,
            "prompt": self.prompt,
        }
        for name, value in required.items():
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
        if self.hook_event_name != "UserPromptSubmit":
            raise ValueError("hook_event_name must be UserPromptSubmit")
        if self.transcript_path is not None and not isinstance(self.transcript_path, str):
            raise TypeError("transcript_path must be a string or null")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "UserPromptSubmitInput":
        """Create the typed input while ignoring host fields not used by the plugin."""
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in allowed})

    @classmethod
    def load_json(cls, stream: TextIO) -> "UserPromptSubmitInput":
        """Read and validate one UserPromptSubmit JSON object."""
        raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("hook input must be a JSON object")
        return cls.from_dict(raw)


@dataclass
class UserPromptSubmitSpecificOutput:
    """UserPromptSubmit 注入额外开发者上下文时使用的专属字段。"""

    hookEventName: Literal["UserPromptSubmit"]
    """钩子事件名称"""

    additionalContext: str
    """ 会被作为额外的开发者上下文添加到提示中"""


@dataclass
class UserPromptSubmitOutput:
    """UserPromptSubmit 可继续、警告或阻止请求的协议输出。"""

    systemMessage: Optional[str] = None
    """显示在 UI 或事件流中的警告信息。"""

    hookSpecificOutput: Optional[UserPromptSubmitSpecificOutput] = None
    """特殊输出，比如添加上下文。"""

    decision: Optional[Literal["block"]] = None
    """可以阻止对话"""

    reason: Optional[str] = None
    """阻止的原因"""

    @staticmethod
    def block(reason: str) -> "UserPromptSubmitOutput":
        """构造阻止当前用户提示的 Hook 响应。"""
        return UserPromptSubmitOutput(decision="block", reason=hook_notice(reason))

    @staticmethod
    def warn(reason: str) -> "UserPromptSubmitOutput":
        """构造继续请求、同时注入警告上下文的 Hook 响应。"""
        message = hook_notice(reason)
        return UserPromptSubmitOutput(
            systemMessage=message,
            hookSpecificOutput=UserPromptSubmitSpecificOutput(
                hookEventName="UserPromptSubmit",
                additionalContext=message,
            ),
        )


    def dump_json(self) -> str:
        """返回可安全写入 Hook 标准输出的一行 JSON。

        Hook 输入有时会含有 Windows 代理字符；使用 ASCII 转义避免 stdout 的 UTF-8
        编码失败。意外的 bytes 值也会先解码，避免再次触发 JSON 序列化异常。
        """
        def json_default(value: Any) -> str:
            """只为意外 bytes 提供安全降级，其他未知类型仍明确报错。"""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

        # 省略 None 字段，避免向 Hook 协议发送没有语义的 null 值。
        payload = {key: value for key, value in asdict(self).items() if value is not None}
        return json.dumps(payload, ensure_ascii=True, default=json_default)
