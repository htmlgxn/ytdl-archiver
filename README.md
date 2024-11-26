# ytdl-archiver

A script for downloading YouTube **playlists** with thumbnails and generate a metadata `.nfo` file for media servers.
Ideal for Jellyfin / Emby users + archivists.

Based on [ytdl-nfo](https://github.com/htmlgxn/ytdl-nfo/)

## Features
- Allows you to set the path to your YouTube archive.
- Custom name each folder within your archive (per playlist), the rest is automated.
- Downloads separate .mp4, .nfo, and .jpg file for media server readability.

## "Installation"
"Install" (make sure to continue to usage):
```bash
git clone https://github.com/htmlgxn/ytdl-archiver.git
cd ytdl-archiver
python -m venv venv
source venv/bin/activate/
pip install --upgrade pip
pip install yt-dlp
```

## Usage
First, edit `playlists.json`. Replace the sample id and folder-name.
Folder name would be a YouTube channel name if downloading an entire channel's uploads for instance.
```json
[
    {
      "id": "UUxxxxxxxxxxxxxxxxxxxxxx",
      "folder-name": "Folder Name"
    },
    {
      "id": "..."
      "folder-name": "..."
    }
]
```

Second, edit `archive.py`. On line `156`, set the path to your base YouTube archive folder.
By default, it is set to `~/Videos/YouTube`

Still in the `(venv)`, run `python archive.py` to begin archiving playlists

## Optional Settings
- Optional arg: `python archive.py json_file /path/to/different/json` to specfify a different json file (good for tests)

- The program sleeps 10 seconds between each video and 30 seconds between each playlist by default, to avoid YouTube blocking requests. These are editable at lines `133` and `167`

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

- It's not a huge program, for now, so take a look!