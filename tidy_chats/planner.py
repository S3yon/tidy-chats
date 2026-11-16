"""Pure sweep planner: chat list + rules + action log + now -> what to archive, unpin and file."""
import json
import re
from datetime import datetime, timedelta, timezone

FINISHED = re.compile(r"^\s*(done:|handed off:)", re.I)
DEFAULTS = {"finished_idle_hours": 24, "idle_days": 14, "routine_titles": ""}


def is_finished_title(title):
    return bool(title) and isinstance(title, str) and bool(FINISHED.match(title))


# --- parsing the list_sessions tool output ----------------------------------

def _is_chat_list(x):
    return isinstance(x, list) and all(isinstance(c, dict) and "sessionId" in c for c in x)


def _from_text(text):
    try:
        return parse_sessions(json.loads(text), _depth=1)
    except ValueError:
        pass
    start, end = text.find("["), text.rfind("]")
    if 0 <= start < end:
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            return None
        return data if _is_chat_list(data) else None
    return None


def parse_sessions(tool_response, _depth=0):
    """The chat list inside an MCP tool response, or None if it isn't one.

    Accepts a JSON string, a list of chats, a list of {type: text, text} blocks,
    a single block, or a dict with `content`.
    """
    if _depth > 4:
        return None
    if isinstance(tool_response, str):
        return _from_text(tool_response)
    if _is_chat_list(tool_response):
        return tool_response
    if isinstance(tool_response, list):
        texts = [b.get("text") for b in tool_response
                 if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
        if texts and len(texts) == len(tool_response):
            return _from_text("".join(texts))
        return None
    if isinstance(tool_response, dict):
        if "content" in tool_response:
            return parse_sessions(tool_response["content"], _depth + 1)
        if tool_response.get("type") == "text" and isinstance(tool_response.get("text"), str):
            return _from_text(tool_response["text"])
    return None


# --- rules ------------------------------------------------------------------

def rule_matches(rule, chat):
    match, value = rule.get("match"), rule.get("value")
    if not value:
        return False
    if match == "session":
        return chat.get("sessionId") == value
    if match == "title_word":
        title = chat.get("title") or ""
        return re.search(r"(?<!\w)%s(?!\w)" % re.escape(str(value)), title, re.I) is not None
    if match == "cwd":
        cwd = (chat.get("cwd") or "").rstrip("/")
        v = str(value).rstrip("/")
        return cwd == v or cwd.startswith(v + "/")
    return False


def _any_rule(rules, kind, chat):
    return any(r.get("kind") == kind and rule_matches(r, chat) for r in rules)


# --- the plan ---------------------------------------------------------------

def _when(chat):
    ts = chat.get("lastActivityAt")
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _routine_re(pattern):
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.I)
    except re.error:
        return None


def _nested(chat):
    return bool(chat.get("startedBy")) and not chat.get("detached")


def make_plan(sessions, *, now, self_id, rules, log, opts):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in (opts or {}).items() if v is not None})
    rules = rules or []
    live = [c for c in sessions if isinstance(c, dict) and c.get("sessionId") and not c.get("isArchived")]
    by_id = {c["sessionId"]: c for c in live}
    routine = _routine_re(o.get("routine_titles"))
    finished_age = timedelta(hours=float(o["finished_idle_hours"]))
    idle_age = timedelta(days=float(o["idle_days"]))

    kids = {}
    for c in live:
        if _nested(c) and c["startedBy"] in by_id:
            kids.setdefault(c["startedBy"], []).append(c["sessionId"])

    def reason(c):
        if c["sessionId"] == self_id or c.get("isRunning") or c.get("pinned"):
            return None
        when = _when(c)
        if when is None or _any_rule(rules, "never_archive", c):
            return None
        age = now - when
        title = c.get("title") or ""
        if is_finished_title(title) and age >= finished_age:
            return "finished"
        if routine is not None and routine.search(title) and age >= timedelta(hours=1):
            return "routine"
        if age >= idle_age:
            return "idle"
        return None

    reasons = {sid: reason(c) for sid, c in by_id.items()}
    chosen = set()

    def blocked(sid, seen=()):
        for k in kids.get(sid, []):
            if k in seen:
                continue
            if k not in chosen or blocked(k, seen + (sid,)):
                return True
        return False

    changed = True
    while changed:  # archiving an open last chat frees the chain above it
        changed = False
        for sid in by_id:
            if sid not in chosen and reasons[sid] and not blocked(sid):
                chosen.add(sid)
                changed = True

    archive = [{"id": sid, "title": c.get("title") or "", "reason": reasons[sid]}
               for sid, c in by_id.items()
               if sid in chosen and not (_nested(c) and c["startedBy"] in chosen)]

    unpin = [{"id": sid, "title": c.get("title") or ""} for sid, c in by_id.items()
             if c.get("pinned") and sid != self_id and is_finished_title(c.get("title"))
             and not _any_rule(rules, "keep_pinned", c)]

    file_ = []
    for sid, c in by_id.items():
        if c.get("group") or _nested(c) or c.get("pinned") or sid == self_id or sid in chosen:
            continue
        item = {"id": sid, "title": c.get("title") or "", "cwd": c.get("cwd") or ""}
        hint = next((r.get("section") for r in rules
                     if r.get("kind") == "section" and r.get("section") and rule_matches(r, c)), None)
        if hint:
            item["section"] = hint
        file_.append(item)

    sections, seen_groups = [], set()
    for c in live:
        g = c.get("group")
        if isinstance(g, dict) and g.get("id") and g["id"] not in seen_groups:
            seen_groups.add(g["id"])
            sections.append({"id": g["id"], "name": g.get("name") or ""})

    return {"archive": archive, "unpin": unpin, "file": file_, "sections": sections,
            "overrides": find_overrides(by_id, log or []), "checked": len(live)}


def find_overrides(by_id, log):
    """The user reversing the keeper's last logged action on a chat."""
    last = {}
    for e in log:
        if isinstance(e, dict) and e.get("target"):
            last[e["target"]] = e
    out = []
    for target, e in last.items():
        c = by_id.get(target)
        if c is None:
            continue
        group = c.get("group") if isinstance(c.get("group"), dict) else None
        kind = None
        action = e.get("action")
        if action == "unpin" and c.get("pinned"):
            kind = "keep_pinned"
        elif action == "archive":
            kind = "never_archive"
        elif action == "file":
            filed_to = e.get("group_id") or e.get("section_id")
            if filed_to and filed_to != "sessions" and group and group.get("id") != filed_to:
                kind = "section"
        if kind:
            out.append({"kind": kind, "id": target, "title": c.get("title") or "",
                        "cwd": c.get("cwd") or "", "group": group, "at": e.get("at")})
    return out
