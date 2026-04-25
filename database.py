import os
import logging

logger = logging.getLogger(__name__)

_seen: set = set()
_FILE = "/tmp/seen.txt"


def init_db():
    global _seen
    try:
        if os.path.exists(_FILE):
            with open(_FILE) as f:
                _seen = set(l.strip() for l in f if l.strip())
            logger.info(f"[DB] {len(_seen)} URLs chargées")
        else:
            _seen = set()
    except Exception as e:
        logger.error(f"[DB] {e}")
        _seen = set()


def is_seen(uid: str) -> bool:
    return uid in _seen


def mark_seen(uid: str):
    if not uid:
        return
    _seen.add(uid)
    try:
        with open(_FILE, "a") as f:
            f.write(uid + "\n")
    except Exception:
        pass
