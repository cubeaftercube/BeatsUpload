# youtube.py
import os
import pickle

import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(_BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(_BASE_DIR, "youtube_token.pickle")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


def get_authenticated_service():
    """Возвращает авторизованный YouTube API-клиент.

    Если сохранённый токен существует — загружает его (авто-обновление
    при истечении). Иначе запускает локальный OAuth-сервер (требуется
    браузер) и сохраняет токен в файл для будущих запусков.
    """
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            credentials = pickle.load(f)
        return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

    # Первый запуск: открыть браузер, авторизоваться
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES
    )
    credentials = flow.run_local_server(port=0)

    # Сохраняем токен (с refresh_token) для будущих запусков
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(credentials, f)

    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


def youtube_is_configured() -> bool:
    """Проверяет, пройдена ли первичная OAuth-авторизация."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return False
    if not os.path.exists(TOKEN_FILE):
        return False
    return True


def upload_video(
    video_file: str,
    title: str,
    description: str,
    tags: list[str],
    category: str = "10",  # 10 = Music
    privacy_status: str = "private",
) -> dict:
    """Загружает видео на YouTube.

    Возвращает:
        success: bool
        video_id: str | None
        video_url: str | None
        error: str | None
    """
    try:
        youtube = get_authenticated_service()
    except Exception as e:
        return {
            "success": False,
            "video_id": None,
            "video_url": None,
            "error": f"Ошибка авторизации YouTube: {e}",
        }

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media_body = MediaFileUpload(video_file, chunksize=-1, resumable=True)

    try:
        insert_request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media_body,
        )

        response = None
        max_retries = 20  # ~10 минут при стандартном chunksize
        attempts = 0
        while response is None:
            attempts += 1
            if attempts > max_retries:
                return {
                    "success": False,
                    "video_id": None,
                    "video_url": None,
                    "error": "Таймаут загрузки: превышено количество попыток",
                }
            status, response = insert_request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")

        video_id = response["id"]
        print(f"Upload Complete! Video ID: {video_id}")

        return {
            "success": True,
            "video_id": video_id,
            "video_url": f"https://youtube.com/watch?v={video_id}",
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "video_id": None,
            "video_url": None,
            "error": f"Ошибка при загрузке: {e}",
        }


if __name__ == "__main__":
    # Запустить ОДИН РАЗ локально для первичной OAuth-авторизации.
    # После этого бот сможет использовать сохранённый токен.
    print("Запуск первичной авторизации YouTube...")
    youtube = get_authenticated_service()
    print(f"Токен сохранён в {TOKEN_FILE}")
    print("Готово! Бот может использовать YouTube API.")
