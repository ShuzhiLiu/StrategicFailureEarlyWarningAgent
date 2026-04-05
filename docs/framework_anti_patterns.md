# What NOT to Do: Lessons from LangChain, LangGraph, and DeepAgents

A critical analysis of design failures in agent frameworks, drawn from production experience reports (2023-2026), community critiques, and source code analysis. This informs what a lite framework should avoid.

---

## 1. LangChain's Core Design Problems

### 1.1 Abstraction Inversion

**The problem**: LangChain wraps simple operations (API calls, string formatting, list operations) in complex class hierarchies, then forces users to unwrap those abstractions to do anything non-trivial.

**Concrete example**: A translation call.

```python
# Direct OpenAI SDK: 4 lines
response = client.chat.completions.create(
    model="gpt-4", messages=[{"role": "user", "content": f"Translate: {text}"}]
)
result = response.choices[0].message.content

# LangChain: 3 classes, 4 function calls, hidden prompt template
from langchain.prompts import ChatPromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
prompt = ChatPromptTemplate.from_template("Translate: {text}")
chain = LLMChain(llm=ChatOpenAI(), prompt=prompt)
result = chain.run(text=text)
```

The LangChain version adds `ChatPromptTemplate`, `LLMChain`, and internal message conversion -- all to do string interpolation and an HTTP POST. When the user needs to access token usage metadata, add retry logic, or inspect the raw request, they must dig through 5+ layers of abstraction.

**Design principle violated**: **Don't wrap what isn't complex.** Abstractions should reduce complexity, not redistribute it. If the abstracted version has more concepts than the raw version, the abstraction is negative-value.

### 1.2 Hidden Token and Cost Overhead

**The problem**: LangChain's internal chain types make undisclosed LLM calls that multiply token consumption.

**Measured example** (from a production RAG system):
- Manual OpenAI SDK: 487 tokens, $0.015
- LangChain `RetrievalQA` with `chain_type="refine"`: 1,017 tokens, $0.039
- **2.7x cost multiplier**

Root causes:
1. The "refine" chain makes sequential LLM calls (4 calls for 3 document chunks), each including the full prompt + previous context. Compounding token accumulation.
2. `OpenAIEmbeddings` defaults to batching 1,000 texts when the API supports 2,048 -- doubling API calls.
3. Hidden internal operations: prompt formatting, retry logic, chain validation, memory management -- all consuming tokens or making extra API calls invisibly.
4. Pre-built agents embed ~800 tokens of system instructions per turn, silently inflating every request.

The `get_openai_callback()` cost tracker was itself broken -- GitHub issues documented it reporting $0.00 while the actual OpenAI balance decreased by $18.24.

**Design principle violated**: **No hidden resource consumption.** Every LLM call, every token, every API request must be visible and auditable. If the framework makes LLM calls the user didn't ask for, the framework is stealing money.

### 1.3 Leaky Abstraction Syndrome

**The problem**: LangChain's abstractions are only useful for the exact happy path they were designed for. Any deviation requires understanding the internals anyway, making the abstraction worse than useless (it adds overhead without reducing complexity).

**Concrete examples**:
- **Conversation history**: Retrieving history requires `RunnableWithMessageHistory` -- described by one developer as "wicked dark magic." A mandatory `session_id` parameter is required even when unnecessary. The simpler approach: pass a list of dicts.
- **Structured output**: Adding structured output requires creating a custom `StructuredResponseTool` class, and "once this is done, it's not possible to bind any more tools." The framework's own constraint forces workarounds.
- **Dynamic tool availability**: Changing which tools an agent can access based on business logic was not supported. The team had to remove LangChain entirely to implement this basic requirement.
- **Agent state observation**: "LangChain does not provide a method for externally observing an agent's state." The framework hides the very information you need to debug and monitor.

**Design principle violated**: **Abstractions must be escapable.** Every layer must expose its internals cleanly. If you need to read framework source code to do something the framework "supports," the abstraction has failed.

### 1.4 Version Instability and Breaking Changes

**The problem**: Frequent interface changes eroded production trust.

- Even minor updates broke existing functionality
- Mock objects in tests failed constantly due to internal interface changes
- Teams maintained multiple service instances for different LangChain versions
- The framework reached "version 0.1.0" (first "stable" release) only in January 2024, after 2 years of production use by early adopters

**Design principle violated**: **Stable public interfaces are non-negotiable.** Breaking changes in a framework cascade to every project that uses it. Semantic versioning must be real, not aspirational.

### 1.5 Dependency Bloat

**The problem**: Basic features pull in dozens of transitive dependencies.

- Package size: ~300MB vs PydanticAI's ~70MB
- Docker images bloated by unused integrations (dozens of vector DB connectors, model providers)
- Installing LangChain for a simple RAG system imports support for services you never use

**Design principle violated**: **Minimal dependency surface.** A framework should have a core with zero or near-zero dependencies beyond the standard library, with integrations as optional extras.

### 1.6 Debugging is Archaeology

**The problem**: Stack traces span 50+ frames across abstraction layers. When something goes wrong, developers spend time stepping through LangChain wrapper code instead of their own logic.

- "We were spending as much time understanding and debugging LangChain as building features."
- Observability required adopting LangSmith (their commercial SaaS) -- basic logging was insufficient.
- "You can't unit test when everything's buried in nested abstractions."
- One production team used LangChain for 12+ months before removing it entirely in 2024.

**Design principle violated**: **Errors must surface at the right level.** Framework errors should tell the user what went wrong in their terms, not in framework internals. Stack traces should not require framework expertise to read.

---

## 2. LangGraph's Problems (Separate from LangChain)

LangGraph is a better design than LangChain -- it provides explicit state management and graph-based control flow. But it introduces its own problems.

### 2.1 Implicit State Reducer Behavior

**The problem**: `Annotated[list, operator.add]` seems simple but has surprising failure modes in production.

**Concrete issues from production**:
- **Exponential duplication**: When tools update state via `Command(update=...)`, the state accumulates exponentially instead of flat-merging. Each tool update wraps previous state in a new array.
- **Silent last-writer-wins**: Without a reducer, concurrent writes silently overwrite. With a reducer, the merge behavior depends on which reducer you chose -- and the wrong choice produces silently corrupt state.
- **Concurrent write errors**: `INVALID_CONCURRENT_GRAPH_UPDATE` when multiple parallel nodes write to the same key without a reducer. The fix (adding `operator.add`) then causes the duplication problems above.

**From our own SFEWA experience** (Iteration 11 in the log):
```
# Risk factors use operator.add (accumulates across passes)
# When adversarial loop-back triggers re-analysis, analysts produce DUPLICATE factors
# Fix required: manual deduplication by dimension (latest factor per dimension wins)
```

The framework provides accumulation but not deduplication. Every project using fan-out with loop-back must implement its own deduplication -- a common, predictable need that the framework ignores.

**Design principle violated**: **State management must be predictable.** If a framework offers concurrent state writes, it must make the merge semantics explicit, visible, and testable -- not something you discover through production bugs.

### 2.2 Graph Overhead for Simple Workflows

**The problem**: LangGraph requires explicit graph construction even for simple linear flows, adding ~75% more code than direct alternatives.

**Measured**: Same chat application across frameworks:
- PydanticAI: ~160 lines
- LangChain: ~170 lines
- LangGraph: ~280 lines
- CrewAI: ~420 lines

For a linear "retrieve then generate" pipeline, LangGraph requires defining nodes, edges, conditional routing functions, state schema with reducers, and graph compilation -- when a `for` loop would suffice.

**Design principle violated**: **Complexity should be proportional to the problem.** A framework for complex multi-agent systems should not tax simple sequential workflows. Provide a simple path for simple problems.

### 2.3 Distributed Systems Expertise Required

**The problem**: Parallel workflows, fan-out/fan-in, and state synchronization require expertise in distributed systems concepts. Teams unfamiliar with these concepts face extended debugging sessions, memory leaks, and subtle race conditions.

LangGraph doesn't hide this complexity (which is honest), but it also doesn't provide guardrails. The fan-out with `Send` API is powerful but unforgiving -- concurrent writes to non-reducer fields crash, and debugging state transitions across parallel branches requires tracing tools (LangSmith) that add yet another dependency.

**Design principle violated**: **Provide progressive complexity.** Simple agents should be simple. Complex agents should be possible. The jump from one to the other should be gradual, not a cliff.

### 2.4 Message Format Lock-In

**The problem**: LangGraph requires LangChain message types (`HumanMessage`, `AIMessage`, `ToolMessage`, `SystemMessage`) throughout. Any integration with non-LangChain systems requires conversion code.

The `_convert_history()` pattern (translating between standard dicts and LangChain messages) appears in nearly every LangGraph project that interacts with external systems.

**Design principle violated**: **Use standard data formats.** Messages should be plain dicts or dataclasses that match the OpenAI message format (the de facto standard). Framework-specific message types create unnecessary coupling.

---

## 3. What DeepAgents Tries to Fix and Whether It Succeeds

DeepAgents (github.com/langchain-ai/deepagents, v0.5.0-alpha) is LangChain's official response to Claude Code. It's a "batteries-included agent harness" -- an opinionated, ready-to-run agent with planning, filesystem access, shell execution, and sub-agents built in.

### 3.1 What It Gets Right

**Pattern: Claude Code as reference architecture.** The README explicitly acknowledges: "This project was primarily inspired by Claude Code, and initially was largely an attempt to see what made Claude Code general purpose."

The four elements it identifies as key (planning tool, sub-agents, filesystem access, detailed prompt) are correct. The `BASE_AGENT_PROMPT` is well-written -- concise, direct, anti-preamble.

**Pattern: Middleware for cross-cutting concerns.** The middleware architecture (wrap every LLM call, inject system prompts, filter tools dynamically) is a sound pattern. It separates concerns that would otherwise be tangled in application code: summarization, memory loading, tool filtering, prompt caching.

**Pattern: Backend protocol abstraction.** `BackendProtocol` (read, write, edit, ls, grep, glob) with multiple implementations (state, filesystem, sandbox, LangSmith) is genuinely useful. File operations are a real cross-cutting concern that benefits from abstraction.

**Pattern: Eval-driven development.** 85 evals across 7 categories (file ops, retrieval, tool use, memory, etc.) is the right approach. Testing agent behavior, not just unit correctness.

### 3.2 What It Gets Wrong

**Problem: It's still LangChain all the way down.** Dependencies:

```toml
dependencies = [
    "langchain-core>=1.2.21,<2.0.0",
    "langsmith>=0.3.0",
    "langchain>=1.2.15,<2.0.0",
    "langchain-anthropic>=1.4.0,<2.0.0",
    "langchain-google-genai>=4.2.1,<5.0.0",
    "wcmatch",
]
```

You cannot use DeepAgents without LangChain, LangGraph, LangSmith, and two provider-specific packages. The 11,696 lines of SDK code are built entirely on LangChain primitives (`BaseChatModel`, `BaseTool`, `StructuredTool`, `AgentMiddleware`, `AgentState`). This is not a fix for LangChain's problems -- it's another layer on top.

**Problem: Complexity accumulation, not reduction.** The `create_deep_agent()` function signature has 14 parameters. The middleware stack is 8 layers deep by default:

```
TodoList -> Memory -> Skills -> Filesystem -> SubAgent ->
AsyncSubAgent -> Summarization -> PromptCaching -> PatchToolCalls
```

Each middleware can inject system prompts, filter tools, transform messages, and maintain cross-turn state. When something goes wrong, you must understand all 8 layers, plus the LangGraph runtime, plus the LangChain message system. The debugging archaeology problem from LangChain is not solved -- it's deepened.

**Problem: Anthropic-first, not model-agnostic.** Default model is `claude-sonnet-4-6`. `AnthropicPromptCachingMiddleware` is in the default stack for every agent, including subagents. `langchain-anthropic` is a required dependency. The README claims "provider agnostic" but the defaults, middleware, and dependency list tell a different story. Using a non-Anthropic model means carrying dead weight.

**Problem: Over-engineered sub-agent system.** Three types of subagents (`SubAgent`, `CompiledSubAgent`, `AsyncSubAgent`), a 250-line tool description for the `task` tool, and 540 lines of middleware code. The `TASK_TOOL_DESCRIPTION` string alone is a sprawling prompt with 7 usage examples. This is the LangChain pattern repeated: wrapping a simple concept (call another agent) in layers of configuration, TypedDicts, middleware, and extensive prompt engineering.

Compare to smolagents: "core agent logic fits in ~1,000 lines of code." DeepAgents' middleware + backends alone are 11,696 lines -- and that excludes the CLI, ACP adapter, evals, and partner integrations.

**Problem: State keys are framework-controlled strings.** `_EXCLUDED_STATE_KEYS = {"messages", "todos", "structured_response", "skills_metadata", "memory_contents"}` -- hard-coded magic strings that determine what state flows between agents and what gets filtered. If you add your own state key, you need to know which of these exclusion sets apply.

### 3.3 Verdict

DeepAgents does not fix LangChain's core problems. It is a well-crafted product (Claude Code clone) built on a problematic foundation (LangChain + LangGraph). The patterns it introduces (middleware, backend protocol, eval suite) are good ideas executed within the wrong constraint: mandatory dependency on the entire LangChain ecosystem.

A lite framework should learn from DeepAgents' patterns (middleware for cross-cutting concerns, backend abstraction for IO, eval-driven development) while avoiding its inheritance: zero LangChain dependency, no mandatory provider coupling, explicit over implicit.

---

## 4. Common Anti-Patterns in Agent Frameworks

### Anti-Pattern 1: The God Abstraction

**What it looks like**: A single class or function that "handles everything" -- `AgentExecutor`, `create_deep_agent`, `RetrievalQA.from_chain_type()`.

**Why it fails**: Users cannot understand, debug, or extend what they cannot see. When the god abstraction doesn't do exactly what you need (it never does), you must either fight the framework or bypass it entirely.

**Better alternative**: Composable primitives. Give the user `call_llm()`, `parse_response()`, `execute_tool()` as separate functions. Let them compose these in a `while` loop. The "framework" is their Python code.

### Anti-Pattern 2: Configuration Over Code

**What it looks like**: YAML/JSON config files that control agent behavior. LangChain's chains, CrewAI's crew definitions, LangGraph's graph declarations.

**Why it fails**: Configuration languages are strictly less expressive than code. The moment you need conditional logic, dynamic tool selection, or runtime adaptation, configuration becomes a prison. And you still need to learn a custom config schema.

**Better alternative**: Code is the configuration. A Python function that returns an agent is more readable, more flexible, and more debuggable than any YAML schema.

### Anti-Pattern 3: Implicit LLM Calls

**What it looks like**: Framework makes LLM calls the user didn't request -- chain refinement, automatic summarization, query rewriting, embedding generation.

**Why it fails**: Each hidden call costs money, adds latency, and is invisible in debugging. LangChain's "refine" chain type doubled token consumption silently.

**Better alternative**: Every LLM call must be explicit and auditable. If the framework offers summarization, the user must opt into each summarization call and see the prompt/response.

### Anti-Pattern 4: Framework-Specific Data Types

**What it looks like**: `HumanMessage`, `AIMessage`, `ToolMessage`, `SystemMessage` instead of standard dicts. `Document` instead of a string with metadata.

**Why it fails**: Creates ecosystem lock-in. Every tool, every integration, every test must use framework types. Converting to/from standard formats becomes a tax on every boundary.

**Better alternative**: Use standard Python types. Messages are `dict[str, Any]` matching the OpenAI format. Documents are `str` with optional metadata `dict`. Tools are `Callable` with type hints. Pydantic models for structured output.

### Anti-Pattern 5: Middleware Stacking Without Visibility

**What it looks like**: 8 middleware layers each modifying the request/response. DeepAgents: TodoList -> Memory -> Skills -> Filesystem -> SubAgent -> Summarization -> PromptCaching -> PatchToolCalls.

**Why it fails**: Each layer can inject prompts, filter tools, transform messages, and modify state. When the agent misbehaves, which layer caused it? The middleware pattern from web frameworks (Django, Express) works because HTTP requests are simple and predictable. LLM requests are complex and non-deterministic -- stacking invisible transformations on non-deterministic systems makes debugging exponentially harder.

**Better alternative**: Explicit hooks at defined points. Before-LLM-call and after-LLM-call hooks that the user writes. No invisible prompt injection, no invisible tool filtering. If you want summarization, you call `summarize()` in your before-hook.

### Anti-Pattern 6: Vendor-Funded "Open Source" with Commercial Lock-In

**What it looks like**: Framework is MIT-licensed but observability requires LangSmith (commercial SaaS). Debugging without LangSmith is described as "archaeology." Default backend is the vendor's cloud deployment.

**Why it fails**: The open-source framework becomes a funnel to the commercial product. Users invest in learning the framework, discover they need the commercial observability layer, and are locked in. DeepAgents' `langsmith>=0.3.0` is a required dependency, not optional.

**Better alternative**: Framework observability must work with standard tools (Python logging, OpenTelemetry). Commercial products can provide enhanced observability, but basic debugging must never require a vendor dependency.

---

## 5. Design Principles for a Lite Framework (Learned from These Failures)

### Principle 1: Plain Python First

The best agent framework is no framework. Most agent use cases need:
- An LLM client (OpenAI SDK, httpx, or equivalent)
- A tool execution loop (`while True: call LLM, parse tool calls, execute tools, check if done`)
- State as a Python dict or dataclass
- Structured output via Pydantic

If your framework cannot demonstrate clear value over this baseline, it should not exist.

### Principle 2: Zero Hidden Behavior

Every LLM call, every prompt modification, every tool filtering decision must be visible to the user without requiring a commercial observability product. This means:
- No implicit system prompt injection
- No automatic chain refinement
- No hidden embedding calls
- Full request/response logging via standard Python logging

### Principle 3: Escapable Abstractions

Every abstraction must expose its internals. If the framework provides a `call_llm()` wrapper, the user must be able to:
- See exactly what messages will be sent before they're sent
- Modify the messages at any point
- Access the raw response including token usage and metadata
- Bypass the wrapper entirely and use the raw client

### Principle 4: Standard Data Types

Messages are dicts. Tools are callables. State is a dict or typed dict. Documents are strings. No framework-specific wrapper types that require conversion at every boundary.

### Principle 5: Proportional Complexity

Simple things must be simple. Complex things must be possible. The progression:
1. Single LLM call with tools: 10 lines
2. Multi-turn conversation: 20 lines
3. Agent with tool loop: 30 lines
4. Multi-agent with fan-out: 50-100 lines
5. Persistent state with checkpointing: +20 lines on top of whatever you have

Each level adds only what's needed. There is no "framework tax" for simple use cases.

### Principle 6: Explicit State Management

State is a Python object the user owns and understands. No implicit state merging, no magic reducers, no `Annotated[list, operator.add]` that explodes with concurrent writes. If you want fan-out with merge, you write the merge function and you see exactly what happens.

### Principle 7: Provider Agnostic By Default

The core framework must work with any LLM that implements the OpenAI-compatible chat completions API. No required dependency on any provider SDK. Provider-specific features (prompt caching, extended thinking) are optional extras, not default middleware layers.

### Principle 8: Observability Without Vendor Lock-In

Debugging an agent must work with `print()`, Python `logging`, or OpenTelemetry. If the framework provides tracing, it exports standard formats. No proprietary observability required for basic debugging.

### Principle 9: Test What Matters

Eval-driven development (from DeepAgents) is correct. But evals must test agent behavior, not framework machinery. Test: "Given this input, does the agent produce useful output?" Not: "Does the middleware stack correctly inject the prompt?"

### Principle 10: Composition Over Inheritance

Agents are built by composing functions, not by inheriting from framework classes. There is no `BaseAgent`, no `AgentExecutor`, no `BaseChain`. There are functions that do things, and you call them in the order you need.

---

## 6. Summary: The Spectrum of Agent Framework Design

```
Over-abstracted (LangChain)          Right-sized             Under-abstracted (raw SDK)
|------|------|------|------|------|------|------|------|------|------|
       ^                    ^      ^                          ^
   DeepAgents          LangGraph  smolagents            OpenAI SDK
   (wraps LangGraph)   (explicit  PydanticAI            + while loop
                        but heavy)

Problems:                          Problems:
- Hidden behavior                  - No reuse across projects
- Debugging nightmare              - Reinvent tool execution
- Version churn                    - No standard patterns
- Token/cost overhead              - No observability
- Vendor lock-in                   - Error handling ad-hoc
```

A good lite framework sits in the "right-sized" zone: it provides the tool execution loop, structured output parsing, and state management that every agent needs, without hiding LLM calls, inventing data types, or requiring a PhD in framework internals to debug.

The specific sweet spot: **a library (not a framework) that provides composable primitives for the things that are genuinely hard (tool execution, structured output, state checkpointing) while leaving control flow, prompting, and LLM interaction to the user.**

---

## Sources

### LangChain Critiques
- [Octomind/OctoClaw: Why we no longer use LangChain for building our AI agents](https://octoclaw.ai/blog/why-we-no-longer-use-langchain-for-building-our-ai-agents) -- 12-month production experience, removed in 2024
- [Hacker News discussion (40739982)](https://news.ycombinator.com/item?id=40739982) -- Community technical critiques
- [Latenode Community: Why I'm Avoiding LangChain in 2025](https://community.latenode.com/t/why-im-avoiding-langchain-in-2025/39046)
- [The Hidden Cost of LangChain: 2.7x Token Overhead](https://dev.to/himanjan/the-hidden-cost-of-langchain-why-my-simple-rag-system-cost-27x-more-than-expected-4hk9)

### Framework Comparisons
- [LangChain vs PydanticAI for building an AI Agent](https://medium.com/@finndersen/langchain-vs-pydanticai-for-building-an-ai-agent-e0a059435e9d)
- [Same Chat App, 4 Frameworks: Code Comparison](https://medium.com/@kacperwlodarczyk/same-chat-app-4-frameworks-pydantic-ai-vs-langchain-vs-langgraph-vs-crewai-code-comparison-64c73716da68) -- 160 vs 170 vs 280 vs 420 lines
- [Langfuse: Comparing Open-Source AI Agent Frameworks](https://langfuse.com/blog/2025-03-19-ai-agent-comparison)

### LangGraph Issues
- [LangGraph INVALID_CONCURRENT_GRAPH_UPDATE documentation](https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE)
- [operator.add reducer exponential duplication (LangChain Forum)](https://forum.langchain.com/t/subject-operator-add-reducer-causes-exponential-duplication-in-annotated-list-state-fields-when-tools-update-state/1546)
- [LangGraph Troubleshooting Cheatsheet](https://sumanmichael.github.io/langgraph-cheatsheet/cheatsheet/troubleshooting-debugging/)

### Alternative Frameworks
- [smolagents: agents that think in code (~1,000 lines core)](https://github.com/huggingface/smolagents)
- [PydanticAI: Type-safe agent framework](https://github.com/pydantic/pydantic-ai)
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python)
