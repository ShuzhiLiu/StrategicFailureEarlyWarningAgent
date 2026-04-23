# Design Report: Lite Agent Framework + SFEWA Separation

**Date**: 2026-04-04
**Context**: Refactor SFEWA from a monolithic codebase into (1) a reusable lite agent framework and (2) task-specific scripts for strategic failure analysis.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Lessons from the Field](#2-lessons-from-the-field)
3. [Architecture Overview](#3-architecture-overview)
4. [Part 1: Lite Agent Framework — `liteagent`](#4-part-1-lite-agent-framework--liteagent)
5. [Part 2: SFEWA Task-Specific Code](#5-part-2-sfewa-task-specific-code)
6. [Migration Plan](#6-migration-plan)
7. [Appendix: Anti-Patterns Reference](#7-appendix-anti-patterns-reference)

---

## 1. Executive Summary

### The Problem

SFEWA has successfully migrated from LangChain/LangGraph to plain Python. The current codebase works — zero framework dependency, clean node contracts, real agentic behavior. But generic agent patterns (LLM client, state management, pipeline execution, call logging, retry logic) are entangled with domain-specific code (risk factors, evidence extraction, adversarial review).

### The Proposal

Split the codebase into two packages:

| Package | Purpose | Size Target | Dependency |
|---|---|---|---|
| **`liteagent`** | Reusable agent primitives | ~800-1200 lines | `openai`, `pydantic` (optional) |
| **`sfewa`** | Strategic failure early warning | ~3000 lines | `liteagent` + domain deps |

### Design Philosophy

**Provide utilities, not a runtime.** The framework gives you building blocks — you compose them in plain Python functions. No graph DSL, no declarative config, no framework-owned execution loop. Your pipeline is a function you write and can read top-to-bottom.

This is the lesson from both Claude Code (a `while True` loop is the entire architecture) and the LangChain backlash (frameworks that own your execution flow become prisons when you need to do something original).

---

## 2. Lessons from the Field

### 2.1 What Claude Code Gets Right

Claude Code is 512K+ lines of TypeScript, but the core agent is ~65 lines:

```
while True:
    response = call_model(messages, tools)
    if no_tool_calls(response):
        break
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        messages.append(tool_result(result))
```

**Key insights from the architecture**:

| Principle | Implementation | Why It Works |
|---|---|---|
| Messages are state | Append-only message array is the sole state | Enables persistence, replay, compression through one mechanism |
| Model is the router | LLM decides what tools to call, when to stop | No hardcoded routing logic to maintain |
| Errors are data | Tool failures become tool results for the model | Model self-corrects; only surfaces errors when all recovery fails |
| Fail-closed defaults | New tools are unsafe until explicitly marked safe | Security by default, not by audit |
| Progressive compression | 4 levels: snip → microcompact → collapse → autocompact | Cheap recovery first, expensive only when necessary |
| Streaming execution | Tools execute while model is still generating | Hides ~1s tool latency inside 5-30s generation window |

**The 512K lines exist for edge cases**: error recovery (7 distinct continue sites), context overflow, session crashes, permission management, streaming optimization. The core loop is trivial; production hardening is where the complexity lives.

### 2.2 What LangChain Gets Wrong

LangChain's problems are architectural, not incidental:

**Abstraction inversion** — Wrapping simple operations in complex hierarchies:
```python
# What you need (3 lines)
client = OpenAI()
response = client.chat.completions.create(model="gpt-4", messages=msgs)
print(response.choices[0].message.content)

# What LangChain gives you (import archaeology + hidden behavior)
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
llm = ChatOpenAI(model="gpt-4")
result = llm.invoke([HumanMessage(content="hello")])
# What retry logic runs here? What callbacks fire? What message transforms happen?
# You need LangSmith to find out.
```

**Hidden token/cost overhead** — Production teams measured 2.7× cost multipliers from LangChain's invisible prompt injection, retry logic, and message transformation.

**Debugging archaeology** — 50+ frame stack traces through `Runnable`, `RunnableSequence`, `RunnableWithMessageHistory`. Error messages reference framework internals, not your code.

**Version instability** — Breaking changes across minor versions. `langchain-core` split from `langchain`. Import paths change. Community code rots fast.

### 2.3 What LangGraph Gets Wrong (Separately from LangChain)

LangGraph is better than LangChain but has its own issues:

**Implicit state reducer behavior** — `Annotated[list, operator.add]` looks clean until your quality gate loops and you get exponential duplication. SFEWA hit this exact bug (Iteration 11): adversarial loop-back caused analysts to produce duplicate risk factors, requiring explicit deduplication in 4 downstream nodes.

**Graph overhead for simple workflows** — A chat app is 280 lines in LangGraph vs 160 lines in plain Python. The graph abstraction adds value for complex fan-out patterns but penalizes simple sequential flows.

**Distributed systems expertise required** — Checkpointing, state serialization, message channels — concepts from distributed systems that most agent tasks don't need.

### 2.4 What deepagents Gets Wrong

LangChain's `deepagents` repo (2026) attempts to bring Claude Code patterns into the LangChain ecosystem. It gets the product patterns right (middleware, backend protocol, eval suite) but builds them on the problematic foundation:

- **Still 100% LangChain dependent** — 11,696 lines on top of LangChain, not replacing it
- **8-layer middleware stack** — Deepens the debugging problem LangChain already has
- **Over-engineered subagent system** — 3 types (sub-agent, coordinator, swarm) with 250-line tool descriptions when most tasks need one pattern

**Verdict**: Good product patterns (Claude Code's middleware concept, eval-driven development) on a foundation that amplifies the original problems.

### 2.5 Community Consensus (2025-2026)

The emerging consensus from production teams:

> "Start with the OpenAI SDK directly. Add abstractions only when you feel genuine pain from the lack of them. Most teams need: a retry wrapper, a tool dispatch function, and a conversation loop. That's ~200 lines of Python."

Frameworks that succeeded in this period (PydanticAI, smolagents, Mirascope) share traits:
- Thin wrappers over provider SDKs (not new abstractions)
- Standard Python types (dicts, dataclasses, Pydantic models — not framework-specific message types)
- Escapable at every level (can always drop to raw API calls)
- Explicit behavior (no hidden LLM calls, no implicit retries)

---

## 3. Architecture Overview

### Current State (SFEWA monolith)

```
sfewa/
  main.py           ← CLI (domain)
  llm.py            ← LLM client (GENERIC, but hardcoded to vLLM/Qwen3.5)
  context.py         ← Pipeline context injection (GENERIC pattern, domain content)
  reporting.py       ← Runtime reporter (GENERIC pattern, domain display)
  graph/
    pipeline.py      ← Pipeline executor (GENERIC: merge_state, parallel, loop)
    routing.py       ← Routing functions (GENERIC pattern, domain logic)
  agents/            ← All 10 nodes (DOMAIN)
  prompts/           ← All prompt templates (DOMAIN)
  schemas/           ← State + data models (DOMAIN)
  tools/
    chat_log.py      ← Call logging (GENERIC)
    artifacts.py     ← File saving (GENERIC pattern, domain structure)
    temporal_filter.py ← Date utils (GENERIC)
    corpus_loader.py  ← EDINET loader (DOMAIN)
    edinet.py         ← EDINET API (DOMAIN)
```

### Target State

```
liteagent/                          sfewa/
  ├── llm.py                          ├── main.py
  ├── tool.py                         ├── agents/
  ├── agent.py (tool-loop)            │   ├── init_case.py
  ├── pipeline.py                     │   ├── retrieval.py
  ├── state.py                        │   ├── evidence_extraction.py
  ├── context.py                      │   ├── quality_gate.py
  ├── observe.py                      │   ├── _analyst_base.py
  ├── parse.py                        │   ├── industry/company/peer_analyst.py
  └── errors.py                       │   ├── adversarial.py
                                      │   ├── risk_synthesis.py
  8 files, ~1000 lines                │   └── backtest.py
  Zero domain knowledge               ├── prompts/        (all prompt templates)
                                      ├── schemas/        (all domain types)
                                      ├── tools/          (edinet, corpus_loader)
                                      ├── context.py      (domain-specific builder)
                                      └── reporting.py    (domain-specific display)
```

---

## 4. Part 1: Lite Agent Framework — `liteagent`

### 4.1 Design Principles

These principles are derived from what works (Claude Code) and what fails (LangChain):

| # | Principle | Rationale |
|---|---|---|
| 1 | **Utilities, not a runtime** | You write the loop. Framework provides building blocks. No framework-owned execution. |
| 2 | **Plain Python types** | `dict`, `list`, `str`, `TypedDict`, `dataclass`. No framework-specific message types. |
| 3 | **Zero hidden behavior** | Every LLM call, retry, and state mutation is visible in your code. No implicit callbacks. |
| 4 | **Provider-agnostic via OpenAI protocol** | OpenAI SDK is the lingua franca (vLLM, Anthropic, Gemini all support it). One client, swap `base_url`. |
| 5 | **Escapable at every layer** | Any component can be replaced with raw code. Framework never traps you. |
| 6 | **Errors are data** | Failed tool calls and parse failures become structured results, not exceptions. Model decides recovery. |
| 7 | **Observation is built-in, not bolted-on** | Every LLM call and tool call is logged by default. No separate observability product needed. |
| 8 | **Composition over inheritance** | Functions that compose, not classes to inherit from. `tool()` is a decorator, not a base class. |

### 4.2 Module Structure

```
liteagent/
├── __init__.py          # Public API re-exports
├── llm.py               # LLM client + provider config
├── tool.py              # Tool definition, registry, validation
├── agent.py             # Tool-loop agent (Claude Code pattern)
├── pipeline.py          # Pipeline utilities (merge_state, run_parallel, loop_until)
├── state.py             # State management helpers
├── context.py           # Context window management (truncation, injection)
├── observe.py           # Call logging + pluggable reporters
├── parse.py             # Structured output parsing + retry
└── errors.py            # Error types + retry strategies
```

**8 modules. ~1000 lines total. Zero domain knowledge.**

### 4.3 Module Design — Deep Dive

---

#### 4.3.1 `llm.py` — LLM Client

**What it does**: Provider-agnostic LLM access via the OpenAI-compatible protocol. Supports thinking/non-thinking modes, role-based mode selection, and response normalization.

**What it replaces**: `sfewa/llm.py` (generalized, domain config extracted)

```python
"""Provider-agnostic LLM client via OpenAI-compatible API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from openai import OpenAI


@dataclass(frozen=True)
class LLMResponse:
    """Normalized LLM response.

    All provider-specific quirks (vLLM reasoning_content, Anthropic thinking blocks)
    are normalized into this single type. Agent code never touches raw API responses.
    """
    content: str
    thinking: str | None = None
    usage: TokenUsage = field(default_factory=lambda: TokenUsage())
    raw: Any = field(default=None, repr=False)  # escape hatch: original API response


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class SamplingParams:
    """LLM sampling configuration."""
    temperature: float = 0.7
    max_tokens: int = 32768
    top_p: float = 0.8
    extra_body: dict = field(default_factory=dict)


class LLMClient:
    """Thin wrapper around OpenAI SDK.

    Why wrap at all? Three reasons:
    1. Normalize responses (vLLM puts thinking in .reasoning_content, not .content)
    2. Consistent interface for observation hooks
    3. Clean separation between provider config and call-site code

    The wrapper is ~40 lines of real logic. If it ever fights you, drop to
    self._client directly — that's the escape hatch.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "not-needed",
        sampling: SamplingParams | None = None,
    ) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._sampling = sampling or SamplingParams()

    def call(
        self,
        messages: list[dict[str, str]],
        *,
        sampling: SamplingParams | None = None,
    ) -> LLMResponse:
        """Call the LLM. Returns normalized response.

        Args:
            messages: OpenAI-format messages [{"role": ..., "content": ...}]
            sampling: Override default sampling params for this call.
        """
        p = sampling or self._sampling
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=p.temperature,
            max_tokens=p.max_tokens,
            top_p=p.top_p,
            extra_body=p.extra_body or None,
        )
        return self._normalize(resp)

    def _normalize(self, resp) -> LLMResponse:
        """Normalize provider-specific response into LLMResponse."""
        choice = resp.choices[0]
        content = choice.message.content or ""

        # vLLM with --reasoning-parser puts thinking in .reasoning_content
        thinking = getattr(choice.message, "reasoning_content", None)

        usage = resp.usage
        token_usage = TokenUsage(
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )

        return LLMResponse(
            content=content,
            thinking=thinking,
            usage=token_usage,
            raw=resp,
        )

    @property
    def client(self) -> OpenAI:
        """Escape hatch: access the raw OpenAI client."""
        return self._client


class LLMRouter:
    """Maps role names to LLMClient instances.

    Replaces SFEWA's ROLE_TO_MODE + get_llm_for_role pattern with a
    generic, configurable version.

    Usage:
        router = LLMRouter(
            clients={"thinking": thinking_llm, "fast": fast_llm},
            role_map={"adversarial": "thinking", "extraction": "fast"},
            default="fast",
        )
        llm = router.get("adversarial")  # returns thinking_llm
    """

    def __init__(
        self,
        clients: dict[str, LLMClient],
        role_map: dict[str, str],
        default: str = "default",
    ) -> None:
        self._clients = clients
        self._role_map = role_map
        self._default = default

    def get(self, role: str) -> LLMClient:
        """Get the LLM client for a given role."""
        client_key = self._role_map.get(role, self._default)
        client = self._clients.get(client_key)
        if client is None:
            raise KeyError(
                f"No LLM client for role={role!r} (mapped to {client_key!r}). "
                f"Available: {list(self._clients)}"
            )
        return client
```

**Key design decisions**:
- `LLMResponse` is a frozen dataclass, not a dict — typos are caught, IDE autocomplete works
- `raw` field preserves the original API response as an escape hatch
- `LLMRouter` replaces the hardcoded `ROLE_TO_MODE` — configurable per-project
- No `lru_cache` at the module level — caller decides caching strategy
- `SamplingParams` is a separate, frozen dataclass — can be shared, overridden per-call

**What's NOT here**:
- No provider-specific subclasses (OpenAI protocol covers vLLM, Anthropic, Gemini, etc.)
- No retry logic (that's in `errors.py` — separation of concerns)
- No streaming (add when needed, as a `call_stream()` method)

---

#### 4.3.2 `tool.py` — Tool Definition & Registry

**What it does**: Define tools with JSON schemas, register them, validate inputs, dispatch calls. Inspired by Claude Code's tool system but without the permission layer (add when needed).

**Why this exists**: SFEWA doesn't have a tool system (agents call functions directly). But the tool-loop agent pattern (4.3.3) needs it, and it's the right abstraction for any agent that needs to interact with the world.

```python
"""Tool definition, registration, and dispatch."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints


@dataclass(frozen=True)
class ToolDef:
    """A tool the LLM can call.

    Follows the OpenAI function calling schema convention.
    """
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: dict = field(default_factory=dict)  # JSON Schema
    is_read_only: bool = False


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool execution.

    Errors are data — they go back to the model as content, not exceptions.
    """
    tool_call_id: str
    content: str
    is_error: bool = False


def tool(
    name: str | None = None,
    description: str = "",
    *,
    read_only: bool = False,
    parameters: dict | None = None,
) -> Callable:
    """Decorator to define a tool from a function.

    Usage:
        @tool(description="Search the web for a query")
        def web_search(query: str, max_results: int = 10) -> str:
            ...

    The JSON Schema for parameters is inferred from type hints if not
    provided explicitly. For complex schemas, pass `parameters` directly.
    """
    def decorator(fn: Callable) -> ToolDef:
        tool_name = name or fn.__name__
        schema = parameters or _infer_schema(fn)
        return ToolDef(
            name=tool_name,
            description=description or fn.__doc__ or "",
            handler=fn,
            parameters=schema,
            is_read_only=read_only,
        )
    return decorator


def _infer_schema(fn: Callable) -> dict:
    """Infer JSON Schema from function signature + type hints.

    Covers common cases: str, int, float, bool, list, Optional.
    For complex types, users should provide explicit schemas.
    """
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties = {}
    required = []

    type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        hint = hints.get(param_name, str)

        # Handle Optional[X] → nullable
        origin = getattr(hint, "__origin__", None)
        if origin is list:
            properties[param_name] = {"type": "array"}
        elif hint in type_map:
            properties[param_name] = {"type": type_map[hint]}
        else:
            properties[param_name] = {"type": "string"}

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class ToolRegistry:
    """Registry of available tools with dispatch.

    Usage:
        registry = ToolRegistry([search_tool, read_tool, write_tool])
        result = registry.execute(tool_call)
        schemas = registry.to_openai_format()  # for LLM function calling
    """

    def __init__(self, tools: list[ToolDef]) -> None:
        self._tools: dict[str, ToolDef] = {t.name: t for t in tools}

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def execute(self, name: str, arguments: dict, tool_call_id: str = "") -> ToolResult:
        """Execute a tool by name. Errors become ToolResult, not exceptions."""
        tool_def = self._tools.get(name)
        if tool_def is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Error: unknown tool '{name}'. Available: {list(self._tools)}",
                is_error=True,
            )
        try:
            result = tool_def.handler(**arguments)
            content = result if isinstance(result, str) else json.dumps(result, default=str)
            # Truncate large results
            if len(content) > 50_000:
                content = content[:25_000] + "\n\n... (truncated) ...\n\n" + content[-25_000:]
            return ToolResult(tool_call_id=tool_call_id, content=content)
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call_id,
                content=f"Error executing {name}: {type(e).__name__}: {e}",
                is_error=True,
            )

    def to_openai_format(self) -> list[dict]:
        """Export tool definitions in OpenAI function calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    @property
    def names(self) -> list[str]:
        return list(self._tools)
```

**Key design decisions**:
- `ToolDef` is a frozen dataclass, not a base class — no inheritance, just data
- `@tool` decorator infers JSON Schema from type hints — minimal boilerplate
- `ToolResult` with `is_error` — errors are data, flow back to the model
- Result truncation at 50K chars — prevents context overflow (Claude Code pattern)
- `to_openai_format()` — tools are defined once, used anywhere

---

#### 4.3.3 `agent.py` — Tool-Loop Agent (Claude Code Pattern)

**What it does**: The core `while(tool_call)` loop. LLM decides what tools to call and when to stop. This is the Claude Code pattern adapted for Python.

**Why this exists**: SFEWA uses a pipeline pattern (predefined nodes). But many agent tasks are better served by the tool-loop pattern where the LLM has full autonomy. The framework should support both.

```python
"""Tool-loop agent — the Claude Code pattern.

The LLM decides what tools to call and when to stop.
The code provides the execution environment.

This is the simplest possible agent: a while loop.
Everything else (retry, compression, streaming) is layered on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from liteagent.llm import LLMClient, LLMResponse
from liteagent.tool import ToolRegistry, ToolResult
from liteagent.observe import CallLog


@dataclass
class AgentConfig:
    """Configuration for a tool-loop agent."""
    system_prompt: str = "You are a helpful assistant."
    max_iterations: int = 50
    on_tool_result: Callable[[str, dict, ToolResult], None] | None = None  # hook


@dataclass
class AgentResult:
    """Final result of an agent run."""
    content: str
    messages: list[dict]       # full conversation history
    iterations: int
    log: CallLog


def run_agent(
    llm: LLMClient,
    tools: ToolRegistry,
    user_message: str,
    *,
    config: AgentConfig | None = None,
    messages: list[dict] | None = None,  # resume from existing conversation
    log: CallLog | None = None,
) -> AgentResult:
    """Run a tool-loop agent.

    The loop:
    1. Call LLM with messages + tool definitions
    2. If no tool calls in response → done (model decided to stop)
    3. Execute each tool call
    4. Append results to messages
    5. Go to 1

    Args:
        llm: The LLM client to use.
        tools: Available tools.
        user_message: The user's request.
        config: Agent configuration.
        messages: Resume from existing conversation (optional).
        log: Call log for observation (optional).

    Returns:
        AgentResult with final response and full conversation history.
    """
    cfg = config or AgentConfig()
    log = log or CallLog()

    # Initialize messages
    if messages is None:
        messages = []
        if cfg.system_prompt:
            messages.append({"role": "system", "content": cfg.system_prompt})
        messages.append({"role": "user", "content": user_message})
    else:
        messages = list(messages)  # don't mutate the input
        messages.append({"role": "user", "content": user_message})

    tool_schemas = tools.to_openai_format()
    iterations = 0

    while iterations < cfg.max_iterations:
        iterations += 1

        # Call LLM
        resp = llm.call(messages)  # TODO: pass tools=tool_schemas when using function calling
        log.log_llm_call("agent", messages, resp)

        assistant_msg = {"role": "assistant", "content": resp.content}

        # Check for tool calls in the response
        raw_tool_calls = _extract_tool_calls(resp)
        if not raw_tool_calls:
            # No tool calls — model considers task complete
            messages.append(assistant_msg)
            break

        # Add assistant message with tool calls
        assistant_msg["tool_calls"] = raw_tool_calls
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in raw_tool_calls:
            result = tools.execute(
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
                tool_call_id=tc["id"],
            )
            log.log_tool_call(
                "agent", tc["function"]["name"],
                tc["function"]["arguments"], result.content,
            )

            if cfg.on_tool_result:
                cfg.on_tool_result(tc["function"]["name"], tc["function"]["arguments"], result)

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result.content,
            })
    else:
        # Max iterations reached
        messages.append({
            "role": "assistant",
            "content": f"[Agent stopped: reached max iterations ({cfg.max_iterations})]",
        })

    final_content = messages[-1].get("content", "") if messages else ""
    return AgentResult(
        content=final_content,
        messages=messages,
        iterations=iterations,
        log=log,
    )


def _extract_tool_calls(resp: LLMResponse) -> list[dict]:
    """Extract tool calls from LLM response.

    Handles both OpenAI native function calling and text-based tool calling
    (for models that don't support function calling natively).
    """
    # Check raw response for native function calling
    if resp.raw and hasattr(resp.raw, "choices"):
        choice = resp.raw.choices[0]
        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            return [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                        if isinstance(tc.function.arguments, dict)
                        else _safe_json_loads(tc.function.arguments),
                    },
                }
                for tc in choice.message.tool_calls
            ]
    return []


def _safe_json_loads(s: str) -> dict:
    """Parse JSON string, returning empty dict on failure."""
    import json
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}
```

**Key design decisions**:
- `run_agent()` is a function, not a class method — stateless, testable, composable
- `messages` parameter enables conversation resumption — messages ARE the state
- `on_tool_result` hook — pluggable observation without framework callbacks
- Max iterations as safety bound (Claude Code pattern) — the model decides when to stop, counter prevents infinite loops
- `_extract_tool_calls` handles both native function calling and potential text-based fallback

**What this enables that SFEWA can't do today**: A free-form research agent that decides its own investigation strategy, calling search tools and reading documents in whatever order the LLM determines.

---

#### 4.3.4 `pipeline.py` — Pipeline Utilities

**What it does**: Building blocks for predefined multi-step pipelines with LLM-driven routing. Not a Pipeline class — just utility functions you compose in your own code.

**What it replaces**: `sfewa/graph/pipeline.py` (generalized)

```python
"""Pipeline utilities — building blocks for multi-step agent pipelines.

These are UTILITIES, not a runtime. You compose them in plain Python:

    def my_pipeline(state):
        state = merge_state(state, step_1(state))
        state = loop_until(state, [step_2, step_3], done_check, max_iter=3)
        results = run_parallel([step_4a, step_4b, step_4c], state)
        for r in results:
            state = merge_state(state, r)
        return state

No graph DSL, no declarative config. Your pipeline is a function.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any

# Type alias for a pipeline node: takes state dict, returns state updates dict
Node = Callable[[dict], dict]
RouteCheck = Callable[[dict], bool]


def merge_state(
    state: dict,
    updates: dict,
    *,
    accumulate: set[str] | None = None,
) -> dict:
    """Apply node output to pipeline state.

    Args:
        state: Current pipeline state.
        updates: State updates from a node.
        accumulate: Field names that accumulate (extend) instead of overwrite.
                   E.g., {"evidence", "risk_factors"} — lists grow across nodes.

    Returns:
        Updated state (mutates in place for efficiency, returns for chaining).
    """
    acc = accumulate or set()
    for key, value in updates.items():
        if key in acc and isinstance(value, list):
            state.setdefault(key, []).extend(value)
        else:
            state[key] = value
    return state


def run_parallel(
    nodes: list[Node],
    state: dict,
    *,
    max_workers: int | None = None,
    on_error: Callable[[Exception, Node], dict | None] | None = None,
) -> list[dict]:
    """Run multiple nodes in parallel, return their results.

    Each node receives a COPY of the state (isolation — no concurrent mutation).
    Results are returned in completion order.

    Args:
        nodes: Functions to run in parallel.
        state: Current state (each node gets a shallow copy).
        max_workers: Thread pool size (defaults to len(nodes)).
        on_error: Error handler. Receives (exception, node_fn). Return a dict
                 to use as fallback result, or None to skip.
    """
    workers = max_workers or len(nodes)
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_node = {
            pool.submit(node, dict(state)): node for node in nodes
        }
        for future in as_completed(future_to_node):
            node = future_to_node[future]
            try:
                results.append(future.result())
            except Exception as e:
                if on_error:
                    fallback = on_error(e, node)
                    if fallback is not None:
                        results.append(fallback)
                else:
                    raise

    return results


def loop_until(
    state: dict,
    steps: list[Node],
    done: RouteCheck,
    *,
    max_iterations: int = 3,
    accumulate: set[str] | None = None,
    on_max_iterations: Callable[[dict], None] | None = None,
) -> dict:
    """Run a sequence of steps in a loop until a condition is met.

    This is the quality-gate pattern: execute steps, check if done,
    loop back if not. Max iterations is a safety bound.

    Args:
        state: Current state.
        steps: Nodes to run each iteration (in order).
        done: Function that checks state and returns True when done.
        max_iterations: Safety bound on loop count.
        accumulate: Fields that accumulate across iterations.
        on_max_iterations: Called when max iterations reached (for logging).

    Returns:
        Updated state.
    """
    for i in range(max_iterations):
        for step in steps:
            state = merge_state(state, step(state), accumulate=accumulate)

        if done(state):
            break
    else:
        if on_max_iterations:
            on_max_iterations(state)

    return state


def run_with_retry_loop(
    state: dict,
    generate: Node,
    evaluate: Node,
    should_retry: RouteCheck,
    *,
    max_passes: int = 2,
    accumulate: set[str] | None = None,
) -> dict:
    """Generator-evaluator loop with retry.

    The adversarial pattern: generate output, evaluate it independently,
    retry if evaluation says so. Max passes is a safety bound.

    Args:
        state: Current state.
        generate: Generator node (e.g., analysts).
        evaluate: Evaluator node (e.g., adversarial reviewer).
        should_retry: Check evaluator output — True means retry.
        max_passes: Maximum evaluation passes.
        accumulate: Fields that accumulate.
    """
    for _ in range(max_passes):
        state = merge_state(state, generate(state), accumulate=accumulate)
        state = merge_state(state, evaluate(state), accumulate=accumulate)

        if not should_retry(state):
            break

    return state
```

**Key design decisions**:
- Functions, not classes — `merge_state()`, `run_parallel()`, `loop_until()` are composable utilities
- `accumulate` parameter makes accumulating vs overwriting explicit at the call site (vs LangGraph's implicit `operator.add`)
- `run_parallel()` passes state COPIES to each node — isolation prevents the concurrent write bugs that LangGraph suffered from
- `loop_until()` encapsulates the quality-gate pattern: steps + condition + safety bound
- `run_with_retry_loop()` encapsulates the generator-evaluator pattern (Anthropic's key insight)
- `on_error` callback in `run_parallel()` — handle failures per-node without crashing the pipeline

**How SFEWA's pipeline would look using these utilities**:

```python
from liteagent.pipeline import merge_state, run_parallel, loop_until, run_with_retry_loop

ACCUMULATE = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

def run_sfewa_pipeline(state: dict) -> dict:
    state = merge_state(state, init_case(state))

    # Evidence gathering loop (quality gate drives)
    state = loop_until(
        state,
        steps=[retrieval, extraction, quality_gate],
        done=lambda s: s.get("evidence_sufficient", True),
        max_iterations=3,
        accumulate=ACCUMULATE,
    )

    # Parallel analyst fan-out
    for r in run_parallel([industry, company, peer], state):
        state = merge_state(state, r, accumulate=ACCUMULATE)

    # Adversarial loop
    state = run_with_retry_loop(
        state,
        generate=lambda s: _run_analysts_and_merge(s),  # re-run analysts
        evaluate=adversarial,
        should_retry=lambda s: s.get("adversarial_recommendation") == "reanalyze",
        max_passes=2,
        accumulate=ACCUMULATE,
    )

    # Final synthesis
    state = merge_state(state, synthesis(state))
    state = merge_state(state, backtest(state))
    return state
```

Cleaner than the current `run_pipeline()` and the patterns are reusable.

---

#### 4.3.5 `state.py` — State Management

**What it does**: Helpers for typed state management. Deduplication, field access, snapshot/restore.

```python
"""State management helpers for pipeline agents.

State is a plain dict. These helpers add safety without adding abstraction.
"""

from __future__ import annotations

from typing import Any, Callable


def dedup_by_key(
    items: list[dict],
    key: str,
    *,
    keep: str = "last",
) -> list[dict]:
    """Deduplicate a list of dicts by a key field.

    When pipeline loops cause duplicate entries (e.g., risk factors from
    re-analysis), keep only one per key value.

    Args:
        items: List of dicts to deduplicate.
        key: Field name to deduplicate by (e.g., "dimension").
        keep: "last" (default) keeps the latest entry; "first" keeps the earliest.
    """
    seen: dict[str, dict] = {}
    for item in items:
        k = item.get(key, "")
        if keep == "last" or k not in seen:
            seen[k] = item
    return list(seen.values())


def ensure_field(state: dict, field: str, default: Any) -> Any:
    """Get a field from state, setting default if missing."""
    if field not in state:
        state[field] = default
    return state[field]


def snapshot(state: dict, exclude: set[str] | None = None) -> dict:
    """Create a shallow snapshot of state for debugging/logging.

    Optionally exclude large fields (e.g., retrieved_docs) from the snapshot.
    """
    exc = exclude or set()
    return {k: v for k, v in state.items() if k not in exc}


def count_by(items: list[dict], field: str) -> dict[str, int]:
    """Count items grouped by a field value.

    Useful for computing distributions:
        count_by(evidence, "stance")  → {"supports_risk": 10, "neutral": 5, ...}
        count_by(factors, "severity") → {"high": 3, "medium": 4, ...}
    """
    counts: dict[str, int] = {}
    for item in items:
        val = str(item.get(field, "unknown"))
        counts[val] = counts.get(val, 0) + 1
    return counts
```

**Key design decisions**:
- Utilities, not a State class — works with plain dicts, no wrapping needed
- `dedup_by_key()` extracts the pattern SFEWA uses in 4 places (adversarial, synthesis, backtest, artifacts)
- `count_by()` extracts the pattern SFEWA uses in context.py, quality_gate.py, risk_synthesis.py
- `snapshot()` for logging without serializing large fields

---

#### 4.3.6 `context.py` — Context Window Management

**What it does**: Truncation of tool results, context budget tracking, and a generic context injection builder.

```python
"""Context window management.

Two concerns:
1. Prevent context overflow (truncation, budget tracking)
2. Inject upstream context into downstream prompts (pipeline context pattern)
"""

from __future__ import annotations

from typing import Any


def truncate(
    text: str,
    max_chars: int = 50_000,
    *,
    keep_ends: bool = True,
) -> str:
    """Truncate text to max_chars, preserving both start and end.

    Claude Code pattern: important information lives at both ends
    of tool output. Truncate from the middle.

    Args:
        text: Text to truncate.
        max_chars: Maximum character count.
        keep_ends: If True, preserve both start and end (truncate middle).
                  If False, truncate from the end only.
    """
    if len(text) <= max_chars:
        return text

    if keep_ends:
        half = max_chars // 2
        return text[:half] + f"\n\n... ({len(text) - max_chars} chars truncated) ...\n\n" + text[-half:]
    else:
        return text[:max_chars] + f"\n... ({len(text) - max_chars} chars truncated)"


class TokenBudget:
    """Track token usage against a budget.

    Usage:
        budget = TokenBudget(max_tokens=128_000, warn_at=0.85)
        budget.add(response.usage.total_tokens)
        if budget.should_compress:
            ...  # trigger compression
    """

    def __init__(self, max_tokens: int = 128_000, warn_at: float = 0.85) -> None:
        self.max_tokens = max_tokens
        self.warn_at = warn_at
        self.used = 0

    def add(self, tokens: int) -> None:
        self.used += tokens

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    @property
    def utilization(self) -> float:
        return self.used / self.max_tokens if self.max_tokens else 0.0

    @property
    def should_compress(self) -> bool:
        return self.utilization >= self.warn_at


class ContextBuilder:
    """Build pipeline context summaries for injection into prompts.

    Generic version of SFEWA's build_pipeline_context(). You register
    section builders, and it composes them into a summary string.

    Usage:
        ctx = ContextBuilder("PIPELINE CONTEXT (what has happened so far):")
        ctx.add_section("retrieval", lambda s: f"Retrieved {len(s['docs'])} documents")
        ctx.add_section("evidence", lambda s: f"Extracted {len(s['evidence'])} items")

        summary = ctx.build(state)
        # "PIPELINE CONTEXT (what has happened so far):\n- Retrieved 138 documents\n- Extracted 29 items"
    """

    def __init__(self, header: str = "CONTEXT:") -> None:
        self._header = header
        self._sections: list[tuple[str, Any]] = []

    def add_section(self, name: str, builder: Any) -> "ContextBuilder":
        """Add a section builder.

        builder(state) should return a string (or None/empty to skip).
        """
        self._sections.append((name, builder))
        return self

    def build(self, state: dict) -> str:
        """Build the context string from current state."""
        parts: list[str] = []
        for name, builder in self._sections:
            try:
                result = builder(state)
                if result:
                    parts.append(str(result))
            except Exception:
                pass  # skip sections that fail — context is advisory, not critical
        if not parts:
            return ""
        return self._header + "\n" + "\n".join(f"- {p}" for p in parts)
```

---

#### 4.3.7 `observe.py` — Observability

**What it does**: Call logging for LLM and tool calls, plus a pluggable reporter protocol. No external services required (no LangSmith, no Langfuse).

**What it replaces**: `sfewa/tools/chat_log.py` (generalized) + `sfewa/reporting.py` (protocol only)

```python
"""Observability — call logging and runtime reporting.

Every LLM call and tool call is logged by default. No external
services required. Export as JSONL for analysis.

The Reporter protocol allows pluggable display (Rich terminal,
JSON stream, silent for tests) without framework coupling.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ── Call Log ──

@dataclass
class LLMCallRecord:
    node: str
    label: str
    messages: list[dict]
    content: str
    thinking: str
    usage: dict
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ToolCallRecord:
    node: str
    tool_name: str
    inputs: dict
    output: str
    label: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CallLog:
    """Accumulates LLM and tool call records for a pipeline run.

    Thread-safe for parallel node execution (append is atomic on CPython).
    """

    def __init__(self) -> None:
        self._records: list[LLMCallRecord | ToolCallRecord] = []

    def log_llm_call(
        self,
        node: str,
        messages: list[dict],
        response: Any,
        *,
        label: str = "",
    ) -> None:
        """Record an LLM call."""
        # Normalize response (accept LLMResponse, raw string, or any object)
        if isinstance(response, str):
            content, thinking, usage = response, "", {}
        else:
            content = getattr(response, "content", str(response))
            thinking = getattr(response, "thinking", None) or ""
            usage_obj = getattr(response, "usage", None)
            if usage_obj and hasattr(usage_obj, "total_tokens"):
                usage = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                    "total_tokens": getattr(usage_obj, "total_tokens", 0),
                }
            elif isinstance(usage_obj, dict):
                usage = usage_obj
            else:
                # Fallback: check response_metadata (backward compat with SFEWA)
                meta = getattr(response, "response_metadata", {}) or {}
                usage = meta.get("token_usage", {})

        self._records.append(LLMCallRecord(
            node=node,
            label=label,
            messages=messages,
            content=content,
            thinking=thinking,
            usage=usage,
        ))

    def log_tool_call(
        self,
        node: str,
        tool_name: str,
        inputs: Any,
        output: Any,
        *,
        label: str = "",
    ) -> None:
        """Record a tool call."""
        # Truncate large outputs
        out_str = str(output)
        if len(out_str) > 5000:
            out_str = out_str[:5000] + "... (truncated)"

        self._records.append(ToolCallRecord(
            node=node,
            tool_name=tool_name,
            inputs=inputs if isinstance(inputs, dict) else {"raw": str(inputs)},
            output=out_str,
            label=label,
        ))

    @property
    def records(self) -> list[LLMCallRecord | ToolCallRecord]:
        return list(self._records)

    def save_jsonl(self, path: str | Path) -> None:
        """Save all records as JSONL (one JSON object per line)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for record in self._records:
                f.write(json.dumps(asdict(record), default=str) + "\n")

    def total_tokens(self) -> int:
        """Sum total tokens across all LLM calls."""
        return sum(
            r.usage.get("total_tokens", 0)
            for r in self._records
            if isinstance(r, LLMCallRecord)
        )

    def clear(self) -> None:
        self._records.clear()


# ── Reporter Protocol ──

@runtime_checkable
class Reporter(Protocol):
    """Protocol for pluggable runtime reporting.

    Implement this to customize how pipeline progress is displayed.
    The framework provides NullReporter (silent) and ConsoleReporter (Rich).
    """

    def enter_node(self, node_name: str, summary: dict[str, Any] | None = None) -> None: ...
    def log_action(self, action: str, details: dict[str, Any] | None = None) -> None: ...
    def exit_node(self, node_name: str, output: dict[str, Any] | None = None) -> None: ...


class NullReporter:
    """Silent reporter for tests and batch processing."""
    def enter_node(self, node_name: str, summary: dict[str, Any] | None = None) -> None: pass
    def log_action(self, action: str, details: dict[str, Any] | None = None) -> None: pass
    def exit_node(self, node_name: str, output: dict[str, Any] | None = None) -> None: pass
```

**Key design decisions**:
- `CallLog` is an instance, not a module-level global — supports concurrent pipeline runs, easier testing
- `Reporter` is a Protocol, not a base class — implement it with any library (Rich, plain print, JSON stream)
- `NullReporter` for tests — no console noise in test output
- `save_jsonl()` — vendor-free observability (analyze with `jq`, load into pandas, whatever)
- Backward-compatible: `log_llm_call` accepts both `LLMResponse` and raw strings

---

#### 4.3.8 `parse.py` — Structured Output Parsing

**What it does**: Extract JSON from LLM responses, strip thinking tags, retry on parse failure. This is the most common pain point in agent development — extracted from SFEWA's 6 separate implementations.

```python
"""Structured output parsing from LLM responses.

LLMs wrap JSON in markdown code blocks, prefix it with thinking tags,
and occasionally produce invalid JSON. This module handles all of that.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from liteagent.llm import LLMClient, LLMResponse


def extract_json(text: str) -> Any:
    """Extract JSON from LLM output.

    Handles:
    - Raw JSON (starts with { or [)
    - Markdown code blocks (```json ... ```)
    - <think>...</think> prefixed responses
    - Trailing text after JSON

    Raises:
        json.JSONDecodeError: If no valid JSON found.
    """
    # Strip thinking tags
    text = strip_thinking(text)

    # Try markdown code blocks first
    blocks = re.findall(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    for block in blocks:
        block = block.strip()
        if block.startswith(("{", "[")):
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # Try finding raw JSON (first { or [ to matching close)
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find matching close bracket (handle nesting)
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        # Try truncating at last valid close
        end = text.rfind(end_char)
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("No valid JSON found in LLM output", text, 0)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def parse_llm_json(
    llm: LLMClient,
    messages: list[dict],
    *,
    max_retries: int = 1,
    label: str = "structured_output",
) -> tuple[Any, LLMResponse]:
    """Call LLM and parse JSON response, with retry on parse failure.

    On first parse failure, appends the error message to the conversation
    and retries. This is the pattern every SFEWA agent uses — extracted
    into a reusable function.

    Args:
        llm: LLM client.
        messages: Conversation messages.
        max_retries: Number of retries on parse failure.
        label: Label for logging.

    Returns:
        Tuple of (parsed_data, llm_response).

    Raises:
        json.JSONDecodeError: If all retries exhausted.
    """
    response = llm.call(messages)

    for attempt in range(max_retries + 1):
        try:
            data = extract_json(response.content)
            return data, response
        except json.JSONDecodeError as e:
            if attempt < max_retries:
                # Retry with error feedback (LLM self-correction pattern)
                messages = messages + [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": (
                            f"Your response was not valid JSON. Error: {e}\n"
                            "Please respond with ONLY valid JSON, no other text."
                        ),
                    },
                ]
                response = llm.call(messages)
            else:
                raise

    # Should not reach here, but satisfy type checker
    raise json.JSONDecodeError("Parse failed after retries", "", 0)


def validate_items(
    items: list[dict],
    required_fields: list[str],
    *,
    on_invalid: Callable[[dict, str], None] | None = None,
) -> list[dict]:
    """Validate a list of parsed items, keeping only valid ones.

    Args:
        items: Parsed dicts from LLM output.
        required_fields: Fields that must be present and non-empty.
        on_invalid: Callback for rejected items (for logging).

    Returns:
        List of valid items only.
    """
    valid = []
    for item in items:
        missing = [f for f in required_fields if not item.get(f)]
        if missing:
            if on_invalid:
                on_invalid(item, f"Missing required fields: {missing}")
        else:
            valid.append(item)
    return valid
```

**Key design decisions**:
- `extract_json()` handles ALL the common LLM output formats in one function — no more per-agent JSON extraction
- `parse_llm_json()` encapsulates the retry-with-error-feedback pattern that every SFEWA agent implements separately
- `validate_items()` provides the common field-checking pattern
- Bracket-matching fallback for malformed JSON (handles truncated responses)
- All functions are standalone — use `extract_json` without `parse_llm_json` if you manage your own LLM calls

---

#### 4.3.9 `errors.py` — Error Handling & Retry

**What it does**: Retry strategies for transient failures, structured error types.

```python
"""Error handling and retry strategies.

Design principle: errors are data, not exceptions.
Transient failures retry automatically. Permanent failures
return structured error info for the caller to handle.
"""

from __future__ import annotations

import time
import random
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class NodeError:
    """Structured error from a pipeline node.

    Instead of raising, nodes return this in their state updates.
    Downstream nodes can check and adapt.
    """
    node: str
    error_type: str
    message: str
    recoverable: bool = True


def retry(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Retry a function with exponential backoff + jitter.

    Args:
        fn: Function to call.
        max_attempts: Maximum number of attempts.
        backoff_base: Base delay in seconds (doubles each attempt).
        backoff_max: Maximum delay cap.
        retry_on: Exception types to retry on.

    Returns:
        Function result on success.

    Raises:
        The last exception if all attempts fail.
    """
    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except retry_on as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = min(backoff_base * (2 ** attempt), backoff_max)
                delay *= 0.5 + random.random()  # jitter
                time.sleep(delay)

    raise last_exception  # type: ignore[misc]


def with_fallback(
    primary: Callable[..., T],
    fallback: Callable[..., T],
    *args: Any,
    catch: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Try primary function, fall back on failure.

    Usage:
        result = with_fallback(
            lambda: llm.call(messages),
            lambda: {"error": "LLM unavailable", "risk_factors": []},
        )
    """
    try:
        return primary(*args, **kwargs)
    except catch:
        return fallback(*args, **kwargs)
```

---

### 4.4 Public API Surface

The `__init__.py` re-exports the essential types:

```python
"""liteagent — Minimal agent framework.

Utilities, not a runtime. You compose these in plain Python functions.
"""

from liteagent.llm import LLMClient, LLMRouter, LLMResponse, SamplingParams, TokenUsage
from liteagent.tool import tool, ToolDef, ToolRegistry, ToolResult
from liteagent.agent import run_agent, AgentConfig, AgentResult
from liteagent.pipeline import merge_state, run_parallel, loop_until, run_with_retry_loop
from liteagent.state import dedup_by_key, count_by, snapshot
from liteagent.context import truncate, TokenBudget, ContextBuilder
from liteagent.observe import CallLog, Reporter, NullReporter
from liteagent.parse import extract_json, parse_llm_json, strip_thinking, validate_items
from liteagent.errors import retry, with_fallback, NodeError

__all__ = [
    # LLM
    "LLMClient", "LLMRouter", "LLMResponse", "SamplingParams", "TokenUsage",
    # Tools
    "tool", "ToolDef", "ToolRegistry", "ToolResult",
    # Agent (tool-loop)
    "run_agent", "AgentConfig", "AgentResult",
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
]
```

### 4.5 Dependency Footprint

| Dependency | Required? | Why |
|---|---|---|
| `openai` | Yes | LLM client (OpenAI-compatible protocol) |
| `pydantic` | No | Optional, for schema validation in tools. Framework works without it. |
| Python stdlib | Yes | `concurrent.futures`, `json`, `re`, `dataclasses`, `typing`, `time`, `pathlib` |

**Total: 1 required external dependency.** Compare: LangChain pulls ~300MB of transitive dependencies.

### 4.6 What the Framework Deliberately Omits

| Feature | Why Omitted | When to Add |
|---|---|---|
| Graph DSL | Plain Python functions are clearer and more debuggable | Never — this is a design choice |
| Prompt templates | Domain-specific; no generic abstraction adds value | Never — prompts live in task code |
| Streaming | Not needed for batch pipelines; adds complexity | When building interactive agents |
| Permission system | Not needed until you have untrusted tools | When building user-facing agents |
| Context compression | Only needed for very long conversations | When agent conversations exceed 100K tokens |
| Checkpointing/persistence | Only needed for long-running or resumable pipelines | When pipelines take hours or must survive crashes |
| Multi-model routing | `LLMRouter` handles this; no separate system needed | Already included |
| Async/await | ThreadPoolExecutor is simpler for I/O-bound LLM calls | When you need 10+ concurrent LLM calls |

---

## 5. Part 2: SFEWA Task-Specific Code

### 5.1 What Stays in SFEWA

Everything domain-specific:

```
sfewa/
├── main.py                    # CLI entry point (Typer)
├── reporting.py               # Rich terminal reporter (implements liteagent.Reporter)
├── context.py                 # Domain-specific ContextBuilder sections
│
├── agents/                    # All 10 pipeline nodes
│   ├── init_case.py           # Case expansion (uses liteagent.parse_llm_json)
│   ├── retrieval.py           # 3-pass agentic retrieval (uses liteagent.CallLog)
│   ├── evidence_extraction.py # LLM extraction + temporal filter
│   ├── quality_gate.py        # Evidence sufficiency gate
│   ├── _analyst_base.py       # Shared analyst logic
│   ├── industry_analyst.py    # Thin wrapper
│   ├── company_analyst.py     # Thin wrapper
│   ├── peer_analyst.py        # Thin wrapper
│   ├── adversarial.py         # Independent evaluator
│   ├── risk_synthesis.py      # Scoring + LLM synthesis
│   └── backtest.py            # Ground truth matching
│
├── prompts/                   # All prompt templates (unchanged)
│   ├── init_case.py
│   ├── retrieval.py
│   ├── extraction.py
│   ├── analysis.py
│   ├── adversarial.py
│   └── synthesis.py
│
├── schemas/                   # Domain types (unchanged)
│   ├── config.py              # CaseConfig, GroundTruthEvent
│   ├── state.py               # PipelineState TypedDict
│   └── evidence.py            # EvidenceItem, RiskFactor, etc.
│
├── tools/                     # Domain tools
│   ├── edinet.py              # EDINET API client
│   ├── corpus_loader.py       # PDF loading
│   └── temporal_filter.py     # Date utils (could move to liteagent)
│
└── pipeline.py                # Pipeline orchestration (uses liteagent.pipeline utilities)
```

### 5.2 How SFEWA Uses liteagent

**Before (current)**:
```python
# sfewa/agents/evidence_extraction.py — current
import json, re
from sfewa.llm import get_llm_for_role
from sfewa.tools.chat_log import log_llm_call

def evidence_extraction_node(state):
    llm = get_llm_for_role("extraction")
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": usr}]
    response = llm.invoke(messages)
    log_llm_call("extraction", messages, response)

    # Manual JSON extraction (duplicated in 6 agents)
    text = re.sub(r"<think>.*?</think>", "", response.content, flags=re.DOTALL)
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if match:
        data = json.loads(match.group(1))
    else:
        data = json.loads(text)
    ...
```

**After (with liteagent)**:
```python
# sfewa/agents/evidence_extraction.py — after
from liteagent import parse_llm_json, validate_items

def evidence_extraction_node(state, *, llm, log):
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": usr}]
    data, response = parse_llm_json(llm, messages)  # handles JSON extraction + retry
    log.log_llm_call("extraction", messages, response)

    items = validate_items(
        data.get("evidence_items", []),
        required_fields=["evidence_id", "claim", "published_at"],
    )
    ...
```

**Key changes**:
- `parse_llm_json()` replaces 6 separate JSON extraction implementations
- `validate_items()` replaces 6 separate `_validate_*` functions
- `CallLog` instance passed in (not global) — testable, supports concurrent runs
- `LLMClient` instance passed in (not fetched from module-level cache) — configurable, testable

### 5.3 Pipeline Orchestration

**Before**:
```python
# sfewa/graph/pipeline.py — current (46 lines of custom merge + loop logic)
ACCUMULATING_FIELDS = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

def merge_state(state, updates):
    for key, value in updates.items():
        if key in ACCUMULATING_FIELDS and isinstance(value, list):
            state.setdefault(key, []).extend(value)
        else:
            state[key] = value
    return state
```

**After**:
```python
# sfewa/pipeline.py — after
from liteagent import merge_state, run_parallel, loop_until

ACC = {"evidence", "risk_factors", "adversarial_challenges", "backtest_events"}

def run_pipeline(state: dict) -> dict:
    state = merge_state(state, init_case(state), accumulate=ACC)

    state = loop_until(
        state,
        steps=[retrieval, extraction, quality_gate],
        done=lambda s: s.get("evidence_sufficient", True),
        max_iterations=3,
        accumulate=ACC,
    )

    for r in run_parallel([industry, company, peer], state):
        state = merge_state(state, r, accumulate=ACC)

    # Adversarial loop
    for _ in range(MAX_ADVERSARIAL_PASSES):
        state = merge_state(state, adversarial(state), accumulate=ACC)
        if state.get("adversarial_recommendation") != "reanalyze":
            break
        state = merge_state(state, extraction(state), accumulate=ACC)
        for r in run_parallel([industry, company, peer], state):
            state = merge_state(state, r, accumulate=ACC)

    state = merge_state(state, synthesis(state), accumulate=ACC)
    state = merge_state(state, backtest(state), accumulate=ACC)
    return state
```

The pipeline remains a readable function. `liteagent` provides the building blocks; SFEWA composes them.

### 5.4 Dependency Injection Pattern

The biggest structural change: agents receive their dependencies instead of importing globals.

**Before** (current SFEWA pattern):
```python
# Every agent imports module-level globals
from sfewa.llm import get_llm_for_role           # module-level cache
from sfewa.tools.chat_log import log_llm_call     # module-level global list

def quality_gate_node(state):
    llm = get_llm_for_role("quality_gate")  # hidden dependency
    ...
    log_llm_call("quality_gate", ...)       # writes to global list
```

**After** (dependency injection):
```python
# Dependencies passed via a context object
from dataclasses import dataclass
from liteagent import LLMRouter, CallLog, Reporter, NullReporter

@dataclass
class PipelineContext:
    """Shared dependencies for all pipeline nodes."""
    llm_router: LLMRouter
    log: CallLog
    reporter: Reporter = field(default_factory=NullReporter)

def quality_gate_node(state: dict, ctx: PipelineContext) -> dict:
    llm = ctx.llm_router.get("quality_gate")
    ...
    ctx.log.log_llm_call("quality_gate", ...)
    ctx.reporter.log_action("Evidence gate", {"sufficient": True})
```

**Why this matters**:
- **Testable**: Pass a mock LLM and NullReporter in tests — no module-level state to reset
- **Concurrent**: Each pipeline run gets its own `CallLog` — no global list collision
- **Configurable**: Swap LLM providers, enable/disable reporting, all at construction time

---

## 6. Migration Plan

### Phase 1: Extract liteagent (standalone package)

1. Create `liteagent/` package with the 8 modules described above
2. Write unit tests for each module (~60 tests)
3. Publish as a separate installable package (or local path dependency)
4. **No changes to SFEWA yet** — both codebases exist independently

### Phase 2: Migrate SFEWA to use liteagent

1. Replace `sfewa/llm.py` → `liteagent.LLMClient` + `liteagent.LLMRouter`
2. Replace `sfewa/tools/chat_log.py` → `liteagent.CallLog`
3. Replace manual JSON parsing in all agents → `liteagent.parse_llm_json`
4. Replace `sfewa/graph/pipeline.py` merge/parallel → `liteagent.pipeline`
5. Add `PipelineContext` for dependency injection
6. Move `sfewa/graph/pipeline.py` → `sfewa/pipeline.py` (the graph/ directory was a LangGraph artifact)
7. Delete `sfewa/graph/` directory
8. Run all 51 tests + cross-company validation

### Phase 3: Clean up documentation

1. Update CLAUDE.md to reflect the new architecture
2. Update architecture.md
3. Remove LangGraph references from iteration_log.md
4. Add liteagent README with usage examples

### Risk Mitigation

- Each phase is independently deployable
- Phase 2 changes are refactors only — no behavior change
- Cross-company validation (Honda/Toyota/BYD) gates each phase
- Old code preserved in git history

---

## 7. Appendix: Anti-Patterns Reference

Patterns to avoid in liteagent, learned from LangChain/LangGraph/deepagents failures:

| Anti-Pattern | Example | Why It Fails | liteagent Alternative |
|---|---|---|---|
| **Abstraction inversion** | LangChain wraps `openai.chat.completions.create()` in 5 layers | Simple operations shouldn't need complex wrappers | `LLMClient.call()` is one function call over `client.chat.completions.create()` |
| **Implicit state mutation** | LangGraph `operator.add` silently accumulates lists | Deduplication bugs, exponential growth | Explicit `accumulate=` parameter on `merge_state()` |
| **Hidden LLM calls** | LangChain agents making internal LLM calls users don't see | Cost surprises, debugging blind spots | Every LLM call is explicit in user code, logged by `CallLog` |
| **Framework-specific types** | `HumanMessage`, `AIMessage`, `SystemMessage` | Don't compose with standard tools (json.dumps, etc.) | Plain dicts: `{"role": "user", "content": "..."}` |
| **Configuration over code** | LangGraph graph DSL that compiles to a runtime | Can't set breakpoints, can't add conditional logic easily | Pipeline is a Python function — use `if/for/while` |
| **Middleware stacking** | deepagents' 8-layer middleware with hidden behavior | Each layer adds opacity; debugging requires understanding all layers | No middleware. Hooks are explicit callbacks passed by the caller. |
| **God abstractions** | `Runnable`, `RunnableSequence`, `RunnableParallel` | Everything is a Runnable but the abstraction leaks everywhere | Separate functions for separate concerns: `merge_state`, `run_parallel`, `loop_until` |
| **Vendor-locked observability** | LangSmith required for basic debugging | Debugging requires a paid service | `CallLog.save_jsonl()` — analyze with any tool |

---

## Summary

| Dimension | LangChain | LangGraph | deepagents | **liteagent** |
|---|---|---|---|---|
| Core abstraction | Runnable chains | State graph | Middleware stack | **Utility functions** |
| State model | Framework messages | Annotated reducers | LangChain messages | **Plain dicts** |
| Routing | LangChain Agent | Graph edges | LangGraph routes | **Python if/for/while** |
| Observability | LangSmith | LangSmith | LangSmith | **CallLog (JSONL)** |
| Dependencies | ~300MB | ~200MB | ~300MB (LangChain) | **~5MB (openai only)** |
| Lines of code | 100K+ | 30K+ | 11K+ | **~1000** |
| Escape hatch | Difficult | Moderate | Difficult | **Always available** |
| Learning curve | Steep (abstractions) | Moderate (graph concepts) | Steep (LangChain + middleware) | **Minimal (it's just Python)** |

The framework's value proposition: **Everything you need, nothing you don't. When in doubt, leave it out.**
