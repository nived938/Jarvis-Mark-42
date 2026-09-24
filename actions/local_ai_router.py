"""Direct user-facing tool for the local Ollama model router."""
from __future__ import annotations

from core.local_model_router import generate, installed_models, select_model, is_available
from memory.config_manager import (
    get_local_ai_enabled, save_local_ai_enabled,
    get_local_ai_model, save_local_ai_model,
    get_local_ai_mode, save_local_ai_mode,
)


def _handler(parameters=None, player=None, **_):
    p = parameters or {}
    action = str(p.get("action", "ask")).strip().lower()

    if action == "status":
        models = sorted(installed_models())
        selected = get_local_ai_model() or "AUTO"
        mode = get_local_ai_mode()
        return (
            "Local AI is "
            + ("enabled" if get_local_ai_enabled() else "disabled")
            + "; Ollama is "
            + ("available" if is_available() else "not reachable")
            + f"; selected model: {selected}; mode: {mode}. "
            + "Installed models: "
            + (", ".join(models) if models else "none")
        )

    if action in {"enable", "disable"}:
        enabled = action == "enable"
        save_local_ai_enabled(enabled)
        if player is not None and hasattr(player, "show_local_ai_picker"):
            try:
                player.show_local_ai_picker()
            except Exception:
                pass
        return f"Local AI {'enabled' if enabled else 'disabled'}."

    if action in {"show", "picker"}:
        if player is not None and hasattr(player, "show_local_ai_picker"):
            try:
                player.show_local_ai_picker()
            except Exception:
                pass
        selected = get_local_ai_model() or "AUTO"
        return f"Local AI picker opened. Selected model: {selected}. Mode: {get_local_ai_mode()}."

    if action == "models":
        models = sorted(installed_models(refresh=True))
        if player is not None and hasattr(player, "show_local_ai_picker"):
            try:
                player.show_local_ai_picker()
            except Exception:
                pass
        return "Installed Ollama models:\n" + "\n".join(f"- {m}" for m in models) if models else "No Ollama models were discovered."

    if action == "set_model":
        model = str(p.get("model", "") or "").strip()
        models = installed_models(refresh=True)
        if not model or model not in models:
            return "That Ollama model is not installed."
        save_local_ai_model(model)
        if player is not None and hasattr(player, "show_local_ai_picker"):
            try:
                player.show_local_ai_picker()
            except Exception:
                pass
        return f"Local AI model selected: {model}."

    if action == "set_mode":
        mode = str(p.get("mode", "") or "").strip().lower()
        if mode not in {"fast", "balanced", "smart", "vision"}:
            return "Mode must be fast, balanced, smart, or vision."
        save_local_ai_mode(mode)
        return f"Local AI mode set to {mode}."

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
            "action": {"type": "STRING", "description": "ask | status | models | show | picker | enable | disable | set_model | set_mode"},
            "prompt": {"type": "STRING", "description": "Prompt to send to the local model"},
            "mode": {"type": "STRING", "description": "fast | balanced | smart | vision; used for ask or set_mode"},
            "system": {"type": "STRING", "description": "Optional system instruction"},
            "image_path": {"type": "STRING", "description": "Optional local image path for vision mode"},
            "model": {"type": "STRING", "description": "Exact installed Ollama model for ask or set_model"},
            "timeout": {"type": "NUMBER", "description": "Request timeout in seconds"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
