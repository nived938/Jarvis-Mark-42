"""Direct user-facing tool for the local Ollama model router."""
from __future__ import annotations

from core.local_model_router import generate, installed_models, select_model, is_available
from memory.config_manager import get_local_ai_enabled, save_local_ai_enabled


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "ask")).strip().lower()

    if action == "status":
        models = sorted(installed_models())
        return (
            "Local AI is "
            + ("enabled" if get_local_ai_enabled() else "disabled")
            + "; Ollama is "
            + ("available" if is_available() else "not reachable")
            + ". Installed models: "
            + (", ".join(models) if models else "none")
        )

    if action in {"enable", "disable"}:
        enabled = action == "enable"
        save_local_ai_enabled(enabled)
        return f"Local AI {'enabled' if enabled else 'disabled'}."

    if action == "models":
        models = sorted(installed_models(refresh=True))
        return "Installed Ollama models:\n" + "\n".join(f"- {m}" for m in models) if models else "No Ollama models were discovered."

    prompt = str(p.get("prompt", "")).strip()
    if not prompt:
        return "Provide a prompt for the local AI."
    mode = str(p.get("mode", "balanced")).strip().lower()
    image_path = str(p.get("image_path", "")).strip()
    model = str(p.get("model", "")).strip()

    try:
        picked = model or select_model(mode=mode, has_image=bool(image_path))
        answer = generate(
            prompt,
            mode=mode,
            system=str(p.get("system", "") or ""),
            image_path=image_path,
            timeout=float(p.get("timeout", 45) or 45),
            model=model,
        )
        return f"[Local AI: {picked}]\n{answer}"
    except Exception as exc:
        return f"Local AI failed: {exc}"


TOOL = {
    "name": "local_ai_router",
    "description": (
        "Use JARVIS's local Ollama models for private/offline text or vision work. "
        "Use action status/models to inspect the local AI installation, or ask to "
        "run a prompt locally. The router automatically chooses an installed model "
        "based on task type and available RAM."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "ask | status | models | enable | disable"},
            "prompt": {"type": "STRING", "description": "Prompt to send to the local model"},
            "mode": {"type": "STRING", "description": "fast | balanced | smart | vision"},
            "system": {"type": "STRING", "description": "Optional system instruction"},
            "image_path": {"type": "STRING", "description": "Optional local image path for vision mode"},
            "model": {"type": "STRING", "description": "Optional exact installed Ollama model"},
            "timeout": {"type": "NUMBER", "description": "Request timeout in seconds"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
