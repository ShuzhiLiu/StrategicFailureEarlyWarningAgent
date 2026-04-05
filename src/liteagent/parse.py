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
    # Important: try the bracket that appears EARLIEST in the text.
    # When LLM returns [{"a":1},...], trying { first would extract just the
    # first object instead of the full array.
    pairs = [("{", "}"), ("[", "]")]
    pos_obj = text.find("{")
    pos_arr = text.find("[")
    if pos_arr != -1 and (pos_obj == -1 or pos_arr < pos_obj):
        pairs = [("[", "]"), ("{", "}")]

    for start_char, end_char in pairs:
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
    and retries. This is the pattern every SFEWA agent uses -- extracted
    into a reusable function.

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

    raise json.JSONDecodeError("Parse failed after retries", "", 0)


def validate_items(
    items: list[dict],
    required_fields: list[str],
    *,
    on_invalid: Callable[[dict, str], None] | None = None,
) -> list[dict]:
    """Validate a list of parsed items, keeping only valid ones."""
    valid = []
    for item in items:
        missing = [f for f in required_fields if not item.get(f)]
        if missing:
            if on_invalid:
                on_invalid(item, f"Missing required fields: {missing}")
        else:
            valid.append(item)
    return valid
