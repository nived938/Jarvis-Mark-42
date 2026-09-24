"""JARVIS reasoning tier.

A compact second-pass reasoning tool for complex requests. It returns a decision
summary and executable plan, not private chain-of-thought.
"""
from __future__ import annotations

import json

from core import gemini


def _handler(parameters, **_):
    goal = str(parameters.get("goal", "") or "").strip()
    context = str(parameters.get("context", "") or "").strip()
    mode = str(parameters.get("mode", "plan") or "plan").strip().lower()
    if not goal:
        return "No reasoning goal was provided."

    prompt = f"""
You are the reasoning tier inside a desktop AI assistant.
Do not reveal private chain-of-thought or hidden reasoning.
Solve the user's goal using only the supplied system context.
Return compact JSON with these keys:
decision_summary, assumptions, ordered_steps, tools, risks, done_when.
ordered_steps must be concrete actions the main assistant can perform.
Prefer direct tools over unnecessary planning. When a step depends on a previous
result, say so. Never invent tool results.
MODE: {mode}
GOAL: {goal}
CONTEXT: {context}
"""
    try:
        response = gemini.call(prompt, tier=gemini.SMART, timeout_ms=60000)
        text = getattr(response, "text", None) if response is not None else None
        if not text:
            return "Reasoning tier unavailable. Use the available tools directly."
        cleaned = str(text).strip()
        try:
            data = json.loads(cleaned)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return cleaned
    except Exception as exc:
        return f"Reasoning tier failed: {exc}"


TOOL = {
    "name": "jarvis_brain",
    "description": (
        "Use for complex, multi-step, ambiguous, diagnostic, or decision-heavy requests. "
        "It performs a second reasoning pass and returns a concise executable plan without "
        "private chain-of-thought. Do not use it for simple one-step commands."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {"type": "STRING", "description": "What the user actually wants"},
            "context": {"type": "STRING", "description": "Relevant current state, prior results, or constraints"},
            "mode": {"type": "STRING", "description": "plan | diagnose | decide"},
        },
        "required": ["goal"],
    },
    "handler": _handler,
}
