"""Hook handlers: one per event. Each returns hook output JSON ({} when there is nothing to say)."""
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import config, notes, planner, state

BIG_TRANSCRIPT = 4 * 1024 * 1024
OVERDUE_FOR_BIG = 24 * 3600
MAX_HINTS = 3
SAMPLE_MAX = 4000
FULL_LIST = 200
# A turn the app started, not the user: another chat's message, a side session ending, CI, a task.
AUTOMATED = re.compile(r"\A\s*(?:[^<\n]{0,80}\n\s*)?<(?:cross-session-message|side-sessions-event|"
                       r"ci-monitor-event|task-notification)\b")
# A first prompt that picks up another chat's work: names a handoff, or a line starts "Pick up".
PICKUP = re.compile(r"(?im)(\bhand(?:ed)?[- ]?offs?\b|^\W*pick up\b)")
# A sidebar call the app or the user turned down: nothing changed, so nothing is recorded.
DECLINED = re.compile(r"\b(?:declin|denied|refus|not renamed|not pinned|not moved|cancel|fail|error)",
                      re.I)


def handle(event, payload, env, now):
    try:
        if not isinstance(payload, dict) or payload.get("agent_id") or not config.active(env):
            return {}
        cid = config.chat_id(payload, env)
        if event == "UserPromptSubmit":
            return _prompt(cid, payload, now)
        if event == "PostToolUse":
            return _post_tool(cid, payload, env, now)
        if event == "Stop":
            return _stop(cid, payload, env, now)
        return {}
    except Exception:  # never block the chat
        _log_error(event)
        return {}


def _log_error(event):
    try:
        with open(state.data_dir() / "errors.log", "a", encoding="utf-8") as f:
            f.write("%s %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), event, traceback.format_exc()))
    except Exception:
        pass


def _ctx(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


# --- UserPromptSubmit -------------------------------------------------------

def _section_hints(cwd):
    folder, words = [], []  # a folder match fits this chat for sure, so it comes first
    for r in state.load_rules():
        if r.get("kind") != "section" or not r.get("section"):
            continue
        if r.get("match") == "cwd" and planner.rule_matches(r, {"cwd": cwd}):
            folder.append("%s (folder %s)" % (r["section"], r.get("value")))
        elif r.get("match") == "title_word":
            words.append('%s for titles with "%s"' % (r["section"], r.get("value")))
    return (folder + words)[:MAX_HINTS]


def _keep_pinned():
    """Plain descriptions of the user's keep_pinned rules, for the pick-up notes."""
    out = []
    for r in state.load_rules():
        value = str(r.get("value") or "")
        if r.get("kind") != "keep_pinned" or not value:
            continue
        if r.get("match") == "session":
            out.append(value[:14])  # "local_" + 8 hex: enough to match parentSessionId
        elif r.get("match") == "title_word":
            out.append('titles with "%s"' % value)
        elif r.get("match") == "cwd":
            out.append("folder " + value)
    return out


def _prompt(cid, payload, now):
    st = state.load_chat(cid)
    automated = bool(AUTOMATED.match(str(payload.get("prompt") or "")))
    if not st.get("seen"):
        if automated:  # the first-turn note waits for the user's own prompt
            return {}
        pickup = bool(PICKUP.search(str(payload.get("prompt") or "")))
        state.save_chat(cid, {"seen": 1, "started_at": now, "pickup": pickup, "noted": True})
        hints = _section_hints(payload.get("cwd") or "")
        return _ctx("UserPromptSubmit", notes.pickup_note(hints, _keep_pinned()) if pickup
                    else notes.first_turn_note(hints))
    st.update({"finished": False, "waiting": False, "completed": False, "finish_reminded": False,
               "wrapped_turn": False, "handed_off": False, "pin_asked": False, "noted": False})
    note = None
    if not automated:  # the user wrote here: open work is pinned and not done (his ask 2026-11-16)
        rename = _done_known(cid, st)
        pin = not _pin_known(cid, st)
        if rename or pin:
            note = notes.working_note(pin=pin, rename=rename)
        st["done"] = False
        st["pin_asked"] = pin
    st["noted"] = bool(note)
    state.save_chat(cid, st)
    return _ctx("UserPromptSubmit", note) if note else {}


def _latest(cid, kinds):
    """The newest logged action of these kinds on this chat, by any chat."""
    best = None
    for e in state.read_log():
        if e.get("target") == cid and e.get("action") in kinds:
            if best is None or _at(e) >= _at(best):
                best = e
    return best


def _at(entry):
    try:
        return float(entry.get("at") or 0)
    except (TypeError, ValueError):
        return 0.0


def _pin_known(cid, st):
    """Pinned as far as this keeper saw: the chat's own get_session, or the newest pin action."""
    e = _latest(cid, ("pin", "unpin"))
    seen_at = st.get("pinned_at")
    if seen_at is not None and (e is None or float(seen_at) >= _at(e)):
        return bool(st.get("pinned"))
    if e is not None:
        return e.get("action") == "pin"
    return bool(st.get("pinned"))


def _done_known(cid, st):
    e = _latest(cid, ("rename", "rename_done"))
    seen_at = st.get("title_at")
    if seen_at is not None and (e is None or float(seen_at) >= _at(e)):
        return planner.is_finished_title(st.get("title"))
    if e is not None:
        return e.get("action") == "rename_done"
    return bool(st.get("done"))


# --- PostToolUse ------------------------------------------------------------

def _text(resp):
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        if "content" in resp:
            return _text(resp["content"])
        if isinstance(resp.get("text"), str):
            return resp["text"]
        return ""
    if isinstance(resp, list):
        return "".join(_text(b) for b in resp)
    return ""


def _json_obj(resp):
    if isinstance(resp, dict) and "sessionId" in resp:
        return resp
    try:
        data = json.loads(_text(resp))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _mirror(resp, text):
    """The replacement output, in the same shape the tool returned."""
    if isinstance(resp, list):
        return [{"type": "text", "text": text}]
    if isinstance(resp, dict):
        if "content" in resp:
            out = dict(resp)
            out["content"] = [{"type": "text", "text": text}]
            return out
        if resp.get("type") == "text":
            return {"type": "text", "text": text}
    return text


def _save_sample(short, payload):
    d = state.data_dir()
    if not (d / "debug").exists():
        return
    sample = {"tool_name": payload.get("tool_name"), "tool_input": payload.get("tool_input"),
              "tool_response": payload.get("tool_response")}
    raw = json.dumps(sample, default=str)
    if len(raw) > SAMPLE_MAX:
        sample["tool_response"] = json.dumps(payload.get("tool_response"), default=str)[:SAMPLE_MAX - 500]
        sample["truncated"] = True
    state.write_json(d / "samples" / (short + ".json"), sample)


def _post_tool(cid, payload, env, now):
    name = payload.get("tool_name") or ""
    if not name.startswith("mcp__ccd_"):
        return {}
    short = name.split("__")[-1]
    inp = payload.get("tool_input") or {}
    resp = payload.get("tool_response")
    _save_sample(short, payload)

    def target(sid):
        return cid if sid in (None, "", "self") else sid

    st = state.load_chat(cid)
    before = dict(st)
    out = {}
    # Calls in a turn the keeper sent a note in are the keeper's; the rest the user asked for.
    by = "keeper" if st.get("noted") else "user"
    if short in ("set_session_title", "set_pinned", "move_sessions") and _declined(resp):
        short = "declined"
    if short == "wrap_up":
        st["saw_wrap_up"] = True
        st["wrapped_turn"] = True
        if str(inp.get("ask") or "").strip() or inp.get("blocked"):
            st.update({"finished": False, "waiting": True})
        else:
            st.update({"finished": True, "waiting": False})
            if not (st.get("done") or st.get("handed_off")):
                out = _ctx("PostToolUse", notes.finish_note(_keep_pin(cid, st, payload)))
                st["noted"] = True
    elif short == "start_session":
        # Handing off: the chat keeps its pin until the pick-up chat unpins it (KB rule 2026-10-21).
        if str(inp.get("title") or "").strip().lower().startswith("pick up"):
            st["handed_off"] = True
            state.log_action({"action": "handoff", "target": cid, "chat": cid})
    elif short == "set_session_title":
        t = target(inp.get("session_id"))
        done = planner.is_finished_title(inp.get("title"))
        if t == cid:
            st["done"] = done
            st["title"] = inp.get("title")
            st["title_at"] = now
        state.log_action({"action": "rename_done" if done else "rename", "target": t, "chat": cid,
                          "at": now, "by": by})
    elif short == "set_pinned":
        t = target(inp.get("session_id"))
        pinned = bool(inp.get("pinned"))
        if t == cid:
            st["pinned"] = pinned
            st["pinned_at"] = now
        state.log_action({"action": "pin" if pinned else "unpin", "target": t, "chat": cid, "at": now,
                          "by": by})
    elif short == "move_sessions":
        dest = {k: inp[k] for k in ("section_id", "group_id") if inp.get(k) is not None}
        for sid in inp.get("session_ids") or []:
            t = target(sid)
            if t == cid:
                st["filed"] = True
            entry = {"action": "file", "target": t, "chat": cid, "by": by}
            entry.update(dest)
            state.log_action(entry)
    elif short == "archive_session":
        t = target(inp.get("session_id"))
        if t != cid and "archived session" in _text(resp).lower():
            state.log_action({"action": "archive", "target": t, "chat": cid, "by": by})
    elif short == "mark_completed":
        if target(inp.get("session_id")) == cid:
            st["completed"] = True
    elif short == "detach_session":
        if target(inp.get("session_id")) == cid:
            st["nested"] = False
            st["parent"] = None
    elif short == "get_session":
        if target(inp.get("session_id")) == cid:
            info = _json_obj(resp)
            if info is not None:
                st["filed"] = bool(info.get("group")) or bool(st.get("filed"))
                st["nested"] = bool(info.get("parentSessionId")) and not info.get("detached")
                st["parent"] = info.get("parentSessionId") if st["nested"] else None
                st["pinned"] = bool(info.get("pinned"))
                st["pinned_at"] = now
                if isinstance(info.get("title"), str):
                    st["title"] = info["title"]
                    st["title_at"] = now
                    st["done"] = planner.is_finished_title(info["title"])
    elif short == "list_sessions":
        out = _plan_swap(cid, inp, resp, env, now, st.get("parent"))
        if out:
            st["noted"] = True
    state.merge_chat(cid, before, st)
    return out


def _declined(resp):
    """The call was turned down. Quoted text (a title like "Fix the login failure") is ignored."""
    return bool(DECLINED.search(re.sub(r'"[^"]*"', "", _text(resp))))


def _full_list_limit(inp):
    """The limit of a list_sessions call that asked for the whole list, else None."""
    if not isinstance(inp, dict) or "group" in inp or "linked" in inp:
        return None
    limit = inp.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit < FULL_LIST:
        return None
    return int(limit)


def _keep_pin(cid, st, payload):
    """True when an approved keep_pinned rule matches this chat."""
    chat = {"sessionId": cid, "cwd": payload.get("cwd") or "", "title": st.get("title") or ""}
    return any(r.get("kind") == "keep_pinned" and planner.rule_matches(r, chat)
               for r in state.load_rules())


SAVED = re.compile(r"saved to (/\S+?\.txt)")
SAVED_MAX = 8 * 1024 * 1024


def _saved_list(resp, env):
    """An over-size list_sessions result: the app saves it to a file and returns an error naming it."""
    m = SAVED.search(_text(resp))
    if not m:
        return None
    root = Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").resolve() / "projects"
    path = Path(m.group(1)).resolve()
    if (root not in path.parents or path.parent.name != "tool-results"
            or not path.name.startswith("mcp-ccd_session_mgmt-list_sessions")):
        return None
    try:
        if path.stat().st_size > SAVED_MAX:
            return None
        return planner.parse_sessions(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _plan_swap(cid, inp, resp, env, now, parent=None):
    lock = state.sweep_state()["lock"]
    if not lock or lock.get("holder") != cid:
        return {}
    limit = _full_list_limit(inp)
    if limit is None:
        return {}
    sessions = planner.parse_sessions(resp)
    if sessions is None:
        sessions = _saved_list(resp, env)
    if sessions is None:
        return {}
    opts = config.options(env)
    plan = planner.make_plan(sessions, now=datetime.fromtimestamp(now, timezone.utc), self_id=cid,
                             rules=state.load_rules(), log=state.read_log(), opts=opts,
                             self_parent=parent)
    if len(sessions) >= limit:  # chats past the limit are unseen: their chains can't be judged
        plan["archive"] = []
        plan["truncated"] = limit
    waiting = _update_ideas(plan["overrides"], now)
    text = notes.render_plan(plan, archive_mode=opts["archive"], ideas_waiting=waiting,
                             now=datetime.fromtimestamp(now, timezone.utc))
    state.log_action({"action": "sweep", "chat": cid, "checked": plan["checked"],
                      "archive": len(plan["archive"]), "unpin": len(plan["unpin"]),
                      "file": len(plan["file"]), "finished_idle_hours": opts["finished_idle_hours"],
                      "sweep_hours": opts["sweep_hours"], **_held_counts(plan["held"])})
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "updatedMCPToolOutput": _mirror(resp, text)}}


def _held_counts(held):
    """Finished chats a sweep left because a chat they started is still open, for status."""
    sections = {}
    for h in held:
        name = h.get("section") or "no section"
        sections[name] = sections.get(name, 0) + 1
    return {"held": len(held), "held_by": len({k for h in held for k in h.get("by", [])}),
            "held_sections": sections}


def _update_ideas(overrides, now):
    ideas = state.load_ideas()
    by_key = {(i.get("kind"), i.get("target")): i for i in ideas}
    next_id = max([int(i["id"]) for i in ideas if str(i.get("id", "")).isdigit()] + [0]) + 1
    for o in overrides:
        key = (o["kind"], o["id"])
        idea = by_key.get(key)
        if idea is None:
            idea = {"id": str(next_id), "kind": o["kind"], "target": o["id"], "status": "pending",
                    "events": [], "count": 0, "first_seen": now}
            next_id += 1
            ideas.append(idea)
            by_key[key] = idea
        if idea.get("status") != "pending":
            continue
        idea.update({"title": o.get("title"), "cwd": o.get("cwd"), "group": o.get("group")})
        events = idea.setdefault("events", [])
        if o.get("at") not in events:
            events.append(o.get("at"))
        idea["count"] = len(events)
    state.save_ideas(ideas)
    return sum(1 for i in ideas if i.get("status") == "pending")


# --- Stop -------------------------------------------------------------------

def _transcript_size(payload):
    path = payload.get("transcript_path")
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def _stop(cid, payload, env, now):
    ss = state.sweep_state()
    lock = ss["lock"]
    if lock and lock.get("holder") == cid:
        # The holder's next Stop ends its sweep, whether or not the plan was done.
        state.release_lock(cid, now)
        return {}
    if payload.get("stop_hook_active"):
        return {}

    st = state.load_chat(cid)
    if not st.get("wrapped_turn"):  # no wrap_up this turn: read the last message
        last = str(payload.get("last_assistant_message") or "").rstrip()
        if last.endswith("?"):
            st.update({"finished": False, "waiting": True})
        elif last and not st.get("saw_wrap_up") and not config.has_wrap_up(env):
            st.update({"finished": True, "waiting": False})

    note = None
    if (st.get("finished") and not (st.get("done") or st.get("completed") or st.get("handed_off"))
            and not st.get("finish_reminded")):
        st["finish_reminded"] = True
        note = notes.missed_note("finish", _keep_pin(cid, st, payload))
    elif (st.get("pickup") and not st.get("pickup_reminded")
          and not (st.get("done") or st.get("completed") or st.get("handed_off"))
          and (st.get("nested") is not False or not st.get("pinned"))):
        st["pickup_reminded"] = True
        st["first_turn_reminded"] = True  # the pick-up reminder covers filing too
        note = notes.missed_note("pickup", keep=_keep_pinned())
    elif (st.get("seen") and not st.get("filed") and not st.get("nested")
          and not st.get("first_turn_reminded")):
        st["first_turn_reminded"] = True
        note = notes.missed_note("first_turn")
    elif st.get("pin_asked") and not st.get("finished") and not _pin_known(cid, st):
        note = notes.missed_note("working", rename=_done_known(cid, st))
    elif not st.get("waiting") and _sweep_due(ss, payload, env, now) and state.try_lock(cid, now):
        st["sweep_lock_at"] = now
        note = notes.sweep_note()
    st["pin_asked"] = False  # one pin reminder per prompt
    if note:
        st["noted"] = True
    state.save_chat(cid, st)
    return _ctx("Stop", note) if note else {}


def _sweep_due(ss, payload, env, now):
    last = ss["last_sweep_at"]
    if last is None:
        return True
    late = now - last - config.options(env)["sweep_hours"] * 3600
    if late < 0:
        return False
    return _transcript_size(payload) <= BIG_TRANSCRIPT or late >= OVERDUE_FOR_BIG
