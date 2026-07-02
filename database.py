# database.py
import os
import sqlite3

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE_DIR, "beats.db")


def _resolve_track_paths(track: dict) -> dict:
    """Превращает относительные file_path/cover_path в абсолютные (относительно папки проекта)."""
    for key in ("file_path", "cover_path"):
        path = track.get(key)
        if path and not os.path.isabs(path):
            track[key] = os.path.join(_BASE_DIR, path)
    return track


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
        except sqlite3.OperationalError as e:
            # Игнорируем только «duplicate column name», остальное — пробрасываем
            if "duplicate column name" not in str(e).lower():
                raise

    # Таблица профилей загрузки
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS upload_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            title_template TEXT NOT NULL DEFAULT '{artist} — {title}',
            description_template TEXT NOT NULL DEFAULT '{artist} — {title}\n\n📅 Загружено через BeatsUpload Bot',
            is_default INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # Миграция: переименовываем description в description_template для старых баз
    try:
        cursor.execute("ALTER TABLE upload_profiles ADD COLUMN description_template TEXT NOT NULL DEFAULT '{artist} — {title}\n\n📅 Загружено через BeatsUpload Bot'")
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
    return _resolve_track_paths(dict(row)) if row else None


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
    return _resolve_track_paths(dict(row)) if row else None


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
    return [_resolve_track_paths(dict(row)) for row in rows]


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


def update_track_bpm(track_id: int, bpm: int) -> None:
    """Обновляет BPM трека (целочисленное значение)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tracks SET bpm = ? WHERE id = ?",
        (bpm, track_id),
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
    return [_resolve_track_paths(dict(row)) for row in rows]


# ─── Профили загрузки ────────────────────────────────────────────────

def create_profile(user_id: int, name: str, title_template: str,
                   description_template: str, is_default: bool = False) -> int:
    """Создаёт новый профиль загрузки. Возвращает его id."""
    from datetime import datetime, timezone
    conn = sqlite3.connect(DB_PATH)
    if is_default:
        conn.execute(
            "UPDATE upload_profiles SET is_default = 0 WHERE user_id = ?",
            (user_id,),
        )
    cursor = conn.execute(
        """INSERT INTO upload_profiles
           (user_id, name, title_template, description_template, is_default, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, name, title_template, description_template,
         int(is_default), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    pid = cursor.lastrowid
    conn.close()
    return pid


def get_user_profiles(user_id: int) -> list[dict]:
    """Возвращает все профили пользователя."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM upload_profiles WHERE user_id = ? ORDER BY is_default DESC, id ASC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_profile_by_id(profile_id: int) -> dict | None:
    """Возвращает профиль по id."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM upload_profiles WHERE id = ?", (profile_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_profile(profile_id: int, **kwargs) -> bool:
    """Обновляет поля профиля. kwargs: name, title_template, description_template, is_default."""
    conn = sqlite3.connect(DB_PATH)
    profile = get_profile_by_id(profile_id)
    if not profile:
        conn.close()
        return False

    if kwargs.get("is_default"):
        conn.execute(
            "UPDATE upload_profiles SET is_default = 0 WHERE user_id = ?",
            (profile["user_id"],),
        )

    fields = []
    values = []
    for key in ("name", "title_template", "description_template", "is_default"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            val = kwargs[key]
            values.append(int(val) if key == "is_default" else val)
    if not fields:
        conn.close()
        return False

    values.append(profile_id)
    conn.execute(
        f"UPDATE upload_profiles SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()
    return True


def delete_profile(profile_id: int) -> bool:
    """Удаляет профиль по id. Не даёт удалить последний профиль."""
    conn = sqlite3.connect(DB_PATH)
    profile = get_profile_by_id(profile_id)
    if not profile:
        conn.close()
        return False
    # Не даём удалить последний профиль
    count = conn.execute(
        "SELECT COUNT(*) FROM upload_profiles WHERE user_id = ?",
        (profile["user_id"],),
    ).fetchone()[0]
    if count <= 1:
        conn.close()
        return False
    conn.execute("DELETE FROM upload_profiles WHERE id = ?", (profile_id,))
    conn.commit()
    conn.close()
    return True


def get_default_profile(user_id: int) -> dict | None:
    """Возвращает профиль по умолчанию или первый доступный."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT * FROM upload_profiles WHERE user_id = ? ORDER BY is_default DESC, id ASC LIMIT 1",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def ensure_default_profile(user_id: int) -> dict:
    """Гарантирует, что у пользователя есть хотя бы один профиль.
    Если нет — создаёт стандартный и возвращает его."""
    existing = get_user_profiles(user_id)
    if existing:
        return existing[0]
    pid = create_profile(
        user_id=user_id,
        name="📝 Стандартный",
        title_template="{artist} — {title}",
        description_template="{artist} — {title}\n\n📅 Загружено через BeatsUpload Bot",
        is_default=True,
    )
    return get_profile_by_id(pid)


def render_template(template: str, track: dict) -> str:
    """Подставляет переменные в шаблон.
    Доступные переменные: {artist}, {title}, {bpm}, {key}."""
    artist = track.get("artist") or "Неизвестен"
    title = track.get("title") or "Без названия"
    bpm = track.get("bpm")
    key = track.get("key")

    result = template.replace("{artist}", artist)
    result = result.replace("{title}", title)
    result = result.replace("{bpm}", str(bpm) if bpm else "—")
    result = result.replace("{key}", str(key) if key else "—")

    return result
