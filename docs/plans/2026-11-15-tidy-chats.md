# tidy-chats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin whose hooks keep the desktop app's sidebar tidy during normal chat turns.

**Architecture:** Python 3 stdlib package `tidy_chats` behind one entry script. Hooks emit short
notes (`additionalContext`) that make the model call the sidebar tools, watch those calls to
keep state, and swap the `list_sessions` output for a plan during a sweep.

**Tech Stack:** Python 3.9+ stdlib, pytest for tests, Claude Code plugin format.

**Spec:** `docs/specs/2026-11-15-tidy-chats-design.md`

## Global Constraints
- Stdlib only at runtime; pytest only for tests. Python 3.9+ (no `match`, no `X | Y` types at runtime).
- Every hook handler returns valid JSON (`{}` when nothing to say) and exit 0, even on error.
- Active only when `CLAUDE_CODE_ENTRYPOINT=claude-desktop` and `CLAUDE_CODE_SESSION_ATTENDED=1`, or `TIDY_CHATS_FORCE=1`.
- Ignore input that has `agent_id` (subagents).
- State dir: `TIDY_CHATS_DATA`, else `CLAUDE_PLUGIN_DATA`, else `~/.claude/plugins/data/tidy-chats`.
- Options from env `CLAUDE_PLUGIN_OPTION_<KEY>`: `SWEEP_HOURS`=6, `FINISHED_IDLE_HOURS`=24, `IDLE_DAYS`=14, `ARCHIVE`=auto|ask, `ROUTINE_TITLES`="" (regex).
- Finished title prefixes: `done:` and `handed off:` (case-insensitive, leading space allowed).
- Lock stale after 20 minutes; big-chat skip over 4 MB transcript unless 24 h overdue.
- Notes are factual statements, not shouted orders; each under 900 characters.

## Review Focus
1. `tool_response` for MCP tools may be a string, a list of `{type,text}` blocks, or `{content:[...]}`: the plan swap must parse all three and pass through untouched when it can't (planner test + hooks test).
2. Chat entries missing `group`, `pinned`, `startedBy` or `lastActivityAt`: treat as ungrouped / not pinned / top-level; never archive a chat with no timestamp (planner test).
3. Missing or corrupt state JSON: start fresh, never raise (state test).
4. Two chats stopping at the same moment: only one takes the lock (state test).
5. The sweeping chat ignores the note: its next Stop still releases the lock and records the time (hooks test).

---

### Task 1: State store

**Files:** Create `tidy_chats/__init__.py`, `tidy_chats/state.py`, `tests/conftest.py`, `tests/test_state.py`

**Interfaces — Produces:**
- `data_dir() -> Path` (creates it)
- `load_chat(chat_id: str) -> dict` / `save_chat(chat_id: str, data: dict) -> None` (file `chats/<id>.json`; default `{}`)
- `try_lock(holder: str, now: float) -> bool`, `release_lock(holder: str, now: float) -> None` (sets `last_sweep_at`), `sweep_state() -> dict` (`{"last_sweep_at": float|None, "lock": {"holder","at"}|None}`)
- `log_action(entry: dict) -> None`, `read_log() -> list[dict]` (jsonl, keeps last 2000 lines)
- `load_rules() -> list[dict]`, `save_rules(rules)`, `load_ideas() -> list[dict]`, `save_ideas(ideas)`
- `read_json(path, default)`, `write_json(path, data)` (atomic: temp file + `os.replace`)

- [ ] Tests: `test_chat_roundtrip`, `test_corrupt_chat_file_returns_empty`, `test_lock_exclusive` (second holder gets False), `test_lock_stale_after_20_min` (other holder wins at now+1201), `test_release_sets_last_sweep`, `test_log_append_and_trim` (2005 entries → 2000, newest kept). `conftest.py` sets `TIDY_CHATS_DATA` to `tmp_path` per test.
- [ ] Run `python3 -m pytest tests/test_state.py -q` → fails (no module).
- [ ] Implement `tidy_chats/state.py`.
- [ ] Run → pass. Commit `feat(state): chat state, sweep lock, action log and rules store`.

### Task 2: Planner

**Files:** Create `tidy_chats/planner.py`, `tests/test_planner.py`, `tests/fixtures/sessions.json` (8-10 entries in the real `list_sessions` shape: `sessionId,title,cwd,isArchived,isRunning,lastActivityAt,group{id,name}?,pinned?,startedBy?`)

**Interfaces — Produces:**
- `parse_sessions(tool_response) -> list[dict] | None` (accepts str JSON, list of chats, list of `{type:"text",text}` blocks, or dict with `content`; None if not a chat list)
- `make_plan(sessions: list[dict], *, now: datetime, self_id: str, rules: list[dict], log: list[dict], opts: dict) -> dict` returning `{"archive":[{"id","title","reason"}], "unpin":[{"id","title"}], "file":[{"id","title","cwd"}], "sections":[{"id","name"}], "overrides":[{"kind","id","title","cwd","group"}], "checked": int}`
- `is_finished_title(title: str) -> bool`
- `rule_matches(rule: dict, chat: dict) -> bool` (rule `{"kind","match":{"session"|"title_word"|"cwd"},"value", "section"?}`)

Archive reasons: `finished` (finished title, idle ≥ finished_idle_hours), `idle` (idle ≥ idle_days), `routine` (title matches routine_titles, idle ≥ 1 h). Skip: self, running, pinned, no timestamp, `never_archive` rule match, open chat nested below (fixpoint, as in the author's `chat-plan.py`). Output only chain tops. Unpin: pinned + finished title, minus `keep_pinned` matches. File: no `group` and no `startedBy`. Overrides: last log entry per target — `unpin` but now pinned → `keep_pinned`; `archive` but present and not archived → `never_archive`; `file` into section X but now group id ≠ X → `section`.

- [ ] Tests: `test_finished_idle_archived`, `test_finished_recent_kept` (idle 2 h), `test_running_pinned_self_never_archived`, `test_parent_blocked_by_open_child`, `test_chain_freed_by_fixpoint_lists_top_only`, `test_idle_14_days`, `test_routine_regex`, `test_missing_fields_safe` (no group/pinned/timestamp: not archived, filed if no group), `test_never_archive_rule_exempts`, `test_unpin_finished_pinned_and_keep_pinned_rule`, `test_unfiled_top_level_only`, `test_overrides_detected` (one each kind), `test_parse_sessions_shapes` (str, blocks, content dict, garbage → None).
- [ ] Run → fail. Implement. Run → pass. Commit `feat(planner): sweep plan with chains, rules and override detection`.

### Task 3: Notes

**Files:** Create `tidy_chats/notes.py`, `tests/test_notes.py`

**Interfaces — Produces:** `first_turn_note(section_hints: list[str]) -> str`, `finish_note() -> str`, `reopen_note() -> str`, `missed_note(step: str) -> str` (`step` in `first_turn|finish`), `sweep_note() -> str`, `render_plan(plan: dict, *, archive_mode: str, ideas_waiting: int, now: datetime) -> str`.

`render_plan` lists each action with the chat id and title, names the tool to use (`archive_session`, `set_pinned` false, `move_sessions`), states that archiving is the user's tidy-chats setting (`auto`) or asks one yes/no (`ask`), adds `End your reply with: "tidy-chats has N rule ideas: run /tidy-chats:rules"` when ideas > 0, ends with "Do not list chats again; finish with one short line of what changed." Empty plan → "Nothing to tidy." Caps each list at 25 items with "+N more next sweep".

- [ ] Tests: `test_notes_short` (each < 900 chars, mention `tidy-chats`), `test_first_turn_includes_hints`, `test_render_plan_auto_lists_archive_calls`, `test_render_plan_ask_mode_asks`, `test_render_plan_ideas_line`, `test_render_plan_empty`, `test_render_plan_caps_25`.
- [ ] Run → fail. Implement. Run → pass. Commit `feat(notes): note texts and sweep plan rendering`.

### Task 4: Hook handlers

**Files:** Create `tidy_chats/hooks.py`, `tidy_chats/config.py`, `tests/test_hooks.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `handle(event: str, payload: dict, env: dict, now: float) -> dict`; `config.options(env) -> dict`; `config.active(env) -> bool`; `config.chat_id(payload, env) -> str`.

Behaviour (per spec "Moments"):
- `UserPromptSubmit`: no chat state → first-turn note (with `section` rule hints matching `cwd`), set `{"seen":1,"started_at":now}`. State `done` true → reopen note.
- `PostToolUse` (`tool_name` starts `mcp__ccd_`): 
  - `..._turn__wrap_up`: `ask` empty → `finished=True`, return finish note unless `done`; else `finished=False`, `waiting=True`.
  - `set_session_title` on `self`: title finished → `done=True`, log `rename_done`; else `done=False`.
  - `set_pinned` self → `pinned` flag; other ids → log `unpin`/`pin` with target id.
  - `move_sessions` → `filed=True` if `self` in ids; log `file` per id with `section_id`/`group_id`.
  - `archive_session` → log `archive` with target id.
  - `mark_completed` self → `completed=True`.
  - `list_sessions` while this chat holds the lock → `updatedMCPToolOutput` = rendered plan (plan built with `make_plan`; overrides turned into ideas, deduped by `(kind,id)` with `count`, skipping rejected ones).
- `Stop`: `stop_hook_active` → if holder: `release_lock`; return `{}`. Else, in order, at most one note: finished and not done and finish not yet reminded → `missed_note("finish")`; seen, not filed, first-turn not yet reminded, no `startedBy`-style nesting info known → `missed_note("first_turn")`; sweep due (last sweep older than `sweep_hours`, not waiting, transcript ≤ 4 MB or 24 h overdue) and `try_lock` → `sweep_note()`. Fallback finish detection when `env` has no `mcp__ccd_turn__wrap_up` in `CLAUDE_CODE_TERMINAL_MCP_TOOLS` and the chat never saw wrap_up: last message not ending in `?` → finished.
- Stop notes go out as `{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":...}}`.
- Inactive env or `agent_id` → `{}`. Any exception → append to `errors.log`, return `{}`.

- [ ] Tests: `test_inactive_env_noop`, `test_subagent_noop`, `test_first_prompt_note_then_silent`, `test_wrap_up_without_ask_gives_finish_note`, `test_wrap_up_with_ask_marks_waiting`, `test_rename_done_observed`, `test_reopen_note_after_done`, `test_stop_reminds_missed_finish_once`, `test_stop_takes_lock_when_due`, `test_stop_skips_sweep_when_waiting`, `test_stop_skips_big_transcript_unless_overdue`, `test_list_sessions_swapped_only_for_holder` (holder gets plan; other chat unchanged), `test_list_sessions_unparseable_passes_through`, `test_continuation_releases_lock_even_without_plan`, `test_overrides_become_ideas_deduped`, `test_exception_returns_empty`, `test_fallback_finish_without_wrap_up`.
- [ ] Run → fail. Implement. Run → pass. Commit `feat(hooks): first-turn, finish, reopen and sweep handlers`.

### Task 5: CLI, entry script, skills

**Files:** Create `tidy_chats/cli.py`, `scripts/keeper.py`, `skills/rules/SKILL.md`, `skills/tidy/SKILL.md`, `skills/status/SKILL.md`, `tests/test_cli.py`

**Interfaces — Produces:** `scripts/keeper.py hook <Event>` (stdin JSON → stdout JSON via `hooks.handle`), `scripts/keeper.py status|rules|ideas|accept <idea_id> <scope>|reject <idea_id>|add-rule <kind> <match> <value> [section]|remove-rule <n>|sweep-now|plan <file>`. `scope` is `chat|word:<w>|folder`.

Skills: `rules` lists ideas (`keeper.py ideas`), asks one AskUserQuestion per idea (Just this chat / title word / No), then calls accept/reject. `tidy` runs `sweep-now` then tells the model to call `list_sessions` limit 200 (lock taken by `sweep-now` for this chat via `CLAUDE_CODE_HOST_SESSION_ID`). `status` prints last sweep, lock, rules, ideas, last 10 actions. Skill bodies reference `${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py`.

- [ ] Tests: `test_hook_entry_roundtrip` (subprocess, forced env, prints JSON), `test_hook_entry_bad_stdin_prints_empty_json`, `test_accept_creates_rule_and_drops_idea`, `test_reject_remembered`, `test_status_runs`, `test_plan_file`.
- [ ] Run → fail. Implement. Run → pass. Commit `feat(cli): entry script, rule review and status commands` and `feat(skills): rules, tidy and status skills`.

### Task 6: Plugin packaging

**Files:** Create `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `hooks/hooks.json`, `README.md`, `LICENSE` (MIT), `tests/test_package.py`

hooks.json: `UserPromptSubmit` (no matcher), `PostToolUse` matcher `mcp__ccd_.*`, `Stop`; each `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" hook <Event>`, timeout 10. plugin.json: name `tidy-chats`, version `0.1.0`, author Seyon Sri, userConfig for the five options with the defaults above. marketplace.json: name `tidy-chats`, one plugin with `source: "./"`.

- [ ] Test `test_hooks_json_events_and_commands`, `test_plugin_json_options_match_config_defaults`.
- [ ] Run `python3 -m pytest -q` → pass; `claude plugin validate .` → "Validation passed". Commit `feat(plugin): manifest, marketplace, hooks wiring and README`.

### Task 7: Install and live run
- [ ] `claude plugin marketplace add ~/projects/tidy-chats`, `claude plugin install tidy-chats@tidy-chats`; set his options (`routine_titles` from the author's routine list).
- [ ] Start a fresh chat with a small task; check it filed and pinned itself, renamed `done:` when finished, and that a sweep ran from a Stop (status command shows `last_sweep_at`, action log).
- [ ] Record results in the README "Status" line.
