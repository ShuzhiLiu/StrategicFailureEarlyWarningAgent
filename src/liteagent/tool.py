"""Tool definition and execution for tool-loop agents.

Tools are Python functions with metadata. They get serialized as OpenAI-format
function definitions and dispatched by the agent loop.

Two ways to define tools:

1. Decorator (auto-generates JSON schema from type hints):
    @tool
    def web_search(query: str, max_results: int = 10) -> str:
        '''Search the web for a query.'''
        ...

2. Explicit (full control over schema):
    Tool(
        name="web_search",
        description="Search the web",
        parameters={"type": "object", "properties": {...}, "required": [...]},
        fn=search_function,
    )
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints


# Python type -> JSON schema type
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class Tool:
    """A callable tool with metadata for LLM function calling."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: Callable[..., Any]

    def to_openai(self) -> dict:
        """Serialize as OpenAI function tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, arguments: dict[str, Any]) -> str:
        """Execute with arguments dict, return string result.

        Errors are returned as strings (errors as data, not exceptions).
        """
        try:
            result = self.fn(**arguments)
            return str(result) if not isinstance(result, str) else result
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


def tool(fn: Callable) -> Tool:
    """Decorator: convert a typed Python function into a Tool.

    Uses type hints for parameter schema and the first docstring line
    as the description.
    """
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        hint = hints.get(name, str)
        prop: dict[str, Any] = {"type": _TYPE_MAP.get(hint, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default
        properties[name] = prop

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }

    return Tool(
        name=fn.__name__,
        description=(fn.__doc__ or "").strip().split("\n")[0],
        parameters=schema,
        fn=fn,
    )


def parse_tool_calls(response: Any) -> list[dict]:
    """Extract tool calls from an LLM response (OpenAI format).

    Works with both raw OpenAI API responses and LLMResponse objects.
    Returns list of ``{"id": str, "name": str, "arguments": dict}``.
    """
    # Get the raw response if wrapped in LLMResponse
    raw = getattr(response, "raw", response)

    # Navigate to tool_calls on the message
    message = None
    if hasattr(raw, "choices") and raw.choices:
        message = raw.choices[0].message

    if message is None:
        return []

    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return []

    parsed = []
    for tc in tool_calls:
        args_str = tc.function.arguments
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {"_raw": args_str}

        parsed.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments": args,
        })

    return parsed
