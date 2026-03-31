---
paths:
  - "src/sfewa/agents/**/*.py"
---

# Agent Implementation Rules
- Each agent is a single function that takes PipelineState and returns a dict of state updates
- All LLM calls must use structured output (Pydantic models) not free-form text
- Every evidence reference must include evidence_id traceability
- Never access data beyond the cutoff_date in PipelineState
- Agent functions must be stateless — all state flows through PipelineState
- Use prompts from src/sfewa/prompts/, not inline strings
