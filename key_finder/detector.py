"""
Key & BPM Detector
Uses librosa to detect BPM (tempo) and musical key from an MP3 file.

BPM detection: librosa.beat.beat_track
Key detection : chroma_cqt + Krumhansl-Schmuckler major/minor profiles
"""

import numpy as np

# Chroma labels (12 semitones)
CHROMA_LABELS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles
MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

# Maps librosa chroma label → BeatStars key name prefix
# (BeatStars uses full words like "C-Sharp" not "C#")
CHROMA_TO_BEATSTARS_PREFIX = {
    "C": "C",
    "C#": "C-Sharp",
    "D": "D",
    "D#": "D-Sharp",
    "E": "E",
    "F": "F",
    "F#": "F-Sharp",
    "G": "G",
    "G#": "G-Sharp",
    "A": "A",
    "A#": "A-Sharp",
    "B": "B",
}

# All keys that BeatStars actually supports (from its dropdown)
# Only keys in this set can be selected in the BeatStars upload form
BEATSTARS_VALID_KEYS = {
    "A-Flat-Minor", "A-Flat-Major",
    "A-Minor", "A-Major",
    "A-Sharp-Minor", "A-Sharp-Major",
    "B-Flat-Minor", "B-Flat-Major",
    "B-Minor", "B-Major",
    "C-Flat-Major",
    "C-Minor", "C-Major",
    "C-Sharp-Minor", "C-Sharp-Major",
    "D-Flat-Major",
    "D-Minor", "D-Major",
    "D-Sharp-Minor",
    "E-Flat-Major",
    "E-Minor", "E-Major",
    "F-Minor", "F-Major",
    "F-Sharp-Minor", "F-Sharp-Major",
    "G-Flat-Major",
    "G-Minor", "G-Major",
    "G-Sharp-Minor",
}


def _detect_bpm(y: np.ndarray, sr: float) -> float:
    """Detect BPM (tempo) from an audio signal.

    Args:
        y: Audio time series.
        sr: Sample rate.

    Returns:
        Estimated BPM as a float, rounded to 1 decimal place.
    """
    tempo, _ = __import__("librosa").beat.beat_track(y=y, sr=sr)
    # tempo can be an array or scalar
    if hasattr(tempo, "__len__"):
        return round(float(tempo[0]), 1)
    return round(float(tempo), 1)


def _detect_key(y: np.ndarray, sr: float) -> tuple[str, str]:
    """Detect musical key using chroma features and K-S profiles.

    Args:
        y: Audio time series (should be trimmed of silence).
        sr: Sample rate.

    Returns:
        Tuple of (chroma_label, key_type) — e.g. ("C", "Minor").
    """
    librosa = __import__("librosa")

    # Split into 10-second segments for a more robust estimate
    segment_length = sr * 10
    num_segments = max(1, len(y) // segment_length)
    chroma_mean_total = np.zeros(12)

    for i in range(num_segments):
        start = i * segment_length
        end = (i + 1) * segment_length
        segment = y[start:end]

        chroma = librosa.feature.chroma_cqt(y=segment, sr=sr)
        chroma_mean_total += np.mean(chroma, axis=1)

    chroma_mean_total /= num_segments

    # Normalize
    norm = np.linalg.norm(chroma_mean_total)
    if norm > 0:
        chroma_mean_total /= norm

    # Correlate with major and minor profiles across all 12 key shifts
    major_corrs = [
        np.corrcoef(np.roll(MAJOR_PROFILE, i), chroma_mean_total)[0, 1]
        for i in range(12)
    ]
    minor_corrs = [
        np.corrcoef(np.roll(MINOR_PROFILE, i), chroma_mean_total)[0, 1]
        for i in range(12)
    ]

    major_idx = int(np.argmax(major_corrs))
    minor_idx = int(np.argmax(minor_corrs))

    if major_corrs[major_idx] >= minor_corrs[minor_idx]:
        return CHROMA_LABELS[major_idx], "Major"
    else:
        return CHROMA_LABELS[minor_idx], "Minor"


def _to_beatstars_key(chroma_label: str, key_type: str) -> str | None:
    """Convert a librosa chroma + key type to a BeatStars-compatible key name.

    Returns None if the detected key doesn't have a direct BeatStars equivalent
    (some enharmonic keys like D#-Major are not in BeatStars' dropdown).
    """
    prefix = CHROMA_TO_BEATSTARS_PREFIX.get(chroma_label)
    if prefix is None:
        return None

    candidate = f"{prefix}-{key_type}"

    if candidate in BEATSTARS_VALID_KEYS:
        return candidate

    # Try enharmonic fallbacks for keys not in BeatStars
    # (e.g., D#-Major doesn't exist in BeatStars, but the user can set it manually)
    return None


def detect_key_bpm(audio_path: str) -> dict:
    """Detect BPM and musical key from an MP3 file.

    Args:
        audio_path: Path to the MP3 file.

    Returns:
        A dict with:
        - ``bpm`` (float | None) — detected tempo, or None on failure
        - ``key`` (str | None) — BeatStars-compatible key like "C-Minor",
          or None if detection fails or the key isn't available on BeatStars
        - ``key_raw`` (str | None) — raw detection result e.g. "C# Minor"
        - ``error`` (str | None) — error message on total failure, else None
    """
    try:
        librosa = __import__("librosa")

        # Load audio (mono, native sample rate)
        y, sr = librosa.load(audio_path, sr=None, mono=True)

        # Trim silence for cleaner key detection
        y_trimmed, _ = librosa.effects.trim(y)

        # Detect BPM (on the full signal for better tempo tracking)
        bpm = _detect_bpm(y, sr)

        # Detect key (on trimmed signal)
        chroma, key_type = _detect_key(y_trimmed, sr)
        key_raw = f"{chroma} {key_type}"
        key_beatstars = _to_beatstars_key(chroma, key_type)

        return {
            "bpm": bpm,
            "key": key_beatstars,
            "key_raw": key_raw,
            "error": None,
        }

    except ImportError:
        return {
            "bpm": None,
            "key": None,
            "key_raw": None,
            "error": "librosa is not installed",
        }
    except Exception as e:
        return {
            "bpm": None,
            "key": None,
            "key_raw": None,
            "error": str(e),
        }
