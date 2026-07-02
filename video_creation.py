"""
Video Creator Module
Generates a 4:3 video from an MP3 audio file and a cover image.
"""

import subprocess
import sys
import os


def create_music_video(audio_path: str, image_path: str, output_path: str, width: int = 1280,
                       height: int = 960) -> bool:
    """
    Creates a 4:3 video from an audio file and an image cover.

    - If the image is too vertical, it will be cropped to a 4:3 aspect ratio.
    - If the image is too horizontal, it will stay uncropped (padded with black bars to fit the 4:3 frame).

    Args:
        audio_path (str): Path to the MP3 audio file.
        image_path (str): Path to the cover image.
        output_path (str): Path to save the resulting MP4 video.
        width (int): Output video width (default 1280).
        height (int): Output video height (default 960, which maintains a 4:3 aspect ratio).

    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        from PIL import Image
    except ImportError:
        print("Error: Pillow is required to get image dimensions.")
        print("Please install it using: pip install Pillow")
        return False

    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at {audio_path}")
        return False
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        return False

    try:
        img = Image.open(image_path)
        img_w, img_h = img.size
    except Exception as e:
        print(f"Error opening image with Pillow: {e}")
        return False

    target_aspect = 4 / 3
    img_aspect = img_w / img_h

    # Construct the ffmpeg video filter based on image aspect ratio
    if img_aspect < target_aspect:
        # Too vertical: crop top and bottom to target aspect ratio, then scale
        crop_h = int(img_w / target_aspect)
        y_offset = (img_h - crop_h) // 2
        vf = f"crop={img_w}:{crop_h}:0:{y_offset},scale={width}:{height}"
    else:
        # Horizontal or exact 4:3: scale to fit within 4:3 frame and pad with black bars
        vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"

    cmd = [
        'ffmpeg',
        '-y',  # Overwrite output file without asking
        '-loop', '1',  # Loop the image input
        '-i', image_path,  # Input 0: Image
        '-i', audio_path,  # Input 1: Audio
        '-map', '0:v',  # Map video from the image
        '-map', '1:a',  # Map audio from the mp3
        '-c:v', 'libx264',  # Video codec
        '-tune', 'stillimage',  # Optimize encoder for still images
        '-c:a', 'aac',  # Audio codec
        '-b:a', '192k',  # Audio bitrate
        '-pix_fmt', 'yuv420p',  # Pixel format for maximum player compatibility
        '-vf', vf,  # Apply our dynamic video filters
        '-shortest',  # Stop encoding when the shortest input stream ends (the audio)
        output_path
    ]

    print(f"Running ffmpeg command...")
    try:
        subprocess.run(cmd, check=True)
        print(f"Video successfully created: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running ffmpeg: {e}")
        return False
    except FileNotFoundError:
        print("Error: ffmpeg not found. Please install ffmpeg and ensure it is in your system PATH.")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python script.py <audio.mp3> <cover_image.jpg> <output_video.mp4>")
        sys.exit(1)

    audio_file = sys.argv[1]
    image_file = sys.argv[2]
    output_file = sys.argv[3]

    success = create_music_video(audio_file, image_file, output_file)
    sys.exit(0 if success else 1)