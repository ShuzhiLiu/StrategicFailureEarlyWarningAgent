"""liteagent -- Minimal agent framework.

Utilities, not a runtime. You compose these in plain Python functions.
"""

from liteagent.llm import LLMClient, LLMRouter, LLMResponse, SamplingParams, TokenUsage
from liteagent.pipeline import merge_state, run_parallel, loop_until, run_with_retry_loop
from liteagent.state import dedup_by_key, count_by, snapshot
from liteagent.context import truncate, TokenBudget, ContextBuilder
from liteagent.observe import CallLog, Reporter, NullReporter
from liteagent.parse import extract_json, parse_llm_json, strip_thinking, validate_items
from liteagent.errors import retry, with_fallback, NodeError
from liteagent.tool import Tool, tool, parse_tool_calls
from liteagent.agent import ToolLoopAgent, AgentResult

__all__ = [
    # LLM
    "LLMClient", "LLMRouter", "LLMResponse", "SamplingParams", "TokenUsage",
    # Pipeline
    "merge_state", "run_parallel", "loop_until", "run_with_retry_loop",
    # State
    "dedup_by_key", "count_by", "snapshot",
    # Context
    "truncate", "TokenBudget", "ContextBuilder",
    # Observation
    "CallLog", "Reporter", "NullReporter",
    # Parsing
    "extract_json", "parse_llm_json", "strip_thinking", "validate_items",
    # Errors
    "retry", "with_fallback", "NodeError",
    # Tools
    "Tool", "tool", "parse_tool_calls",
    # Agent
    "ToolLoopAgent", "AgentResult",
]
