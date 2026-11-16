import json
from datetime import datetime, timedelta, timezone

from tidy_chats import config, hooks, state

T0 = 1_763_200_000.0  # a fixed "now"
ME = "local_me"
OTHER = "local_other"
WRAP = "mcp__ccd_turn__wrap_up"


def env(**kw):
    e = {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "CLAUDE_CODE_SESSION_ATTENDED": "1",
         "CLAUDE_CODE_HOST_SESSION_ID": ME, "CLAUDE_CODE_TERMINAL_MCP_TOOLS": WRAP}
    e.update(kw)
    return {k: v for k, v in e.items() if v is not None}


def run(event, payload=None, now=T0, **envkw):
    p = {"session_id": "uuid-1", "cwd": "/Users/u/kb", "hook_event_name": event}
    p.update(payload or {})
    out = hooks.handle(event, p, env(**envkw), now)
    json.dumps(out)  # always serialisable
    return out


def ctx(out):
    return (out.get("hookSpecificOutput") or {}).get("additionalContext")


def tool(name, tool_input=None, tool_response="ok", now=T0, **envkw):
    return run("PostToolUse", {"tool_name": name, "tool_input": tool_input or {},
                               "tool_response": tool_response}, now=now, **envkw)


def stop(now=T0, last="Done, it works.", active=False, transcript=None, **envkw):
    p = {"stop_hook_active": active, "last_assistant_message": last}
    if transcript:
        p["transcript_path"] = str(transcript)
    return run("Stop", p, now=now, **envkw)


def iso(hours_ago):
    return (datetime.fromtimestamp(T0, timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def sessions_json():
    return json.dumps([
        {"sessionId": "local_old", "title": "done: Old", "cwd": "/w", "isArchived": False,
         "isRunning": False, "lastActivityAt": iso(48), "group": {"id": "cg-1", "name": "System"}},
        {"sessionId": ME, "title": "Me", "cwd": "/w", "isArchived": False, "isRunning": True,
         "lastActivityAt": iso(0), "group": {"id": "cg-1", "name": "System"}, "pinned": True},
    ])


def settle_first_turn():
    """A chat past its first turn that is filed and pinned."""
    run("UserPromptSubmit", {"prompt": "hi"})
    tool("mcp__ccd_sidebar__move_sessions", {"session_ids": ["self"], "section_id": "cg-1"})
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True})


# --- config -----------------------------------------------------------------

def test_config_defaults_and_overrides():
    assert config.options({}) == {"sweep_hours": 6.0, "finished_idle_hours": 24.0, "idle_days": 14.0,
                                  "archive": "auto", "routine_titles": ""}
    o = config.options({"CLAUDE_PLUGIN_OPTION_SWEEP_HOURS": "2", "CLAUDE_PLUGIN_OPTION_ARCHIVE": "ask",
                        "CLAUDE_PLUGIN_OPTION_IDLE_DAYS": "junk", "CLAUDE_PLUGIN_OPTION_ROUTINE_TITLES": "^Daily"})
    assert o["sweep_hours"] == 2.0 and o["archive"] == "ask" and o["idle_days"] == 14.0
    assert o["routine_titles"] == "^Daily"
    assert config.options({"CLAUDE_PLUGIN_OPTION_ARCHIVE": "never"})["archive"] == "auto"


def test_config_chat_id():
    assert config.chat_id({"session_id": "u"}, {"CLAUDE_CODE_HOST_SESSION_ID": "local_x"}) == "local_x"
    assert config.chat_id({"session_id": "u"}, {}) == "u"


# --- guards -----------------------------------------------------------------

def test_inactive_env_noop():
    assert run("UserPromptSubmit", CLAUDE_CODE_ENTRYPOINT="cli") == {}
    assert run("UserPromptSubmit", CLAUDE_CODE_SESSION_ATTENDED="0") == {}
    assert state.load_chat(ME) == {}
    forced = run("UserPromptSubmit", CLAUDE_CODE_ENTRYPOINT="cli", TIDY_CHATS_FORCE="1")
    assert "tidy-chats" in ctx(forced)


def test_subagent_noop():
    assert run("UserPromptSubmit", {"agent_id": "a1"}) == {}
    assert run("Stop", {"agent_id": "a1"}) == {}


def test_exception_returns_empty(monkeypatch, data_dir):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(state, "load_chat", boom)
    assert run("UserPromptSubmit") == {}
    assert "disk on fire" in (data_dir / "errors.log").read_text()


# --- first turn, finish, reopen ---------------------------------------------

def test_first_prompt_note_then_silent():
    out = run("UserPromptSubmit", {"prompt": "hi"})
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "first turn" in ctx(out)
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True})
    assert run("UserPromptSubmit", {"prompt": "again"}) == {}


def test_first_prompt_carries_section_rule_hints():
    state.save_rules([{"kind": "section", "match": "cwd", "value": "/Users/u/kb", "section": "System"},
                      {"kind": "section", "match": "cwd", "value": "/Users/u/site", "section": "Website"}])
    note = ctx(run("UserPromptSubmit", {"cwd": "/Users/u/kb/sub"}))
    assert "System" in note and "Website" not in note


def test_wrap_up_without_ask_gives_finish_note():
    settle_first_turn()
    out = tool(WRAP, {"recap": "Built it."})
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "done: " in ctx(out)
    assert state.load_chat(ME)["finished"] is True


def test_keep_pinned_rule_respected_at_finish():
    state.save_rules([{"kind": "keep_pinned", "match": "title_word", "value": "atlas"}])
    settle_first_turn()
    resp = json.dumps({"sessionId": ME, "title": "Atlas v14 pace", "group": {"id": "cg-1", "name": "S"}})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    note = ctx(tool(WRAP, {"recap": "Built it."}))
    assert "done: " in note and "set_pinned" not in note


def test_keep_pinned_rule_by_session_and_folder_at_missed_finish():
    state_sweep_recent()
    state.save_rules([{"kind": "keep_pinned", "match": "cwd", "value": "/Users/u/kb"}])
    settle_first_turn()
    tool(WRAP, {"recap": "r"})
    note = ctx(stop())
    assert "mark_completed" in note and "set_pinned" not in note
    state.save_rules([{"kind": "keep_pinned", "match": "session", "value": ME}])
    run("UserPromptSubmit", {"prompt": "more", "cwd": "/elsewhere"})
    assert "set_pinned" not in ctx(tool(WRAP, {"recap": "r"}))


def test_title_kept_from_rename():
    settle_first_turn()
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "Atlas v15"})
    assert state.load_chat(ME)["title"] == "Atlas v15"


def test_wrap_up_with_ask_marks_waiting():
    settle_first_turn()
    assert tool(WRAP, {"recap": "r", "ask": "Ship it?"}) == {}
    st = state.load_chat(ME)
    assert st["waiting"] is True and st["finished"] is False


def test_rename_done_observed():
    settle_first_turn()
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "done: Build"})
    assert state.load_chat(ME)["done"] is True
    assert any(e["action"] == "rename_done" and e["target"] == ME for e in state.read_log())
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": ME, "title": "Build v2"})
    assert state.load_chat(ME)["done"] is False


def test_reopen_note_after_done():
    settle_first_turn()
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "done: Build"})
    note = ctx(run("UserPromptSubmit", {"prompt": "one more thing"}))
    assert DROP_DONE in note
    assert state.load_chat(ME)["done"] is False
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "Build"})
    assert run("UserPromptSubmit", {"prompt": "and another"}) == {}


AUTOMATED = ['<side-sessions-event>\nSession "tests" ended its turn: done.\n</side-sessions-event>',
             'Another Claude session sent a message:\n<cross-session-message from="local_x">bug</cross-session-message>',
             '<ci-monitor-event pr="12">checks failed</ci-monitor-event>',
             '<task-notification>agent finished</task-notification>']


def test_automated_turn_does_not_reopen_a_done_chat():
    settle_first_turn()
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "done: Build"})
    for prompt in AUTOMATED:
        assert run("UserPromptSubmit", {"prompt": prompt}) == {}, prompt
        assert state.load_chat(ME)["done"] is True
    assert DROP_DONE in ctx(run("UserPromptSubmit", {"prompt": "one more thing"}))


def test_automated_first_prompt_waits_for_the_user():
    assert run("UserPromptSubmit", {"prompt": AUTOMATED[1]}) == {}
    assert not state.load_chat(ME).get("seen")
    assert "first turn" in ctx(run("UserPromptSubmit", {"prompt": "hi"}))


# --- the user working in a chat keeps it pinned (his ask 2026-11-16) -------

DROP_DONE = 'without its "done: "'
PIN = 'set_pinned "self" true'


def test_later_prompt_in_an_unpinned_chat_asks_to_pin():
    run("UserPromptSubmit", {"prompt": "hi"})
    note = ctx(run("UserPromptSubmit", {"prompt": "next step"}))
    assert PIN in note and "working in this chat" in note
    assert DROP_DONE not in note


def test_pinned_chat_stays_quiet():
    settle_first_turn()
    assert run("UserPromptSubmit", {"prompt": "next step"}) == {}


def test_chat_another_chat_closed_is_reopened_when_the_user_returns():
    settle_first_turn()
    # A pick-up chat renames this one done and unpins it.
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": ME, "title": "done: Build"},
         now=T0 + 10, CLAUDE_CODE_HOST_SESSION_ID=OTHER)
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": ME, "pinned": False},
         now=T0 + 11, CLAUDE_CODE_HOST_SESSION_ID=OTHER)
    note = ctx(run("UserPromptSubmit", {"prompt": "one more thing"}, now=T0 + 20))
    assert PIN in note and DROP_DONE in note
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "Build"}, now=T0 + 21)
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True}, now=T0 + 22)
    assert run("UserPromptSubmit", {"prompt": "and another"}, now=T0 + 30) == {}


def test_a_newer_get_session_pin_beats_an_older_unpin():
    settle_first_turn()
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": ME, "pinned": False},
         now=T0 + 10, CLAUDE_CODE_HOST_SESSION_ID=OTHER)
    resp = json.dumps({"sessionId": ME, "title": "Build", "group": {"id": "cg-1"}, "pinned": True})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp, now=T0 + 20)
    assert run("UserPromptSubmit", {"prompt": "next"}, now=T0 + 30) == {}


def test_app_started_turns_never_ask_to_pin():
    run("UserPromptSubmit", {"prompt": "hi"})
    for prompt in AUTOMATED:
        assert run("UserPromptSubmit", {"prompt": prompt}) == {}, prompt


def test_stop_reminds_a_missed_pin_once():
    state_sweep_recent()
    run("UserPromptSubmit", {"prompt": "hi"})
    tool("mcp__ccd_sidebar__move_sessions", {"session_ids": ["self"], "section_id": "cg-1"})
    run("UserPromptSubmit", {"prompt": "next step"})
    note = ctx(stop(last="Here it is."))
    assert PIN in note
    assert stop(now=T0 + 5, last="Here it is.") == {}


def test_no_pin_reminder_once_the_chat_pinned():
    state_sweep_recent()
    run("UserPromptSubmit", {"prompt": "hi"})
    tool("mcp__ccd_sidebar__move_sessions", {"session_ids": ["self"], "section_id": "cg-1"})
    run("UserPromptSubmit", {"prompt": "next step"})
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True})
    assert stop(last="Here it is.") == {}


def test_self_actions_logged_with_chat_id():
    settle_first_turn()
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": False})
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": OTHER, "pinned": False})
    actions = [(e["action"], e["target"]) for e in state.read_log()]
    assert ("file", ME) in actions and ("unpin", ME) in actions and ("unpin", OTHER) in actions
    assert state.load_chat(ME)["pinned"] is False


def test_get_session_marks_filed_and_nested():
    run("UserPromptSubmit")
    resp = [{"type": "text", "text": json.dumps({"sessionId": ME, "group": {"id": "cg-1", "name": "S"},
                                                  "parentSessionId": "local_p", "detached": False})}]
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    st = state.load_chat(ME)
    assert st["filed"] is True and st["nested"] is True
    tool("mcp__ccd_session_mgmt__detach_session", {"session_id": "self"})
    assert state.load_chat(ME)["nested"] is False


def test_archive_logged_only_when_it_worked():
    tool("mcp__ccd_session_mgmt__archive_session", {"session_id": "local_a"},
         'Archived session local_a ("done: A").')
    tool("mcp__ccd_session_mgmt__archive_session", {"session_id": "local_b"},
         "Session local_b is still working and was not archived.")
    assert [e["target"] for e in state.read_log() if e["action"] == "archive"] == ["local_a"]


# --- pick-up chats and handing off ------------------------------------------

PICKUP_PROMPT = ('Background (from the session that started this one): finish the battle helper.\n'
                 'Task: Pick up "Puzzle app battle helper step 1, parts 7-8".\n'
                 'first: rename session local_0a1b2c3d to "handed off: Pick up: Puzzle app" '
                 '(skip if it already starts with "done: " or "handed off: "; do not archive it)')


def test_pickup_prompt_gets_pickup_note():
    note = ctx(run("UserPromptSubmit", {"prompt": PICKUP_PROMPT}))
    for word in ("detach_session", "set_pinned", "move_sessions", "done: ", "set_session_title"):
        assert word in note, word
    assert "handed-off" in note
    assert state.load_chat(ME)["pickup"] is True
    assert len(note) < 900


def test_pick_up_title_prompt_counts_as_pickup():
    run("UserPromptSubmit", {"prompt": "Pick up: tidy-chats review fixes. Read the notes first."})
    assert state.load_chat(ME)["pickup"] is True
    run("UserPromptSubmit", {"prompt": 'Context first.\nPick up "example.com upgrade". Read the notes.'},
        CLAUDE_CODE_HOST_SESSION_ID=OTHER)
    assert state.load_chat(OTHER)["pickup"] is True


def test_plain_first_prompt_is_not_a_pickup():
    note = ctx(run("UserPromptSubmit", {"prompt": "Fix the deck page"}))
    assert "first turn" in note and "handed-off" not in note
    assert not state.load_chat(ME).get("pickup")


def test_pickup_stop_reminds_once_when_still_nested():
    state_sweep_recent()
    run("UserPromptSubmit", {"prompt": PICKUP_PROMPT})
    resp = json.dumps({"sessionId": ME, "group": {"id": "cg-1", "name": "S"},
                       "parentSessionId": "local_p", "detached": False})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    note = ctx(stop())
    assert "detach_session" in note and "set_pinned" in note
    assert stop(now=T0 + 5) == {}


def test_pickup_quiet_when_detached_filed_and_pinned():
    state_sweep_recent()
    run("UserPromptSubmit", {"prompt": PICKUP_PROMPT})
    resp = json.dumps({"sessionId": ME, "group": {"id": "cg-1", "name": "S"},
                       "parentSessionId": "local_p", "detached": False})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    tool("mcp__ccd_session_mgmt__detach_session", {"session_id": "self"})
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True})
    assert stop() == {}


def test_handing_off_chat_keeps_its_pin():
    state_sweep_recent()
    settle_first_turn()
    tool("mcp__ccd_session__start_session", {"title": "Pick up: tidy-chats", "prompt": "p"})
    assert tool(WRAP, {"recap": "Handed off."}) == {}
    assert stop() == {}


def test_handing_off_is_logged_for_the_sweep():
    settle_first_turn()
    tool("mcp__ccd_session__start_session", {"title": "Pick up: tidy-chats", "prompt": "p"})
    tool("mcp__ccd_session__start_session", {"title": "Fix the flaky test", "prompt": "p"})
    assert [e["target"] for e in state.read_log() if e["action"] == "handoff"] == [ME]


def test_handed_off_flag_lasts_one_turn():
    state_sweep_recent()
    settle_first_turn()
    tool("mcp__ccd_session__start_session", {"title": "Pick up: tidy-chats", "prompt": "p"})
    run("UserPromptSubmit", {"prompt": "one more fix"})
    assert "done: " in ctx(tool(WRAP, {"recap": "Fixed."}))


def test_other_side_session_does_not_count_as_handoff():
    settle_first_turn()
    tool("mcp__ccd_session__start_session", {"title": "Fix the flaky test", "prompt": "p"})
    assert "done: " in ctx(tool(WRAP, {"recap": "r"}))


# --- Stop -------------------------------------------------------------------

def test_stop_reminds_missed_finish_once():
    settle_first_turn()
    state_sweep_recent()
    tool(WRAP, {"recap": "r"})
    out = stop()
    assert out["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "mark_completed" in ctx(out)
    assert stop(now=T0 + 5) == {}


def test_stop_quiet_when_finish_steps_done():
    settle_first_turn()
    state_sweep_recent()
    tool(WRAP, {"recap": "r"})
    tool("mcp__ccd_session_mgmt__set_session_title", {"session_id": "self", "title": "done: x"})
    assert stop() == {}


def test_stop_reminds_unfiled_once():
    state_sweep_recent()
    run("UserPromptSubmit")
    out = stop()
    assert "move_sessions" in ctx(out)
    assert stop(now=T0 + 5) == {}


def test_stop_no_unfiled_reminder_for_nested_side_session():
    state_sweep_recent()
    run("UserPromptSubmit")
    resp = json.dumps({"sessionId": ME, "group": None, "parentSessionId": "local_p", "detached": False})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    assert stop() == {}


def state_sweep_recent():
    state.try_lock("local_somebody", T0 - 60)
    state.release_lock("local_somebody", T0 - 60)


def test_stop_takes_lock_when_due():
    settle_first_turn()
    out = stop()
    assert "list_sessions" in ctx(out)
    assert state.sweep_state()["lock"]["holder"] == ME


def test_stop_no_sweep_when_recent():
    settle_first_turn()
    state_sweep_recent()
    assert stop() == {}


def test_stop_skips_sweep_when_lock_held_elsewhere():
    settle_first_turn()
    state.try_lock(OTHER, T0 - 10)
    assert stop() == {}


def test_stop_skips_sweep_when_waiting():
    settle_first_turn()
    tool(WRAP, {"recap": "r", "ask": "Which one?"})
    assert stop() == {}
    assert state.sweep_state()["lock"] is None


def test_stop_skips_sweep_after_question_without_wrap_up():
    settle_first_turn()
    assert stop(last="Which one do you want?") == {}
    assert state.sweep_state()["lock"] is None
    assert state.load_chat(ME)["waiting"] is True


def test_wrap_up_flag_lasts_one_turn():
    settle_first_turn()
    tool(WRAP, {"recap": "r"})
    run("UserPromptSubmit", {"prompt": "quick question"})
    assert stop(last="Want the long version?") == {}
    assert state.sweep_state()["lock"] is None


def test_stop_skips_big_transcript_unless_overdue(tmp_path):
    settle_first_turn()
    big = tmp_path / "t.jsonl"
    big.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    state.try_lock("local_somebody", T0 - 7 * 3600)
    state.release_lock("local_somebody", T0 - 7 * 3600)  # 7 h ago: due, not a day overdue
    assert stop(transcript=big) == {}
    state.try_lock("local_somebody", T0 - 31 * 3600)
    state.release_lock("local_somebody", T0 - 31 * 3600)  # 31 h ago: 25 h overdue
    assert "list_sessions" in ctx(stop(transcript=big))


def test_stop_hook_active_never_adds_notes():
    run("UserPromptSubmit")
    assert stop(active=True) == {}


def test_list_sessions_swapped_only_for_holder():
    settle_first_turn()
    stop()  # takes the lock
    resp = [{"type": "text", "text": sessions_json()}]
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, resp)
    swapped = out["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert isinstance(swapped, list) and swapped[0]["type"] == "text"
    assert "local_old" in swapped[0]["text"] and "archive_session" in swapped[0]["text"]
    other = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, resp,
                 CLAUDE_CODE_HOST_SESSION_ID=OTHER)
    assert other == {}


def test_list_sessions_swap_mirrors_string_shape():
    settle_first_turn()
    stop()
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, sessions_json())
    assert isinstance(out["hookSpecificOutput"]["updatedMCPToolOutput"], str)
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200},
               {"content": [{"type": "text", "text": sessions_json()}]})
    assert out["hookSpecificOutput"]["updatedMCPToolOutput"]["content"][0]["type"] == "text"


def test_nested_sweeper_keeps_its_parent_open():
    settle_first_turn()
    resp = json.dumps({"sessionId": ME, "group": {"id": "cg-1", "name": "S"},
                       "parentSessionId": "local_old", "detached": False})
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, resp)
    stop()  # takes the lock
    without_me = [c for c in json.loads(sessions_json()) if c["sessionId"] != ME]
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, json.dumps(without_me))
    text = out["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert "local_old" not in text


def test_list_sessions_swap_only_for_a_full_list():
    settle_first_turn()
    stop()  # takes the lock
    for args in ({}, {"limit": 50}, {"limit": "lots"}, {"limit": 200, "linked": True},
                 {"limit": 200, "group": "System"}):
        assert tool("mcp__ccd_session_mgmt__list_sessions", args, sessions_json()) == {}, args


def test_list_at_its_limit_holds_archives():
    settle_first_turn()
    stop()
    rows = json.loads(sessions_json())
    rows += [{"sessionId": "local_f%d" % i, "title": "Filler %d" % i, "cwd": "/w", "isArchived": False,
              "isRunning": False, "lastActivityAt": iso(1), "group": {"id": "cg-1", "name": "System"}}
             for i in range(200 - len(rows))]
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, json.dumps(rows))
    text = out["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert "archive_session" not in text and "local_old" not in text
    assert "limit" in text


def oversize_error(path):
    return ("Error: result (57,464 characters across 1,591 lines) exceeds maximum allowed tokens. "
            "Output has been saved to %s.\nFormat: Plain text\n- For targeted searches: use grep." % path)


def test_oversized_list_planned_from_the_saved_file(tmp_path):
    settle_first_turn()
    stop()  # takes the lock
    home = tmp_path / "cfg"
    saved = home / "projects" / "-w" / "abc" / "tool-results" / "mcp-ccd_session_mgmt-list_sessions-1.txt"
    saved.parent.mkdir(parents=True)
    saved.write_text(sessions_json())
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, oversize_error(saved),
               CLAUDE_CONFIG_DIR=str(home))
    text = out["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert "local_old" in text and "archive_session" in text and "Error" not in text


def test_oversized_list_outside_config_dir_ignored(tmp_path):
    settle_first_turn()
    stop()
    stray = tmp_path / "elsewhere" / "tool-results" / "mcp-ccd_session_mgmt-list_sessions-1.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text(sessions_json())
    assert tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, oversize_error(stray),
                CLAUDE_CONFIG_DIR=str(tmp_path / "cfg")) == {}


def test_list_sessions_unparseable_passes_through():
    settle_first_turn()
    stop()
    assert tool("mcp__ccd_session_mgmt__list_sessions", {}, "Error: no app window") == {}


def test_continuation_releases_lock_even_without_plan():
    settle_first_turn()
    stop()  # takes the lock, chat ignores the note
    assert stop(now=T0 + 30, active=True) == {}
    ss = state.sweep_state()
    assert ss["lock"] is None and ss["last_sweep_at"] == T0 + 30


def test_holder_releases_on_next_stop_even_if_not_flagged_active():
    settle_first_turn()
    stop()
    assert stop(now=T0 + 30) == {}
    assert state.sweep_state()["lock"] is None


def test_overrides_become_ideas_deduped():
    settle_first_turn()
    state.log_action({"action": "unpin", "target": "local_old", "at": 1.0})
    sessions = json.loads(sessions_json())
    sessions[0]["pinned"] = True  # the user pinned it back
    for i in range(2):
        state.try_lock(ME, T0 + i)
        tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, json.dumps(sessions), now=T0 + i)
        state.release_lock(ME, T0 + i)
    ideas = state.load_ideas()
    assert len(ideas) == 1
    assert ideas[0]["kind"] == "keep_pinned" and ideas[0]["target"] == "local_old"
    assert ideas[0]["count"] == 1 and ideas[0]["status"] == "pending"
    state.log_action({"action": "unpin", "target": "local_old", "at": 2.0})
    state.try_lock(ME, T0 + 9)
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, json.dumps(sessions), now=T0 + 9)
    assert state.load_ideas()[0]["count"] == 2
    assert "1 rule idea" in out["hookSpecificOutput"]["updatedMCPToolOutput"]


def test_rejected_idea_not_raised_again():
    settle_first_turn()
    state.save_ideas([{"id": "1", "kind": "keep_pinned", "target": "local_old", "status": "rejected",
                       "events": [1.0], "count": 1}])
    state.log_action({"action": "unpin", "target": "local_old", "at": 5.0})
    sessions = json.loads(sessions_json())
    sessions[0]["pinned"] = True
    state.try_lock(ME, T0)
    out = tool("mcp__ccd_session_mgmt__list_sessions", {"limit": 200}, json.dumps(sessions))
    assert len(state.load_ideas()) == 1
    assert "rule idea" not in out["hookSpecificOutput"]["updatedMCPToolOutput"]


def test_fallback_finish_without_wrap_up():
    state_sweep_recent()
    run("UserPromptSubmit", CLAUDE_CODE_TERMINAL_MCP_TOOLS=None)
    tool("mcp__ccd_sidebar__move_sessions", {"session_ids": ["self"], "section_id": "cg-1"},
         CLAUDE_CODE_TERMINAL_MCP_TOOLS=None)
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True},
         CLAUDE_CODE_TERMINAL_MCP_TOOLS=None)
    out = stop(last="All set, the page is live.", CLAUDE_CODE_TERMINAL_MCP_TOOLS=None)
    assert "mark_completed" in ctx(out)
    run("UserPromptSubmit", CLAUDE_CODE_TERMINAL_MCP_TOOLS=None)
    assert stop(last="Which colour do you want?", CLAUDE_CODE_TERMINAL_MCP_TOOLS=None) == {}


def test_debug_samples_saved_only_when_on(data_dir):
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, "x")
    assert not (data_dir / "samples").exists()
    (data_dir / "debug").write_text("on")
    tool("mcp__ccd_session_mgmt__get_session", {"session_id": "self"}, "x" * 10000)
    sample = json.loads((data_dir / "samples" / "get_session.json").read_text())
    assert sample["tool_input"] == {"session_id": "self"}
    assert len(json.dumps(sample)) < 6000


# --- review minors (0.1.5) ---------------------------------------------------

def test_parallel_tool_calls_keep_each_others_flags(monkeypatch):
    """Two sidebar calls in one turn run their hooks at once; neither loses the other's flag."""
    run("UserPromptSubmit", {"prompt": "hi"})
    stale = state.load_chat(ME)
    tool("mcp__ccd_sidebar__set_pinned", {"session_id": "self", "pinned": True})
    real, calls = state.load_chat, []

    def first_read_is_stale(cid):
        if not calls:
            calls.append(cid)
            return dict(stale)
        return real(cid)

    monkeypatch.setattr(state, "load_chat", first_read_is_stale)
    tool("mcp__ccd_sidebar__move_sessions", {"session_ids": ["self"], "section_id": "cg-1"})
    monkeypatch.setattr(state, "load_chat", real)
    st = state.load_chat(ME)
    assert st["pinned"] is True and st["filed"] is True
