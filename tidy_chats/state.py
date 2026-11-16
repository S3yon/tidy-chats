"""State store: per-chat state, the sweep lock, the action log, rules and rule ideas.

Every read tolerates missing or corrupt files (start fresh); every write is atomic.
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path

LOCK_STALE_SECONDS = 20 * 60
LOG_KEEP = 2000


def data_dir():
    """The state folder, created on first use."""
    root = (os.environ.get("TIDY_CHATS_DATA")
            or os.environ.get("CLAUDE_PLUGIN_DATA")
            or str(Path.home() / ".claude" / "plugins" / "data" / "tidy-chats"))
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe(chat_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", chat_id).lstrip(".") or "_"


def _chat_path(chat_id):
    return data_dir() / "chats" / (_safe(chat_id) + ".json")


def load_chat(chat_id):
    data = read_json(_chat_path(chat_id), {})
    return data if isinstance(data, dict) else {}


def save_chat(chat_id, data):
    write_json(_chat_path(chat_id), data)


# --- sweep lock -------------------------------------------------------------

def _lock_path():
    return data_dir() / "sweep.lock"


def _sweep_path():
    return data_dir() / "sweep.json"


def _read_lock(path):
    """The lock's {holder, at}; a lock file that can't be read counts as taken at its mtime."""
    data = read_json(path, None)
    if isinstance(data, dict) and "holder" in data and isinstance(data.get("at"), (int, float)):
        return data
    try:
        return {"holder": None, "at": os.path.getmtime(path)}
    except OSError:
        return None


def _create_lock(path, holder, now):
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"holder": holder, "at": now}, f)
    return True


def try_lock(holder, now):
    """Take the global sweep lock. Only one chat can hold it; a lock older than 20 min is stale."""
    path = _lock_path()
    if _create_lock(path, holder, now):
        return True
    cur = _read_lock(path)
    if cur is None:  # vanished between the two calls
        return _create_lock(path, holder, now)
    if cur.get("holder") == holder:
        return True
    if now - cur["at"] <= LOCK_STALE_SECONDS:
        return False
    # Stale: move it aside (only one mover wins the rename), then race for a fresh one.
    aside = path.with_name("sweep.lock.stale-%s-%d" % (_safe(holder), os.getpid()))
    try:
        os.rename(str(path), str(aside))
    except OSError:
        return False
    try:
        os.unlink(str(aside))
    except OSError:
        pass
    return _create_lock(path, holder, now)


def release_lock(holder, now):
    """Free the lock and record the sweep time, if `holder` holds it."""
    path = _lock_path()
    cur = _read_lock(path)
    if not cur or cur.get("holder") != holder:
        return
    data = read_json(_sweep_path(), {})
    if not isinstance(data, dict):
        data = {}
    data["last_sweep_at"] = now
    write_json(_sweep_path(), data)
    try:
        os.unlink(str(path))
    except OSError:
        pass


def sweep_state():
    data = read_json(_sweep_path(), {})
    last = data.get("last_sweep_at") if isinstance(data, dict) else None
    if not isinstance(last, (int, float)):
        last = None
    path = _lock_path()
    lock = _read_lock(path) if path.exists() else None
    return {"last_sweep_at": last, "lock": lock}


# --- action log -------------------------------------------------------------

def _log_path():
    return data_dir() / "actions.jsonl"


def log_action(entry):
    entry = dict(entry)
    entry.setdefault("at", time.time())
    path = _log_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    if len(lines) > LOG_KEEP:
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines[-LOG_KEEP:])
        os.replace(tmp, path)


def read_log():
    out = []
    try:
        with open(_log_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        pass
    return out


# --- rules and rule ideas ---------------------------------------------------

def _list(name):
    data = read_json(data_dir() / name, [])
    return data if isinstance(data, list) else []


def load_rules():
    return _list("rules.json")


def save_rules(rules):
    write_json(data_dir() / "rules.json", rules)


def load_ideas():
    return _list("ideas.json")


def save_ideas(ideas):
    write_json(data_dir() / "ideas.json", ideas)
