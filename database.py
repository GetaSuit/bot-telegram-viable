import os
import logging

logger = logging.getLogger(__name__)

_seen_urls: set = set()
_DB_FILE = "/tmp/seen_urls.txt"

def init_db():
    global _seen_urls
    try:
        if os.path.exists(_DB_FILE):
            with open(_DB_FILE, "r") as f:
                _seen_urls = set(line.strip() for line in f if line.strip())
            logger.info(f"[DB] {len(_seen_urls)} URLs chargées")
        else:
            _seen_urls = set()
            logger.info("[DB] Nouvelle base initialisée")
    except Exception as e:
        logger.error(f"[DB] Erreur init: {e}")
        _seen_urls = set()

def is_already_seen(url: str) -> bool:
    return url in _seen_urls

def mark_as_seen(url: str):
    if not url:
        return
    _seen_urls.add(url)
    try:
        with open(_DB_FILE, "a") as f:
            f.write(url + "\n")
    except Exception as e:
        logger.warning(f"[DB] Erreur sauvegarde: {e}")
