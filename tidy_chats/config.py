"""Options, the active check and the chat's own id, all read from the hook's environment."""

DEFAULTS = {"sweep_hours": 6.0, "finished_idle_hours": 24.0, "idle_days": 14.0,
            "archive": "auto", "routine_titles": ""}
NUMBERS = ("sweep_hours", "finished_idle_hours", "idle_days")


def options(env):
    out = dict(DEFAULTS)
    for key in DEFAULTS:
        raw = env.get("CLAUDE_PLUGIN_OPTION_" + key.upper())
        if raw is None or str(raw).strip() == "":
            continue
        if key in NUMBERS:
            try:
                val = float(raw)
            except ValueError:
                continue
            if val > 0:
                out[key] = val
        elif key == "archive":
            if str(raw).strip().lower() in ("auto", "ask"):
                out[key] = str(raw).strip().lower()
        else:
            out[key] = str(raw)
    return out


def active(env):
    if env.get("TIDY_CHATS_FORCE") == "1":
        return True
    return (env.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop"
            and env.get("CLAUDE_CODE_SESSION_ATTENDED") == "1")


def chat_id(payload, env):
    return env.get("CLAUDE_CODE_HOST_SESSION_ID") or payload.get("session_id") or "unknown"


def has_wrap_up(env):
    return "wrap_up" in (env.get("CLAUDE_CODE_TERMINAL_MCP_TOOLS") or "")
