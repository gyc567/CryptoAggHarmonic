"""OpenAI-compatible LLM provider with native tool-calling support."""

import json
import logging
import os
from typing import Optional

from app.openai_handler import _get_client
from app.services.vibe.llm.provider import LLMProvider, LLMResponse, LLMUsage, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """Provider that uses the OpenAI client (compatible with OpenAI, DeepSeek, Kimi, etc.)."""

    name = "openai"

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("OPENAI_API_MODEL", "gpt-3.5-turbo")
        self._tool_support: Optional[bool] = None
        self._client = _get_client()

    def is_tool_call_supported(self) -> bool:
        """Return whether the configured model supports tool-calling.

        Priority:
          1. VIBE_TOOL_CALLING_SUPPORTED env var ("true"/"false").
          2. Cached probe result.
          3. Pessimistic fallback: probe the model once.

        The probe makes a real LLM call; use the env var in production to avoid
        startup latency and unnecessary token spend.
        """
        explicit = os.getenv("VIBE_TOOL_CALLING_SUPPORTED")
        if explicit is not None:
            return explicit.lower() in ("1", "true", "yes", "on")

        if self._tool_support is not None:
            return self._tool_support

        # Cheap probe: ask the model to call a dummy tool.
        probe_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello."},
        ]
        dummy_tools = [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "Do nothing.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=probe_messages,
                tools=dummy_tools,
                tool_choice="auto",
                max_tokens=10,
            )
            self._tool_support = True
            logger.info("Model %s supports tool-calling", self.model)
        except Exception as e:
            logger.warning(
                "Model %s does not appear to support tool-calling: %s",
                self.model,
                e,
            )
            self._tool_support = False
        return self._tool_support

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """Call the LLM and parse the response."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools and self.is_tool_call_supported():
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.exception("LLM call failed")
            return LLMResponse(error=f"LLM call failed: {e}")

        choice = response.choices[0]
        message = choice.message

        content = getattr(message, "content", None)
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = LLMUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )

    def approximate_tokens(self, text: str) -> int:
        """Approximate tokens as 1 token per 4 characters (rough heuristic)."""
        if not text:
            return 0
        return max(1, len(text) // 4)
