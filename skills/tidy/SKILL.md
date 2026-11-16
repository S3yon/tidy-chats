---
name: tidy
description: Tidy the desktop app's Code-tab sidebar now instead of waiting for the next automatic sweep - archive finished chats, unpin done ones, file unfiled ones. Use when the user says "tidy my chats", "clean up the sidebar" or "sweep now".
---

# Sweep the sidebar now

1. Take the sweep lock for this chat: `TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" sweep-now`.
   Exit code 1 means another chat is sweeping: say so in one line and stop.
2. Call `list_sessions` with limit 200. If it is deferred, load it first with ToolSearch
   `select:mcp__ccd_session_mgmt__list_sessions`. tidy-chats replaces its output with a short plan.
3. Do what the plan says, loading the sidebar tools it names in one ToolSearch call.
4. Reply with one short line of what changed. The lock frees itself when this turn ends.

## Done when
Every action in the plan was made (or failed and was skipped), and the reply says what changed in one line.
