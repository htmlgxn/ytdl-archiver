# Setup as a Linux service (systemctl)

## Instructions
This is the simplest way to go about it.

- Copy the default .service file to your system:
```bash
sudo cp optional/ytdl-archiver.service /etc/systemd/system/ytdl-archiver.service
```
Optionally you can change the name of the .service file on copy

-Edit the .service file:
`nano /etc/systemd/system/ytdl-archiver.service`

```ini
[Service]
# Change to your python binary
# Change to your FULL path to archive.py
# Optional: Add arguments with full paths
# Example: -j /home/username/ytdl-archiver/playlists_alt.json 
# Example: -d /full/path/to/archive
ExecStart=/usr/bin/python /home/username/ytdl-archiver/archive.py

# Change to your FULL path to the script directory (archive.py location)
WorkingDirectory=/home/username/ytdl-archiver

# Change these to your system username
User=your_username
Group=your_username
```

- Run the following commands:
```bash
sudo cp optional/ytdl-archiver.service /
sudo systemctl daemon-reload
sudo systemctl enable ytdl-archiver.service
sudo systemctl start ytdl-archiver.service
```
## Maintenance
-To stop the service:
```bash 
sudo systemctl stop ytdl-archiver.service
```

- To disable the service from startup:
```bash
sudo systemctl disable ytdl-archiver.service
```

- To check the status of the service:
```bash
sudo systemctl status ytdl-archiver.service
```

- To view the logs:
```bash
journalctl -u ytdl-archiver.service
```
