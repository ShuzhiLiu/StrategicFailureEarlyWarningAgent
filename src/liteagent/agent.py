"""Tool-loop agent -- the while(tool_call) pattern.

The simplest possible agent: send messages, check for tool calls,
execute tools, append results, repeat. Claude Code's agent is a
while(tool_call) loop with ~65 lines of core logic. This is the
same pattern, generalized.

Usage::

    agent = ToolLoopAgent(
        llm=llm_client,
        tools=[search_tool, extract_tool],
        system_prompt="You are a research agent...",
    )
    result = agent.run("Find evidence about Honda's EV strategy")
    print(result.content)       # final LLM response
    print(result.tool_call_count)  # how many tools were called
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from liteagent.llm import LLMClient, LLMResponse
from liteagent.observe import CallLog
from liteagent.tool import Tool, parse_tool_calls


@dataclass
class AgentResult:
    """Result from a tool-loop agent run."""

    content: str
    messages: list[dict] = field(default_factory=list)
    tool_call_count: int = 0
    iterations: int = 0
    hit_limit: bool = False


class ToolLoopAgent:
    """Agent that calls tools in a loop until the LLM stops.

    The core loop:
      1. Send messages to LLM (with tool definitions)
      2. If LLM returns tool_calls -> execute each, append results
      3. If LLM returns text only -> done, return result
      4. Repeat until max_iterations safety bound
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: list[Tool],
        system_prompt: str = "",
        *,
        max_iterations: int = 20,
        call_log: CallLog | None = None,
        node_name: str = "agent",
    ) -> None:
        self._llm = llm
        self._tools = {t.name: t for t in tools}
        self._tools_openai = [t.to_openai() for t in tools]
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._call_log = call_log
        self._node_name = node_name

    def run(self, user_message: str) -> AgentResult:
        """Run the agent loop. Returns final content + metadata."""
        messages: list[dict] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        messages.append({"role": "user", "content": user_message})

        tool_call_count = 0
        last_content = ""

        for iteration in range(self._max_iterations):
            # Call LLM with tools
            response = self._llm.call_with_tools(messages, self._tools_openai)
            last_content = response.content or ""

            # Log LLM call
            if self._call_log:
                self._call_log.log_llm_call(
                    self._node_name, messages, response, label="tool_loop",
                )

            # Parse tool calls from response
            calls = parse_tool_calls(response)

            if not calls:
                # LLM is done -- return final content
                return AgentResult(
                    content=last_content,
                    messages=messages + [
                        {"role": "assistant", "content": last_content},
                    ],
                    tool_call_count=tool_call_count,
                    iterations=iteration + 1,
                )

            # Append assistant message with tool calls
            messages.append(self._build_assistant_msg(response))

            # Execute each tool call and append results
            for call in calls:
                tool = self._tools.get(call["name"])
                if tool is None:
                    result_text = (
                        f"Error: Unknown tool '{call['name']}'. "
                        f"Available: {list(self._tools)}"
                    )
                else:
                    result_text = tool.execute(call["arguments"])
                    if self._call_log:
                        self._call_log.log_tool_call(
                            self._node_name,
                            call["name"],
                            call["arguments"],
                            result_text,
                        )

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result_text,
                })
                tool_call_count += 1

        # Max iterations reached -- return what we have
        return AgentResult(
            content=last_content,
            messages=messages,
            tool_call_count=tool_call_count,
            iterations=self._max_iterations,
            hit_limit=True,
        )

    def _build_assistant_msg(self, response: LLMResponse) -> dict:
        """Build assistant message with tool_calls from raw API response."""
        raw = response.raw
        message = raw.choices[0].message
        msg: dict[str, Any] = {"role": "assistant"}
        if message.content:
            msg["content"] = message.content
        if message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        return msg
