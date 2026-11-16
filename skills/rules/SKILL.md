---
name: rules
description: Review tidy-chats rule ideas, learned from times the user undid its sidebar tidying, and approve or reject each one. Use when a sweep ends with "tidy-chats has N rule ideas", or the user says "review tidy-chats rules" or "what has tidy-chats learned".
---

# Review tidy-chats rule ideas

Waiting ideas, at load time:

!`TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" ideas`

Nothing applies until the user says yes. Each idea came from the user reversing something tidy-chats did.

1. No ideas waiting: say so in one line and stop.
2. Ask with AskUserQuestion, one question per idea (up to 4 per call). Name the chat and what the user did. Options, recommended first:
   - "Just this chat": scope `chat`
   - "Every chat with \"<word>\"": scope `word:<word>`, using one distinctive word from the title (leave this out if no word fits)
   - For a section idea only, "Every chat in this folder": scope `folder`
   - "No": reject, and it is never raised again
3. For each answer run one of:
   - `TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" accept <id> <scope>`
   - `TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" reject <id>`
4. Show the rules now in force: `TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" rules`.

What each rule does: `keep_pinned` (sweeps never unpin it), `never_archive` (sweeps never archive it),
`section` (new chats that match are told to file into that section).
To remove a rule: `TIDY_CHATS_DATA="${CLAUDE_PLUGIN_DATA}" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" remove-rule <n>`.

## Done when
Every waiting idea is accepted or rejected, and the user has seen the rule list.
