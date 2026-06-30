# processor.py
from datetime import datetime, timezone

import file_processing
import database


def process_audio(file_path: str, unique_id: int, user_id: int = 0) -> dict:
    """Полный пайплайн обработки аудиофайла вне контекста Telegram.

    1. Обрабатывает файл (хеш + метаданные + обложка).
    2. Проверяет базу на дубликат по SHA-256.
    3. Если трек новый — сохраняет в базу.
    4. Возвращает структурированный результат.

    Возвращает словарь:
        is_new: bool              — True если трек успешно добавлен в базу
        is_duplicate: bool        — True если трек с таким хешем уже есть
        error: str | None         — текст ошибки или None
        track: dict | None        — метаданные обработанного трека
        existing: dict | None     — данные существующего трека (если дубликат)
    """
    print(f"[Processor] Получен сигнал. Начинаю обработку файла: {file_path} (ID: {unique_id})")

    # Шаг 1: обработка файла
    result = file_processing.process_audio(file_path)

    if not result["success"]:
        print(f"[Processor] Ошибка обработки: {result['error']}")
        return {
            "is_new": False,
            "is_duplicate": False,
            "error": result["error"],
            "track": None,
            "existing": None,
        }

    print(f"[Processor] Файл обработан. Хеш: {result['file_hash'][:16]}...")

    # Шаг 2: проверка на дубликат
    existing = database.track_exists_by_hash(result["file_hash"])

    if existing is not None:
        print(f"[Processor] Обнаружен дубликат! Трек уже загружен {existing['uploaded_at']}")
        return {
            "is_new": False,
            "is_duplicate": True,
            "error": None,
            "track": result,
            "existing": existing,
        }

    # Шаг 3: сохранение в базу
    now = datetime.now(timezone.utc).isoformat()
    track_data = {
        "unique_id": unique_id,
        "user_id": user_id,
        "file_hash": result["file_hash"],
        "file_path": file_path,
        "file_size": result["file_size"],
        "title": result["title"],
        "artist": result["artist"],
        "duration": result["duration"],
        "bitrate": result["bitrate"],
        "sample_rate": result["sample_rate"],
        "has_cover": int(result["has_cover"]),
        "cover_path": result["cover_path"],
        "uploaded_at": now,
    }

    row_id = database.insert_track(track_data)

    if row_id is None:
        # Гонка: кто-то вставил такой же хеш между проверкой и вставкой
        existing = database.track_exists_by_hash(result["file_hash"])
        print(f"[Processor] Обнаружен дубликат (гонка)!")

        return {
            "is_new": False,
            "is_duplicate": True,
            "error": None,
            "track": result,
            "existing": existing,
        }

    print(f"[Processor] Трек сохранён в базу (ID: {row_id}). "
          f"Название: {result['title']}, Исполнитель: {result['artist']}")

    # Добавляем row_id в результат для информации
    result["db_id"] = row_id
    result["uploaded_at"] = now

    return {
        "is_new": True,
        "is_duplicate": False,
        "error": None,
        "track": result,
        "existing": None,
    }
