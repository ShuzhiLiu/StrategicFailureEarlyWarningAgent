# liteagent Architecture

A minimal agent framework: 8 modules, ~800 lines, 1 external dependency.
Provides utilities for building LLM-powered pipelines in plain Python.

---

## 1. Design Philosophy

### Utilities, Not a Runtime

liteagent provides building blocks -- you compose them in plain Python functions. There is no graph DSL, no declarative config, no framework-owned execution loop. Your pipeline is a function you write and can read top-to-bottom.

```python
def my_pipeline(state):
    state = merge_state(state, step_1(state))
    state = loop_until(state, [step_2, step_3], done_check, max_iterations=3)
    for r in run_parallel([step_4a, step_4b], state):
        state = merge_state(state, r)
    return state
```

### Why Not LangChain / LangGraph

| Problem | LangChain/LangGraph | liteagent |
|---|---|---|
| Abstraction inversion | 5 layers to wrap `openai.chat.completions.create()` | 1 layer: `LLMClient.call()` |
| Implicit state mutation | `Annotated[list, operator.add]` causes silent dedup bugs | Explicit `accumulate=` param on `merge_state()` |
| Hidden LLM calls | Framework makes internal calls users can't see | Every LLM call is in your code |
| Framework-specific types | `HumanMessage`, `AIMessage` don't compose with stdlib | Plain dicts: `{"role": "user", "content": "..."}` |
| Debugging | 50+ frame stack traces through Runnable internals | Your function, your stack trace |
| Vendor-locked observability | LangSmith required for basic debugging | `CallLog.save_jsonl()` -- analyze with any tool |

### Learned from Claude Code

Claude Code's agent is a `while(tool_call)` loop -- ~65 lines of core logic. The 512K lines exist for production hardening (error recovery, context overflow, streaming). liteagent takes the same approach: the core is trivial, the value is in well-tested utilities that handle the messy edges.

Key patterns adopted from Claude Code:

| Pattern | Claude Code | liteagent |
|---|---|---|
| Messages as state | Append-only message array | Plain dict state (pipelines) or message array (tool-loop) |
| Errors as data | Tool failures become tool results | `NodeError` dataclass, `on_error` callbacks |
| Progressive truncation | 4-level context compression | `truncate()` with middle-cut preservation |
| Pipeline context injection | TODO state injected after every tool use | `ContextBuilder` composes upstream summaries |
| Dead-loop protection | Max iterations as safety bounds | `max_iterations` param on all loop utilities |
| Fail-closed defaults | New tools unsafe until marked safe | `on_error` defaults to raising, not swallowing |

---

## 2. Module Map

```
liteagent/
  __init__.py       Public API (18 symbols)
  llm.py            LLM client + provider routing
  pipeline.py       Pipeline composition utilities
  state.py          State dict helpers
  context.py        Context window management
  observe.py        Call logging + reporter protocol
  parse.py          Structured output extraction
  errors.py         Retry + fallback strategies
```

### Dependency Graph

```
parse.py -----> llm.py -----> openai (sole external dep)
                  ^
pipeline.py     |  (no framework deps)
state.py        |  (stdlib only)
context.py      |  (stdlib only)
observe.py      |  (stdlib only)
errors.py       |  (stdlib only)
```

Only `llm.py` and `parse.py` import `openai`. Every other module is pure stdlib Python.

---

## 3. Module Details

### 3.1 `llm.py` -- LLM Client

**Purpose**: Provider-agnostic LLM access via the OpenAI-compatible protocol.

**Types**:
- `LLMResponse` -- Frozen dataclass normalizing all provider quirks. Fields: `content`, `thinking` (for reasoning models), `usage` (TokenUsage), `raw` (escape hatch to original API response).
- `TokenUsage` -- Frozen dataclass: `prompt_tokens`, `completion_tokens`, `total_tokens`.
- `SamplingParams` -- Frozen dataclass: `temperature`, `max_tokens`, `top_p`, `extra_body`.

**Classes**:

```python
class LLMClient:
    """Thin wrapper around OpenAI SDK."""

    def __init__(self, model, base_url, api_key="not-needed", sampling=None): ...
    def call(self, messages, *, sampling=None) -> LLMResponse: ...
    def invoke(self, messages) -> LLMResponse: ...  # alias for call()
    @property
    def client(self) -> OpenAI: ...  # escape hatch
```

`LLMClient` wraps exactly one thing: `client.chat.completions.create()` + response normalization. The `_normalize()` method handles vLLM's `reasoning_content` attribute (where `<think>` blocks are placed when using `--reasoning-parser`).

```python
class LLMRouter:
    """Maps role names to LLMClient instances."""

    def __init__(self, clients, role_map, default="default"): ...
    def get(self, role) -> LLMClient: ...
```

`LLMRouter` is the generic version of SFEWA's `get_llm_for_role()` pattern. Configure once, use everywhere. Useful when different pipeline nodes need different models or sampling configs (e.g., thinking mode for evaluators, fast mode for extractors).

**Design decisions**:
- Frozen dataclasses for `LLMResponse`, `TokenUsage`, `SamplingParams` -- immutable, IDE-friendly, no accidental mutation.
- `raw` field on `LLMResponse` -- escape hatch to the original API response when normalization isn't enough.
- No retry logic here -- that's in `errors.py` (separation of concerns).
- No streaming -- add as `call_stream()` when needed.

---

### 3.2 `pipeline.py` -- Pipeline Composition

**Purpose**: Building blocks for multi-step pipelines with parallel execution and LLM-driven loops.

**Functions**:

```python
def merge_state(state, updates, *, accumulate=None) -> dict:
    """Apply node output to state. Accumulating fields extend; others overwrite."""

def run_parallel(nodes, state, *, max_workers=None, on_error=None) -> list[dict]:
    """Run nodes in parallel via ThreadPoolExecutor. Each gets a state copy."""

def loop_until(state, steps, done, *, max_iterations=3, accumulate=None) -> dict:
    """Run steps in a loop until done() returns True. Safety-bounded."""

def run_with_retry_loop(state, generate, evaluate, should_retry, *, max_passes=2) -> dict:
    """Generator-evaluator loop: generate, evaluate, retry if needed."""
```

**Key pattern -- explicit accumulation**:

LangGraph uses `Annotated[list, operator.add]` to declare accumulating fields in the type system. This is implicit -- you discover the behavior when dedup bugs appear. liteagent makes accumulation explicit at every call site:

```python
# Explicit: you see accumulation at the call site
state = merge_state(state, node(state), accumulate={"evidence", "risk_factors"})

# vs LangGraph implicit: accumulation declared far away in the state schema
class State(TypedDict):
    evidence: Annotated[list, operator.add]  # silently accumulates everywhere
```

**Key pattern -- isolated parallel execution**:

`run_parallel()` passes `dict(state)` (shallow copy) to each node. Nodes cannot interfere with each other's state. Results are collected and merged by the caller -- the caller decides accumulation semantics, not the framework.

**Key pattern -- loop utilities encode agentic patterns**:

- `loop_until()` = quality gate pattern (gather info, check sufficiency, loop)
- `run_with_retry_loop()` = generator-evaluator pattern (produce, critique, retry)

Both accept `max_iterations` / `max_passes` as safety bounds. The LLM makes the routing decision; the counter is a backstop.

---

### 3.3 `state.py` -- State Helpers

**Purpose**: Common operations on pipeline state dicts, extracted from patterns that were duplicated across multiple agents.

```python
def dedup_by_key(items, key, *, keep="last") -> list[dict]:
    """Deduplicate list of dicts by a field. Solves the loop-accumulation dedup problem."""

def count_by(items, field) -> dict[str, int]:
    """Count items grouped by field value. E.g., count_by(evidence, 'stance')."""

def ensure_field(state, field, default) -> Any:
    """Get-or-set-default for state fields."""

def snapshot(state, exclude=None) -> dict:
    """Shallow copy excluding large fields (for logging)."""
```

`dedup_by_key()` deserves special attention: when a pipeline loops (quality gate retries, adversarial re-analysis), accumulating fields grow with duplicates. The pattern "keep latest per dimension" was implemented 4 separate times in SFEWA's agents. This function extracts it.

---

### 3.4 `context.py` -- Context Window Management

**Purpose**: Prevent context overflow and inject pipeline history into prompts.

```python
def truncate(text, max_chars=50_000, *, keep_ends=True) -> str:
    """Middle-cut truncation preserving both start and end.
    Claude Code pattern: important info lives at both ends of tool output."""

class TokenBudget:
    """Track token usage against a budget. Fires should_compress at 85%."""

class ContextBuilder:
    """Compose pipeline context summaries from registered section builders."""
```

`ContextBuilder` is the generic version of pipeline context injection. Register section builders (functions that take state and return a summary string), then `build(state)` composes them:

```python
ctx = ContextBuilder("PIPELINE CONTEXT:")
ctx.add_section("retrieval", lambda s: f"Retrieved {len(s.get('docs', []))} documents")
ctx.add_section("evidence", lambda s: f"Extracted {len(s.get('evidence', []))} items")
prompt = f"{ctx.build(state)}\n\n{system_prompt}"
```

---

### 3.5 `observe.py` -- Observability

**Purpose**: Record all LLM and tool interactions for debugging. No external services.

```python
class CallLog:
    """Accumulates LLMCallRecord and ToolCallRecord instances."""
    def log_llm_call(self, node, messages, response, *, label=""): ...
    def log_tool_call(self, node, tool_name, inputs, output, *, label=""): ...
    def save_jsonl(self, path): ...
    def to_dicts(self) -> list[dict]: ...
    def total_tokens(self) -> int: ...

class Reporter(Protocol):
    """Pluggable runtime reporting (Rich terminal, JSON stream, silent)."""
    def enter_node(self, node_name, summary=None): ...
    def log_action(self, action, details=None): ...
    def exit_node(self, node_name, output=None): ...

class NullReporter:
    """Silent reporter for tests and batch processing."""
```

**Design decisions**:
- `CallLog` is an instance, not a module-level global -- supports concurrent pipeline runs and clean testing.
- `Reporter` is a Protocol -- implement with any library (Rich, plain print, JSON). No base class to inherit.
- `log_llm_call()` normalizes diverse response objects (LLMResponse, raw strings, objects with `response_metadata`) -- backward compatible with multiple calling conventions.
- `save_jsonl()` -- vendor-free observability. Analyze with `jq`, pandas, or any JSON tool.

---

### 3.6 `parse.py` -- Structured Output Parsing

**Purpose**: Extract JSON from LLM output, handling all common formats.

```python
def extract_json(text) -> Any:
    """Handles: raw JSON, markdown ```json blocks, <think> prefixes, nested brackets."""

def strip_thinking(text) -> str:
    """Remove <think>...</think> blocks."""

def parse_llm_json(llm, messages, *, max_retries=1) -> tuple[Any, LLMResponse]:
    """Call LLM, parse JSON, retry with error feedback on failure."""

def validate_items(items, required_fields, *, on_invalid=None) -> list[dict]:
    """Keep only items with all required fields present."""
```

`parse_llm_json()` encapsulates the most common agent pattern: call LLM expecting JSON, parse it, and if parsing fails, append the error to the conversation and retry. This pattern was implemented separately in 6+ agents before extraction.

`extract_json()` handles the full spectrum of LLM output quirks:
1. Clean JSON (starts with `{` or `[`)
2. Markdown code blocks (` ```json ... ``` `)
3. `<think>...</think>` prefix (thinking models)
4. Trailing text after JSON
5. Array-first detection (tries `[` before `{` when array appears first)
6. Bracket-matching fallback for malformed responses

---

### 3.7 `errors.py` -- Error Handling

**Purpose**: Retry strategies and structured errors.

```python
@dataclass
class NodeError:
    """Structured error: node returns this instead of raising."""
    node: str; error_type: str; message: str; recoverable: bool = True

def retry(fn, *args, max_attempts=3, backoff_base=1.0, retry_on=(Exception,)) -> T:
    """Exponential backoff + jitter. Re-raises after exhausting attempts."""

def with_fallback(primary, fallback, *args, catch=(Exception,)) -> T:
    """Try primary, fall back on failure."""
```

---

## 4. Patterns Encoded in liteagent

### Pattern 1: Explicit State Accumulation

**Problem**: Pipeline loops create duplicates in accumulating fields.

**Solution**: `merge_state()` with explicit `accumulate=` + `dedup_by_key()` for post-loop cleanup.

```python
ACC = {"evidence", "risk_factors"}

for _ in range(max_iter):
    state = merge_state(state, node(state), accumulate=ACC)
    if done(state): break

# Clean up loop-induced duplicates
state["risk_factors"] = dedup_by_key(state["risk_factors"], "dimension")
```

### Pattern 2: LLM-Driven Routing with Safety Bounds

**Problem**: Hardcoded routing is not agentic. Unbounded LLM routing risks infinite loops.

**Solution**: LLM sets a state field, routing function reads it, `max_iterations` is the backstop.

```python
# LLM decides (inside the node):
state["evidence_sufficient"] = llm_says_sufficient

# Routing reads the decision:
state = loop_until(
    state, steps=[retrieve, extract, gate],
    done=lambda s: s.get("evidence_sufficient", True),
    max_iterations=3,  # safety bound only
)
```

### Pattern 3: Separated Evaluation

**Problem**: Generators cannot reliably self-evaluate (Anthropic's key insight).

**Solution**: `run_with_retry_loop()` structurally separates generation from evaluation.

```python
state = run_with_retry_loop(
    state,
    generate=analysts,       # produces risk factors
    evaluate=adversarial,    # challenges them independently
    should_retry=lambda s: s.get("recommendation") == "reanalyze",
    max_passes=2,
)
```

### Pattern 4: Pipeline Context Injection

**Problem**: Downstream nodes don't know what happened upstream.

**Solution**: `ContextBuilder` composes summaries, injected into system prompts.

```python
ctx = ContextBuilder("PIPELINE CONTEXT:")
ctx.add_section("retrieval", summarize_retrieval)
ctx.add_section("evidence", summarize_evidence)
# Inject into any node's prompt:
system_prompt = f"{ctx.build(state)}\n\n{node_specific_prompt}"
```

### Pattern 5: Parse-Retry Loop

**Problem**: LLMs produce malformed JSON. Each agent reimplements parse+retry.

**Solution**: `parse_llm_json()` handles the full cycle.

```python
data, response = parse_llm_json(llm, messages, max_retries=1)
items = validate_items(data["items"], required_fields=["id", "content"])
```

---

## 5. What liteagent Deliberately Omits

| Feature | Why Omitted | Add When |
|---|---|---|
| Graph DSL | Plain Python is clearer and more debuggable | Never |
| Prompt templates | Domain-specific; no generic abstraction adds value | Never |
| Tool-loop agent | Not needed for pipeline-style agents; easy to add | When building interactive tool-calling agents |
| Streaming | Not needed for batch pipelines | When building interactive agents |
| Async/await | ThreadPoolExecutor suffices for I/O-bound LLM calls | When running 10+ concurrent LLM calls |
| Checkpointing | Only needed for long-running resumable pipelines | When pipelines take hours |
| Permission system | Only needed for user-facing agents with untrusted tools | When exposing tools to end users |

---

## 6. Dependency Footprint

| Dependency | Required | Purpose |
|---|---|---|
| `openai` | Yes | LLM client (OpenAI-compatible protocol covers vLLM, Anthropic, Gemini) |
| Python 3.11+ stdlib | Yes | `concurrent.futures`, `json`, `re`, `dataclasses`, `typing`, `pathlib` |
| `pydantic` | No | Optional, for tool schema validation. Framework works without it. |

**Total: 1 required external dependency.** Installs in seconds, not minutes.
