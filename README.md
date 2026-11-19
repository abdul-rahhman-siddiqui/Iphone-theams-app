# PhoneCam

Use your iPhone as a webcam on Windows over your private network (Wi-Fi/LAN). No iPhone app install needed — the phone uses Safari.

## Setup (Windows)
1. Install [Python 3.10+](https://python.org) (tick "Add to PATH").
2. For a system-wide virtual webcam (Zoom/Teams/OBS/etc.), install [OBS Studio](https://obsproject.com) once (it provides the virtual camera driver).
3. Double-click `run.bat` (installs deps on first run), or `run.bat --vcam` for the virtual webcam.
   `build.bat` creates a standalone `dist\PhoneCam.exe`.

## Use
1. PC and iPhone on the same Wi-Fi/LAN. Allow Python/PhoneCam through Windows Firewall (Private network) when prompted.
2. Scan the QR code / open the printed `https://…` URL in iPhone Safari. Accept the self-signed certificate warning (Show Details → visit website).
3. Allow camera, tap **Start**. Video shows in the preview window; with `--vcam` pick **OBS Virtual Camera** in your app.

Options: `--vcam --width 1920 --height 1080 --fps 30 --rotate 90 --mirror --port 8443 --no-preview`.
Preview keys: `q` quit, `m` mirror, `r` rotate.

## Security
Only private/LAN addresses are accepted, and a random token in the URL is required to stream. Traffic is TLS-encrypted (self-signed cert stored in `%USERPROFILE%\.phonecam`).

## Notes
Video is sent as JPEG frames over WebSocket (simple, low-latency on LAN; no audio). Keep the iPhone screen on while streaming (the page requests a wake lock).
