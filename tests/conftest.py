import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty state folder."""
    d = tmp_path / "data"
    monkeypatch.setenv("TIDY_CHATS_DATA", str(d))
    return d
