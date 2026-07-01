import librosa
import numpy as np

# 1. Load the audio file
y, sr = librosa.load('your_song.mp3')

# 2. Detect BPM (Tempo)
tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
print(f"Estimated BPM: {tempo:.2f}")

# 3. Extract Chroma Features for Key Detection
chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
chroma_sum = np.sum(chroma, axis=1) # Sum energy of each of the 12 pitch classes

# Note: To get the final Key string (e.g., "C Major"), you must compare
# # 'chroma_sum' against the Krumhansl-Schmuckler major/minor profiles
# using a dot product or Pearson correlation across all 12 shifts.