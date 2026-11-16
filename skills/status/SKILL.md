---
name: status
description: Show what tidy-chats has been doing - last sweep, the sweep lock, approved rules, waiting rule ideas and the last 10 sidebar actions. Use when the user asks "what has tidy-chats done", "tidy-chats status" or why a chat was archived or unpinned.
---

# tidy-chats status

!`TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" status`

Summarise that in plain words, five lines at most: when the last sweep ran, what was tidied
recently, and the rules in force. If rule ideas are waiting, end with: run `/tidy-chats:rules`.
To answer why a chat was archived or unpinned, find it in the actions above.

## Done when
The user has the summary, and knows about waiting rule ideas if there are any.
