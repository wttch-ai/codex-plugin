from pydantic.dataclasses import dataclass
from dataclasses import asdict
import json
from typing import Any, Literal, Optional


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
    turn_id: str
    """特定于 Codex 的扩展。当前活动的 Codex 轮次 ID。"""

    prompt: str
    """用户提示词。"""


@dataclass
class UserPromptSubmitSpecificOutput:
    hookEventName: Literal["UserPromptSubmit"]
    """钩子事件名称"""

    additionalContext: str
    """ 会被作为额外的开发者上下文添加到提示中"""


@dataclass
class UserPromptSubmitOutput:
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
        return UserPromptSubmitOutput(decision="block", reason=reason)

    @staticmethod
    def warn(reason: str) -> "UserPromptSubmitOutput":
        """构造继续请求、同时注入警告上下文的 Hook 响应。"""
        return UserPromptSubmitOutput(
            systemMessage=reason,
            hookSpecificOutput=UserPromptSubmitSpecificOutput(
                hookEventName="UserPromptSubmit",
                additionalContext=reason,
            ),
        )


    def dump_json(self) -> str:
        """返回可安全写入 Hook 标准输出的一行 JSON。

        Hook 输入有时会含有 Windows 代理字符；使用 ASCII 转义避免 stdout 的 UTF-8
        编码失败。意外的 bytes 值也会先解码，避免再次触发 JSON 序列化异常。
        """
        def json_default(value: Any) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

        payload = {key: value for key, value in asdict(self).items() if value is not None}
        return json.dumps(payload, ensure_ascii=True, default=json_default)
