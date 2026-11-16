import json
import os
import subprocess
import sys
from pathlib import Path

from tidy_chats import cli, state

ROOT = Path(__file__).resolve().parent.parent
KEEPER = ROOT / "scripts" / "keeper.py"
FIXTURE = Path(__file__).parent / "fixtures" / "sessions.json"


def keeper(args, stdin="", **extra_env):
    e = dict(os.environ)
    e.update({"TIDY_CHATS_FORCE": "1", "CLAUDE_CODE_HOST_SESSION_ID": "local_me"})
    e.update(extra_env)
    return subprocess.run([sys.executable, str(KEEPER)] + args, input=stdin, capture_output=True,
                          text=True, env=e, timeout=30)


def idea(**kw):
    i = {"id": "1", "kind": "keep_pinned", "target": "local_x", "title": "Atlas v14 pace",
         "cwd": "/Users/u/kb", "group": {"id": "cg-2", "name": "Jobs"}, "status": "pending",
         "count": 2, "events": [1.0, 2.0]}
    i.update(kw)
    return i


def test_hook_entry_roundtrip():
    r = keeper(["hook", "UserPromptSubmit"], json.dumps({"session_id": "u", "cwd": "/w"}))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "tidy-chats" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_entry_bad_stdin_prints_empty_json():
    r = keeper(["hook", "Stop"], "{not json")
    assert r.returncode == 0 and json.loads(r.stdout) == {}
    r = keeper(["hook", "Stop"], "")
    assert r.returncode == 0 and json.loads(r.stdout) == {}


def test_hook_entry_inactive_outside_desktop():
    r = keeper(["hook", "UserPromptSubmit"], json.dumps({"session_id": "u"}), TIDY_CHATS_FORCE="0",
               CLAUDE_CODE_ENTRYPOINT="cli")
    assert json.loads(r.stdout) == {}


def test_ideas_lists_pending_only(capsys):
    state.save_ideas([idea(), idea(id="2", target="local_y", title="Gone", status="rejected")])
    assert cli.main(["ideas"]) == 0
    out = capsys.readouterr().out
    assert "#1" in out and "Atlas v14 pace" in out and "Gone" not in out


def test_accept_creates_rule_and_drops_idea(capsys):
    state.save_ideas([idea(), idea(id="2", kind="section", target="local_z", title="Hero copy",
                                   cwd="/Users/u/site")])
    assert cli.main(["accept", "1", "word:atlas"]) == 0
    assert cli.main(["accept", "2", "folder"]) == 0
    rules = state.load_rules()
    assert {"kind": "keep_pinned", "match": "title_word", "value": "atlas"} in rules
    assert {"kind": "section", "match": "cwd", "value": "/Users/u/site", "section": "Jobs"} in rules
    capsys.readouterr()
    cli.main(["ideas"])
    assert "No rule ideas" in capsys.readouterr().out
    assert [i["status"] for i in state.load_ideas()] == ["accepted", "accepted"]


def test_accept_chat_scope():
    state.save_ideas([idea(kind="never_archive")])
    assert cli.main(["accept", "1", "chat"]) == 0
    assert state.load_rules() == [{"kind": "never_archive", "match": "session", "value": "local_x"}]


def test_accept_unknown_idea_or_scope_fails():
    state.save_ideas([idea()])
    assert cli.main(["accept", "9", "chat"]) == 2
    assert cli.main(["accept", "1", "everything"]) == 2
    assert state.load_rules() == []


def test_reject_remembered():
    state.save_ideas([idea()])
    assert cli.main(["reject", "1"]) == 0
    assert state.load_ideas()[0]["status"] == "rejected"
    assert state.load_rules() == []


def test_add_and_remove_rule():
    assert cli.main(["add-rule", "section", "cwd", "/Users/u/site", "Website"]) == 0
    assert cli.main(["add-rule", "keep_pinned", "title_word", "atlas"]) == 0
    assert cli.main(["add-rule", "section", "cwd", "/x"]) == 2  # section needs a name
    assert cli.main(["add-rule", "bogus", "cwd", "/x"]) == 2
    assert len(state.load_rules()) == 2
    assert cli.main(["remove-rule", "1"]) == 0
    assert state.load_rules() == [{"kind": "keep_pinned", "match": "title_word", "value": "atlas"}]
    assert cli.main(["remove-rule", "5"]) == 2


def test_status_runs(capsys):
    state.log_action({"action": "unpin", "target": "local_x", "chat": "local_me"})
    state.save_ideas([idea()])
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Last sweep: never" in out and "unpin" in out and "1 rule idea" in out


def test_sweep_now_takes_lock(monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", "local_me")
    assert cli.main(["sweep-now"]) == 0
    assert state.sweep_state()["lock"]["holder"] == "local_me"
    assert "list_sessions" in capsys.readouterr().out
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", "local_other")
    assert cli.main(["sweep-now"]) == 1


def test_sweep_now_needs_a_chat(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)
    assert cli.main(["sweep-now"]) == 2


def test_plan_file(capsys):
    assert cli.main(["plan", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "local_done_old" in out and "checked 10 chats" in out
    assert state.load_ideas() == []


def test_debug_toggle(data_dir):
    assert cli.main(["debug", "on"]) == 0
    assert (data_dir / "debug").exists()
    assert cli.main(["debug", "off"]) == 0
    assert not (data_dir / "debug").exists()


def test_usage_errors():
    assert cli.main([]) == 2
    assert cli.main(["nope"]) == 2
