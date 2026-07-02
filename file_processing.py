# file_processing.py
import os
import re
import hashlib

from mutagen.mp3 import MP3
from key_finder.detector import (
    detect_key_bpm,
    CHROMA_TO_BEATSTARS_PREFIX,
    BEATSTARS_VALID_KEYS,
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TEMP_DIR = os.path.join(_BASE_DIR, "temp")


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
    os.makedirs(_TEMP_DIR, exist_ok=True)

    if audio.tags is None:
        return None

    for key in audio.tags.keys():
        if key.startswith("APIC"):
            frame = audio.tags[key]
            image_data = frame.data
            mime_type = frame.mime  # например, "image/jpeg"

            ext = "jpg" if "jpeg" in mime_type else "png"
            cover_path = os.path.join(_TEMP_DIR, f"cover_{file_hash[:12]}.{ext}")

            with open(cover_path, "wb") as f:
                f.write(image_data)

            return cover_path

    return None


def _parse_bpm_from_filename(filename: str | None) -> float | None:
    """Извлекает BPM из названия файла, если оно там есть.

    Примеры:
        'time to run @aaabeats 166bpm.mp3' → 166.0
        'track 140bpm D#min.mp3'           → 140.0
        'track without bpm.mp3'             → None
    """
    if not filename:
        return None
    match = re.search(r"(\d{2,3})\s*bpm", filename, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


# Масштабы/лады, которые могут встретиться в названиях файлов.
# Для BeatStars: ТОЛЬКО «maj»/«major» → Major, ВСЁ ОСТАЛЬНОЕ → Minor.
# (True = мажор для BeatStars, False = всё остальное)
_KEY_SCALE_ABBREVIATIONS: dict[str, bool] = {
    # Для BeatStars: ТОЛЬКО явный «maj» → Major, ВСЁ ОСТАЛЬНОЕ → Minor
    "maj": True, "major": True,
    "min": False, "minor": False,
    "key": False,  # неуверен → минор по дефолту

    # Диатонические лады (все → Minor для BeatStars)
    "ion": False, "ionian": False,
    "dor": False, "dorian": False,
    "phr": False, "phry": False, "phrygian": False,
    "lyd": False, "lydian": False,
    "mix": False, "mixo": False, "mixolydian": False,
    "aeo": False, "aeol": False, "aeolian": False,
    "loc": False, "locrian": False,

    # Гармонические
    "hmin": False, "harmin": False, "harmonicminor": False,
    "hmaj": False, "harmaj": False, "harmonicmajor": False,

    # Мелодические
    "mmin": False, "melmin": False, "melodicminor": False,

    # Блюзовые
    "blues": False, "blu": False,

    # Пентатоники
    "pent": False, "pentatonic": False,
    "pentmaj": False, "pentmajor": False,
    "pentmin": False, "pentminor": False,

    # Уменьшённые / увеличенные
    "dim": False, "diminished": False,
    "aug": False, "augmented": False,

    # Прочие
    "chrom": False, "chromatic": False,
    "wt": False, "wholetone": False,
    "neap": False, "neapolitan": False,
    "bebop": False, "bebopmaj": False, "bebopmin": False,
    "hex": False, "hexatonic": False,
    "superloc": False, "superlocrian": False,
    "alt": False, "altered": False,
    "doubleharm": False, "doubleharmonic": False,

    # Экзотические
    "phrygiandom": False, "phrydom": False,
    "lydiandom": False, "lyddom": False,
    "hungmin": False, "hungarianminor": False,
    "enigma": False, "enigmatic": False,
    "arabian": False, "arabic": False,
    "japanese": False, "jap": False,
    "oriental": False,
    "spanish": False,
    "egyptian": False,
    "hirajoshi": False,
    "kumoi": False,
}


def _parse_key_from_filename(filename: str | None) -> str | None:
    """Извлекает тональность из названия файла «как есть».

    Возвращает исходный текст из названия, например:
        'track D#min.mp3'     → 'D#min'
        'track Emaj.mp3'      → 'Emaj'
        'track G#key.mp3'     → 'G#key'   (key — неуверен, мажор/минор)
        'track Flydian.mp3'   → 'Flydian'
        'track Bbdorian.mp3'  → 'Bbdorian'
        'track Cphrygian.mp3' → 'Cphrygian'
        'track without key'   → None
    """
    if not filename:
        return None
    # Сортируем ключи по длине (от длинных к коротким),
    # чтобы "phrygian" нашлось раньше, чем "phr"
    scale_names = sorted(_KEY_SCALE_ABBREVIATIONS, key=len, reverse=True)
    pattern = rf"([A-Ga-g])([#b]?)\s*({'|'.join(scale_names)})"
    match = re.search(pattern, filename, re.IGNORECASE)
    if not match:
        return None
    # Возвращаем весь заматченный кусок «как есть» из названия
    return match.group(0)


def convert_key_to_beatstars(key_str: str | None) -> str | None:
    """Конвертирует любую строку тональности в BeatStars-формат (Major/Minor).

    Используется ТОЛЬКО при загрузке на BeatStars, где нужны строго
    мажор или минор. Всё, что не «maj», по дефолту становится минором.

    Примеры:
        'D#min'     → 'D-Sharp-Minor'
        'Emaj'      → 'E-Major'
        'G#key'     → 'G-Sharp-Minor'   (key → Minor)
        'Flydian'   → 'F-Minor'         (Lydian → Minor по дефолту)
        'Bbdorian'  → 'A-Sharp-Minor'   (Dorian → Minor)
        'C-Minor'   → 'C-Minor'         (уже в BeatStars-формате)
        'C Minor'   → 'C-Minor'         (librosa raw → BeatStars)
        None        → None
    """
    if not key_str:
        return None

    # 1. Уже в BeatStars-формате? («X-Major» / «X-Minor»)
    if key_str in BEATSTARS_VALID_KEYS:
        return key_str

    # 2. librosa raw: «C Minor», «D# Major» → «C-Minor», «D-Sharp-Major»
    librosa_match = re.match(
        r"([A-Ga-g])([#b]?)\s+(Major|Minor)", key_str, re.IGNORECASE
    )
    if librosa_match:
        note = librosa_match.group(1).upper()
        acc = librosa_match.group(2)
        ktype = librosa_match.group(3).capitalize()  # "Major" / "Minor"
        chroma = _normalize_chroma(note, acc)
        prefix = CHROMA_TO_BEATSTARS_PREFIX.get(chroma)
        if prefix:
            candidate = f"{prefix}-{ktype}"
            if candidate in BEATSTARS_VALID_KEYS:
                return candidate
        return None

    # 3. Формат из названия файла: «D#min», «Emaj», «Flydian», ...
    scale_names = sorted(_KEY_SCALE_ABBREVIATIONS, key=len, reverse=True)
    pattern = rf"^([A-Ga-g])([#b]?)\s*({'|'.join(scale_names)})$"
    match = re.match(pattern, key_str, re.IGNORECASE)
    if match:
        note = match.group(1).upper()
        acc = match.group(2)
        scale_abbr = match.group(3).lower()

        # Определяем мажор / минор (всё кроме явного maj → Minor)
        is_major = _KEY_SCALE_ABBREVIATIONS.get(scale_abbr, False)
        ktype = "Major" if is_major else "Minor"

        chroma = _normalize_chroma(note, acc)
        prefix = CHROMA_TO_BEATSTARS_PREFIX.get(chroma)
        if prefix:
            candidate = f"{prefix}-{ktype}"
            if candidate in BEATSTARS_VALID_KEYS:
                return candidate

    return None


def _normalize_chroma(note: str, accidental: str) -> str:
    """Приводит ноту + знак альтерации к формату chroma («C», «C#», …)."""
    if accidental == "b":
        flat_to_sharp = {
            "Ab": "G#", "Bb": "A#", "Db": "C#", "Eb": "D#", "Gb": "F#",
        }
        return flat_to_sharp.get(f"{note}b", note)
    elif accidental == "#":
        return f"{note}#"
    return note


def process_audio(path: str, original_filename: str | None = None) -> dict:
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
                "bpm": None,
                "key": None,
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

        # Key & BPM — сначала пробуем извлечь из названия файла
        bpm = None
        detected_key = None

        if original_filename:
            bpm = _parse_bpm_from_filename(original_filename)
            detected_key = _parse_key_from_filename(original_filename)

        # Если чего-то не нашли в названии — детектируем через librosa
        if bpm is None or detected_key is None:
            key_bpm = detect_key_bpm(path)
            if bpm is None:
                bpm = key_bpm.get("bpm")
            if detected_key is None:
                detected_key = key_bpm.get("key")

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
            "bpm": bpm,
            "key": detected_key,
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
            "bpm": None,
            "key": None,
        }
