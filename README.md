# ytdl-archiver

A script for downloading YouTube **playlists** with thumbnails and generate a metadata `.nfo` file for media servers.
Ideal for Jellyfin / Emby users + archivists.

Based on [ytdl-nfo](https://github.com/htmlgxn/ytdl-nfo/)

## Features
- Allows you to set the path to your YouTube archive.
- Custom name each folder within your archive (per playlist), the rest is automated.
- Downloads separate .mp4, .nfo, and .jpg file for media server readability.
- Creates an .archive.txt file in each playlist folder to allow rerun and refresh content efficiently

## "Installation"
Make sure th
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
python -m venv venv
source venv/bin/activate/
pip install --upgrade pip
pip install yt-dlp
```

## Usage
- First, edit your `playlists.json` file. Replace the sample id and folder-name.
Folder name would be a YouTube channel name if downloading an entire channel's uploads for instance.
```json
{
    "id": "UUxxxxxxxxxxxxxxxxxxxxxx",
    "folder-name": "Folder Name"
},
{
    "id": "...",
    "folder-name": "..."
}
```

- Still in the `(venv)`, run `python archive.py` to begin archiving playlists to the default folder. See optional arguments below.

## Arguments
```bash
-h, --help          Show help message and exit
-j [JSON], --json [JSON]
                    Path to JSON file containing playlist IDs and names.
                    Defaults to ./playlists.json
-d [DIR], --dir [DIR]
                    Path to archive directory.
                    Defaults to $HOME/Videos/YouTube
```

## Optional Settings
- The program sleeps 10 seconds between each video and 30 seconds between each playlist by default, to avoid YouTube blocking requests. These are editable at lines `133` and `167`:
```python
time.sleep(10) # Delay between videos to avoid triggering YouTube login requests
time.sleep(30)  # Extra delay between playlists to avoid triggering YouTube login requests
```

- Of course, all `ydl_opts` are fully editable:
```python
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
```

- More to come shortly!