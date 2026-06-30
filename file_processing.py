# file_processing.py
import os
import hashlib

from mutagen.mp3 import MP3


def _compute_sha256(path: str) -> str:
    """Вычисляет SHA-256 хеш файла (читается поблочно, не загружая весь файл в память)."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):  # 64 KB
            sha256.update(chunk)
    return sha256.hexdigest()


def _extract_cover(audio: MP3, file_hash: str) -> str | None:
    """Извлекает обложку из MP3-тегов и сохраняет в temp/.

    Возвращает путь к сохранённому файлу или None, если обложки нет.
    """
    os.makedirs("temp", exist_ok=True)

    for key in audio.tags.keys():
        if key.startswith("APIC"):
            frame = audio.tags[key]
            image_data = frame.data
            mime_type = frame.mime  # например, "image/jpeg"

            ext = "jpg" if "jpeg" in mime_type else "png"
            cover_path = f"temp/cover_{file_hash[:12]}.{ext}"

            with open(cover_path, "wb") as f:
                f.write(image_data)

            return cover_path

    return None


def process_audio(path: str) -> dict:
    """Обрабатывает MP3-файл: хеширует, извлекает метаданные и обложку.

    Возвращает словарь:
        success: bool
        error: str | None
        file_hash: str           — SHA-256 хеш содержимого файла
        file_size: int           — размер файла в байтах
        title: str | None        — название трека (TIT2)
        artist: str | None       — исполнитель (TPE1)
        duration: float          — длительность в секундах
        bitrate: int             — битрейт (bps)
        sample_rate: int         — частота дискретизации (Hz)
        has_cover: bool          — есть ли встроенная обложка
        cover_path: str | None   — путь к сохранённой обложке
    """
    try:
        # Хеш — до mutagen, чтобы ловить любые ошибки чтения файла
        file_hash = _compute_sha256(path)
        file_size = os.path.getsize(path)

        audio = MP3(path)

        if audio is None or audio.tags is None:
            return {
                "success": True,
                "error": None,
                "file_hash": file_hash,
                "file_size": file_size,
                "title": None,
                "artist": None,
                "duration": 0.0,
                "bitrate": 0,
                "sample_rate": 0,
                "has_cover": False,
                "cover_path": None,
            }

        # Метаданные
        title = audio.tags.get("TIT2", [None])[0]
        if title is not None:
            title = str(title)

        artist = audio.tags.get("TPE1", [None])[0]
        if artist is not None:
            artist = str(artist)

        # Техническая информация
        info = audio.info
        duration = info.length if hasattr(info, "length") else 0.0
        bitrate = info.bitrate if hasattr(info, "bitrate") else 0
        sample_rate = info.sample_rate if hasattr(info, "sample_rate") else 0

        # Обложка
        cover_path = _extract_cover(audio, file_hash)
        has_cover = cover_path is not None

        return {
            "success": True,
            "error": None,
            "file_hash": file_hash,
            "file_size": file_size,
            "title": title,
            "artist": artist,
            "duration": duration,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "has_cover": has_cover,
            "cover_path": cover_path,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "file_hash": "",
            "file_size": 0,
            "title": None,
            "artist": None,
            "duration": 0.0,
            "bitrate": 0,
            "sample_rate": 0,
            "has_cover": False,
            "cover_path": None,
        }
