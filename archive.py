import os
import re
from pathlib import Path
from yt_dlp import YoutubeDL
import argparse
import json
import time

def sanitize_filename(name):
    # Convert to lowercase and replace spaces with dashes
    name = name.lower().replace(' ', '-')
    # Remove or replace unwanted characters
    name = re.sub(r'[.\'()<>"|?*]|[^-\w]', '', name)
    return name

def get_metadata(video_url):
    ydl_opts = {}
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(video_url, download=False)
            return info_dict
        except Exception as e:
            print(f"Error occurred while fetching metadata for {video_url}: {e}")
            return None

def download_video(video_url, output_template, output_directory, filename):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4',  # Force .mp4 container
        'merge_output_format': 'mp4',  # Ensure output is .mp4
        'writesubtitles': True,        # Download subtitles
        'subtitlesformat': 'vtt',      # Preferred subtitle format for download
        'convertsubtitles': 'srt',     # Convert subtitles to .srt
        'subtitleslangs': ['all'],     # All languages
        'writethumbnail': True,        # Download thumbnail
        'postprocessors': [
            {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'},  # Convert thumbnail to .jpg
        ],
        'outtmpl': {
            'default': output_template,
            'subtitle': str(output_directory / f"{filename}.%(subtitle_lang)s.%(ext)s"), # Save subtitles with the same filename
            'thumbnail': str(output_directory / f"{filename}.%(ext)s"),  # Save thumbnail with the same filename
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        },
    }
    with YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([video_url])
            print(f"Downloaded: {output_template}")
        except Exception as e:
            print(f"Error occurred while downloading video {video_url}: {e}")

def create_nfo_file(metadata, nfo_path):
    title = metadata.get("title", "Unknown Title")
    channel = metadata.get("uploader", "Unknown Channel")
    upload_date = metadata.get("upload_date", "")
    formatted_date = (
        f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
        if upload_date
        else "Unknown Date"
    )
    upload_year = (
        f"{upload_date[:4]}"
        if upload_date
        else "Unknown Year"
    )
    description = metadata.get("description", "Unknown Description")
    video_id = metadata.get("id", "Unknown ID")
    nfo_content = f"""<episodedetails>
  <title>{title}</title>
  <studio>{channel}</studio>
  <releasedate>{formatted_date}</releasedate>
  <year>{upload_year}</year>
  <plot>{description}</plot>
  <id>{video_id}</id>
</episodedetails>
"""
    try:
        with open(nfo_path, "w", encoding="utf-8") as nfo_file:
            nfo_file.write(nfo_content)
        print(f".nfo file created: {nfo_path.name}")
    except IOError as e:
        print(f"Error writing .nfo file {nfo_path}: {e}")

def download_video_and_create_nfo(video_url, output_directory=None):
    metadata = get_metadata(video_url)
    if metadata is None:
        return

    title = metadata.get("title", "unknown-title")
    channel = metadata.get("uploader", "unknown-channel")

    safe_title = sanitize_filename(title)
    safe_channel = sanitize_filename(channel)
    filename = f"{safe_title}_{safe_channel}"

    # If no output directory is provided, create a folder with the filename in the working directory
    if output_directory is None:
        output_directory = Path.cwd() / filename
    else:
        output_directory = Path(output_directory)

    output_directory.mkdir(parents=True, exist_ok=True)

    # Output template with dynamic extension
    output_template = str(output_directory / f"{filename}.%(ext)s")

    download_video(video_url, output_template, output_directory, filename)

    # Assuming the video file has .mp4 extension
    video_file = output_directory / f"{filename}.mp4"
    if video_file.exists():
        nfo_path = video_file.with_suffix('.nfo')
        create_nfo_file(metadata, nfo_path)
    else:
        print(f"Downloaded video file not found for {video_url}.")

def download_playlist(playlist_id, playlist_name, base_directory):
    # Create the output directory for the playlist
    output_directory = Path(base_directory) / playlist_name
    output_directory.mkdir(parents=True, exist_ok=True)

    # Define the archive file path for the playlist
    archive_file = output_directory / ".archive.txt"

    # Ensure the archive file exists
    if not archive_file.exists():
        archive_file.touch()  # Create an empty file

    # Options for extracting the playlist info
    ydl_opts = {
        'extract_flat': True,  # Extract metadata without downloading
        'quiet': True,         # Suppress non-critical output
    }
    playlist_url = f'https://www.youtube.com/playlist?list={playlist_id}'

    with YoutubeDL(ydl_opts) as ydl:
        try:
            # Extract the playlist metadata
            playlist_info = ydl.extract_info(playlist_url, download=False)

            if 'entries' in playlist_info:
                for entry in playlist_info['entries']:
                    video_url = f"https://www.youtube.com/watch?v={entry['id']}"

                    # Skip if the video is already in the archive file
                    if archive_file.exists():
                        with open(archive_file, 'r') as f:
                            downloaded_videos = f.read().splitlines()
                        if entry['id'] in downloaded_videos:
                            print(f"Skipping already downloaded video: {entry['id']}")
                            continue

                    # Call the original function to download and create .nfo
                    download_video_and_create_nfo(video_url, output_directory)

                    # Add the video ID to the archive file after successful download
                    with open(archive_file, 'a') as f:
                        f.write(entry['id'] + '\n')

                    # Delay to avoid rate limits
                    time.sleep(10)
        except Exception as e:
            print(f"Error occurred while downloading playlist {playlist_name}: {e}")

def main():
    # Set the default directory
    default_directory = str(Path.home() / "Videos" / "YouTube")

    # Set args
    parser = argparse.ArgumentParser(description='Download YouTube playlists and save them in organized directories.')
    parser.add_argument('-j', '--json', nargs='?', default='playlists.json', help='Path to JSON file containing playlist IDs and names. Defaults to ./playlists.json')
    parser.add_argument('-d', '--dir', nargs='?', default=default_directory, help='Path to archive directory. Defaults to $HOME/Videos/YouTube')
    args = parser.parse_args()

    # Read playlists JSON
    if not os.path.exists(args.json):
        print(f"JSON file not found: {args.json}")
        return

    with open(args.json, 'r') as f:
        try:
            playlists = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error reading JSON file: {e}")
            return

    # Read archive directory
    base_directory = Path(args.dir)
    base_directory.mkdir(parents=True, exist_ok=True)

    # Download playlists
    for playlist in playlists:
        playlist_id = playlist.get('id')
        playlist_name = playlist.get('folder-name')
        if not playlist_id or not playlist_name:
            print("Invalid playlist entry in JSON. Skipping.")
            continue

        download_playlist(playlist_id, playlist_name, base_directory)
        time.sleep(30)  # Extra delay between playlists to avoid triggering YouTube login requests

if __name__ == '__main__':
    main()
