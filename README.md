# tidy-chats

A Claude Code plugin that keeps the desktop app's Code-tab sidebar tidy as a side effect of
normal chat turns. No scheduled job.

- **Pinned** holds only chats in progress: a new chat pins itself, a finished one unpins itself,
  and any chat you write in again pins itself and drops its `done: ` prefix.
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
claude plugin marketplace add S3yon/tidy-chats
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
| `routine_titles` | empty | Regex for routine run titles: archived after 1 h idle, never filed |

## Skills
- `/tidy-chats:tidy`: sweep now instead of waiting.
- `/tidy-chats:status`: last sweep and when the next is due, finished chats held back by an open
  one, rules in force, recent sidebar actions.
- `/tidy-chats:rules`: approve or reject rule ideas learned from your undos.

## Never archived
The chat running the sweep, a running chat, a pinned chat, a chat with an open chat nested
under it, a chat with no activity time, and anything a rule you approved exempts.

A finished chain of hand-offs stays open while its last chat is open or pinned, because
archiving a chat also archives the idle chats nested under it. Status counts these
("Held back: 26 finished chats wait on 12 open chats they started"). A section's number in the
sidebar also counts its archived chats, so it can read 209 while 38 are open.

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
v0.1.9: running live in the desktop app since 2026-11-16. Seen working in real chats: the
first-turn and pick-up notes (a pick-up renamed the old chat `done: `, unpinned it, detached,
filed and pinned itself before its first reply), the finish steps, and a sweep from a Stop
(107 chats checked: 1 archived, 1 unpinned). The live run found three bugs, each fixed
test-first: an over-size chat list (0.1.1), turns the app started reopening done chats (0.1.2),
and a sweep unpinning a hand-off whose pick-up card was still unclicked (0.1.3). 0.1.4 pins any
chat you write in; 0.1.5 fixes the code review's smaller findings (locks, parallel hooks,
declined calls, rule ideas) and logs the options each sweep planned with. 0.1.6: a finished pick-up chat
no longer gets a false "steps missed" note at its last turn, which had used up the turn a
sweep was due on. 0.1.7: status says when the next sweep is due or how late it is. 0.1.8:
status says how many finished chats wait on an open chat they started, and in which sections.
0.1.9: a sweep no longer plans a section move for a routine run (the app keeps scheduled
runs under their task and refuses the move).

## License
MIT
