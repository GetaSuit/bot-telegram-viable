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


def is_seen(url: str) -> bool:
    return url in _seen


def mark_seen(url: str):
    if not url:
        return
    _seen.add(url)
    try:
        with open(_FILE, "a") as f:
            f.write(url + "\n")
    except Exception:
        pass
