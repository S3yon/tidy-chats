from datetime import datetime, timezone

from tidy_chats import notes

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def empty_plan(**kw):
    p = {"archive": [], "unpin": [], "file": [], "sections": [], "overrides": [], "checked": 12}
    p.update(kw)
    return p


def test_notes_short():
    texts = [notes.first_turn_note([]), notes.first_turn_note(["Website for /Users/u/site"] * 3),
             notes.finish_note(), notes.reopen_note(), notes.missed_note("first_turn"),
             notes.missed_note("finish"), notes.sweep_note()]
    for t in texts:
        assert len(t) < 900, t
        assert "tidy-chats" in t


def test_notes_name_the_tools():
    assert "move_sessions" in notes.first_turn_note([])
    assert "set_pinned" in notes.first_turn_note([])
    finish = notes.finish_note()
    for tool in ("set_session_title", "set_pinned", "mark_completed", "done: "):
        assert tool in finish
    assert "list_sessions" in notes.sweep_note()
    assert "set_session_title" in notes.reopen_note()


def test_first_turn_includes_hints():
    t = notes.first_turn_note(["Website (folder /Users/u/site)"])
    assert "Website (folder /Users/u/site)" in t
    assert "Website" not in notes.first_turn_note([])


def test_missed_note_steps_differ():
    assert notes.missed_note("first_turn") != notes.missed_note("finish")
    assert "mark_completed" in notes.missed_note("finish")
    assert "move_sessions" in notes.missed_note("first_turn")


def test_render_plan_auto_lists_archive_calls():
    p = empty_plan(archive=[{"id": "local_a", "title": "done: A", "reason": "finished"}],
                   unpin=[{"id": "local_b", "title": "done: B"}],
                   file=[{"id": "local_c", "title": "C", "cwd": "/w/c", "section": "Life"}],
                   sections=[{"id": "cg-1", "name": "System"}, {"id": "cg-2", "name": "Life"}])
    t = notes.render_plan(p, archive_mode="auto", ideas_waiting=0, now=NOW)
    for s in ("archive_session", "local_a", "done: A", "set_pinned", "local_b",
              "move_sessions", "local_c", "/w/c", "Life", "System", "cg-2", "auto",
              "Do not list chats again"):
        assert s in t, s
    assert "AskUserQuestion" not in t
    assert "rule ideas" not in t


def test_render_plan_ask_mode_asks():
    p = empty_plan(archive=[{"id": "local_a", "title": "done: A", "reason": "finished"}])
    t = notes.render_plan(p, archive_mode="ask", ideas_waiting=0, now=NOW)
    assert "AskUserQuestion" in t and "yes/no" in t
    assert "local_a" in t


def test_render_plan_ideas_line():
    t = notes.render_plan(empty_plan(unpin=[{"id": "x", "title": "done: x"}]),
                          archive_mode="auto", ideas_waiting=3, now=NOW)
    assert 'End your reply with: "tidy-chats has 3 rule ideas: run /tidy-chats:rules"' in t
    one = notes.render_plan(empty_plan(), archive_mode="auto", ideas_waiting=1, now=NOW)
    assert "1 rule idea:" in one


def test_render_plan_empty():
    t = notes.render_plan(empty_plan(), archive_mode="auto", ideas_waiting=0, now=NOW)
    assert "Nothing to tidy." in t
    assert "12" in t
    assert "archive_session" not in t


def test_render_plan_caps_25():
    many = [{"id": "local_%d" % i, "title": "done: %d" % i, "reason": "idle"} for i in range(30)]
    t = notes.render_plan(empty_plan(archive=many), archive_mode="auto", ideas_waiting=0, now=NOW)
    assert "local_24" in t and "local_25" not in t
    assert "+5 more next sweep" in t


def test_render_plan_trims_long_titles():
    p = empty_plan(unpin=[{"id": "x", "title": "done: " + "y" * 300}])
    t = notes.render_plan(p, archive_mode="auto", ideas_waiting=0, now=NOW)
    assert "y" * 300 not in t


def test_first_turn_note_drops_hints_to_stay_short():
    hints = ["Website (folder /Users/someone/projects/a-long-site-folder-name)"] * 5
    t = notes.first_turn_note(hints)
    assert len(t) < 900
    assert "Website" in t


def test_render_plan_says_when_list_hit_its_limit():
    text = notes.render_plan(empty_plan(truncated=200), archive_mode="auto", ideas_waiting=0, now=NOW)
    assert "limit of 200" in text
    assert "limit" not in notes.render_plan(empty_plan(), archive_mode="auto", ideas_waiting=0, now=NOW)


def test_finish_notes_keep_pin_drop_the_unpin_step():
    assert "set_pinned" in notes.finish_note() and "set_pinned" in notes.missed_note("finish")
    for text in (notes.finish_note(keep_pin=True), notes.missed_note("finish", keep_pin=True)):
        assert "set_pinned" not in text
        assert "mark_completed" in text and "done: " in text
