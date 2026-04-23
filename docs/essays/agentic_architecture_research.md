# Agentic Architecture Design: Lessons from Production Coding Agents (2025)

**Sources**: Analysis of Claude Code internals (via [claw-code](https://github.com/ultraworkers/claw-code) reverse-engineering and [how-claude-code-works](https://github.com/Windy3f3f3f3f/how-claude-code-works) 15-chapter analysis), and [NousResearch Hermes Agent](https://github.com/nousresearch/hermes-agent) framework.

**Date**: April 2025

**Thesis**: In the emerging agentic AI era, a company's core intellectual property extends beyond training data to encompass the *harness*—the architecture around the model. System prompts, tool registries, skill libraries, memory systems, permission models, and context management strategies are the differentiating assets that turn a generic LLM into a reliable autonomous agent.

---

## 1. The Controlled Tool-Loop: The Universal Agent Architecture

Every production agent converges on the same fundamental pattern: a **controlled tool-loop** where the LLM repeatedly generates actions, the harness executes them, and results are fed back until the task completes.

### 1.1 The Core Loop

```
User Input
    |
    v
+-------------------+
| System Prompt     |  <-- assembled from static + dynamic sections
| Assembly          |
+-------------------+
    |
    v
+-------------------+
| API Call          |  <-- messages + tools + system prompt
| (LLM inference)  |
+-------------------+
    |
    v
+-------------------+     +-------------------+
| Response Parse    |---->| Pure Text?        |---> Return to User
| (stream tokens)   |     | (no tool calls)   |
+-------------------+     +-------------------+
    |
    | tool_use blocks detected
    v
+-------------------+
| Pre-execution     |  <-- hooks, permissions, validation
| Pipeline          |
+-------------------+
    |
    v
+-------------------+
| Tool Execution    |  <-- parallel for read-only, serial for writes
+-------------------+
    |
    v
+-------------------+
| Post-execution    |  <-- hooks, result truncation, disk persistence
| Pipeline          |
+-------------------+
    |
    v
+-------------------+
| Context Check     |  <-- token estimation, compression if needed
+-------------------+
    |
    +---> Loop back to API Call
```

**Termination conditions** (Claude Code): Pure text response (no tool calls), max turns reached, USD budget exceeded, user abort, unrecoverable errors, or compression circuit breaker (3+ consecutive failures).

### 1.2 Two-Layer Architecture

Claude Code separates the loop into two distinct layers:

- **QueryEngine** (session lifecycle): Tracks session state, manages USD budgets and token usage, handles user input processing and slash commands, orchestrates recovery strategies across turns.
- **query()** (loop executor): Manages a single turn—API calls, tool execution, compression pipeline, and error recovery within that turn.

This separation means session-level concerns (billing, persistence, user interaction) don't pollute the tight inner loop, and the inner loop can be tested independently.

Hermes Agent uses a monolithic `AIAgent` class (~11,000 lines) where `run_conversation()` implements the loop. While less cleanly separated, it compensates with an `IterationBudget` (thread-safe counter, default max 90 turns) that prevents runaway loops—subagents share the parent's budget.

### 1.3 Streaming as Core UX

Both systems treat streaming as fundamental, not optional:

- **Claude Code**: Uses async generators (TypeScript) for token-by-token flow. The `StreamingToolExecutor` processes completed tool blocks *during* API streaming—read operations execute in parallel while the model is still generating. This hides tool execution latency in the 5–30 second generation window.
- **Hermes Agent**: The gateway's `StreamConsumer` bridges sync agent callbacks to async platform delivery, with progressive message editing and overflow handling that splits at natural boundaries.

The key insight: **streaming is not just about perceived latency—it enables overlapping computation**. Starting tool execution before the model finishes generating saves real wall-clock time.

### 1.4 Error Recovery Without User Exposure

Claude Code implements **error withholding**: recoverable errors are never immediately shown to users. The loop holds the error internally and attempts a graduated recovery sequence:

| Recovery Strategy | When Triggered |
|---|---|
| `collapse_drain_retry` | Submit folds, release tokens |
| `reactive_compact_retry` | Force full context compression |
| `max_output_tokens_escalate` | Upgrade to 64K output tokens |
| `max_output_tokens_recovery` | Inject continuation prompt (max 3 attempts) |
| `token_budget_continuation` | Resume generation |

Only if all recovery strategies fail does the error surface to the user. This creates the illusion of reliability—the agent handles its own operational problems transparently.

Hermes Agent implements a similar pattern with a 7-stage error classification pipeline mapping API errors to 14 `FailoverReason` categories, each with recovery hints (retryability, credential rotation needs, compression requirements, fallback eligibility). It also maintains an ordered fallback chain of backup LLM providers activated per-turn.

---

## 2. Tool System Design

The tool system is where the agent's capabilities are defined. Both Claude Code and Hermes Agent treat tools as the primary extension mechanism.

### 2.1 Unified Tool Interface

Claude Code's `Tool<Input, Output, P>` interface standardizes all 66+ tools. Every tool—from file reading to web search to subagent spawning—conforms to the same interface. Adding a new tool requires **zero changes to the execution pipeline**.

Each tool is constructed via a `buildTool()` factory with **fail-closed defaults**:
- `isConcurrencySafe: false` (serial execution unless proven safe)
- `isReadOnly: false` (treated as mutating unless proven otherwise)
- `checkPermissions: allow` (requires explicit permission configuration)

This means a new tool with no safety annotations is automatically treated as dangerous and serial—a secure-by-default posture.

Hermes Agent's `ToolRegistry` follows a similar singleton pattern with thread-safe operations. Tools self-register at import time, and the `discover_builtin_tools()` function uses **AST analysis** to find self-registering modules automatically—no manual manifest needed.

### 2.2 Tool Categories

Both systems organize tools into functional groups:

| Category | Claude Code | Hermes Agent |
|---|---|---|
| File I/O | Read, Edit, Write, Glob, Grep | read_file, write_file, patch_file, search |
| Shell | Bash (with AST validation) | terminal (with command safety) |
| Web | WebFetch, WebSearch | web_search, web_extract, web_crawl |
| Agent | Agent (subagent spawning) | delegate_task, mixture_of_agents |
| Memory | Auto-memory extraction | memory tool (MEMORY.md, USER.md) |
| Planning | EnterPlanMode, ExitPlanMode | (implicit via skills) |
| Tasks | TaskCreate, TaskUpdate, TaskList | (via skills) |
| MCP | MCP bridge tools | mcp_tool (full protocol) |
| Notebook | NotebookEdit | (via code execution) |
| Skills | Skill (invocation) | skills management tools |

### 2.3 The Bash Tool: Where Security Gets Hard

Shell execution is the most security-critical tool. Both systems invest heavily here:

**Claude Code's 6-stage Bash validation**:
1. **tree-sitter AST parsing** — parses the command into an AST rather than relying on regex. This catches obfuscation that regex-based approaches miss.
2. **23 named security checks** — command substitution variants, Zsh module loading, sed `e` flag abuse, path validation, destructive command warnings.
3. **Semantic classification** — commands are classified as ReadOnly, Write, Destructive, Network, ProcessManagement, PackageManagement, SystemAdmin, or Unknown. Classification determines the required permission level.
4. **Path validation** — detects directory traversal and home directory escapes.
5. **Sandbox isolation** — `sandbox-exec` (macOS Seatbelt) or bubblewrap (Linux) for OS-level containment.
6. **FAIL-CLOSED semantics** — unknown command structures are automatically distrusted.

**Hermes Agent's approach**:
- 50+ regex patterns for dangerous commands (rm -r /, chmod 777, DROP TABLE, force push)
- Three approval modes: Interactive (user chooses), Smart (auxiliary LLM assesses risk), Container bypass (auto-approved inside Docker)
- External security scanner (Tirith) checking for homograph URLs, pipe-to-interpreter attacks, terminal injection
- Unicode normalization (NFKC) and ANSI stripping to prevent obfuscation

The key difference: Claude Code uses **AST-based analysis** (tree-sitter) for structural understanding of commands, while Hermes uses **pattern matching + LLM classification**. AST is more robust against obfuscation; LLM classification is more flexible for novel attack patterns.

### 2.4 Delayed Tool Loading (Prompt Cache Optimization)

Claude Code introduces a subtle but important optimization: **deferred tool schemas**. The `ToolSearchTool` stabilizes the tool list that forms the prompt cache key. Optional or rarely-used tools aren't included in the initial tool list—they're loaded on demand via `ToolSearch`. This prevents prompt cache invalidation when unused tools change.

This reveals a deep architectural truth: **the tool list is part of the prompt, and prompt stability directly affects inference cost**. Every tool schema change invalidates the prefix cache, forcing a full re-read of 100K+ tokens.

### 2.5 Concurrency Control

Claude Code's concurrency model is precise:
- Tools where `isReadOnly(input) === true` execute in parallel
- Non-readonly tools serialize exclusively
- The `StreamingToolExecutor` overlaps tool execution with model streaming output

Hermes Agent classifies tools into three groups:
- `_PARALLEL_SAFE_TOOLS` (read_file, web_search, etc.) — always parallelizable
- `_NEVER_PARALLEL_TOOLS` (clarify) — always serial
- `_PATH_SCOPED_TOOLS` (write_file) — parallelizable only when operating on different paths

Both systems recognize that **naive parallelism is dangerous for stateful tools**, but conservative serialization wastes latency.

### 2.6 Tool Result Management

Large tool outputs can overwhelm the context window. Both systems implement multi-layer defenses:

**Claude Code**:
- Outputs >100K characters persist to disk; context keeps only previews
- Time-based pruning of old tool results during compression
- Self-rendering: each tool defines its own `renderToolUseMessage()` and `renderToolResultMessage()`

**Hermes Agent** (three layers):
1. Per-tool output cap (tool authors pre-truncate)
2. Per-result persistence (results > threshold written to sandbox, replaced with `<persisted-output>` preview)
3. Per-turn aggregate budget (200K chars; largest results progressively spilled to disk)

---

## 3. System Prompt Architecture

The system prompt is the agent's constitution—it defines identity, capabilities, behavioral constraints, and operational context. Both systems treat prompt engineering as a first-class architectural concern.

### 3.1 Static vs. Dynamic Separation

Claude Code splits its system prompt into **7 static sections** (globally cacheable) and **dynamic sections** (recomputed per turn):

**Static sections** (shared across users, maximizes cache hits):
- **Intro**: Identity and security boundaries
- **System**: Runtime environment rules
- **Doing Tasks**: Coding principles ("Don't add features beyond what was asked")
- **Actions**: Risk assessment framework requiring confirmation for destructive operations
- **Using Your Tools**: Tool usage methodology with explicit hierarchy (Read over cat, Edit over sed)
- **Tone and Style**: Communication preferences
- **Output Efficiency**: Brevity directives

**Dynamic sections** (user-specific, recomputed):
- Session guidance, memory systems, environment info, language preferences, MCP instructions, scratchpad configuration

This split is architecturally motivated: the static prefix is identical across users, enabling **global KV cache sharing** at the inference layer. A 50K-token static prefix shared by 1,000 concurrent users saves enormous compute.

### 3.2 Instruction Discovery and Layering

Both systems support hierarchical instruction files that layer context:

**Claude Code**: Traverses ancestor directories looking for `CLAUDE.md`, `CLAUDE.local.md`, and `.claw/instructions.md`. Content is deduplicated across scopes with strict character budgets (4,000 per file, 12,000 total).

**Hermes Agent**: Discovers `.hermes.md`, `AGENTS.md`, `CLAUDE.md`, `.cursorrules` in priority order. Applies prompt injection defense (regex detection of "ignore previous instructions" patterns and invisible Unicode filtering) before injection.

The pattern: **project-level instructions are untrusted input**. A malicious repository could include a `CLAUDE.md` designed to manipulate the agent. Both systems sanitize and budget-constrain these inputs.

### 3.3 Agent-Type-Specific Prompts

Claude Code defines **six specialized agent types**, each with distinct system prompts and capabilities:

| Agent Type | Model | Capabilities | Purpose |
|---|---|---|---|
| Explore | Haiku (fast) | Read-only tools | Quick codebase navigation |
| Plan | — | Read-only tools | Software architecture |
| General-Purpose | — | Full tools | Complex multi-step tasks |
| Verification | — | Read-only, adversarial | Validates agent work |
| Statusline-Setup | — | Limited (Read, Edit) | Configure UI settings |
| Claude-Code-Guide | — | Documentation lookup | Help/FAQ |

This is a key pattern: **different tasks need different capability profiles**. A read-only explorer agent can't accidentally modify files. A verification agent probes for errors without being able to "fix" them (which would compromise its independence).

### 3.4 System Reminders

Both systems inject dynamic information via structured tags:

Claude Code wraps system metadata in `<system-reminder>` XML tags, creating semantic boundaries so the model recognizes injected context as system data—distinct from user input or tool output. This is a defense against prompt injection: the model is trained to treat `<system-reminder>` content as authoritative system information.

---

## 4. Context Window Management

With context windows of 128K–200K tokens, managing what stays in context is a critical engineering challenge. Both systems implement sophisticated multi-level compression.

### 4.1 Claude Code's Five-Level Compression Pipeline

Each level costs more than the previous. The system tries the cheapest approach first:

| Level | Mechanism | Cost |
|---|---|---|
| 1. Tool Result Budgeting | Large outputs persist to disk; context keeps previews | Free (local I/O) |
| 2. History Snip | Feature-gated removal of redundant message segments | Free (local logic) |
| 3. Microcompact | Clears old tool results via time-based or cache-edit instructions | Free (local logic) |
| 4. Context Collapse | Read-time projection summarizing early messages (without modifying originals) | Free (local compute) |
| 5. Autocompact | Forks a sub-Agent to generate full conversation summary | Expensive (API call) |

Critical design decision: **Context Collapse is a read-time projection**—it doesn't modify the original message history. This means the full history is always available for recovery, debugging, or re-processing.

### 4.2 Hermes Agent's Compression Strategy

Hermes Agent's `ContextCompressor` implements multi-phase compression:

1. **Tool result pruning**: Replaces old tool outputs with one-line summaries (e.g., `[terminal] ran npm test -> exit 0, 47 lines output`)
2. **Boundary protection**: Preserves first N messages (system + initial exchange) and last ~20K tokens
3. **Middle turn summarization**: LLM-based structured summary with Goal, Completed Actions, Active State, Blocked Issues, Pending Questions
4. **Iterative updates**: Subsequent compressions update existing summaries rather than regenerating
5. **Anti-thrashing**: Tracks compression effectiveness; skips if recent passes saved less than 10% each

The anti-thrashing mechanism is important: without it, a conversation near the context limit could enter an infinite compress-expand-compress cycle, burning API calls on compression that barely helps.

### 4.3 Prompt Cache Stability

Claude Code treats **cache stability as a first-class architectural concern**. The prompt cache creates a three-layer chain with breakpoints at:
1. System prompt boundary (static vs. dynamic)
2. Tools array (after last standard tool)
3. Message array (on final message)

Four defenses protect cache stability:
1. **System prompt splitting** — maximizes global sharing
2. **Session-level latching** — locks TTL eligibility and beta headers for the session
3. **Tool/message ordering** — optional tools placed after breakpoints
4. **Cache breakage detection** — snapshot comparison to diagnose when and why cache breaks

This means that architectural decisions about prompt structure directly impact inference economics. A carelessly placed dynamic section in the middle of the prompt can break the cache chain and multiply costs.

### 4.4 Token Estimation Without API Calls

Claude Code's `tokenCountWithEstimation()` uses the server's last reported token usage as an anchor point and estimates new messages via character count (<5% error, zero latency). This avoids an API call just to check whether compression is needed—a common trap in naive implementations.

### 4.5 Post-Compression Restoration

After compression, Claude Code automatically restores the five most recently edited files into context. This ensures the agent doesn't lose awareness of its own recent work—a critical UX concern when the agent is mid-task.

---

## 5. Memory Systems

Memory transforms a stateless LLM into an agent that learns across sessions. Both systems implement persistent memory but with different philosophies.

### 5.1 Claude Code's Four-Type Taxonomy

Claude Code defines a **closed taxonomy** of memory types:

| Type | Purpose | When to Save |
|---|---|---|
| **user** | Identity, preferences, knowledge domains | Learning about user's role, expertise, style |
| **feedback** | Behavioral corrections AND affirmations | User corrects approach or confirms non-obvious choice |
| **project** | Active work, decisions, deadlines | Who is doing what, why, by when (absolute dates) |
| **reference** | External system pointers | URLs, dashboards, tracking systems |

What is explicitly **excluded** from memory:
- Code patterns, conventions, architecture, file paths — derivable from the current project state
- Git history — `git log` / `git blame` are authoritative
- Debugging solutions — the fix is in the code; the commit message has the context
- Anything already in CLAUDE.md files
- Ephemeral task details

This exclusion list reveals a deep principle: **memory should store what cannot be derived from the current state of the world**. Code changes, git history, and file structure are self-describing—storing them in memory creates staleness risk without adding value.

### 5.2 Memory Architecture

**Storage**: `~/.claude/projects/{project-hash}/memory/` with three-level path priority (env override > user settings > default). Project-level settings are excluded from controlling the memory path—this prevents malicious repos from redirecting memory writes.

**MEMORY.md as index**: A 200-line maximum, 25KB byte-limit index file that loads in every session's system context. It points to detailed memory files, never stores content directly. Each entry is one line under ~150 characters.

**Semantic recall pipeline**:
1. `scanMemoryFiles()` — scan all .md files, read first 30 lines (frontmatter), sort by mtime, retain newest 200
2. `formatMemoryManifest()` — ranked list with ISO timestamps
3. `selectRelevantMemories()` — Sonnet (a smaller model) evaluates semantic relevance, returns up to 5 files
4. Filter & return — remove already-surfaced memories, validate filenames

**Background memory extraction**: Post-response, a forked Agent auto-identifies valuable information from the conversation. It has minimal permissions (read-only Bash, write access only to memory directory), frequency throttling, and concurrency safety with the main agent.

**Freshness defense**: Memories get human-readable age labels ("today," "47 days ago"). Memories >1 day old get explicit warnings. A `TRUSTING_RECALL_SECTION` in the system prompt requires verification via Glob/Read before acting on remembered facts.

### 5.3 Hermes Agent's Memory System

Hermes takes a different but complementary approach:

**Two memory files**: `MEMORY.md` (agent observations) and `USER.md` (user profile/preferences).

**Frozen snapshot pattern**: Memory is injected into the system prompt at session start. Mid-session writes persist to disk immediately but **don't update the active prompt** until the next session. This preserves prefix caching stability—a pragmatic trade-off between memory freshness and inference cost.

**Memory Provider abstraction**: An abstract base class with lifecycle hooks (`initialize()`, `prefetch()`, `sync_turn()`, `handle_tool_call()`, `shutdown()`), allowing pluggable external backends (Honcho, Hindsight, Mem0) alongside the built-in file-based provider.

**Security scanning**: Blocks prompt injection and credential exfiltration patterns in memory entries—because memory is injected into the system prompt, a compromised memory entry is effectively a prompt injection attack.

### 5.4 Agent Memory Isolation

Both systems isolate subagent memory:
- **Claude Code**: Sub-agents maintain separate memory at `~/.claude/agent-memory/{agentType}/` to prevent cross-contamination
- **Hermes Agent**: Delegated subagents get fresh conversations with no parent history and restricted toolsets (memory tool is blocked for children)

### 5.5 The Key Insight: Memory as Institutional Knowledge

The memory system is where the thesis—*harness design as core IP*—becomes most concrete. A company's agent accumulates:
- **User memories**: Understanding of each team member's expertise, preferences, communication style
- **Feedback memories**: Behavioral calibration from thousands of corrections and confirmations
- **Project memories**: Contextual knowledge about decisions, constraints, deadlines that aren't in any document
- **Reference memories**: Navigational knowledge of the organization's tooling landscape

This accumulated memory represents **institutional knowledge in machine-readable form**. It's not the model weights (those are Anthropic's or Meta's). It's not the training data. It's the accumulated wisdom of how *this organization* works, encoded in a format the agent can use. This is a new category of intellectual property.

---

## 6. Skill Systems: Procedural Knowledge

Skills are reusable, composable workflows that turn multi-step procedures into one-shot invocations. They represent the agent's **learned capabilities**—procedural knowledge that would otherwise need to be re-derived from scratch each session.

### 6.1 Claude Code's Skill Architecture

Skills are "AI Shell scripts"—prompt templates + metadata + execution context. Each skill is a `SKILL.md` file in a directory.

**Dual invocation** (key innovation): Users invoke manually via `/commit`, OR the model automatically triggers via `SkillTool` based on `whenToUse` descriptions. Both paths converge on identical execution logic. This means the same skill serves as both a user command and an autonomous agent capability.

**Six sources (priority order)**:
1. Bundled (highest—cannot be overridden by project skills)
2. Managed (enterprise policy)
3. User filesystem (`~/.claude/skills/`)
4. Project filesystem
5. Workflow scripts
6. MCP (remote, lowest trust)

**Lazy loading**: Only frontmatter (name, description, whenToUse) loads at startup. Full Markdown content loads on actual invocation. The skill listing budget is ~1% of context window (~8KB for 200K context).

**Two execution modes**:
- **Inline** (default): Skill prompt injected as message into current conversation. Shares context, can modify agent behavior via `contextModifier` (allowed tools, model override, effort level).
- **Fork**: Creates isolated sub-Agent with own message history and tool pool. Provides permission, context, and model isolation.

**Long-session persistence**: After compression, skills are rebuilt from state with budgets: 25,000 total tokens, 5,000 per skill, most-recently-used priority.

### 6.2 Hermes Agent's Skills as Self-Improvement

Hermes Agent takes skills further with a **self-improvement loop**:

- The agent creates skills after successful complex tasks (5+ iterations), user-corrected approaches, or non-trivial workflow discoveries
- Skills undergo security scanning on creation (detecting exfiltration, injection, destructive operations, reverse shells, obfuscation)
- A three-tier trust model: builtin > trusted > community
- A Skills Hub (`agentskills.io`) for external sharing
- 26+ built-in skill categories covering everything from DevOps to red-teaming

**Progressive disclosure** for context efficiency:
- Tier 1 (list): Minimal metadata only
- Tier 2 (view): Full SKILL.md content
- Tier 3 (execute): Specific supporting files loaded

### 6.3 Skills as Competitive Moat

Skills represent a significant competitive moat for organizations:

1. **Codified expertise**: A skill for "deploy to production" encodes the organization's specific deployment procedure—secrets management, canary strategies, rollback procedures, notification channels.
2. **Compound improvement**: Each new skill builds on existing ones. A "debug production incident" skill might invoke "check monitoring dashboards" and "search logs" skills.
3. **Transferable knowledge**: Skills outlive individual team members. When a senior engineer leaves, their debugging workflow persists as a skill.
4. **Version-controlled process**: Unlike tribal knowledge, skills are files in a repository—they can be reviewed, tested, and rolled back.

---

## 7. Permission and Safety Architecture

Agentic systems that execute code and modify files need rigorous safety models. Both systems implement defense-in-depth.

### 7.1 Claude Code's Seven-Layer Defense

1. **Trust Dialog**: Initial workspace confirmation; disables custom hooks if untrusted
2. **Permission Modes**: 5 global policies (default, acceptEdits, plan, bypassPermissions, dontAsk)
3. **Permission Rules**: User-defined allow/deny/ask patterns with wildcard matching. 7-source hierarchy (session > CLI > local > user > project > policy > flags)
4. **Bash Multi-Layer Security**: tree-sitter AST parsing, 23 static security checks, sed operation whitelisting, path validation, sandbox isolation
5. **Tool-Level Validation**: Input validation and permission checks per tool
6. **Sandboxing**: OS-level isolation via Seatbelt/sandbox-exec (macOS) or bubblewrap (Linux)
7. **User Confirmation**: Interactive dialogs with 200ms anti-typo delay

**Critical rules**:
- Deny rules trump everything, even in `bypassPermissions` mode
- Unknown Bash structures are automatically distrusted (fail-closed)
- Dangerous paths (`.bashrc`, `.gitconfig`, `.claude/settings.json`) require confirmation even in bypass mode
- Case-normalization prevents macOS case-insensitivity exploits
- 3 consecutive or 20 total rejections triggers fallback to interactive mode

### 7.2 Hermes Agent's Safety Layers

- **Command safety**: 50+ regex patterns for dangerous commands
- **Three approval modes**: Interactive (user chooses), Smart (auxiliary LLM assesses risk), Container bypass
- **External security scanner**: Tirith binary with SHA-256 + cosign verification
- **Path security**: Defense-in-depth path validation—preliminary `..` check, canonical symlink resolution, boundary enforcement
- **Secret redaction**: Regex-based masking of 20+ secret types (API keys, GitHub PATs, Stripe keys, AWS keys, DB connection strings)
- **Filesystem checkpoints**: Shadow git repos capture filesystem state before mutating operations, enabling list, diff, and restore
- **Skill security**: Static analysis threat detection for externally-sourced skills

### 7.3 Permission as UX Design

The permission system isn't just security—it's **trust calibration UX**. Claude Code's Plan Mode is unique: it's the only mechanism where the model **voluntarily reduces its own permissions** to build trust. The agent enters a read-only exploration mode, presents a plan, and only gains execution permissions after user approval.

This pattern—**earned autonomy**—is likely the future of human-agent interaction. The agent starts conservative, demonstrates understanding, and gradually receives broader permissions as trust is established.

---

## 8. Multi-Agent Architecture

Both systems support multiple agents working together, but with different coordination patterns.

### 8.1 Claude Code's Three Operating Modes

1. **Subagent Mode**: Parent delegates independent tasks to children via fork-return. Simplest pattern. Children get isolated contexts created via `createSubagentContext()` with deny-by-default mutable state.

2. **Coordinator Pattern**: Central orchestrator (read-only, assignment-only, cannot self-execute) distributes work across workers and synthesizes findings. Forces parallelization by preventing the coordinator from doing the work itself.

3. **Swarm Teams**: Peer-to-peer agent communication through named mailboxes. True collaborative workflows without hierarchy. Scratchpad directories enable cross-worker sharing without coordinator mediation.

**Git Worktrees**: Each agent gets an isolated copy of the codebase via git worktrees, preventing file conflicts between concurrent agents.

**Worker lifecycle**: `Spawning` -> `TrustRequired` -> `ReadyForPrompt` -> `Running` -> `Finished`/`Failed`, with state machine observation for trust prompts, prompt misdeliveries, and ready signals.

**Recovery recipes**: Seven automated failure scenarios with prescribed recovery (trust prompt unresolved, prompt misdelivery, stale branch, compile errors, MCP handshake failure, partial plugin startup, provider failure). One attempt before mandatory escalation.

### 8.2 Hermes Agent's Delegation Model

**Parent-child isolation**:
- Children get fresh conversations (no parent history), unique `task_id`, and restricted toolsets
- Blocked tools for children: `delegate_task`, `clarify`, `memory`, `send_message`, `execute_code`
- Depth limit: MAX_DEPTH = 2 (no grandchild agents)
- Batch mode: Up to 3 concurrent tasks via ThreadPoolExecutor
- Credential isolation: Children can use different LLM providers than parent

**Mixture of Agents**: A 2-layer collaborative framework (based on Wang et al., arXiv:2406.04692v1):
- Layer 1: Four frontier models (Claude, Gemini, GPT, DeepSeek) generate diverse responses in parallel
- Layer 2: Claude synthesizes into a final output
- Used for complex reasoning where model diversity improves quality

### 8.3 The Lane System (Claude Code Advanced)

Claude Code's claw-code rewrite reveals an advanced **multi-lane development model**:
- **Lanes** represent parallel work streams (like parallel feature branches)
- **17 event types** tracking lane lifecycle (Started, Ready, Blocked, Red, Green, Finished, etc.)
- **Green Contract**: Quality levels (`TargetedTests` < `Package` < `Workspace` < `MergeReady`)
- **Branch lock collision detection** for multi-lane development
- **Stale branch detection** with four policies: AutoRebase, AutoMergeForward, WarnOnly, Block

This suggests the future direction: agents that don't just write code but **manage entire development workflows**—branching, testing, merging, and conflict resolution across parallel workstreams.

---

## 9. Hook Systems: Extensibility Without Core Changes

Hooks enable external code to intercept and modify agent behavior without changing the core agent code.

### 9.1 Claude Code's 27-Event Hook System

**Event categories**:
- Tool lifecycle: PreToolUse, PostToolUse, PostToolUseFailure
- Permission system: PermissionRequest, PermissionDenied
- Session management: SessionStart, SessionEnd
- Environment changes: FileChanged, CwdChanged, ConfigChange
- Agent coordination: SubagentStart, SubagentStop, TeammateIdle

**Six hook types**:

| Type | Best For |
|---|---|
| Command | Shell subprocess: linting, CI, logging |
| Prompt | Single LLM call: semantic safety checks |
| Agent | Multi-turn Agent Loop: complex verification |
| HTTP | REST POST: audit logging, webhooks |
| Callback | In-process async (SDK only): internal tracking |
| Function | Session-scoped callback: structured output enforcement |

**Exit code semantics**: 0 = success (silent), 1 = user-visible error (model unaware), 2 = blocking error (model must respond).

Hooks can **modify tool input** and **override permissions** (Allow/Deny/Ask), making them powerful enough to implement organizational policies (e.g., "all SQL queries must go through the read replica" or "never push directly to main").

### 9.2 Hermes Agent's Gateway Hooks

Hermes implements hooks at the gateway level:
- Each hook lives in `~/.hermes/hooks/<name>/` with `HOOK.yaml` (metadata + event list) and `handler.py`
- Events: `gateway:startup`, `session:{start,end,reset}`, `agent:{start,step,end}`, `command:*` (wildcard)
- Errors are caught and logged, never blocking the pipeline

### 9.3 Hooks as Organizational Policy Enforcement

Hooks are the mechanism by which organizations encode their policies into agent behavior:
- **Code review hooks**: Automatically run linters, type checkers, or security scanners after every file edit
- **Compliance hooks**: Ensure agent never accesses forbidden systems or writes to protected branches
- **Audit hooks**: Log every tool invocation to an external system for compliance tracking
- **Quality hooks**: Verify test coverage after code changes, block commits below a threshold

This makes the hook configuration itself a form of IP—it encodes the organization's development standards in machine-enforceable form.

---

## 10. Platform Integration and Protocol Support

### 10.1 MCP (Model Context Protocol)

Both systems implement full MCP support, but with different emphasis:

**Claude Code**:
- 6 transport types: Stdio, SSE, HTTP, WebSocket, SDK, ManagedProxy
- 11-phase lifecycle management (ConfigLoad through Cleanup) with validated state transitions
- Tool naming: `mcp__[server]__[tool]` convention
- MCP tools bypass agent tool-filtering layers (user-configured, user-responsible)

**Hermes Agent**:
- Background event loop in daemon thread for async server connections
- OAuth 2.1 PKCE authentication support
- Dynamic tool discovery with `tools/list_changed` notification handling
- Sampling support (server-initiated LLM calls) with rate limiting
- Reconnection with exponential backoff (up to 5 attempts, 60s cap)
- Security: environment filtering, credential stripping from errors, prompt injection detection in tool descriptions

### 10.2 Hermes Agent's Multi-Platform Gateway

Hermes stands out with its 18+ platform gateway: Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost, WeChat, WeCom, DingTalk, Feishu, QQ Bot, Email, SMS, BlueBubbles, Home Assistant, Webhook, and API Server.

The architecture:
- Central orchestrator: load config -> suspend crashed sessions -> create platform adapters -> connect -> register handlers -> launch background watchers
- Deterministic session key generation from platform/chat_id/thread_id
- Progressive streaming delivery with think-block filtering, overflow handling, and flood-control resilience
- Platform-specific formatting hints in system prompts

### 10.3 Multi-Provider LLM Support

**Claude Code** (via claw-code): Anthropic (primary), xAI/Grok, OpenAI, DashScope/Qwen.

**Hermes Agent**: OpenAI-compatible (OpenRouter, custom endpoints) and native Anthropic with dedicated adapter. Smart model routing for cost optimization—simple queries routed to cheaper models based on conservative classification (message length, code indicators, vocabulary complexity).

---

## 11. The Harness as Core IP: Architectural Implications

### 11.1 What Constitutes the Harness

Based on the analysis of these production systems, the "harness" comprises:

1. **System Prompt Architecture**: The layered prompt structure, safety rules, behavioral guidelines, and dynamic context assembly. This is the agent's constitution.

2. **Tool Registry**: The curated set of capabilities, their security constraints, concurrency rules, and result management. This defines what the agent *can do*.

3. **Skill Library**: The accumulated procedural knowledge—deployment workflows, debugging procedures, code review checklists, incident response playbooks. This is **learned organizational expertise**.

4. **Memory System**: The accumulated user preferences, behavioral calibrations, project context, and organizational reference points. This is **institutional knowledge**.

5. **Permission Model**: The security policies, trust hierarchy, and approval workflows. This encodes **organizational risk tolerance**.

6. **Hook Configuration**: The linting rules, compliance checks, audit trails, and quality gates. This encodes **organizational standards**.

7. **Context Management Strategy**: The compression pipeline, cache optimization, and token budget allocation. This encodes **operational efficiency**.

### 11.2 Why the Harness Matters More Than the Model

The model is a commodity. Claude, GPT, Gemini, DeepSeek—they're increasingly comparable in raw capability. What differentiates an agent is:

- **The model doesn't know your deployment procedure**—your skills do.
- **The model doesn't know your team's preferences**—your memory system does.
- **The model doesn't know your compliance requirements**—your hooks do.
- **The model doesn't enforce your security policies**—your permission model does.
- **The model doesn't manage its own context efficiently**—your compression pipeline does.

An organization that invests in building a sophisticated harness—rich skills, deep memory, precise permissions, comprehensive hooks—has an agent that is **qualitatively different** from one running the same model with a bare system prompt.

### 11.3 The Compound Effect

These components compound:
- Memory informs skill invocation ("this user prefers method A over method B")
- Skills build on tools (a deployment skill orchestrates 15 tool calls)
- Hooks enforce standards that skills produce ("run tests after every code edit")
- Permission models shape what skills are allowed to do
- Context management enables longer, more complex skill executions

A harness with 500 skills, 10,000 memory entries, and 50 hooks represents months of organizational learning encoded in machine-executable form. This cannot be replicated by switching models—it must be rebuilt from scratch.

### 11.4 Design Principles for Building a Harness

From the analysis of these production systems, key principles emerge:

1. **Fail-closed by default**: New capabilities should be restricted until explicitly proven safe. (Claude Code's `buildTool()` defaults)

2. **Separate discovery from execution**: Load metadata eagerly, content lazily. This applies to tools, skills, and memory. (Both systems)

3. **Progressive cost escalation**: Try the cheapest recovery/compression strategy first. Only escalate when cheaper approaches fail. (Claude Code's 5-level compression)

4. **Cache stability as architecture**: Every structural decision affects prompt cache efficiency. Tool ordering, prompt splitting, and session latching are architectural, not incidental. (Claude Code)

5. **Memory stores what code cannot**: Don't duplicate what's already in the codebase, git history, or documentation. Memory is for human context, behavioral calibration, and organizational knowledge. (Both systems)

6. **Skills are write-once, execute-many**: A good skill pays for its creation cost across hundreds of invocations. Invest in skill quality. (Both systems)

7. **Hooks encode policy, not logic**: Hooks should express organizational rules ("always lint after edit"), not implement business logic. Keep them simple and composable. (Both systems)

8. **Earned autonomy through transparency**: Start conservative, demonstrate competence, earn broader permissions. Plan Mode is the prototype. (Claude Code)

9. **Error withholding builds trust**: Users should see the agent working reliably, not struggling with transient errors. Handle operational problems transparently. (Both systems)

10. **Multi-agent for breadth, single-agent for depth**: Subagents are best for independent parallel tasks. Complex, sequential reasoning should stay in a single agent context. (Both systems)

---

## 12. Minimal Implementation Path

For organizations looking to build their own harness, the how-claude-code-works analysis suggests a staged evolution:

### Stage 1: Minimal Agent (~500 lines, 3 tools)
- System prompt with CWD, git context, OS info
- Tool registry with Read, Bash, Write
- Basic agent loop: user input -> model -> tool extraction -> execution -> loop

### Stage 2: Capable Agent (~2K lines)
- Add Edit, Grep, Glob tools
- Permission system (allow/deny rules)
- Basic error handling and retries

### Stage 3: Production Agent (~5K lines)
- Streaming execution
- Context compression (tool result pruning + LLM summarization)
- Retry with graduated recovery strategies
- Memory system (file-based, session-injected)

### Stage 4: Enterprise Agent (~20K lines)
- Progressive compression pipeline (5 levels)
- AST-based bash security + OS-level sandboxing
- MCP integration for external tools
- Multi-agent coordination with git worktrees
- Skill system with lazy loading
- Hook system with policy enforcement
- Prompt cache optimization

Each stage is self-contained and usable. The key is to **not skip stages**—each builds competence and understanding needed for the next.

---

## Appendix A: Technology Stacks

| Component | Claude Code | Hermes Agent |
|---|---|---|
| Language | TypeScript (original), Rust (rewrite) | Python |
| Runtime | Bun | Python 3.x |
| Terminal UI | React + Ink + Yoga (WASM) | Rich / platform adapters |
| CLI Framework | Commander.js | argparse / custom |
| Validation | Zod | Pydantic-style / custom |
| LLM SDK | Anthropic SDK | OpenAI SDK + Anthropic adapter |
| AST Parsing | tree-sitter (Bash security) | ast module (tool discovery) |
| Concurrency | Async generators + StreamingToolExecutor | asyncio + ThreadPoolExecutor |
| Sandbox | sandbox-exec (macOS) / bubblewrap (Linux) | Container detection + approval modes |
| MCP | 6 transports, 11-phase lifecycle | Stdio + HTTP, OAuth 2.1 PKCE |

## Appendix B: Scale Metrics

| Metric | Claude Code | Hermes Agent |
|---|---|---|
| Built-in tools | 66+ | 54+ |
| Skill categories | 17 bundled | 26+ built-in |
| Platform integrations | CLI + IDE | 18+ messaging platforms |
| Security checks (Bash) | 23 AST-based | 50+ regex patterns |
| Hook event types | 27 | ~10 gateway events |
| Context compression levels | 5 | 5 phases |
| Agent types | 6 specialized | 1 + delegation + mixture |
| Permission sources | 7-layer hierarchy | Config + approval modes |
| Bootstrap phases | 11 (235ms critical path) | Single-phase |
| Original codebase | ~512K lines TypeScript | ~11K lines core Python |
