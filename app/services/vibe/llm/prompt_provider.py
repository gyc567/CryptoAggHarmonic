"""Fallback LLM provider for models without native tool-calling.

The provider injects tool descriptions into the system prompt and parses the
model's response for JSON-like tool calls.
"""

import json
import logging
import re
from typing import Optional

from app.services.vibe.llm.openai_provider import OpenAIProvider
from app.services.vibe.llm.provider import LLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


# Match fenced json blocks like ```json ... ```
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class PromptProvider(LLMProvider):
    """Provider that uses prompt injection to elicit tool calls."""

    name = "prompt"

    def __init__(self, base_provider: Optional[OpenAIProvider] = None):
        self.base_provider = base_provider or OpenAIProvider()

    def is_tool_call_supported(self) -> bool:
        return False

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """Send a prompt-injected request and parse tool calls from the output."""
        if tools:
            messages = self._inject_tool_prompt(messages, tools)

        response = self.base_provider.chat(
            messages=messages,
            tools=None,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if response.is_error:
            return response

        content, tool_calls = self._parse_response(response.content or "")
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=response.usage,
        )

    def approximate_tokens(self, text: str) -> int:
        return self.base_provider.approximate_tokens(text)

    def _inject_tool_prompt(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """Append tool descriptions to the system message."""
        tool_text = self._format_tools(tools)
        injection = (
            "\n\n你可以使用以下工具。如需调用工具，"
            "请在回复中 STRICTLY 输出一段 JSON，格式如下：\n"
            '{"tool": "tool_name", "arguments": {"arg1": "value1"}}\n'
            "每个 JSON 占一行。你可以一次性输出多个工具调用。"
            "如果不需要工具，直接回复用户即可。\n\n"
            f"可用工具：\n{tool_text}"
        )

        new_messages = []
        system_injected = False
        for msg in messages:
            if msg.get("role") == "system" and not system_injected:
                new_messages.append({"role": "system", "content": msg.get("content", "") + injection})
                system_injected = True
            else:
                new_messages.append(msg)

        if not system_injected:
            new_messages.insert(0, {"role": "system", "content": injection})

        return new_messages

    def _format_tools(self, tools: list[dict]) -> str:
        lines = []
        for tool in tools:
            fn = tool.get("function", {})
            lines.append(f"- {fn.get('name')}: {fn.get('description', '')}")
            lines.append(f"  参数：{json.dumps(fn.get('parameters', {}), ensure_ascii=False)}")
        return "\n".join(lines)

    def _parse_response(self, text: str) -> tuple[str | None, list[ToolCall]]:
        """Extract tool calls from the response text.

        Returns remaining content and a list of parsed ToolCall objects.
        """
        tool_calls: list[ToolCall] = []
        remaining_lines: list[str] = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                remaining_lines.append(line)
                continue

            parsed_on_line = self._parse_tool_json(stripped)
            if parsed_on_line:
                tool_calls.extend(parsed_on_line)
                continue

            remaining_lines.append(line)

        remaining_content = "\n".join(remaining_lines).strip() or None
        return remaining_content, tool_calls

    def _parse_tool_json(self, text: str) -> list[ToolCall]:
        """Try to parse one or more tool-call JSON objects from ``text``.

        Handles whole-line JSON, multiple inline objects, and fenced blocks.
        """
        tool_calls: list[ToolCall] = []

        # 1. Fenced json blocks (common in markdown-style responses).
        fenced_texts: list[str] = []
        remaining = text
        for match in _FENCED_JSON_RE.finditer(text):
            fenced_texts.append(match.group(1))
            remaining = remaining.replace(match.group(0), "")

        candidates: list[str] = []
        for fenced in fenced_texts:
            candidates.extend(self._extract_json_objects(fenced))

        # 2. Inline JSON objects in the non-fenced remainder.
        candidates.extend(self._extract_json_objects(remaining))

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "tool" in data:
                tool_calls.append(
                    ToolCall(
                        id=f"prompt_{len(tool_calls)}",
                        name=data["tool"],
                        arguments=data.get("arguments", {}),
                    )
                )

        return tool_calls

    @staticmethod
    def _extract_json_objects(text: str) -> list[str]:
        """Extract top-level JSON objects from ``text`` using brace balancing.

        This avoids the greedy/fragile ``re.findall(r"\\{.*\\}")`` pattern and
        correctly handles nested objects and multiple objects on the same line.
        """
        objects: list[str] = []
        i = 0
        length = len(text)
        while i < length:
            if text[i] != "{":
                i += 1
                continue

            depth = 0
            in_string = False
            escape = False
            start = i
            for j in range(i, length):
                ch = text[j]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        objects.append(text[start : j + 1])
                        i = j
                        break
            i += 1
        return objects
