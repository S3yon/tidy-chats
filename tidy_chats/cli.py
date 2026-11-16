"""Command line: the hook entry, rule review, status and manual sweeps."""
import json
import os
import sys
import time
from datetime import datetime, timezone

from . import config, hooks, notes, planner, state

KINDS = ("keep_pinned", "never_archive", "section")
MATCHES = ("session", "title_word", "cwd")
USAGE = """usage: keeper.py <command>
  hook <Event>                 read hook JSON on stdin, print hook output JSON
  status                       last sweep, lock, rules, ideas, recent actions
  rules                        list rules
  ideas                        list rule ideas waiting for a yes or no
  accept <id> chat|word:<w>|folder
  reject <id>
  add-rule <kind> <match> <value> [section]   kind: keep_pinned|never_archive|section
  remove-rule <n>
  sweep-now                    take the sweep lock for this chat
  plan <file>                  print the plan for a saved list_sessions output
  debug on|off                 save samples of sidebar tool calls"""

WHY = {"keep_pinned": "you pinned it back after tidy-chats unpinned it",
       "never_archive": "you brought it back after tidy-chats archived it",
       "section": "you moved it to another section than the one it was filed into"}


def main(argv):
    if not argv:
        print(USAGE)
        return 2
    cmd, args = argv[0], argv[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(USAGE)
        return 2
    return fn(args)


def cmd_hook(args):
    try:
        event = args[0] if args else ""
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
        out = hooks.handle(event, payload, os.environ, time.time()) if isinstance(payload, dict) else {}
    except Exception:
        out = {}
    print(json.dumps(out))
    return 0


def _ago(ts, now):
    mins = int((now - ts) / 60)
    if mins < 60:
        return "%d min ago" % mins
    if mins < 48 * 60:
        return "%d h ago" % (mins // 60)
    return "%d days ago" % (mins // 1440)


def _rule_line(n, r):
    line = "%d. %s: %s = %s" % (n, r.get("kind"), r.get("match"), r.get("value"))
    return line + (" -> %s" % r["section"] if r.get("section") else "")


def _pending():
    return [i for i in state.load_ideas() if i.get("status") == "pending"]


def cmd_status(args):
    now = time.time()
    ss = state.sweep_state()
    print("Last sweep: %s" % (_ago(ss["last_sweep_at"], now) if ss["last_sweep_at"] else "never"))
    hours = next((e.get("sweep_hours") for e in reversed(state.read_log())
                  if e.get("action") == "sweep" and e.get("sweep_hours")), None)
    if ss["last_sweep_at"] and hours:
        due = ss["last_sweep_at"] + hours * 3600
        span = _ago(min(due, now), max(due, now))[:-len(" ago")]
        print("Next sweep: %s (every %g h; a chat's Stop starts it)"
              % (("overdue by " if due <= now else "due in ") + span, hours))
    lock = ss["lock"]
    print("Sweep lock: %s" % ("held by %s since %s" % (lock.get("holder"), _ago(lock["at"], now))
                              if lock else "free"))
    rules = state.load_rules()
    print("Rules: %d" % len(rules))
    for n, r in enumerate(rules, 1):
        print("  " + _rule_line(n, r))
    n = len(_pending())
    print("%d rule idea%s waiting%s" % (n, "" if n == 1 else "s", " (/tidy-chats:rules)" if n else ""))
    log = state.read_log()[-10:]
    print("Last actions:" if log else "Last actions: none")
    for e in log:
        when = _ago(e["at"], now) if isinstance(e.get("at"), (int, float)) else "?"
        if e.get("action") == "sweep":
            detail = "checked %s, archive %s, unpin %s, file %s" % tuple(
                e.get(k, "?") for k in ("checked", "archive", "unpin", "file"))
            if e.get("finished_idle_hours") is not None:
                detail += ", finished chats after %g h" % e["finished_idle_hours"]
            print("  %s  sweep (%s)" % (when, detail))
            continue
        print("  %s  %s %s" % (when, e.get("action"), e.get("target") or ""))
    return 0


def cmd_rules(args):
    rules = state.load_rules()
    if not rules:
        print("No rules yet.")
    for n, r in enumerate(rules, 1):
        print(_rule_line(n, r))
    return 0


def cmd_ideas(args):
    ideas = _pending()
    if not ideas:
        print("No rule ideas waiting.")
        return 0
    for i in ideas:
        group = (i.get("group") or {}).get("name")
        print('#%s %s: "%s" — %s (%d time%s). Folder: %s.%s' % (
            i["id"], i["kind"], i.get("title") or "", WHY.get(i["kind"], ""), i.get("count", 1),
            "" if i.get("count", 1) == 1 else "s", i.get("cwd") or "?",
            (" Section now: %s." % group) if group else ""))
    return 0


def _find_idea(ideas, idea_id):
    return next((i for i in ideas if str(i.get("id")) == str(idea_id) and i.get("status") == "pending"), None)


def cmd_accept(args):
    if len(args) != 2:
        print(USAGE)
        return 2
    ideas = state.load_ideas()
    idea = _find_idea(ideas, args[0])
    if idea is None:
        print("No waiting rule idea #%s." % args[0])
        return 2
    scope = args[1]
    if scope == "chat" and idea["kind"] == "section":
        print("A section rule for one chat does nothing: that chat is already filed. "
              "Use word:<word> or folder.")
        return 2
    if scope == "chat":
        rule = {"kind": idea["kind"], "match": "session", "value": idea["target"]}
    elif scope.startswith("word:") and scope[5:].strip():
        rule = {"kind": idea["kind"], "match": "title_word", "value": scope[5:].strip().lower()}
    elif scope == "folder" and idea.get("cwd"):
        rule = {"kind": idea["kind"], "match": "cwd", "value": idea["cwd"]}
    else:
        print("Scope must be chat, word:<word> or folder.")
        return 2
    if idea["kind"] == "section":
        name = (idea.get("group") or {}).get("name")
        if not name:
            print("Idea #%s has no section name." % idea["id"])
            return 2
        rule["section"] = name
    rules = state.load_rules()
    if rule not in rules:
        rules.append(rule)
        state.save_rules(rules)
    idea["status"] = "accepted"
    state.save_ideas(ideas)
    print("Rule added: " + _rule_line(len(rules), rule))
    return 0


def cmd_reject(args):
    if len(args) != 1:
        print(USAGE)
        return 2
    ideas = state.load_ideas()
    idea = _find_idea(ideas, args[0])
    if idea is None:
        print("No waiting rule idea #%s." % args[0])
        return 2
    idea["status"] = "rejected"
    state.save_ideas(ideas)
    print("Rule idea #%s rejected; it won't be raised again." % idea["id"])
    return 0


def cmd_add_rule(args):
    if len(args) not in (3, 4) or args[0] not in KINDS or args[1] not in MATCHES:
        print(USAGE)
        return 2
    rule = {"kind": args[0], "match": args[1], "value": args[2]}
    if args[0] == "section":
        if len(args) != 4:
            print("A section rule needs the section name.")
            return 2
        rule["section"] = args[3]
    rules = state.load_rules()
    if rule not in rules:
        rules.append(rule)
        state.save_rules(rules)
    print("Rule added: " + _rule_line(len(rules), rule))
    return 0


def cmd_remove_rule(args):
    rules = state.load_rules()
    try:
        n = int(args[0])
    except (IndexError, ValueError):
        print(USAGE)
        return 2
    if not 1 <= n <= len(rules):
        print("No rule %d." % n)
        return 2
    gone = rules.pop(n - 1)
    state.save_rules(rules)
    print("Removed: " + _rule_line(n, gone))
    return 0


def cmd_sweep_now(args):
    chat = os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")
    if not chat:
        print("Run this inside a desktop-app chat (CLAUDE_CODE_HOST_SESSION_ID is not set).")
        return 2
    now = time.time()
    if state.try_lock(chat, now):
        print("Sweep lock taken for this chat. Now call list_sessions with limit 200; "
              "its output comes back as the plan.")
        return 0
    lock = state.sweep_state()["lock"] or {}
    print("Another chat (%s) is sweeping, since %s. Try again later." % (
        lock.get("holder"), _ago(lock.get("at", now), now)))
    return 1


def cmd_plan(args):
    if len(args) != 1:
        print(USAGE)
        return 2
    with open(args[0], encoding="utf-8") as f:
        raw = f.read()
    sessions = planner.parse_sessions(raw)
    if sessions is None:
        print("Not a list_sessions output.")
        return 2
    opts = config.options(os.environ)
    now = datetime.now(timezone.utc)
    plan = planner.make_plan(sessions, now=now, self_id=os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", ""),
                             rules=state.load_rules(), log=state.read_log(), opts=opts)
    print(notes.render_plan(plan, archive_mode=opts["archive"], ideas_waiting=len(_pending()), now=now))
    return 0


def cmd_debug(args):
    flag = state.data_dir() / "debug"
    if args == ["on"]:
        flag.write_text("on\n")
        print("Saving samples of sidebar tool calls to %s" % (state.data_dir() / "samples"))
    elif args == ["off"]:
        if flag.exists():
            flag.unlink()
        print("Samples off.")
    else:
        print(USAGE)
        return 2
    return 0


COMMANDS = {"hook": cmd_hook, "status": cmd_status, "rules": cmd_rules, "ideas": cmd_ideas,
            "accept": cmd_accept, "reject": cmd_reject, "add-rule": cmd_add_rule,
            "remove-rule": cmd_remove_rule, "sweep-now": cmd_sweep_now, "plan": cmd_plan,
            "debug": cmd_debug}
