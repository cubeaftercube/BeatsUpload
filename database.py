# database.py
import sqlite3

DB_PATH = "beats.db"


def init_db() -> None:
    """Создаёт таблицу tracks и индекс, если их ещё нет.
    Добавляет новые колонки через ALTER TABLE для обратной совместимости.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_id INTEGER NOT NULL,
            file_hash TEXT UNIQUE NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            title TEXT,
            artist TEXT,
            duration REAL,
            bitrate INTEGER,
            sample_rate INTEGER,
            has_cover INTEGER DEFAULT 0,
            cover_path TEXT,
            uploaded_at TEXT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_hash ON tracks(file_hash)"
    )

    # Миграция: добавляем колонки, которых может не быть в старых базах
    migrations = [
        "ALTER TABLE tracks ADD COLUMN user_id INTEGER",
        "ALTER TABLE tracks ADD COLUMN youtube_video_id TEXT",
        "ALTER TABLE tracks ADD COLUMN youtube_status TEXT",
        "ALTER TABLE tracks ADD COLUMN beatstars_status TEXT",
        "ALTER TABLE tracks ADD COLUMN bpm REAL",
        "ALTER TABLE tracks ADD COLUMN key TEXT",
    ]
    for sql in migrations:
        try:
            cursor.execute(sql)
        except sqlite3.OperationalError:
            pass  # колонка уже существует

    conn.commit()
    conn.close()


def track_exists_by_hash(file_hash: str) -> dict | None:
    """Проверяет, есть ли уже трек с таким SHA-256 хешем."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM tracks WHERE file_hash = ?", (file_hash,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def insert_track(track_data: dict) -> int | None:
    """Вставляет новый трек в базу. Возвращает ID или None при дубликате."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            """
            INSERT INTO tracks
                (unique_id, user_id, file_hash, file_path, file_size,
                 title, artist, duration, bitrate, sample_rate,
                 bpm, key, has_cover, cover_path, uploaded_at)
            VALUES
                (:unique_id, :user_id, :file_hash, :file_path, :file_size,
                 :title, :artist, :duration, :bitrate, :sample_rate,
                 :bpm, :key, :has_cover, :cover_path, :uploaded_at)
            """,
            track_data,
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_track_by_id(track_id: int) -> dict | None:
    """Возвращает трек по его id или None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_tracks(user_id: int, limit: int = 5, offset: int = 0) -> list[dict]:
    """Возвращает треки пользователя, от новых к старым (с пагинацией)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM tracks WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def count_user_tracks(user_id: int) -> int:
    """Возвращает общее количество треков пользователя."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE user_id = ?", (user_id,)
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def update_youtube_status(track_id: int, video_id: str | None, status: str) -> None:
    """Обновляет статус загрузки на YouTube."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tracks SET youtube_video_id = ?, youtube_status = ? WHERE id = ?",
        (video_id, status, track_id),
    )
    conn.commit()
    conn.close()


def update_beatstars_status(track_id: int, status: str) -> None:
    """Обновляет статус загрузки на BeatStars."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tracks SET beatstars_status = ? WHERE id = ?",
        (status, track_id),
    )
    conn.commit()
    conn.close()


def get_all_tracks() -> list[dict]:
    """Возвращает все треки, от новых к старым."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tracks ORDER BY uploaded_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
