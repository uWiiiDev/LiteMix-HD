# 🎬 LiteMix HD

**LiteMix HD** is a lightweight, hardware-accelerated live video switcher, recorder, live streamer, instant-replay engine, and tablet web remote controller for Linux (Wayland & X11), built in Python with **PyQt6**, **GStreamer**, and **FFmpeg VA-API**.

Specifically engineered for compact laptops and low-power CPUs (e.g. Intel Core i5 Dual-Core with Intel HD Graphics VA-API `/dev/dri/renderD128` and 1536×864 screens).

---

## ✨ Key Features

- **Bilingual User Interface & In-App Help (`🌐 DE/EN` & `❓`):**
  - Live one-click language switching between **German (`DE`)** and **English (`EN`)** for both the desktop UI, the Web Remote UI, and the comprehensive built-in Help & Function Guide (`❓` / `F12`).
- **Preview (`PREVIEW`) & Live (`PROGRAM`) Monitoring + External Output (`🖥️`):**
  - Direct media transport bar (`▶`/`⏸`, `⏹`, Loop `🔁`, Auto-Return `↩`, Scrubber & Timecode) inside the `PREVIEW` monitor and on each playable input tile.
  - Broadcast transitions via **CUT**, **FADE** (configurable duration in ms), manual **T-Bar**, and **FTB** (Fade to Black).
  - **External `PROGRAM` Output (`🖥️` / `F11`):** Output the clean live Program feed either as a separate resizable 16:9 window (ideal for Zoom/Teams/Discord screen sharing) or borderless fullscreen on any connected monitor, projector, or HDMI output.
- **2 Freely Positionable & Resizable Overlays (`OV1` & `OV2`):**
  - Drag directly inside the `PROGRAM` monitor with the mouse, resize via 8 corner/edge handles, zoom with the mouse wheel, or use right-click layout presets (PiP corners, fullscreen, 16:9 snap).
- **3 Broadcast Lower Third Templates & Multi-Line Text / Slide / Scroller Editor (`📝`):**
  - **Lower Thirds:** *Classic Broadcast*, *Modern Compact (Pill)*, and *Breaking / Sports Banner* with live preview and instant editing (`✎`).
  - **Multi-Line Text Slide & Vertical Scroller (`TextSlideInput`):** Rich multi-line text editor supporting multiple slides (separated by `---`, switchable via `⏮` / `⏭` on the tile), 5 background styles (alpha overlay box, 100% transparent floating text, or 3 fullscreen studio slates), 5 color themes, and smooth vertical Auto-Scroll / Teleprompter / Credits mode (`📜`).
- **Manual Instant Replay & Slow-Motion Highlights (`h264_vaapi`):**
  - Start and stop replay recording at any time via **`⏺ REPLAY`** (`Ctrl+R`).
  - Automatically loads into **`⏪ Latest Replay`** (paused in `PREVIEW` at `00:00`, playable at `0.25×`, `0.5×`, `0.75×`, `1.0×`).
  - Every recorded replay of a session is automatically added to the **`⭐ Highlights`** source (single clip or sequential playlist).
- **iPad / Tablet / Browser Web Remote Control (`📱`):**
  - Built-in multi-threaded HTTP remote server (`port 8088`) protected by a random security token and scannable **QR code**.
  - Features live Preview/Program monitors, transition deck, source grid (`PRV`, `CUT`, `OV1`, `OV2`), media transport (`▶/⏸`, `⏹`, `🔁`, `↩`, slow-motion speed), audio mixer, and live lower-third text editor.
- **Hardware-Accelerated Recording & Live Streaming (`h264_vaapi`):**
  - Lip-synced audio/video streaming to **YouTube Live, Twitch, Custom RTMP/RTMPS, SRT, and UDP**.
  - Local MP4 recording to `~/Videos` with minimal CPU usage (~18 %).
- **Audio Mixer with Audio-Follow-Video (AFV) & Real-Time VU Meters:**
  - Supports microphones, system/desktop audio loopback (PipeWire/PulseAudio), and audio files (MP3/WAV/FLAC/OGG).
- **Customizable Keyboard Shortcuts (`⌨️`):**
  - 28 actions freely assignable via keypress (`~/.config/litemix/shortcuts.json`).
- **Built-in GitHub Auto-Updater (`🔄`):**
  - Checks [`uWiiiDev/LiteMix-HD`](https://github.com/uWiiiDev/LiteMix-HD) directly from the UI, downloads updates, and restarts LiteMix HD on demand.

---

## 🚀 Getting Started

```bash
./run.sh
# or directly:
python3 main.py
```

## 🔄 Updating

Click the **`🔄`** button in the bottom footer bar of **LiteMix HD** (*"Check GitHub for updates"*) to automatically update the application to the latest release.
