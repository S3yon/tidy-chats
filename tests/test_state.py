import json
import threading

from tidy_chats import state


def test_chat_roundtrip():
    assert state.load_chat("local_abc") == {}
    state.save_chat("local_abc", {"seen": 1, "pinned": True})
    assert state.load_chat("local_abc") == {"seen": 1, "pinned": True}


def test_corrupt_chat_file_returns_empty(data_dir):
    state.save_chat("local_abc", {"seen": 1})
    (data_dir / "chats" / "local_abc.json").write_text("{not json")
    assert state.load_chat("local_abc") == {}


def test_chat_id_cannot_escape_data_dir(data_dir):
    state.save_chat("../../evil", {"x": 1})
    assert not (data_dir.parent / "evil.json").exists()
    assert state.load_chat("../../evil") == {"x": 1}


def test_write_json_is_atomic_and_leaves_no_temp(data_dir):
    p = data_dir / "x.json"
    state.write_json(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert [f.name for f in data_dir.iterdir()] == ["x.json"]


def test_read_json_missing_returns_default(data_dir):
    assert state.read_json(data_dir / "nope.json", []) == []


def test_lock_exclusive():
    assert state.try_lock("local_a", 1000.0) is True
    assert state.try_lock("local_b", 1001.0) is False
    assert state.sweep_state()["lock"]["holder"] == "local_a"


def test_lock_stale_after_20_min():
    assert state.try_lock("local_a", 1000.0) is True
    assert state.try_lock("local_b", 1000.0 + 1199) is False
    assert state.try_lock("local_b", 1000.0 + 1201) is True
    assert state.sweep_state()["lock"]["holder"] == "local_b"


def test_lock_race_one_winner():
    wins = []
    barrier = threading.Barrier(8)

    def grab(i):
        barrier.wait()
        if state.try_lock("local_%d" % i, 5000.0):
            wins.append(i)

    threads = [threading.Thread(target=grab, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1


def test_release_sets_last_sweep():
    assert state.sweep_state() == {"last_sweep_at": None, "lock": None}
    state.try_lock("local_a", 1000.0)
    state.release_lock("local_b", 1100.0)  # not the holder: nothing happens
    assert state.sweep_state()["lock"]["holder"] == "local_a"
    assert state.sweep_state()["last_sweep_at"] is None
    state.release_lock("local_a", 1200.0)
    assert state.sweep_state() == {"last_sweep_at": 1200.0, "lock": None}
    assert state.try_lock("local_b", 1201.0) is True


def test_corrupt_sweep_state_starts_fresh(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sweep.json").write_text("garbage")
    assert state.sweep_state() == {"last_sweep_at": None, "lock": None}


def test_log_append_and_trim():
    for i in range(2005):
        state.log_action({"n": i})
    log = state.read_log()
    assert len(log) == 2000
    assert log[0]["n"] == 5
    assert log[-1]["n"] == 2004


def test_log_skips_corrupt_lines(data_dir):
    state.log_action({"n": 1})
    with open(data_dir / "actions.jsonl", "a") as f:
        f.write("not json\n")
    state.log_action({"n": 2})
    assert [e["n"] for e in state.read_log()] == [1, 2]


def test_rules_and_ideas_roundtrip():
    assert state.load_rules() == []
    assert state.load_ideas() == []
    state.save_rules([{"kind": "keep_pinned"}])
    state.save_ideas([{"id": "i1"}])
    assert state.load_rules() == [{"kind": "keep_pinned"}]
    assert state.load_ideas() == [{"id": "i1"}]
