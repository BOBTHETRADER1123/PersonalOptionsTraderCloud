import json
import os
from pathlib import Path
from threading import Lock
from .config import settings

_lock = Lock()


def append_journal(record: dict) -> None:
    """Append and fsync before database acknowledgement; JSONL is the recovery source."""
    path = settings.data_path / "journal" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str) + "\n"
    with _lock, path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
