    when every model on the ladder failed; the reason for each is printed, since
    a silent None during a session nobody can debug is how the original problem
    stayed hidden.
    """
    # `tier` is normally FAST or SMART. Anything else is taken to be an explicit
    # model name — screen_agent lets the user pick one in its settings — and it
    # is tried first, with the reasoning ladder behind it. So a user's choice is
    # honoured, and a user's choice that is having an outage still degrades to
    # something that answers instead of to nothing.
    ladder = _LADDERS.get(tier)
    if ladder is None:
        ladder = (tier,) + tuple(m for m in _LADDERS[SMART] if m != tier)

    resolved_key = key or api_key()
    cl = None

    # Cloud remains the preferred path. Local Ollama is a final fallback for
    # text-only one-shot work so normal Live conversation and grounded search
    # semantics stay unchanged.
    if resolved_key:
        tried = [m for m in ladder if not _cooling(m)] or list(ladder)
        for model in tried:
            try:
                if model == LIVE:
                    reply = _live_call(contents, config, timeout_ms, resolved_key)
                    if reply is not None:
                        return reply
                    raise RuntimeError("the Live turn came back empty")
                if cl is None:
                    cl = client(timeout_ms=timeout_ms, key=resolved_key)
                kwargs = {"model": model, "contents": contents}
                if config is not None:
                    kwargs["config"] = config
                return cl.models.generate_content(**kwargs)
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    _cool(model)
                    print(f"[Gemini] {model}: out of quota — skipping it for "
                          f"{_COOLDOWN_SECONDS // 60} minutes")
                else:
                    print(f"[Gemini] {model}: {type(e).__name__}: {msg[:140]}")
    else:
        print("[Gemini] no Gemini API key is configured; trying local AI fallback")

    # Grounded search requires REST grounding metadata. Never replace it with a local answer.\n    if tier == SEARCH:\n        return None\n\n    # Do not silently turn an image-bearing request into a text-only request.\n    plain_parts = contents if isinstance(contents, (list, tuple)) else [contents]\n    local_text_parts = []
    has_binary = False
    for item in plain_parts:
        if isinstance(item, str):
            local_text_parts.append(item)
            continue
        if getattr(item, "inline_data", None) is not None:
            has_binary = True
            break
        text_part = getattr(item, "text", None)
        if text_part:
            local_text_parts.append(text_part)
        elif isinstance(item, dict) and item.get("text"):
            local_text_parts.append(str(item["text"]))

    if not has_binary and local_text_parts:
        try:
            from core.local_model_router import fallback_text
            system = ""
            if config is not None:
                system = getattr(config, "system_instruction", None) or ""
                if isinstance(config, dict):
                    system = config.get("system_instruction", "") or ""
            answer = fallback_text(
                "\n\n".join(local_text_parts),
                tier=tier if tier in (FAST, SMART) else FAST,
                system=system,
                timeout=max(15.0, timeout_ms / 1000.0),
            )
            if answer:
                return _Reply(answer)
        except Exception as e:
            print(f"[LocalAI] fallback exception: {e}")

    return None


def text(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default: str = "") -> str:
    """`call`, reduced to the reply text. `default` when nothing answered."""
    resp = call(contents, tier=tier, config=config,
                timeout_ms=timeout_ms, key=key)
    if resp is None:
        return default
    return (getattr(resp, "text", None) or "").strip() or default


def as_json(contents, tier: str = FAST, config=None,
            timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default=None):
    """`text`, parsed as JSON, tolerating the fences and prose a model wraps it
    in. `default` when nothing answered or the answer would not parse."""
    raw = text(contents, tier=tier, config=config, timeout_ms=timeout_ms, key=key)
    if not raw:
        return default
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    elif "[" in raw and "]" in raw:
        raw = raw[raw.find("["): raw.rfind("]") + 1]
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[Gemini] reply was not JSON: {e}")
        return default