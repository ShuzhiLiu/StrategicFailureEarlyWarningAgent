"""Generate self-contained HTML report from pipeline output artifacts."""
from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_timeline(jsonl_path: Path) -> list[dict]:
    """Transform llm_history.jsonl into structured timeline events."""
    if not jsonl_path.exists():
        return []

    events: list[dict] = []
    # Track last tool_loop LLM call per (node, iteration-key) to deduplicate.
    # (ToolLoopAgent logs the full conversation at EACH iteration; only the
    # final one carries the complete multi-turn transcript.)
    _last_tool_loop: dict[str, int] = {}  # node -> event index in `events`

    for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines():
        record = json.loads(line)

        if "event_type" in record:
            # Pipeline event: node_enter, node_exit, action, routing, parallel_*
            events.append({
                "id": len(events),
                "type": record["event_type"],
                "node": record.get("node", ""),
                "timestamp": record.get("timestamp", ""),
                "data": record.get("data", {}),
            })
        elif "tool_name" in record:
            # Tool call record
            events.append({
                "id": len(events),
                "type": "tool_call",
                "node": record.get("node", ""),
                "timestamp": record.get("timestamp", ""),
                "tool_name": record.get("tool_name", ""),
                "tool_inputs": record.get("inputs", {}),
                "tool_output": record.get("output", ""),
            })
        elif "messages" in record:
            # LLM call — extract system/user for simple calls,
            # and full conversation for tool-loop agents
            messages = record.get("messages", [])
            system_prompt = ""
            user_prompt = ""
            for msg in messages:
                if msg.get("role") == "system":
                    system_prompt = msg.get("content", "")
                elif msg.get("role") == "user":
                    user_prompt = msg.get("content", "")

            # Build chat-format conversation from messages
            conversation = _build_conversation(messages)

            # For simple LLM calls (not tool_loop), the response is NOT in
            # the messages array — it's in the record's content/thinking fields.
            # Append it so the conversation view shows the full exchange.
            response_content = record.get("content", "")
            thinking_content = record.get("thinking", "")
            has_assistant_msg = any(m.get("role") == "assistant" for m in messages)
            if not has_assistant_msg and (response_content or thinking_content):
                assistant_entry: dict = {"role": "assistant", "content": _truncate(response_content)}
                if thinking_content:
                    assistant_entry["thinking"] = _truncate(thinking_content)
                conversation.append(assistant_entry)

            node = record.get("node", "")
            label = record.get("label", "")

            event = {
                "id": len(events),
                "type": "llm_call",
                "node": node,
                "timestamp": record.get("timestamp", ""),
                "label": label,
                "system_prompt": system_prompt,
                "user_prompt": _truncate(user_prompt),
                "response": record.get("content", ""),
                "thinking": record.get("thinking", ""),
                "token_usage": record.get("usage", {}),
                "conversation": conversation,
            }

            # Deduplicate tool_loop calls: each iteration logs the FULL
            # conversation, so only keep the last one (most complete).
            if label == "tool_loop":
                key = node
                if key in _last_tool_loop:
                    # Replace previous with this one (more complete)
                    prev_idx = _last_tool_loop[key]
                    event["id"] = events[prev_idx]["id"]
                    events[prev_idx] = event
                else:
                    _last_tool_loop[key] = len(events)
                    events.append(event)
            else:
                events.append(event)

    return events


_MAX_MSG_CHARS = 200_000  # Safety cap only — normal messages pass through intact


def _truncate(text: str, limit: int = _MAX_MSG_CHARS) -> str:
    if not text or len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n... [{len(text) - limit:,} characters truncated] ...\n\n" + text[-half:]


def _build_conversation(messages: list[dict]) -> list[dict]:
    """Build a chat-format conversation from OpenAI-style messages.

    Groups tool calls with their results for a clean chat view.
    Truncates very long messages to keep the HTML manageable.
    """
    conv: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            conv.append({"role": "system", "content": _truncate(msg.get("content", ""))})
        elif role == "user":
            conv.append({"role": "user", "content": _truncate(msg.get("content", ""))})
        elif role == "assistant":
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", [])
            entry: dict = {"role": "assistant", "content": _truncate(content)}
            if tool_calls:
                entry["tool_calls"] = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    entry["tool_calls"].append({
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", ""),
                    })
            conv.append(entry)
        elif role == "tool":
            conv.append({
                "role": "tool",
                "name": msg.get("name", ""),
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": _truncate(msg.get("content", "")),
            })
    return conv


def generate_report(output_dir: Path) -> Path:
    """Read artifacts from output_dir, inject into HTML template, write report.html."""
    # Load all artifact files
    data: dict = {}
    data["summary"] = _load_json(output_dir / "run_summary.json")

    evidence_path = output_dir / "evidence.json"
    data["evidence"] = _load_json(evidence_path) if evidence_path.exists() else []

    factors_path = output_dir / "risk_factors.json"
    data["risk_factors"] = _load_json(factors_path) if factors_path.exists() else []

    challenges_path = output_dir / "challenges.json"
    data["challenges"] = _load_json(challenges_path) if challenges_path.exists() else []

    backtest_path = output_dir / "backtest.json"
    data["backtest"] = _load_json(backtest_path) if backtest_path.exists() else {}

    memo_path = output_dir / "risk_memo.md"
    data["memo"] = memo_path.read_text(encoding="utf-8") if memo_path.exists() else ""

    # Parse timeline from llm_history
    data["timeline"] = _parse_timeline(output_dir / "llm_history.jsonl")

    # Inject into template
    template_path = Path(__file__).parent / "template.html"
    template = template_path.read_text(encoding="utf-8")
    html = template.replace("/* __SFEWA_DATA__ */ {}", json.dumps(data, ensure_ascii=False))

    dest = output_dir / "report.html"
    dest.write_text(html, encoding="utf-8")
    return dest


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m sfewa.web <output_directory>")
        print("  e.g. python -m sfewa.web outputs/honda_motor_co_20250519_20260410_020235/")
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    if not output_dir.is_dir():
        print(f"Error: {output_dir} is not a directory")
        sys.exit(1)

    summary_file = output_dir / "run_summary.json"
    if not summary_file.exists():
        print(f"Error: {output_dir} does not contain run_summary.json")
        sys.exit(1)

    report_path = generate_report(output_dir)
    print(f"Report generated: {report_path}")
    webbrowser.open(f"file://{report_path.resolve()}")


if __name__ == "__main__":
    main()
