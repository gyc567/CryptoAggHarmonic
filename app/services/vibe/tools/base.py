"""Base classes for vibe tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolRuntime:
    """Runtime context passed to every tool execution."""

    user_id: str
    session_id: str
    run_id: str
    context: dict = field(default_factory=dict)


@dataclass
class ToolOutput:
    """Result of a tool execution."""

    status: str  # completed, error, timeout, invalid_input
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    summary: Optional[str] = None

    @classmethod
    def success(cls, data: dict, summary: Optional[str] = None) -> "ToolOutput":
        return cls(status="completed", data=data, summary=summary)

    @classmethod
    def from_error(cls, message: str, code: str = "error") -> "ToolOutput":
        """Construct an error ToolOutput.

        Named ``from_error`` (not ``error``) so the dataclass field and the
        factory don't share an attribute name — ruff F811 and runtime
        attribute shadowing are both avoided.
        """
        return cls(status="error", error=message, data={"code": code})

    @classmethod
    def invalid_input(cls, message: str) -> "ToolOutput":
        return cls(status="invalid_input", error=message)

    @classmethod
    def timeout(cls, message: str = "工具执行超时") -> "ToolOutput":
        return cls(status="timeout", error=message, data={"code": "TIMEOUT"})


class Tool(ABC):
    """Abstract base class for all vibe tools."""

    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)

    @abstractmethod
    def run(self, input: dict, runtime: ToolRuntime) -> ToolOutput:
        """Execute the tool with validated input."""
        ...

    def validate_input(self, input: dict) -> tuple[bool, str | None]:
        """Best-effort input validation.

        Returns (is_valid, error_message).
        """
        required = self.input_schema.get("required", [])
        for key in required:
            if key not in input or input[key] is None:
                return False, f"缺少必填参数: {key}"
        return True, None

    def to_openai_schema(self) -> dict:
        """Return OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_prompt_description(self) -> str:
        """Return a prompt-friendly tool description."""
        import json

        return f"- {self.name}: {self.description}\n  参数: {json.dumps(self.input_schema, ensure_ascii=False)}"
