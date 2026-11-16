"""Note texts the hooks add to a chat, and the sweep plan rendering. Factual, short, under 900 chars."""

CAP = 25
TITLE_MAX = 70

_SIDEBAR = "mcp__ccd_sidebar__"
_SESSION = "mcp__ccd_session_mgmt__"


def _load(*names):
    return "If deferred, load them in one ToolSearch call: select:" + ",".join(names) + "."


def first_turn_note(section_hints):
    text = (
        "tidy-chats (sidebar upkeep), first turn of this chat. Alongside your first tool calls: "
        "get_session \"self\". If this chat picks up work another chat handed off and still nests "
        "under it, detach_session \"self\". If it has no group, move_sessions [\"self\"] into the "
        "closest existing section (list_sections; never create one). Then set_pinned \"self\" true; "
        "if the title starts with \"done: \", drop that prefix. Skip all this for a routine run or "
        "a side session doing part of the work of the chat that started it (a pick-up is not one). "
        + _load(_SESSION + "get_session", _SESSION + "detach_session", _SIDEBAR + "list_sections",
                _SIDEBAR + "move_sessions", _SIDEBAR + "set_pinned")
        + " Keep this out of your reply."
    )
    return _with_hints(text, section_hints)


def _with_hints(text, section_hints):
    kept = []
    for hint in section_hints:
        trial = text + " Sections the user chose for chats like this: " + "; ".join(kept + [hint]) + "."
        if len(trial) >= 900:
            break
        kept.append(hint)
    if kept:
        text += " Sections the user chose for chats like this: " + "; ".join(kept) + "."
    return text


_PICKUP_TOOLS = (_SESSION + "get_session", _SESSION + "set_session_title", _SESSION + "detach_session",
                 _SIDEBAR + "list_sections", _SIDEBAR + "move_sessions", _SIDEBAR + "set_pinned")


def pickup_note(section_hints):
    text = (
        "tidy-chats: this first prompt looks like a pick-up of a handed-off chat. If it is, before "
        "the task: set_session_title that chat to \"done: \" plus its title (always \"done: \", "
        "whatever the prompt says; drop a \"handed off: \" prefix) and set_pinned it false. "
        "get_session \"self\"; if it has a parentSessionId and isn't detached, detach_session "
        "\"self\", even as a side session. If it has no group, move_sessions [\"self\"] into that "
        "chat's section, else the closest (list_sections). Then set_pinned \"self\" true. That chat is parentSessionId or the one "
        "the prompt names. " + _load(*_PICKUP_TOOLS) + " Keep this out of your reply."
    )
    return _with_hints(text, section_hints)


def _finish_tools(keep_pin):
    if keep_pin:  # the user's keep_pinned rule: no unpin step
        return ("", _load(_SESSION + "set_session_title", _SIDEBAR + "mark_completed"))
    return ("set_pinned \"self\" false, ",
            _load(_SESSION + "set_session_title", _SIDEBAR + "set_pinned", _SIDEBAR + "mark_completed"))


def finish_note(keep_pin=False):
    unpin, load = _finish_tools(keep_pin)
    return (
        "tidy-chats: this turn finished with nothing waiting on the user. Before your closing "
        "message: set_session_title \"self\" to \"done: \" plus the current title (skip if it "
        "already starts with \"done: \" or \"handed off: \"), " + unpin + "then "
        "mark_completed \"self\". " + load + " Don't mention this upkeep in your reply."
    )


def reopen_note():
    return (
        "tidy-chats: this chat was marked done and the user wrote again. Alongside your first "
        "tool call: set_session_title \"self\" to the title without its \"done: \" or \"handed "
        "off: \" prefix, and "
        "set_pinned \"self\" true. "
        + _load(_SESSION + "set_session_title", _SIDEBAR + "set_pinned")
        + " Don't mention this upkeep in your reply."
    )


def missed_note(step, keep_pin=False):
    if step == "finish":
        unpin, load = _finish_tools(keep_pin)
        body = ("this chat finished but its done steps were not seen: set_session_title \"self\" "
                "to \"done: \" plus the title, " + unpin + "mark_completed \"self\". " + load)
    elif step == "pickup":
        body = ("this pick-up chat's steps were not all seen: rename the chat that handed off "
                "\"done: \" plus its title and set_pinned it false; detach_session \"self\" if it "
                "still nests under that chat; if it has no group, move_sessions [\"self\"] into a "
                "section; set_pinned \"self\" true. Skip what is already done. "
                + _load(*_PICKUP_TOOLS))
    else:
        body = ("this chat's first-turn filing was not seen: get_session \"self\"; if it has no "
                "group, move_sessions [\"self\"] into the closest existing section (list_sections); "
                "then set_pinned \"self\" true. Skip both for a routine run or a side session doing "
                "part of the work of the chat that started it. "
                + _load(_SESSION + "get_session", _SIDEBAR + "list_sections",
                        _SIDEBAR + "move_sessions", _SIDEBAR + "set_pinned"))
    return "tidy-chats: " + body + " No reply text needed."


def sweep_note():
    return (
        "tidy-chats: a sidebar sweep is due and this chat holds the sweep lock. Call list_sessions "
        "with limit 200. " + _load(_SESSION + "list_sessions")
        + " Its output comes back as a short plan instead of the full list; do what the plan "
        "says, then end with one short line of what changed."
    )


def _trim(title):
    title = " ".join(str(title or "").split())
    return title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1] + "…"


def _items(rows, fmt):
    lines = [fmt(r) for r in rows[:CAP]]
    if len(rows) > CAP:
        lines.append("+%d more next sweep" % (len(rows) - CAP))
    return lines


REASONS = {"finished": "finished, idle", "idle": "idle for days", "routine": "routine run"}


def render_plan(plan, *, archive_mode, ideas_waiting, now):
    checked = plan.get("checked", 0)
    archive, unpin, file_ = plan.get("archive", []), plan.get("unpin", []), plan.get("file", [])
    head = "tidy-chats sweep (%s): checked %d chats; the full list is not shown." % (
        now.strftime("%Y-%m-%d %H:%M UTC"), checked)
    out = [head]
    if plan.get("truncated"):
        out.append("The list hit its limit of %d chats, so archiving waits for a sweep that sees "
                   "every chat." % plan["truncated"])
    if not (archive or unpin or file_):
        out.append("Nothing to tidy.")
    if archive:
        if archive_mode == "ask":
            out.append("Archive: ask the user one yes/no question (AskUserQuestion) to archive these "
                       "%d chats; on yes, archive_session each one:" % len(archive))
        else:
            out.append("Archive with archive_session, one call each. Archiving is the user's tidy-chats "
                       "setting (archive: auto), so don't ask. Archiving a chat also archives its "
                       "idle nested chats:")
        out += _items(archive, lambda a: '- %s "%s" (%s)' % (
            a["id"], _trim(a.get("title")), REASONS.get(a.get("reason"), a.get("reason", ""))))
    if unpin:
        out.append("Unpin with set_pinned false:")
        out += _items(unpin, lambda u: '- %s "%s"' % (u["id"], _trim(u.get("title"))))
    if file_:
        secs = ", ".join("%s (%s)" % (s.get("name"), s.get("id")) for s in plan.get("sections", []))
        out.append("File with move_sessions into the closest existing section%s; skip any that fail:"
                   % ((" (" + secs + ")") if secs else ""))
        out += _items(file_, lambda f: '- %s "%s" in %s%s' % (
            f["id"], _trim(f.get("title")), f.get("cwd") or "?",
            (" → " + f["section"] + " (user rule)") if f.get("section") else ""))
    if archive or unpin or file_:
        out.append("Load the tools in one ToolSearch call if deferred.")
    if ideas_waiting:
        out.append('End your reply with: "tidy-chats has %d rule idea%s: run /tidy-chats:rules"'
                   % (ideas_waiting, "" if ideas_waiting == 1 else "s"))
    out.append("Do not list chats again; finish with one short line of what changed.")
    return "\n".join(out)
