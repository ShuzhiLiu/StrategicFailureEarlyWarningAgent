"""Pipeline utilities -- building blocks for multi-step agent pipelines.

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
                   E.g., {"evidence", "risk_factors"} -- lists grow across nodes.

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

    Each node receives a COPY of the state (isolation -- no concurrent mutation).
    Results are returned in completion order.
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
    """
    for _ in range(max_passes):
        state = merge_state(state, generate(state), accumulate=accumulate)
        state = merge_state(state, evaluate(state), accumulate=accumulate)

        if not should_retry(state):
            break

    return state
