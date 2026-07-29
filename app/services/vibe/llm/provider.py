"""Abstract LLM provider for the vibe agent."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass
class LLMUsage:
    """Token usage for an LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """Structured response from an LLM provider."""

    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    error: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    name: str = "abstract"

    @abstractmethod
    def is_tool_call_supported(self) -> bool:
        """Return True if this provider supports native tool-calling."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """Send a chat request and return a structured response."""
        ...

    @abstractmethod
    def approximate_tokens(self, text: str) -> int:
        """Approximate token count for a text string."""
        ...
