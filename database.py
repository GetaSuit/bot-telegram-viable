import sqlite3

DB_PATH = "seen_articles.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            url TEXT PRIMARY KEY,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_already_seen(url: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM seen WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row is not None

def mark_as_seen(url: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO seen (url) VALUES (?)", (url,))
    conn.commit()
    conn.close()
