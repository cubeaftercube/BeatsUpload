# BeatsUpload — Telegram Bot for Beat Producers

A Telegram bot that lets beat producers manage their instrumental library, auto-detect BPM & musical key, generate music videos, and publish to **YouTube** and **BeatStars** — all from a Telegram chat.

## Features

- **🎧 MP3 Reception** — Accept MP3 files via Telegram (direct audio or document), extract ID3 metadata (title, artist, cover art).
- **🔍 Duplicate Detection** — SHA-256 hashing prevents importing the same track twice.
- **🎼 Key & BPM Detection** — Uses librosa with the Krumhansl-Schmuckler algorithm to detect tempo and musical key automatically.
- **📚 Library Management** — Browse your tracks with pagination, view metadata, see upload status.
- **🎬 Video Creation** — Generates a 4:3 MP4 video from audio + cover art using ffmpeg.
- **📤 YouTube Upload** — Upload videos to YouTube via the YouTube Data API v3 with private/unlisted/public visibility.
- **🎹 BeatStars Upload** — Automates the BeatStars.com upload form via Selenium, filling in title, tags, BPM, key, and cover image.
- **🖼 Cover Art Handling** — Extracts embedded album art from MP3 files; fallback cover generation if none exists.

## Architecture

```
main.py                     ← Entry point; initializes DB and starts the bot
telegram_module.py          ← Telegram bot (aiogram 3.x): FSM, callbacks, inline keyboards
processor.py                ← Orchestrates file processing → dedup → DB insert pipeline
file_processing.py          ← MP3 hash, metadata extraction (mutagen), cover art
database.py                 ← SQLite CRUD with schema migration
youtube.py                  ← YouTube Data API v3 upload (OAuth 2.0)
video_creation.py           ← ffmpeg-based music video generation
beatstars/
  beatstars_uploader.py     ← Selenium automation for BeatStars upload form
  beatstars-upload/         ← Original cloned helper project (standalone)
key_finder/
  detector.py               ← BPM + key detection using librosa (K-S profiles)
  ai.py                     ← Standalone key-finder script
script.py                   ← Standalone key-finder script (alternative)
```

## Requirements

- Python **3.8+**
- **ffmpeg** installed and available in your system PATH (for video creation)
- A Chrome/Chromium browser (for BeatStars Selenium automation)

### Python Dependencies

See `requirements.txt` / `pyproject.toml`:

| Package | Purpose |
|---|---|
| `aiogram` | Telegram Bot API framework |
| `mutagen` | MP3 metadata (ID3 tags, cover art) |
| `librosa` | Audio analysis (BPM & key detection) |
| `numpy` | Numerical computation (librosa dependency) |
| `Pillow` | Image processing (cover cropping, fallback) |
| `selenium` | Browser automation for BeatStars |
| `webdriver-manager` | Automatic ChromeDriver management |
| `google-api-python-client` | YouTube Data API v3 |
| `google-auth-oauthlib` | YouTube OAuth 2.0 |
| `python-dotenv` | Environment variable loading |

## Setup

### 1. Clone & Install

```bash
git clone <repo-url>
cd BeatsUpload
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```ini
BOT_API_TOKEN=your_telegram_bot_token
BEATSTARS_USERNAME=your_beatstars_email
BEATSTARS_PASSWORD=your_beatstars_password
```

Get a Telegram bot token from [@BotFather](https://t.me/BotFather).

### 3. YouTube OAuth (one-time setup)

The Google API client secrets file (`client_secrets.json`) is **not** included in the repo. To obtain it:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the **YouTube Data API v3**
4. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: **Desktop app**
5. Download the JSON file and save it as `client_secrets.json` in the project root

Then run the one-time authorization script:

```bash
python youtube.py
```

This opens a browser for Google OAuth consent and saves a `youtube_token.pickle` file. The bot uses this token for all future uploads.

### 4. Run the Bot

```bash
python main.py
```

## Usage

### Telegram Commands

| Command | Description |
|---|---|
| `/start` | Welcome message with instructions |
| `/library` | Browse your track library (paginated with inline buttons) |

### Uploading a Track

1. Send an MP3 file to the bot in a private chat
2. The bot extracts metadata, detects BPM/key, checks for duplicates, and adds it to your library
3. Use `/library` to see all your tracks

### Publishing a Track

1. Open `/library` and tap a track number to see its details
2. **YouTube** — Tap "Upload to YouTube", choose visibility (Private / Unlisted / Public). The bot creates a video from the audio + cover art and uploads it.
3. **BeatStars** — Tap "Upload to BeatStars", enter up to 3 artist tags (e.g. "Drake, Travis Scott, Metro Boomin"). The bot opens a Chrome browser, logs into BeatStars, fills in the form with all metadata, and leaves the browser open for you to set the publish date and confirm.

### Library Detail View

Each track shows:
- Title & artist (from ID3 tags)
- Duration, file size, bitrate
- Cover art presence
- Detected BPM & musical key
- YouTube video link (if uploaded)
- BeatStars upload status

## Key Detection

The key detector (`key_finder/detector.py`) uses:
- **Chroma CQT** features for pitch-class representation
- **Krumhansl-Schmuckler** key profiles correlated across all 12 shifts
- Multi-segment averaging (10-second windows) for robustness
- Silence trimming before analysis

Detected keys are mapped to the BeatStars dropdown format (e.g. `C-Sharp-Minor`).

## Project Structure

```
├── main.py                     ← Entry point
├── telegram_module.py          ← Telegram bot logic
├── processor.py                ← Audio processing pipeline
├── file_processing.py          ← MP3 hashing & metadata
├── database.py                 ← SQLite database layer
├── youtube.py                  ← YouTube API upload
├── video_creation.py           ← ffmpeg video generation
├── beatstars/
│   ├── beatstars_uploader.py   ← BeatStars Selenium automation
│   └── beatstars-upload/       ← Original standalone upload tool
├── key_finder/
│   ├── detector.py             ← BPM & key detection
│   ├── script.py               ← Standalone key finder
│   └── ai.py                   ← Alternative key finder
├── audio_storage/              ← Uploaded MP3 files (gitignored)
├── video_storage/              ← Generated videos (gitignored)
├── temp/                       ← Extracted cover art (gitignored)
├── .env                        ← Secrets (gitignored)
├── client_secrets.json         ← Google OAuth (gitignored)
├── youtube_token.pickle        ← YouTube auth token (gitignored)
├── beats.db                    ← SQLite database (gitignored)
├── pyproject.toml              ← Project metadata & dependencies
└── requirements.txt            ← Pip dependencies
```

## Notes

- **BeatStars upload** opens a visible Chrome window. It logs in, fills the upload form, and uploads MP3/cover. The browser is left open for you to select the publish date and manually publish — this is by design.
- **Duplicate detection** is based on SHA-256 of the file content, not ID3 metadata. Identical files (even with different tags) are detected as duplicates.
- **YouTube upload** requires ffmpeg. If the MP3 has no embedded cover art, a dark fallback image is used.
