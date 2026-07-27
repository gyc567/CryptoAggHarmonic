"""Tool registry for vibe agent tools."""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Optional

from app.services.vibe.tools.base import Tool, ToolRuntime, ToolOutput

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_SECONDS = 60


class ToolRegistry:
    """Registry and dispatcher for vibe tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vibe_tool")

    def register(self, tool: Tool) -> "ToolRegistry":
        """Register a tool instance."""
        self._tools[tool.name] = tool
        logger.info("Registered vibe tool: %s", tool.name)
        return self

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """Return OpenAI-compatible tool schemas."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def get_prompt_description(self) -> str:
        """Return a prompt-friendly description of all tools."""
        lines = [tool.to_prompt_description() for tool in self._tools.values()]
        return "\n".join(lines)

    def execute(
        self,
        name: str,
        input: dict,
        runtime: ToolRuntime,
        timeout_seconds: Optional[int] = None,
    ) -> ToolOutput:
        """Execute a tool by name with input validation and timeout.

        Args:
            name: Tool name.
            input: Validated input dict.
            runtime: Runtime context.
            timeout_seconds: Max execution time. Defaults to 60s.

        Returns:
            ToolOutput with status completed/error/timeout/invalid_input.
        """
        tool = self.get(name)
        if tool is None:
            return ToolOutput.error(f"未知工具: {name}", code="TOOL_NOT_FOUND")

        is_valid, error = tool.validate_input(input)
        if not is_valid:
            return ToolOutput.invalid_input(error or "参数校验失败")

        timeout = timeout_seconds or DEFAULT_TOOL_TIMEOUT_SECONDS
        future = self._executor.submit(tool.run, input, runtime)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            logger.warning("Tool %s timed out after %ss", name, timeout)
            return ToolOutput.timeout(f"工具 {name} 执行超时（{timeout}s）")
        except Exception as e:
            logger.exception("Tool %s execution failed", name)
            return ToolOutput.error(f"工具执行失败: {e}", code="TOOL_EXECUTION_ERROR")
