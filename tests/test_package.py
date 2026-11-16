import json
import os
import subprocess
from pathlib import Path

from tidy_chats import config

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ("UserPromptSubmit", "PostToolUse", "Stop")


def load(rel):
    return json.loads((ROOT / rel).read_text())


def test_hooks_json_events_and_commands():
    hooks = load("hooks/hooks.json")["hooks"]
    assert sorted(hooks) == sorted(EVENTS)
    for event in EVENTS:
        groups = hooks[event]
        assert len(groups) == 1
        group = groups[0]
        if event == "PostToolUse":
            assert group["matcher"] == "mcp__ccd_.*"
        else:
            assert "matcher" not in group
        assert len(group["hooks"]) == 1
        h = group["hooks"][0]
        assert h["type"] == "command"
        assert h["command"] == 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/keeper.py" hook ' + event
        assert h["timeout"] == 10


def test_hook_commands_run_from_the_plugin_root():
    hooks = load("hooks/hooks.json")["hooks"]
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT), TIDY_CHATS_FORCE="0",
               CLAUDE_CODE_ENTRYPOINT="cli")
    for event in EVENTS:
        cmd = hooks[event][0]["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
        r = subprocess.run(cmd, shell=True, input="{}", capture_output=True, text=True,
                           env=env, timeout=30)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) == {}


def test_plugin_json_options_match_config_defaults():
    p = load(".claude-plugin/plugin.json")
    assert p["name"] == "tidy-chats"
    assert p["version"] == "0.1.6"
    assert p["author"]["name"] == "Seyon Sri"
    assert p["license"] == "MIT"
    opts = p["userConfig"]
    assert sorted(opts) == sorted(config.DEFAULTS)
    for key, default in config.DEFAULTS.items():
        o = opts[key]
        assert o["title"] and o["description"]
        assert o["default"] == default
        assert o["type"] == ("number" if key in config.NUMBERS else "string")
    assert opts["archive"]["options"] == ["auto", "ask"]


def test_marketplace_lists_the_plugin_at_the_root():
    m = load(".claude-plugin/marketplace.json")
    p = load(".claude-plugin/plugin.json")
    assert m["name"] == "tidy-chats"
    assert m["owner"]["name"] == "Seyon Sri"
    assert len(m["plugins"]) == 1
    entry = m["plugins"][0]
    assert entry["name"] == "tidy-chats" and entry["source"] == "./"
    assert entry["version"] == p["version"]


def test_license_and_readme_exist():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    readme = (ROOT / "README.md").read_text()
    for word in ("Install", "Options", "Status", "/tidy-chats:rules"):
        assert word in readme


def test_routine_option_promises_only_what_the_planner_does():
    p = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert "never pinned" not in p["userConfig"]["routine_titles"]["description"]
    assert "never pinned" not in (ROOT / "README.md").read_text()
