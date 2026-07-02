# bot.py
import os
import asyncio
import logging
import math
import time
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, BaseMiddleware
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
if not API_TOKEN:
    raise RuntimeError(
        "BOT_API_TOKEN не задан! Создай файл .env с BOT_API_TOKEN=твой_токен"
    )
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── Доступ: только владелец бота ──────────────────────────────────

ALLOWED_USER_IDS = {
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}  # задаётся в .env через запятую, например: ALLOWED_USER_IDS=845035436,123456789


class AccessMiddleware(BaseMiddleware):
    """Middleware, блокирующий доступ всем, кроме владельца."""

    async def __call__(self, handler, event, data):
        user_id = None

        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id is not None and user_id not in ALLOWED_USER_IDS:
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён. Этот бот приватный.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return  # не передавать событие дальше

        return await handler(event, data)


# Регистрируем middleware для сообщений и callback-запросов
dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

# --- FSM для загрузки на BeatStars ---


class BeatStarsUpload(StatesGroup):
    waiting_for_tags = State()


class BPMSelection(StatesGroup):
    waiting_for_bpm_choice = State()
    waiting_for_custom_bpm = State()


class ProfileEditor(StatesGroup):
    waiting_for_name = State()
    waiting_for_title_template = State()
    waiting_for_description_template = State()
    editing_profile_id = State()  # хранит id редактируемого профиля

# Директории (абсолютные пути — чтобы работало из любой папки)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(_BASE_DIR, "audio_storage")
VIDEO_DIR = os.path.join(_BASE_DIR, "video_storage")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

TRACKS_PER_PAGE = 5


# ─── Команда /start ───────────────────────────────────────────────

@dp.message(Command("start"))
async def send_welcome(message: Message):
    if message.chat.type == "private":
        await message.answer(
            "Привет! Отправь мне MP3-файл (бит), и я сохраню его в твою библиотеку.\n\n"
            "📚 /library — посмотреть твою библиотеку и загрузить трек на YouTube\n"
            "📝 /profiles — управление профилями загрузки (шаблоны названий и описаний)"
        )


# ─── Команда /profiles ──────────────────────────────────────────────

def _build_profiles_text(profiles: list[dict]) -> str:
    """Формирует текст списка профилей."""
    lines = ["📝 <b>Профили загрузки</b>\n"]
    for i, p in enumerate(profiles, 1):
        default_mark = " ★" if p["is_default"] else ""
        lines.append(
            f"<b>{i}.</b> {p['name']}{default_mark}\n"
            f"    🏷 Название: <code>{p['title_template']}</code>\n"
            f"    📄 Описание: <code>{p['description_template'][:80]}{'…' if len(p.get('description_template', '')) > 80 else ''}</code>"
        )
    lines.append(
        f"\n<i>Переменные: {'{artist}'}, {'{title}'}, {'{bpm}'}, {'{key}'}</i>"
    )
    return "\n".join(lines)


def _build_profiles_keyboard(profiles: list[dict]) -> InlineKeyboardMarkup:
    """Кнопки управления профилями."""
    buttons = []
    for p in profiles:
        row = [
            InlineKeyboardButton(
                text=f"✏️ {p['name']}",
                callback_data=f"proedit_{p['id']}",
            ),
        ]
        if not p["is_default"]:
            row.append(
                InlineKeyboardButton(
                    text="★",
                    callback_data=f"prodef_{p['id']}",
                )
            )
        if len(profiles) > 1:
            row.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"prodel_{p['id']}",
                )
            )
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            text="➕ Создать новый профиль",
            callback_data="procreate",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("profiles"))
async def show_profiles(message: Message):
    """Показывает список профилей загрузки."""
    user_id = message.from_user.id
    database.ensure_default_profile(user_id)
    profiles = database.get_user_profiles(user_id)

    text = _build_profiles_text(profiles)
    keyboard = _build_profiles_keyboard(profiles)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


# ─── Callback: управление профилями ──────────────────────────────────


@dp.callback_query(lambda c: c.data == "procreate")
async def start_create_profile(callback: CallbackQuery, state: FSMContext):
    """Начинает создание нового профиля."""
    await state.set_state(ProfileEditor.waiting_for_name)
    await callback.message.edit_text(
        "📝 <b>Создание профиля загрузки</b>\n\n"
        "Шаг 1/3: Отправь <b>название</b> профиля\n"
        "<i>Например: «Для BeatStars», «Короткое», «Свой стиль»</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("proedit_"))
async def start_edit_profile(callback: CallbackQuery, state: FSMContext):
    """Начинает редактирование профиля."""
    profile_id = int(callback.data.split("_")[1])
    profile = database.get_profile_by_id(profile_id)
    if not profile:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    await state.update_data(editing_profile_id=profile_id)
    await state.set_state(ProfileEditor.waiting_for_title_template)
    await callback.message.edit_text(
        f"📝 <b>Редактирование: {profile['name']}</b>\n\n"
        f"Шаг 1/2: Отправь <b>шаблон названия</b> видео\n"
        f"Текущий: <code>{profile['title_template']}</code>\n\n"
        f"<i>Доступные переменные: {'{artist}'}, {'{title}'}, {'{bpm}'}, {'{key}'}</i>\n"
        f"<i>Например: <code>{'{artist} — {title}'}</code></i>",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("prodef_"))
async def set_default_profile(callback: CallbackQuery):
    """Устанавливает профиль по умолчанию."""
    profile_id = int(callback.data.split("_")[1])
    database.update_profile(profile_id, is_default=True)
    await callback.answer("★ Установлен по умолчанию!", show_alert=True)

    profiles = database.get_user_profiles(callback.from_user.id)
    text = _build_profiles_text(profiles)
    keyboard = _build_profiles_keyboard(profiles)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("prodel_"))
async def delete_profile(callback: CallbackQuery):
    """Удаляет профиль."""
    profile_id = int(callback.data.split("_")[1])
    ok = database.delete_profile(profile_id)
    if not ok:
        await callback.answer("⚠️ Нельзя удалить последний профиль!", show_alert=True)
        return

    await callback.answer("🗑 Профиль удалён!", show_alert=True)
    profiles = database.get_user_profiles(callback.from_user.id)
    text = _build_profiles_text(profiles)
    keyboard = _build_profiles_keyboard(profiles)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


# ─── Приём MP3-файлов ─────────────────────────────────────────────

def _build_track_success_message(track: dict, unique_id: int) -> str:
    """Формирует текст сообщения об успешном добавлении трека."""
    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"
    duration = track.get("duration", 0)
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    has_cover = "🖼" if track.get("has_cover") else "—"

    lines = [
        "✅ Трек добавлен в библиотеку!",
        "",
        f"🎵 Название: <b>{title}</b>",
        f"👤 Исполнитель: <b>{artist}</b>",
        f"⏱ Длительность: {minutes}:{seconds:02d}",
        f"📦 Размер: {track['file_size'] / 1024 / 1024:.1f} МБ",
        f"🔊 Битрейт: {track['bitrate'] // 1000} kbps",
        f"🖼 Обложка: {has_cover}",
    ]

    bpm = track.get("bpm")
    if bpm is not None:
        lines.append(f"🎼 BPM: <b>{bpm}</b>")

    key = track.get("key")
    if key is not None:
        lines.append(f"🎹 Тональность: <b>{key}</b>")

    lines += [
        f"🆔 ID: <code>{unique_id}</code>",
        "",
        f"📚 <b>/library</b> — библиотека и загрузка на YouTube",
    ]

    return "\n".join(lines)


@dp.message(lambda m: (m.audio or m.document) and m.chat.type == "private")
async def handle_audio(message: Message, state: FSMContext):
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
            processor.process_audio, file_path, unique_id, user_id, file.file_name
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
            bpm_raw = track.get("bpm_raw")
            bpm_stored = track.get("bpm")

            # Если BPM дробный — даём пользователю выбор перед показом результата
            if (
                bpm_raw is not None
                and bpm_stored is not None
                and bpm_raw != bpm_stored
                and bpm_raw != int(bpm_raw)
            ):
                floor_bpm = int(math.floor(bpm_raw))
                ceil_bpm = int(math.ceil(bpm_raw))

                await state.set_state(BPMSelection.waiting_for_bpm_choice)
                await state.update_data(
                    bpm_track=track,
                    bpm_floor=floor_bpm,
                    bpm_ceil=ceil_bpm,
                    bpm_unique_id=unique_id,
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"⬇️ {floor_bpm}",
                            callback_data="bpm_floor",
                        ),
                        InlineKeyboardButton(
                            text=f"⬆️ {ceil_bpm}",
                            callback_data="bpm_ceil",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="✏️ Своё значение",
                            callback_data="bpm_custom",
                        ),
                    ],
                ])

                await message.answer(
                    f"🎼 Обнаружен дробный BPM: <b>{bpm_raw}</b>\n\n"
                    f"BeatStars принимает только целые числа. Выбери вариант:",
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                return  # не показываем финальное сообщение до выбора

            # BPM целый (или отсутствует) — сразу показываем результат
            text = _build_track_success_message(track, unique_id)
            await message.answer(text, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка при скачивании или обработке: {e}")
        await message.answer("❌ Произошла ошибка при загрузке или обработке файла.")


# ─── FSM: выбор целого BPM при дробном значении ────────────────────


@dp.callback_query(lambda c: c.data in ("bpm_floor", "bpm_ceil", "bpm_custom"))
async def bpm_choice_callback(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор BPM: округление вниз / вверх / своё значение."""
    data = await state.get_data()
    action = callback.data

    if action == "bpm_custom":
        await state.set_state(BPMSelection.waiting_for_custom_bpm)
        await callback.message.edit_text(
            "✏️ Отправь целое значение BPM (например, <b>162</b>):",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # floor или ceil
    bpm = data["bpm_floor"] if action == "bpm_floor" else data["bpm_ceil"]
    track = data["bpm_track"]
    database.update_track_bpm(track["db_id"], bpm)
    track["bpm"] = bpm

    text = _build_track_success_message(track, data["bpm_unique_id"])
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.clear()
    await callback.answer(f"✅ BPM = {bpm}")


@dp.message(BPMSelection.waiting_for_custom_bpm)
async def custom_bpm_entered(message: Message, state: FSMContext):
    """Пользователь ввёл своё значение BPM."""
    data = await state.get_data()

    try:
        bpm = int(message.text.strip())
        if bpm <= 0 or bpm > 999:
            raise ValueError
    except ValueError:
        await message.answer(
            "⚠️ Введи целое положительное число от 1 до 999 (например, <b>162</b>):",
            parse_mode="HTML",
        )
        return

    track = data["bpm_track"]
    database.update_track_bpm(track["db_id"], bpm)
    track["bpm"] = bpm

    text = _build_track_success_message(track, data["bpm_unique_id"])
    await message.answer(text, parse_mode="HTML")
    await state.clear()


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


# ─── Callback: выбор профиля → видимость ──────────────────────────

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
    user_id = callback.from_user.id
    profiles = database.get_user_profiles(user_id)

    # Если один профиль — пропускаем выбор и сразу показываем видимость
    if len(profiles) <= 1:
        profile_id = profiles[0]["id"] if profiles else 0
        await _show_visibility(callback, track_id, profile_id, track)
        return

    # Несколько профилей — показываем выбор
    profile_buttons = []
    for p in profiles:
        default_mark = " ★" if p["is_default"] else ""
        profile_buttons.append([
            InlineKeyboardButton(
                text=f"{p['name']}{default_mark}",
                callback_data=f"profupload_{track_id}_{p['id']}",
            )
        ])

    profile_buttons.append([
        InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"track_{track_id}",
        ),
    ])

    await callback.message.edit_text(
        f"⬆️ <b>Загрузка на YouTube</b>\n\n"
        f"🎵 {artist} — {title}\n\n"
        f"📝 Выбери <b>профиль загрузки</b>\n"
        f"(шаблон названия и описания):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=profile_buttons),
    )
    await callback.answer()


# ─── Callback: профиль выбран → показываем видимость ────────────────

@dp.callback_query(lambda c: c.data.startswith("profupload_"))
async def profile_selected_for_upload(callback: CallbackQuery):
    _, track_id, profile_id = callback.data.split("_")
    track_id = int(track_id)
    profile_id = int(profile_id)

    track = database.get_track_by_id(track_id)
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    await _show_visibility(callback, track_id, profile_id, track)


async def _show_visibility(callback: CallbackQuery, track_id: int,
                           profile_id: int, track: dict):
    """Показывает выбор видимости (общая для обоих путей)."""
    profile = database.get_profile_by_id(profile_id)
    profile_name = profile["name"] if profile else "Стандартный"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔒 Private",
                callback_data=f"vis_{track_id}_{profile_id}_private",
            ),
            InlineKeyboardButton(
                text="🔓 Unlisted",
                callback_data=f"vis_{track_id}_{profile_id}_unlisted",
            ),
            InlineKeyboardButton(
                text="🌍 Public",
                callback_data=f"vis_{track_id}_{profile_id}_public",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"upload_{track_id}",
            ),
        ],
    ])

    title = track.get("title") or "Без названия"
    artist = track.get("artist") or "Неизвестен"

    await callback.message.edit_text(
        f"⬆️ <b>Загрузка на YouTube</b>\n\n"
        f"🎵 {artist} — {title}\n"
        f"📝 Профиль: <b>{profile_name}</b>\n\n"
        f"Выбери видимость видео:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


# ─── Callback: выполнение загрузки ────────────────────────────────

def _make_fallback_cover() -> str:
    """Создаёт чёрную заглушку 1280×960 если нет обложки."""
    from PIL import Image

    fallback_path = os.path.join(VIDEO_DIR, "_fallback_cover.jpg")
    if not os.path.exists(fallback_path):
        img = Image.new("RGB", (1280, 960), color=(15, 15, 15))
        img.save(fallback_path, "JPEG")
    return fallback_path


@dp.callback_query(lambda c: c.data.startswith("vis_"))
async def do_upload(callback: CallbackQuery):
    # Парсим: vis_{track_id}_{profile_id}_{privacy}
    parts = callback.data.split("_")
    track_id = int(parts[1])
    profile_id = int(parts[2])
    privacy = parts[3]

    track = database.get_track_by_id(track_id)
    if track is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    # Загружаем профиль и рендерим шаблоны
    profile = database.get_profile_by_id(profile_id)
    if profile:
        yt_title = database.render_template(profile["title_template"], track)
        yt_description = database.render_template(profile["description_template"], track)
    else:
        artist = track.get("artist") or "Неизвестен"
        title = track.get("title") or "Без названия"
        yt_title = f"{artist} — {title}"
        yt_description = f"{artist} — {title}\n\n📅 Загружено через BeatsUpload Bot"

    artist = track.get("artist") or "Неизвестен"
    title = track.get("title") or "Без названия"

    # Пути
    audio_path = track["file_path"]
    cover_path = track.get("cover_path")

    if not os.path.exists(audio_path):
        await callback.message.edit_text("❌ Аудиофайл не найден на диске.")
        await callback.answer()
        return

    if not cover_path or not os.path.exists(cover_path):
        cover_path = _make_fallback_cover()

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


# ─── FSM: создание профиля (шаги 1→2→3) ──────────────────────────────


@dp.message(ProfileEditor.waiting_for_name)
async def profile_name_entered(message: Message, state: FSMContext):
    """Шаг 1: получили название, просим title_template."""
    name = message.text.strip()[:100]
    await state.update_data(profile_name=name)
    await state.set_state(ProfileEditor.waiting_for_title_template)
    await message.answer(
        f"📝 <b>Новый профиль: {name}</b>\n\n"
        f"Шаг 2/3: Отправь <b>шаблон названия</b> видео\n\n"
        f"<i>Доступные переменные: {'{artist}'}, {'{title}'}, {'{bpm}'}, {'{key}'}</i>\n"
        f"<i>Например: <code>{'{artist} — {title}'}</code> или <code>{'{title}'}</code></i>",
        parse_mode="HTML",
    )


@dp.message(ProfileEditor.waiting_for_title_template)
async def profile_title_template_entered(message: Message, state: FSMContext):
    """Шаг 2: получили title_template, просим description_template или сохраняем при редактировании."""
    template = message.text.strip()[:500]
    data = await state.get_data()
    editing_id = data.get("editing_profile_id")

    if editing_id:
        # Режим редактирования — сохраняем оба поля сразу
        await state.update_data(title_template=template)
        await state.set_state(ProfileEditor.waiting_for_description_template)
        profile = database.get_profile_by_id(editing_id)
        current_desc = profile["description_template"] if profile else ""
        await message.answer(
            f"📝 Шаг 2/2: Отправь <b>шаблон описания</b> видео\n"
            f"Текущий: <code>{current_desc[:100]}{'…' if len(current_desc) > 100 else ''}</code>\n\n"
            f"<i>Доступные переменные: {'{artist}'}, {'{title}'}, {'{bpm}'}, {'{key}'}</i>\n"
            f"<i>Например: <code>{'{artist} — {title}\\n\\nBPM: {bpm} | Key: {key}'}</code></i>",
            parse_mode="HTML",
        )
        return

    # Режим создания — сохраняем и идём дальше
    await state.update_data(title_template=template)
    await state.set_state(ProfileEditor.waiting_for_description_template)
    await message.answer(
        f"Шаг 3/3: Отправь <b>шаблон описания</b> видео\n\n"
        f"<i>Доступные переменные: {'{artist}'}, {'{title}'}, {'{bpm}'}, {'{key}'}</i>\n"
        f"<i>Например: <code>{'{artist} — {title}\\n\\nBPM: {bpm} | Key: {key}\\n📅 Загружено через BeatsUpload Bot'}</code></i>",
        parse_mode="HTML",
    )


@dp.message(ProfileEditor.waiting_for_description_template)
async def profile_description_template_entered(message: Message, state: FSMContext):
    """Шаг 3 (или 2 при редактировании): сохраняем профиль."""
    template = message.text.strip()[:2000]
    data = await state.get_data()
    editing_id = data.get("editing_profile_id")

    if editing_id:
        # Завершаем редактирование
        title_tpl = data.get("title_template", "")
        database.update_profile(
            editing_id,
            title_template=title_tpl,
            description_template=template,
        )
        profile = database.get_profile_by_id(editing_id)
        await state.clear()
        await message.answer(
            f"✅ Профиль <b>«{profile['name']}»</b> обновлён!\n\n"
            f"🏷 Название: <code>{title_tpl}</code>\n"
            f"📄 Описание: <code>{template[:100]}{'…' if len(template) > 100 else ''}</code>",
            parse_mode="HTML",
        )
        return

    # Завершаем создание
    name = data.get("profile_name", "Без названия")
    title_tpl = data.get("title_template", "{artist} — {title}")
    user_id = message.from_user.id
    database.create_profile(
        user_id=user_id,
        name=name,
        title_template=title_tpl,
        description_template=template,
    )
    await state.clear()
    await message.answer(
        f"✅ Профиль <b>«{name}»</b> создан!\n\n"
        f"🏷 Название: <code>{title_tpl}</code>\n"
        f"📄 Описание: <code>{template[:100]}{'…' if len(template) > 100 else ''}</code>\n\n"
        f"Используй /profiles чтобы управлять профилями.",
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
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске бота: {e}")
        raise
