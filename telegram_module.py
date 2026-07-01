# bot.py
import os
import asyncio
import logging
import time
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import processor
import database
import video_creation
import youtube
from beatstars import beatstars_uploader

# Настройка логирования
logging.basicConfig(level=logging.INFO)
load_dotenv()

API_TOKEN = os.getenv("BOT_API_TOKEN")
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM для загрузки на BeatStars ---


class BeatStarsUpload(StatesGroup):
    waiting_for_tags = State()

# Директории
AUDIO_DIR = "audio_storage"
VIDEO_DIR = "video_storage"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

TRACKS_PER_PAGE = 5


# ─── Команда /start ───────────────────────────────────────────────

@dp.message(Command("start"))
async def send_welcome(message: Message):
    if message.chat.type == "private":
        await message.answer(
            "Привет! Отправь мне MP3-файл (бит), и я сохраню его в твою библиотеку.\n\n"
            "📚 /library — посмотреть твою библиотеку и загрузить трек на YouTube"
        )


# ─── Приём MP3-файлов ─────────────────────────────────────────────

@dp.message(lambda m: (m.audio or m.document) and m.chat.type == "private")
async def handle_audio(message: Message):
    await message.answer("🎧 Аудио получено. Загружаю на сервер...")

    # Определяем объект файла и расширение
    if message.audio:
        file = message.audio
        ext = ".mp3"
    elif message.document:
        file = message.document
        ext = os.path.splitext(file.file_name)[1] if file.file_name else ".mp3"
        if ext.lower() != ".mp3":
            await message.answer("⚠️ Бот принимает только MP3-файлы.")
            return
    else:
        return

    unique_id = int(time.time() * 1000000)
    file_name = f"{unique_id}{ext}"
    file_path = os.path.join(AUDIO_DIR, file_name)
    user_id = message.from_user.id

    try:
        await bot.download(file, destination=file_path)

        await message.answer(
            f"✅ Файл успешно сохранен на диск!\n"
            f"🆔 Уникальный номер: <code>{unique_id}</code>",
            parse_mode="HTML",
        )

        result = await asyncio.to_thread(
            processor.process_audio, file_path, unique_id, user_id
        )

        if result["error"]:
            await message.answer(f"❌ Ошибка при обработке файла:\n{result['error']}")
        elif result["is_duplicate"]:
            existing = result["existing"]
            await message.answer(
                f"⚠️ <b>Дубликат!</b> Этот трек уже есть в твоей библиотеке.\n\n"
                f"🎵 Название: {existing.get('title', '—')}\n"
                f"👤 Исполнитель: {existing.get('artist', '—')}\n"
                f"📅 Загружен: {existing['uploaded_at'][:10]}\n"
                f"🆔 ID: <code>{existing['unique_id']}</code>",
                parse_mode="HTML",
            )
        else:
            track = result["track"]
            title = track.get("title") or "Без названия"
            artist = track.get("artist") or "Неизвестен"
            duration = track.get("duration", 0)
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            has_cover = "🖼" if track.get("has_cover") else "—"

            await message.answer(
                f"✅ Трек добавлен в библиотеку!\n\n"
                f"🎵 Название: <b>{title}</b>\n"
                f"👤 Исполнитель: <b>{artist}</b>\n"
                f"⏱ Длительность: {minutes}:{seconds:02d}\n"
                f"📦 Размер: {track['file_size'] / 1024 / 1024:.1f} МБ\n"
                f"🔊 Битрейт: {track['bitrate'] // 1000} kbps\n"
                f"🖼 Обложка: {has_cover}\n"
                f"🆔 ID: <code>{unique_id}</code>\n\n"
                f"📚 <b>/library</b> — библиотека и загрузка на YouTube",
                parse_mode="HTML",
            )

    except Exception as e:
        logging.error(f"Ошибка при скачивании или обработке: {e}")
        await message.answer("❌ Произошла ошибка при загрузке или обработке файла.")


# ─── Команда /library ─────────────────────────────────────────────

def _build_track_list_text(tracks: list[dict], page: int, total: int) -> str:
    """Формирует текст списка треков для библиотеки."""
    total_pages = max(1, (total + TRACKS_PER_PAGE - 1) // TRACKS_PER_PAGE)
    lines = [f"📚 <b>Твоя библиотека</b> (стр. {page}/{total_pages})\n"]

    for i, t in enumerate(tracks, 1):
        title = t.get("title") or "Без названия"
        artist = t.get("artist") or "—"
        duration = t.get("duration", 0)
        m, s = int(duration // 60), int(duration % 60)
        yt = " 🔗" if t.get("youtube_status") == "uploaded" else ""

        lines.append(
            f"<b>{i}.</b> {artist} — {title} ({m}:{s:02d}){yt}"
        )

    return "\n".join(lines)


def _build_library_keyboard(
    tracks: list[dict], page: int, total: int, user_id: int
) -> InlineKeyboardMarkup:
    """Строит клавиатуру для библиотеки: кнопки треков + навигация."""
    total_pages = max(1, (total + TRACKS_PER_PAGE - 1) // TRACKS_PER_PAGE)
    buttons = []

    # Кнопки треков (по номеру)
    for i, t in enumerate(tracks, 1):
        label = f"{i}"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"track_{t['id']}",
            )
        ])

    # Навигация
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"page_{user_id}_{page - 1}",
        ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data=f"page_{user_id}_{page + 1}",
        ))
    if nav:
        buttons.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("library"))
async def show_library(message: Message):
    """Показывает библиотеку треков пользователя с пагинацией."""
    user_id = message.from_user.id
    await _show_library_page(message, user_id, page=1)


async def _show_library_page(
    target: Message | CallbackQuery, user_id: int, page: int
):
    """Общая логика отображения страницы библиотеки."""
    offset = (page - 1) * TRACKS_PER_PAGE
    tracks = database.get_user_tracks(user_id, limit=TRACKS_PER_PAGE, offset=offset)
    total = database.count_user_tracks(user_id)

    if total == 0:
        text = "📭 Твоя библиотека пуста. Отправь MP3-файл, чтобы добавить трек."
        keyboard = None
    else:
        text = _build_track_list_text(tracks, page, total)
        keyboard = _build_library_keyboard(tracks, page, total, user_id)

    if isinstance(target, Message):
        await target.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await target.answer()


# ─── Callback: пагинация библиотеки ───────────────────────────────

@dp.callback_query(lambda c: c.data.startswith("page_"))
async def library_page(callback: CallbackQuery):
    _, owner_id, page_str = callback.data.split("_")
    page = int(page_str)

    # Только владелец может листать свою библиотеку
    if int(owner_id) != callback.from_user.id:
        await callback.answer("Это не твоя библиотека!", show_alert=True)
        return

    await _show_library_page(callback, callback.from_user.id, page)


# ─── Callback: детали трека ───────────────────────────────────────

def _build_track_detail_text(track: dict) -> str:
    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"
    duration = track.get("duration", 0)
    m, s = int(duration // 60), int(duration % 60)
    size_mb = (track.get("file_size") or 0) / 1024 / 1024
    bitrate = (track.get("bitrate") or 0) // 1000
    has_cover = "✅" if track.get("has_cover") else "❌"
    yt_status = track.get("youtube_status")
    yt_video_id = track.get("youtube_video_id")
    bs_status = track.get("beatstars_status")
    detected_bpm = track.get("bpm")
    detected_key = track.get("key")

    lines = [
        f"🎵 <b>{artist} — {title}</b>",
        f"",
        f"⏱ Длительность: {m}:{s:02d}",
        f"📦 Размер: {size_mb:.1f} МБ",
        f"🔊 Битрейт: {bitrate} kbps",
        f"🖼 Обложка: {has_cover}",
    ]

    if detected_bpm:
        lines.append(f"🎼 BPM: {detected_bpm}")
    if detected_key:
        lines.append(f"🎹 Тональность: {detected_key}")

    lines.append(f"📅 Загружен: {track['uploaded_at'][:10]}")

    if yt_status == "uploaded" and yt_video_id:
        lines.append(f"")
        lines.append(f"🔗 <a href='https://youtube.com/watch?v={yt_video_id}'>Смотреть на YouTube</a>")
    elif yt_status == "failed":
        lines.append(f"")
        lines.append(f"⚠️ Предыдущая попытка загрузки на YouTube не удалась.")

    if bs_status == "uploaded":
        lines.append(f"")
        lines.append(f"🎹 Загружен на BeatStars ✅")
    elif bs_status == "failed":
        lines.append(f"")
        lines.append(f"⚠️ Предыдущая попытка загрузки на BeatStars не удалась.")

    return "\n".join(lines)


@dp.callback_query(lambda c: c.data.startswith("track_"))
async def track_detail(callback: CallbackQuery):
    track_id = int(callback.data.split("_")[1])
    track = database.get_track_by_id(track_id)

    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    text = _build_track_detail_text(track)

    # Кнопки
    buttons = []
    yt_status = track.get("youtube_status")
    bs_status = track.get("beatstars_status")

    if yt_status != "uploaded":
        buttons.append([
            InlineKeyboardButton(
                text="⬆️ Загрузить на YouTube",
                callback_data=f"upload_{track_id}",
            )
        ])

    if bs_status != "uploaded":
        buttons.append([
            InlineKeyboardButton(
                text="🎹 Загрузить на BeatStars",
                callback_data=f"upload_bs_{track_id}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔙 Назад к библиотеке",
            callback_data=f"page_{callback.from_user.id}_1",
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Если есть обложка — шлём фото + подпись, иначе просто текст
    cover_path = track.get("cover_path")
    if cover_path and os.path.exists(cover_path):
        try:
            await callback.message.answer_photo(
                photo=cover_path,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            await callback.message.delete()
            await callback.answer()
            return
        except Exception:
            pass  # fallback to text

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# ─── Callback: выбор видимости ────────────────────────────────────

@dp.callback_query(lambda c: c.data.startswith("upload_") and not c.data.startswith("upload_bs_"))
async def ask_visibility(callback: CallbackQuery):
    track_id = int(callback.data.split("_")[1])
    track = database.get_track_by_id(track_id)

    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    if not youtube.youtube_is_configured():
        await callback.message.edit_text(
            "⚠️ <b>YouTube не настроен!</b>\n\n"
            "Сначала запусти <code>python youtube.py</code> локально, "
            "чтобы авторизоваться через браузер. После этого бот сможет "
            "загружать видео.",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔒 Private",
                callback_data=f"vis_{track_id}_private",
            ),
            InlineKeyboardButton(
                text="🔓 Unlisted",
                callback_data=f"vis_{track_id}_unlisted",
            ),
            InlineKeyboardButton(
                text="🌍 Public",
                callback_data=f"vis_{track_id}_public",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"track_{track_id}",
            ),
        ],
    ])

    await callback.message.edit_text(
        f"⬆️ <b>Загрузка на YouTube</b>\n\n"
        f"🎵 {artist} — {title}\n\n"
        f"Выбери видимость видео:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


# ─── Callback: выполнение загрузки ────────────────────────────────

def _make_fallback_cover(audio_path: str) -> str:
    """Создаёт чёрную заглушку 1280×960 если нет обложки."""
    from PIL import Image

    fallback_path = os.path.join(VIDEO_DIR, "_fallback_cover.jpg")
    if not os.path.exists(fallback_path):
        img = Image.new("RGB", (1280, 960), color=(15, 15, 15))
        img.save(fallback_path, "JPEG")
    return fallback_path


@dp.callback_query(lambda c: c.data.startswith("vis_"))
async def do_upload(callback: CallbackQuery):
    _, track_id, privacy = callback.data.split("_")
    track_id = int(track_id)

    track = database.get_track_by_id(track_id)
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"

    # Пути
    audio_path = track["file_path"]
    cover_path = track.get("cover_path")

    if not os.path.exists(audio_path):
        await callback.message.edit_text("❌ Аудиофайл не найден на диске.")
        await callback.answer()
        return

    if not cover_path or not os.path.exists(cover_path):
        cover_path = _make_fallback_cover(audio_path)

    video_path = os.path.join(VIDEO_DIR, f"video_{track_id}.mp4")

    # Шаг 1: создаём видео
    await callback.message.edit_text(
        f"🎬 <b>Создаю видео...</b>\n\n"
        f"🎵 {artist} — {title}",
        parse_mode="HTML",
    )
    await callback.answer()

    success = await asyncio.to_thread(
        video_creation.create_music_video,
        audio_path=audio_path,
        image_path=cover_path,
        output_path=video_path,
    )

    if not success:
        database.update_youtube_status(track_id, None, "failed")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при создании видео.</b>\n\n"
            f"Убедись, что ffmpeg установлен и доступен в PATH.",
            parse_mode="HTML",
        )
        return

    # Шаг 2: загружаем на YouTube
    await callback.message.edit_text(
        f"⬆️ <b>Загружаю на YouTube...</b>\n\n"
        f"🎵 {artist} — {title}\n"
        f"👁 Видимость: {privacy}",
        parse_mode="HTML",
    )

    yt_title = f"{artist} — {title}"
    yt_description = (
        f"{artist} — {title}\n\n"
        f"📅 Загружено через BeatsUpload Bot"
    )
    yt_tags = ["beats", "instrumental", "beatsupload"]
    if artist:
        yt_tags.append(artist)
    if title:
        yt_tags.append(title)

    result = await asyncio.to_thread(
        youtube.upload_video,
        video_file=video_path,
        title=yt_title,
        description=yt_description,
        tags=yt_tags,
        category="10",  # Music
        privacy_status=privacy,
    )

    if result["success"]:
        database.update_youtube_status(track_id, result["video_id"], "uploaded")
        await callback.message.edit_text(
            f"✅ <b>Загрузка завершена!</b>\n\n"
            f"🎵 {artist} — {title}\n"
            f"👁 Видимость: {privacy}\n"
            f"🔗 <a href='{result['video_url']}'>Смотреть на YouTube</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    else:
        database.update_youtube_status(track_id, None, "failed")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при загрузке на YouTube:</b>\n\n"
            f"{result['error']}",
            parse_mode="HTML",
        )


# ─── Callback: запрос тегов для BeatStars ──────────────────────────


@dp.callback_query(lambda c: c.data.startswith("upload_bs_"))
async def ask_beatstars_tags(callback: CallbackQuery, state: FSMContext):
    track_id = int(callback.data.split("_")[2])
    track = database.get_track_by_id(track_id)

    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    # Сохраняем track_id в состоянии
    await state.update_data(track_id=track_id)
    await state.set_state(BeatStarsUpload.waiting_for_tags)

    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"
    bpm = track.get("bpm")
    detected_key = track.get("key")

    extra = ""
    if bpm or detected_key:
        extra += f"\n\nАвто-определено:"
        if bpm:
            extra += f"\n🎼 BPM: <b>{bpm}</b>"
        if detected_key:
            extra += f"\n🎹 Тональность: <b>{detected_key}</b>"

    await callback.message.edit_text(
        f"🎹 <b>Загрузка на BeatStars</b>\n\n"
        f"🎵 {artist} — {title}{extra}\n\n"
        f"Отправь <b>3 тега</b> (имена артистов через запятую),\n"
        f"чтобы твой бит находили чаще:\n\n"
        f"<i>Например: Drake, Travis Scott, Metro Boomin</i>",
        parse_mode="HTML",
    )
    await callback.answer()


# ─── FSM: приём тегов и запуск загрузки на BeatStars ───────────────


@dp.message(BeatStarsUpload.waiting_for_tags)
async def receive_beatstars_tags(message: Message, state: FSMContext):
    data = await state.get_data()
    track_id = data.get("track_id")
    await state.clear()

    if track_id is None:
        await message.answer("❌ Что-то пошло не так. Попробуй снова из библиотеки.")
        return

    track = database.get_track_by_id(track_id)
    if track is None:
        await message.answer("❌ Трек не найден в базе.")
        return

    # Парсим теги
    raw = message.text.strip() if message.text else ""
    tags = [t.strip() for t in raw.split(",") if t.strip()]

    if len(tags) < 1:
        await message.answer(
            "⚠️ Нужен хотя бы один тег. Попробуй ещё раз из библиотеки."
        )
        return

    if len(tags) > 3:
        tags = tags[:3]

    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"
    detected_bpm = track.get("bpm")
    detected_key = track.get("key")

    extra = ""
    if detected_bpm:
        extra += f"\n🎼 BPM: {detected_bpm}"
    if detected_key:
        extra += f"\n🎹 Тональность: {detected_key}"

    await message.answer(
        f"🎹 <b>Загружаю на BeatStars...</b>\n\n"
        f"🎵 {artist} — {title}\n"
        f"🏷 Теги: {', '.join(tags)}{extra}\n\n"
        f"<i>Браузер откроется для завершения загрузки...</i>",
        parse_mode="HTML",
    )

    # Запускаем загрузку в отдельном потоке (Selenium блокирующий)
    import asyncio
    result = await asyncio.to_thread(
        beatstars_uploader.upload_to_beatstars,
        track=track,
        tags=tags,
    )

    if result["success"]:
        database.update_beatstars_status(track_id, "uploaded")
        await message.answer(
            f"✅ <b>Форма BeatStars заполнена!</b>\n\n"
            f"🎵 {artist} — {title}\n"
            f"🏷 Теги: {', '.join(tags)}\n\n"
            f"{result['message']}",
            parse_mode="HTML",
        )
    else:
        database.update_beatstars_status(track_id, "failed")
        await message.answer(
            f"❌ <b>Ошибка при загрузке на BeatStars:</b>\n\n"
            f"{result['error']}",
            parse_mode="HTML",
        )


# ─── Точка входа ──────────────────────────────────────────────────

async def main():
    await dp.start_polling(bot)


def start_bot():
    """Точка входа для синхронного внешнего вызова"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
