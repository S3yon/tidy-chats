# tidy-chats

A Claude Code plugin that keeps the desktop app's Code-tab sidebar tidy as a side effect of
normal chat turns. No scheduled job.

- **Pinned** holds only chats in progress: a new chat pins itself, a finished one unpins itself.
- **Sections:** a new chat files itself into the closest existing section.
- **Finished chats** rename themselves `done: <title>` and mark themselves completed.
- **Pick-ups:** a chat that continues work handed off by another chat (even one that chat
  started as a side session) detaches from it, files and pins itself, renames the old chat
  `done: ` and unpins it, so one open chat no longer holds a whole chain open.
- **Hand-offs:** a chat that starts a `Pick up: ...` session keeps its pin until the pick-up
  chat unpins it, so Pinned always shows the next click.
- **Archive:** every few hours one chat runs a sweep that archives finished chats idle 24 h+,
  any chat idle 14 days+, and routine runs idle 1 h+.
- **Learning:** when you undo something it did (re-pin, move, unarchive), it proposes a rule.
  Nothing applies until you approve it with `/tidy-chats:rules`.

## How it works
Hooks cannot call the app's sidebar tools, so the work is split in two:
- The hooks add a short note to the chat at the right moment (first prompt, finished turn,
  sweep due). The model makes the sidebar tool calls.
- A hook watches each sidebar tool call and records it, so a skipped step gets one reminder at
  Stop, and the sweep plan knows what was done before.

During a sweep, the chat's `list_sessions` output is replaced with a short plan (a few hundred
words instead of the full list), so a sweep costs little context.

It runs only in the desktop app, in attended chats. Everywhere else the hooks do nothing.
Every hook returns valid output even on error, so a broken install never blocks a chat.

## Install
Needs Python 3.9+ on `PATH` as `python3`.

```bash
claude plugin marketplace add <path or git URL of this repo>
```

```bash
claude plugin install tidy-chats@tidy-chats
```

## Options
Set when the plugin is enabled, or later in `/config`.

| Option | Default | What it does |
|---|---|---|
| `sweep_hours` | 6 | Hours between sweeps |
| `finished_idle_hours` | 24 | Archive `done:` / `handed off:` chats after this many idle hours |
| `idle_days` | 14 | Archive any chat idle this many days |
| `archive` | `auto` | `auto` archives in the sweep; `ask` asks one yes/no question first |
| `routine_titles` | empty | Regex for routine run titles: never pinned, archived after 1 h idle |

## Skills
- `/tidy-chats:tidy`: sweep now instead of waiting.
- `/tidy-chats:status`: last sweep, rules in force, recent sidebar actions.
- `/tidy-chats:rules`: approve or reject rule ideas learned from your undos.

## Never archived
The chat running the sweep, a running chat, a pinned chat, a chat with an open chat nested
under it, a chat with no activity time, and anything a rule you approved exempts.

## Development
```bash
python3 -m pytest -q
```

```bash
claude plugin validate .
```

State lives in the plugin data folder (`${CLAUDE_PLUGIN_DATA}`); `TIDY_CHATS_DATA` overrides it.
`keeper.py debug on` saves samples of the sidebar tool calls to `samples/` there.

## Status
v0.1.0: built test-first; not yet run live.

## License
MIT
