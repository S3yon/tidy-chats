import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tidy_chats import planner

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "sessions.json"
OPTS = {"finished_idle_hours": 24, "idle_days": 14, "routine_titles": ""}


def chat(sid, title="Some work", hours=1.0, **kw):
    c = {"sessionId": sid, "title": title, "cwd": "/w", "isArchived": False, "isRunning": False,
         "lastActivityAt": (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
         "group": {"id": "cg-1", "name": "System"}, "pinned": False}
    c.update(kw)
    return c


def plan(sessions, rules=(), log=(), self_id="local_me", self_parent=None, **opts):
    o = dict(OPTS)
    o.update(opts)
    return planner.make_plan(list(sessions), now=NOW, self_id=self_id, rules=list(rules),
                             log=list(log), opts=o, self_parent=self_parent)


def archived_ids(p):
    return [a["id"] for a in p["archive"]]


def test_finished_idle_archived():
    p = plan([chat("a", "done: Write it", hours=30), chat("b", "handed off: Scan", hours=25)])
    assert archived_ids(p) == ["a", "b"]
    assert {a["reason"] for a in p["archive"]} == {"finished"}


def test_finished_recent_kept():
    assert plan([chat("a", "done: Write it", hours=2)])["archive"] == []


def test_finished_title_prefix_rules():
    assert planner.is_finished_title("done: x")
    assert planner.is_finished_title("  Done: x")
    assert planner.is_finished_title("HANDED OFF: x")
    assert not planner.is_finished_title("undone: x")
    assert not planner.is_finished_title("Get it done: x")
    assert not planner.is_finished_title(None)


def test_running_pinned_self_never_archived():
    p = plan([chat("run", "done: a", hours=99, isRunning=True),
              chat("pin", "done: b", hours=99, pinned=True),
              chat("local_me", "done: c", hours=99)])
    assert p["archive"] == []


def test_parent_blocked_by_open_child():
    p = plan([chat("parent", "done: v13", hours=99),
              chat("child", "v14 pace", hours=1, startedBy="parent")])
    assert p["archive"] == []


def test_detached_child_does_not_block_parent():
    p = plan([chat("parent", "done: v13", hours=99),
              chat("child", "v14 pace", hours=1, startedBy="parent", detached=True)])
    assert archived_ids(p) == ["parent"]


def test_chain_freed_by_fixpoint_lists_top_only():
    # top <- mid <- leaf: the leaf is finished, which frees mid, which frees top.
    sessions = [chat("top", "done: one", hours=99),
                chat("mid", "done: two", hours=50, startedBy="top"),
                chat("leaf", "done: three", hours=30, startedBy="mid")]
    p = plan(list(reversed(sessions)))
    assert archived_ids(p) == ["top"]


def test_nested_archivable_under_open_parent_listed_itself():
    p = plan([chat("parent", "Still working", hours=1),
              chat("kid", "done: side job", hours=30, startedBy="parent")])
    assert archived_ids(p) == ["kid"]


def test_held_lists_finished_chats_waiting_on_an_open_chat():
    # A section showed 26 finished chats left open behind 12 open ones and nothing said why.
    vw = {"id": "cg-v", "name": "Video & web"}
    p = plan([chat("top", "handed off: v10", hours=99, group=vw),
              chat("mid", "done: v13", hours=50, startedBy="top", group=vw),
              chat("tail", "Pick up: v14 pace", hours=30, startedBy="mid", pinned=True, group=vw),
              chat("solo", "done: side", hours=40),
              chat("kid", "Still going", hours=2, startedBy="solo"),
              chat("free", "done: other", hours=30)])
    assert archived_ids(p) == ["free"]
    held = {h["id"]: h for h in p["held"]}
    assert set(held) == {"top", "mid", "solo"}
    assert held["top"]["by"] == ["tail"] and held["mid"]["by"] == ["tail"]
    assert held["solo"]["by"] == ["kid"]
    assert held["top"]["section"] == "Video & web" and held["solo"]["section"] == "System"


def test_nothing_held_when_the_chain_is_free():
    p = plan([chat("top", "done: one", hours=99), chat("leaf", "done: two", hours=30, startedBy="top")])
    assert p["held"] == []


def test_held_survives_a_child_loop():
    p = plan([chat("a", "done: a", hours=99, startedBy="b"), chat("b", "done: b", hours=99, startedBy="a"),
              chat("c", "Open", hours=1, startedBy="b")])
    assert {h["id"] for h in p["held"]} == {"a", "b"}
    assert all(h["by"] == ["c"] for h in p["held"])


def test_idle_14_days():
    p = plan([chat("old", "Old idea", hours=24 * 14 + 1), chat("new", "New idea", hours=24 * 13)])
    assert archived_ids(p) == ["old"]
    assert p["archive"][0]["reason"] == "idle"


def test_routine_regex():
    sessions = [chat("r1", "Daily X scan", hours=2), chat("r2", "Daily X scan", hours=0.5),
                chat("other", "Daily notes", hours=2)]
    assert plan(sessions)["archive"] == []  # no regex set
    p = plan(sessions, routine_titles=r"^Daily X scan")
    assert archived_ids(p) == ["r1"]
    assert p["archive"][0]["reason"] == "routine"


def test_bad_routine_regex_ignored():
    assert plan([chat("r1", "Daily X scan", hours=2)], routine_titles="(")["archive"] == []


def test_missing_fields_safe():
    bare = {"sessionId": "bare", "title": "done: bare"}
    p = plan([bare])
    assert p["archive"] == []
    assert p["unpin"] == []
    assert p["file"] == []  # no group key: unknown, not unfiled


def test_bad_timestamp_never_archived():
    p = plan([dict(chat("x", "done: x"), lastActivityAt="yesterday")])
    assert p["archive"] == []


def test_already_archived_entries_ignored():
    p = plan([chat("gone", "done: x", hours=99, isArchived=True, group=None)])
    assert p["archive"] == [] and p["file"] == [] and p["checked"] == 0


def test_never_archive_rule_exempts():
    rules = [{"kind": "never_archive", "match": "title_word", "value": "atlas"}]
    p = plan([chat("a", "done: Atlas v13", hours=99), chat("b", "done: other", hours=99)], rules)
    assert archived_ids(p) == ["b"]


def test_sweeping_chat_missing_from_list_still_blocks_its_parent():
    parent = chat("parent", "done: v13", hours=99)
    assert archived_ids(plan([parent])) == ["parent"]
    assert plan([parent], self_parent="parent")["archive"] == []


def test_unpin_finished_pinned_and_keep_pinned_rule():
    sessions = [chat("a", "done: x", hours=1, pinned=True),
                chat("b", "handed off: y", hours=1, pinned=True),
                chat("c", "Working", hours=1, pinned=True),
                chat("local_me", "done: me", hours=1, pinned=True)]
    p = plan(sessions)
    assert [u["id"] for u in p["unpin"]] == ["a", "b"]
    rules = [{"kind": "keep_pinned", "match": "session", "value": "b"}]
    assert [u["id"] for u in plan(sessions, rules)["unpin"]] == ["a"]


def test_hand_off_keeps_its_pin_until_the_pickup_unpins_it():
    sessions = [chat("h", "handed off: y", pinned=True)]
    log = [{"action": "pin", "target": "h", "at": 1.0},
           {"action": "handoff", "target": "h", "at": 2.0},
           {"action": "rename_done", "target": "h", "at": 3.0}]
    assert plan(sessions, log=log)["unpin"] == []
    picked_up = log + [{"action": "rename_done", "target": "h", "at": 4.0},
                       {"action": "unpin", "target": "h", "at": 5.0}]
    assert [u["id"] for u in plan(sessions, log=picked_up)["unpin"]] == ["h"]


def test_pin_made_after_the_done_rename_is_kept():
    log = [{"action": "pin", "target": "f", "at": 1.0},
           {"action": "rename_done", "target": "d", "at": 2.0},
           {"action": "unpin", "target": "d", "at": 3.0},
           {"action": "pin", "target": "d", "at": 4.0},
           {"action": "rename_done", "target": "f", "at": 5.0}]
    p = plan([chat("d", "done: x", pinned=True), chat("f", "done: y", pinned=True)], log=log)
    assert [u["id"] for u in p["unpin"]] == ["f"]


def test_unfiled_top_level_only():
    sessions = [chat("loose", "Loose", group=None),
                chat("nested", "Nested", group=None, startedBy="loose"),
                chat("pinned", "Pinned loose", group=None, pinned=True),
                chat("filed", "Filed"),
                chat("dying", "done: x", hours=99, group=None)]
    p = plan(sessions)
    assert [f["id"] for f in p["file"]] == ["loose"]
    assert p["file"][0]["cwd"] == "/w"


def test_missing_group_key_is_unknown_not_unfiled():
    no_key = chat("nokey", "No key")
    del no_key["group"]
    p = plan([no_key, chat("loose", "Loose", group=None)])
    assert [f["id"] for f in p["file"]] == ["loose"]


def test_running_chats_never_unpinned_or_filed():
    p = plan([chat("busy", "done: still going", pinned=True, isRunning=True),
              chat("busy2", "Filing itself", group=None, isRunning=True)])
    assert p["unpin"] == [] and p["file"] == []


def test_section_rule_hint_on_file():
    rules = [{"kind": "section", "match": "cwd", "value": "/Users/u/site", "section": "Website"}]
    p = plan([chat("a", "Hero", group=None, cwd="/Users/u/site/app")], rules)
    assert p["file"][0]["section"] == "Website"


def test_sections_listed_once():
    p = plan([chat("a"), chat("b"), chat("c", group={"id": "cg-2", "name": "Jobs"})])
    assert p["sections"] == [{"id": "cg-1", "name": "System"}, {"id": "cg-2", "name": "Jobs"}]


def test_overrides_detected():
    sessions = [chat("p", "done: kept", pinned=True),
                chat("u", "Back again"),
                chat("m", "Moved", group={"id": "cg-2", "name": "Jobs"}),
                chat("fine", "Fine", pinned=False)]
    log = [{"action": "unpin", "target": "p", "at": 1.0},
           {"action": "archive", "target": "u", "at": 2.0},
           {"action": "file", "target": "m", "group_id": "cg-1", "at": 3.0},
           {"action": "unpin", "target": "fine", "at": 4.0},
           {"action": "archive", "target": "absent", "at": 5.0}]
    p = plan(sessions, log=log)
    got = {(o["kind"], o["id"]) for o in p["overrides"]}
    assert got == {("keep_pinned", "p"), ("never_archive", "u"), ("section", "m")}
    m = [o for o in p["overrides"] if o["id"] == "m"][0]
    assert m["group"] == {"id": "cg-2", "name": "Jobs"} and m["at"] == 3.0


def test_override_uses_last_action_only():
    log = [{"action": "unpin", "target": "p", "at": 1.0}, {"action": "pin", "target": "p", "at": 2.0}]
    assert plan([chat("p", "Work", pinned=True)], log=log)["overrides"] == []


def test_undoing_the_users_own_action_is_not_an_override():
    log = [{"action": "unpin", "target": "p", "at": 1.0, "by": "user"},
           {"action": "archive", "target": "u", "at": 2.0, "by": "user"}]
    sessions = [chat("p", "done: kept", pinned=True), chat("u", "Back again")]
    assert plan(sessions, log=log)["overrides"] == []

def test_rule_matches_kinds():
    c = chat("local_x", "Atlas v14 pace", cwd="/Users/u/kb")
    assert planner.rule_matches({"kind": "keep_pinned", "match": "session", "value": "local_x"}, c)
    assert planner.rule_matches({"kind": "keep_pinned", "match": "title_word", "value": "ATLAS"}, c)
    assert not planner.rule_matches({"kind": "keep_pinned", "match": "title_word", "value": "sco"}, c)
    assert planner.rule_matches({"kind": "section", "match": "cwd", "value": "/Users/u/kb"}, c)
    assert not planner.rule_matches({"kind": "section", "match": "cwd", "value": "/Users/u/k"}, c)
    assert not planner.rule_matches({"kind": "x", "match": "nope", "value": "v"}, c)


def test_fixture_plan():
    sessions = json.loads(FIXTURE.read_text())
    p = plan(sessions, self_id="local_self", routine_titles=r"^Daily X scan")
    assert sorted(archived_ids(p)) == ["local_done_old", "local_routine", "local_stale"]
    assert [u["id"] for u in p["unpin"]] == ["local_handed"]
    assert [f["id"] for f in p["file"]] == ["local_unfiled"]
    assert p["checked"] == 10


def test_parse_sessions_shapes():
    sessions = json.loads(FIXTURE.read_text())
    text = json.dumps(sessions)
    assert planner.parse_sessions(text) == sessions
    assert planner.parse_sessions(sessions) == sessions
    assert planner.parse_sessions([{"type": "text", "text": text}]) == sessions
    assert planner.parse_sessions({"content": [{"type": "text", "text": text}]}) == sessions
    assert planner.parse_sessions({"type": "text", "text": text}) == sessions
    assert planner.parse_sessions("Sessions:\n" + text) == sessions
    assert planner.parse_sessions("[]") == []
    assert planner.parse_sessions("not a list") is None
    assert planner.parse_sessions({"content": "Error: window closed"}) is None
    assert planner.parse_sessions([{"foo": 1}]) is None
    assert planner.parse_sessions(None) is None
    assert planner.parse_sessions(42) is None
