# tidy-chats design

Date: 2026-11-15. Status: approved from the visual pack and quiz (same day).

## Goal
Keep the desktop app's Code-tab sidebar tidy as a side effect of normal chat turns, with no
scheduled job: Pinned holds only chats in progress, every chat sits in a section, finished chats
get marked and archived, and the keeper learns from the user's undos. Ship it as a Claude Code
plugin anyone with the desktop app can install.

## Decisions (quiz answers, 2026-11-15)
| Question | Answer |
|---|---|
| How it runs | Hook keeper: each chat tidies itself; one chat runs an overdue sweep |
| v1 scope | Pin, file, mark done, unhook pick-ups, archive finished chats idle 24 h+, on its own |
| Learning | From the user's overrides, but the user approves each rule |
| Name, home | `tidy-chats`, own repo, private until it has run live, then public |

## Why hooks and not rules or a cron
Written rules ("pin on the first turn") drift: one user had 18 pins with 11 stale and 138 of
192 open chats already finished. A cron needs a scheduler the user may turn off. Hooks run on
every turn whatever the model remembers. Prior art and the five options considered: see the
research note in the author's knowledge base (git gc --auto, Kubernetes controllers, Redis
expiry were the models for "upkeep piggybacks on normal work").

## Hard constraint
Hooks are shell commands. They cannot call the app's sidebar tools (`mcp__ccd_*`). So the keeper
works in two halves:
- **The model acts.** Hooks put short factual notes into the chat (`additionalContext`) at the
  right moment; the model makes the tool calls.
- **Hooks watch and remember.** PostToolUse hooks see each sidebar tool call and record it, so
  the keeper knows what was done and can enforce once at Stop if a step was skipped.

## Moments
| Moment | Signal | What the chat is told |
|---|---|---|
| New chat | First UserPromptSubmit with no state for this chat | File into the closest existing section, then pin; detach first if it continues work handed off by another chat; skip pinning for routine runs and nested side sessions |
| Finished | PostToolUse on `mcp__ccd_turn__wrap_up` with no `ask` (nothing waits on the user) | Before the closing message: rename `done: <title>`, unpin, mark completed |
| Waiting | `wrap_up` with an `ask` | Nothing; stays pinned |
| Reopened | UserPromptSubmit in a chat marked done | Drop the `done: ` prefix and pin again |
| Missed step | Stop, step still not seen | One Stop note naming the step (at most once per moment) |
| Sweep due | Stop, last sweep over `sweep_hours` ago, lock free, turn not waiting on the user | Call `list_sessions` (limit 200); the hook swaps its output for a short plan; do the plan |

Fallback when the app has no `wrap_up` tool: a turn counts as finished when the last assistant
message does not end in a question (checked at Stop).

## The sweep
- **Lock:** one global lock file; stale after 20 minutes. The holder is the chat whose Stop took it.
- **Plan swap:** PostToolUse on `list_sessions` in the lock-holding chat replaces the tool output
  (`updatedMCPToolOutput`) with a plan of at most a few hundred words. Any other `list_sessions`
  call passes through untouched.
- **Plan contents:**
  - Archive: title starts `done:` or `handed off:` and idle `finished_idle_hours` (24) or more;
    any chat idle `idle_days` (14) or more; titles matching `routine_titles` idle 1 h or more.
    Never the sweeping chat, a running chat, a pinned chat, or one with an open chat nested
    below it. Repeats until nothing changes (archiving a nested last chat frees its parent), and
    lists only the top of each archived chain, since archiving a parent takes its idle nested chats.
  - Unpin: pinned chats whose title starts `done:` or `handed off:`.
  - File: chats not in any section and not nested (the model picks the closest section).
  - Rule ideas waiting: a count and the command to review them.
  - Learned rules exempt matching chats from each action.
- **Release:** the next Stop in the holder (a continuation) records `last_sweep_at` and frees the
  lock, whether or not the model did the plan, so a failing sweep backs off like `git gc --auto`.
- **Big chats skip:** a chat whose transcript file is over 4 MB does not take the lock unless the
  sweep is a day overdue, so sweeps land in cheap chats.
- **Archive mode:** `archive` option `auto` (default; the user chose this) lists archives as
  actions; `ask` lists them as one yes/no question for the user.

## Learning
- Every sidebar action the model makes is appended to an action log (target chat, action, detail).
- During a sweep the planner compares the log with the live list. An override is the user
  reversing the last logged action: re-pinned a chat the keeper unpinned, moved a chat to another
  section than the one it was filed into, or brought back a chat the keeper archived.
- Each override becomes a rule idea (deduplicated, with a count). Nothing applies until the user
  approves it with `/tidy-chats:rules`, which asks one question per idea: just this chat, every
  chat matching a title word (or folder, for sections), or no. A "no" is remembered.
- Rule kinds: `keep_pinned`, `never_archive`, `section` (folder or title word → section name).
  Section rules are given to new chats in the first-turn note.

## Scope guards
- Runs only in the desktop app (`CLAUDE_CODE_ENTRYPOINT=claude-desktop`) and attended sessions
  (`CLAUDE_CODE_SESSION_ATTENDED=1`); a no-op elsewhere. `TIDY_CHATS_FORCE=1` overrides for tests.
- Ignores hook input from subagents (`agent_id` present).
- Never blocks with an error: every handler catches exceptions, logs them, and returns `{}`.
- State lives in `${CLAUDE_PLUGIN_DATA}` (`TIDY_CHATS_DATA` overrides). Writes are atomic.
- The chat's own id comes from `CLAUDE_CODE_HOST_SESSION_ID`, falling back to the hook's `session_id`.

## Components
| Unit | Job |
|---|---|
| `tidy_chats/state.py` | Data dir, per-chat state, sweep lock, action log, rules, rule ideas; atomic JSON writes |
| `tidy_chats/planner.py` | Pure: list of chats + rules + log + now → plan (archive, unpin, file, overrides) |
| `tidy_chats/notes.py` | The note texts and the plan rendering |
| `tidy_chats/hooks.py` | One handler per event; reads stdin JSON, writes hook output JSON |
| `tidy_chats/cli.py` | `status`, `rules`, `ideas` (accept/reject), `sweep-now`, `plan <file>` |
| `scripts/keeper.py` | Entry point the hooks and skills call |
| `hooks/hooks.json` | UserPromptSubmit, PostToolUse (`mcp__ccd_.*`), Stop |
| `skills/rules`, `skills/tidy`, `skills/status` | Review rule ideas, sweep now, show what it did |

Options (`userConfig`, read from `CLAUDE_PLUGIN_OPTION_*`): `sweep_hours` 6,
`finished_idle_hours` 24, `idle_days` 14, `archive` auto|ask, `routine_titles` (regex, empty).

## Testing
- Unit tests (pytest, stdlib only) for the planner (fixpoint, chains, exemptions, overrides),
  state (atomic writes, lock expiry), every hook handler (fed recorded-shape JSON on stdin,
  assert on the output JSON), and the CLI.
- `claude plugin validate .` must pass.
- Live: installed in the author's app; a fresh chat files and pins itself, marks itself done when
  finished, and a sweep runs from a Stop.

## Not in v1
Background watcher, sampling other chats on every turn, memory warnings for too many running
chats, the author's handoff file upkeep (stays in his own system).
