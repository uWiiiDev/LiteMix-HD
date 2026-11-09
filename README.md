# 🎬 LiteMix HD

**LiteMix HD** ist ein ressourcenschonender Live-Video-Mischer, Hardware-Recorder, Live-Streamer und Instant-Replay-Mischer für Linux (Wayland & X11), entwickelt in Python mit **PyQt6**, **GStreamer** und **FFmpeg VA-API**.

Speziell optimiert für kompakte Laptops (z. B. Intel Core i5 Dual-Core mit Intel HD Graphics VA-API `/dev/dri/renderD128` und 1536×864 Bildschirmen).

---

## ✨ Hauptfunktionen

- **Vorschau (`PREVIEW`) & Live (`PROGRAM`) Monitoring:**
  - Direkte Transportsteuerung (`▶`/`⏸`, `⏹`, Loop `🔁`, Auto-Return `↩`, Scrubber & Timecode) im Vorschaufenster und auf den Quellen-Kacheln.
  - Übergänge per **CUT**, **FADE** (einstellbare Dauer), manueller **T-Bar** und **FTB** (Fade to Black).
- **2 frei positionier- & skalierbare Overlays (`OV1` & `OV2`):**
  - Direkt im `PROGRAM`-Monitor per Maus verschiebbar, über 8 Anfasser skalierbar, per Mausrad zoombar und mit Rechtsklick-Layout-Presets (PiP, Vollbild, 16:9-Snap).
- **3 Broadcast-Bauchbinden-Templates (Lower Thirds):**
  - *Klassisch Broadcast*, *Modern Kompakt (Pill)* und *Breaking / Sport Banner* mit Live-Vorschau.
- **Manuelles Instant-Replay & Highlights in Zeitlupe (`h264_vaapi`):**
  - Jederzeit per **`⏺ REPLAY`** starten und stoppen.
  - Automatische Bereitstellung in **`⏪ Letztes Replay`** (pausiert im Vorschaufenster bei `00:00`, abspielbar in `0.25×`, `0.5×`, `0.75×`, `1.0×`).
  - Alle Replays einer Sitzung landen automatisch in der **`⭐ Highlights`**-Quelle (Einzelauswahl oder Playlist).
- **Hardware-beschleunigtes Recording & Live-Streaming (`h264_vaapi`):**
  - Lippensynchrones Audio/Video-Streaming zu **YouTube Live, Twitch, Custom RTMP/RTMPS, SRT und UDP**.
  - Lokale MP4-Aufnahme in `~/Videos` bei minimaler CPU-Last (~18 %).
- **Audio-Mixer mit Audio-Follow-Video (AFV) & Echtzeit-VU-Metern:**
  - Unterstützung für Mikrofone, System-/Desktop-Audio (PipeWire/PulseAudio) und Audio-Dateien (MP3/WAV/FLAC/OGG).
- **Frei belegbare Tastenkürzel (Hotkeys):**
  - 27 Aktionen frei per Tastendruck zuweisbar (`~/.config/litemix/shortcuts.json`).
- **Integrierte GitHub-Updatefunktion (`🔄`):**
  - Prüft direkt aus der Oberfläche heraus auf neue Versionen im GitHub-Repository [`uWiiiDev/LiteMix-HD`](https://github.com/uWiiiDev/LiteMix-HD), lädt Updates herunter und startet LiteMix HD auf Wunsch neu.

---

## 🚀 Starten

```bash
./run.sh
# oder direkt:
python3 main.py
```

## 🔄 Aktualisieren (Update)

Klicke unten in der Fußzeile von **LiteMix HD** einfach auf den **`🔄`**-Button (*„Auf GitHub nach Updates suchen“*), um das Projekt automatisch auf den neuesten Stand zu bringen.
