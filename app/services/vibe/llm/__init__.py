"""LLM provider package for vibe agent."""

from typing import Optional

from app.services.vibe.llm.openai_provider import OpenAIProvider
from app.services.vibe.llm.prompt_provider import PromptProvider
from app.services.vibe.llm.provider import LLMProvider, LLMResponse, LLMUsage, ToolCall


def create_llm_provider(model: Optional[str] = None) -> LLMProvider:
    """Create the best available LLM provider for the configured model.

    If the model supports native tool-calling, return OpenAIProvider.
    Otherwise fall back to PromptProvider.
    """
    openai_provider = OpenAIProvider(model=model)
    if openai_provider.is_tool_call_supported():
        return openai_provider
    return PromptProvider(base_provider=openai_provider)


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "ToolCall",
    "OpenAIProvider",
    "PromptProvider",
    "create_llm_provider",
]
