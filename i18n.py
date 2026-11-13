import os
import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
)


_CURRENT_LANG = "de"
_LANG_LOADED = False


def _ui_config_path() -> str:
    """Return the path to the persistent UI configuration file."""
    cfg_dir = os.path.expanduser("~/.config/litemix")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "ui_config.json")


def _ensure_loaded():
    """Load the saved UI language from disk on first access."""
    global _CURRENT_LANG, _LANG_LOADED
    if _LANG_LOADED:
        return
    _LANG_LOADED = True
    p = _ui_config_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            lang = str(data.get("lang", "de")).strip().lower()
            if lang in ("de", "en"):
                _CURRENT_LANG = lang
        except Exception:
            pass


def get_lang() -> str:
    """Return the active UI language code ('de' or 'en')."""
    _ensure_loaded()
    return _CURRENT_LANG


def set_lang(lang: str) -> str:
    """Set and persist the active UI language code ('de' or 'en')."""
    global _CURRENT_LANG, _LANG_LOADED
    _LANG_LOADED = True
    _CURRENT_LANG = "en" if str(lang).strip().lower() == "en" else "de"
    try:
        with open(_ui_config_path(), "w", encoding="utf-8") as f:
            json.dump({"lang": _CURRENT_LANG}, f, indent=2)
    except Exception:
        pass
    return _CURRENT_LANG


def toggle_lang() -> str:
    """Toggle between German ('de') and English ('en') and return the new language code."""
    return set_lang("en" if get_lang() == "de" else "de")


def tr(de_text: str, en_text: str) -> str:
    """Return de_text when language is German ('de'), or en_text when English ('en')."""
    return en_text if get_lang() == "en" else de_text


HELP_HTML_DE = """
<style>
  body { background-color: #141821; color: #e4e9f2; font-family: 'Sans Serif'; font-size: 12px; line-height: 1.45; }
  h2 { color: #38b6ff; margin-top: 14px; margin-bottom: 6px; border-bottom: 1px solid #2b3548; padding-bottom: 4px; }
  h3 { color: #20d660; margin-top: 10px; margin-bottom: 4px; }
  .box { background-color: #1c2230; border: 1px solid #2e384d; border-radius: 6px; padding: 8px 12px; margin-bottom: 8px; }
  .key { background-color: #283246; border: 1px solid #485878; border-radius: 4px; padding: 1px 6px; font-weight: bold; color: #ffffff; font-family: monospace; }
  ul { margin-top: 4px; margin-bottom: 6px; padding-left: 20px; }
  li { margin-bottom: 4px; }
</style>

<h2>🎬 1. Vorschau (PREVIEW) &amp; Live-Ausgang (PROGRAM)</h2>
<div class="box">
  <ul>
    <li><b>PREVIEW (Grün, links):</b> Hier bereiten Sie die nächste Quelle vor, ohne dass die Zuschauer sie schon sehen.
      Ist ein abspielbares Medium (Video, Audio, Replay oder Highlight) geladen, erscheint unten im Vorschaufenster eine <b>interaktive Transportleiste</b>:
      <ul>
        <li><span class="key">▶</span> / <span class="key">⏸</span> Startet oder pausiert die Wiedergabe direkt in der Vorschau.</li>
        <li><span class="key">⏹</span> Stoppt die Wiedergabe und spult auf <span class="key">00:00</span> zurück.</li>
        <li><span class="key">🔁</span> <b>Loop (Endlosschleife):</b> Blau hervorgehoben = Clip wiederholt sich endlos; Aus = Clip stoppt am Ende.</li>
        <li><span class="key">↩</span> <b>Auto-Zurück zur Vorschau:</b> Grün hervorgehoben = Sobald das Video/Audio im Live-Programm zu Ende ist, schaltet LiteMix automatisch zurück auf die vorherige Quelle und legt den beendeten Clip wieder in die Vorschau.</li>
      </ul>
    </li>
    <li><b>PROGRAM (Rot, rechts):</b> Das Live-Bild, das aufgezeichnet (<span class="key">🔴</span>) und gestreamt (<span class="key">📡</span>) wird.</li>
  </ul>
</div>

<h2>🔀 2. Übergänge, Schwarzblende &amp; Instant-Replay (Mittelspalte)</h2>
<div class="box">
  <ul>
    <li><span class="key">CUT</span> – Harter, sofortiger Schnitt: Tauscht <b>PREVIEW</b> und <b>PROGRAM</b> sofort aus.</li>
    <li><span class="key">FADE</span> – Weiche Überblendung zwischen Vorschau und Programm (Dauer in Millisekunden darunter im Feld <b>Dauer</b> einstellbar, Standard: <span class="key">600 ms</span>).</li>
    <li><span class="key">FTB</span> – <b>Fade to Black (Schwarzblende):</b> Blendet den Live-Ausgang komplett auf Schwarz (und schaltet den Programmton stumm), bis erneut auf <span class="key">FTB</span> geklickt wird.</li>
    <li><b>T-Bar (Schieberegler):</b> Manuelle Überblendung von 0 % bis 100 % per Maus.</li>
    <li><span class="key">⏺ REPLAY</span> – <b>Manuelle Replay-Aufnahme:</b>
      <ul>
        <li>1. Klick startet die Hardware-Aufzeichnung des laufenden Programms.</li>
        <li>2. Klick (<span class="key">■ 00:xx</span>) beendet die Aufzeichnung, legt den Clip automatisch in die Quelle <b>⏪ Letztes Replay</b>, lädt ihn <b>pausiert bei 00:00</b> ins Vorschaufenster und fügt ihn zu <b>⭐ Highlights</b> hinzu.</li>
        <li>Mit <span class="key">⏱ Standard-Tempo</span> wählen Sie das Standard-Zeitlupentempo (<span class="key">0.25×</span>, <span class="key">0.5×</span>, <span class="key">0.75×</span>, <span class="key">1.0×</span>).</li>
      </ul>
    </li>
  </ul>
</div>

<h2>🖼️ 3. Overlays (OV1 &amp; OV2) per Maus steuern</h2>
<div class="box">
  <ul>
    <li>Jede Video-, Kamera-, Bild- oder Bauchbinden-Quelle kann über <span class="key">OV1</span> (Blau, z. B. Bild-in-Bild) oder <span class="key">OV2</span> (Violett, z. B. Bauchbinde/Vollbild-Grafik) über das Live-Bild gelegt werden.</li>
    <li><b>Direkt im PROGRAM-Monitor mit der Maus:</b>
      <ul>
        <li><b>Ziehen:</b> Overlay frei im Bild verschieben (mit magnetischem Einrasten an den Rändern).</li>
        <li><b>8 Anfasser (Ecken &amp; Kanten):</b> Größe frei ziehen.</li>
        <li><b>Mausrad:</b> Overlay stufenlos vergrößern/verkleinern.</li>
        <li><b>Rechtsklick / Doppelklick:</b> Kontextmenü mit Schnell-Layouts (Unten rechts, Unten links, Oben, Vollbild, 16:9-Anpassung, Farbrahmen ein/aus).</li>
      </ul>
    </li>
  </ul>
</div>

<h2>🎛️ 4. Buttons auf den Quellen-Kacheln (Inputs)</h2>
<div class="box">
  <ul>
    <li><span class="key">PRV</span> – Lädt diese Quelle in das linke Vorschaufenster (Grüner Rahmen).</li>
    <li><span class="key">CUT</span> – Schaltet diese Quelle sofort live in das Programmfenster (Roter Rahmen).</li>
    <li><span class="key">OV1</span> / <span class="key">OV2</span> – Blendet diese Quelle als Overlay 1 oder Overlay 2 ein/aus.</li>
    <li><span class="key">✎</span> (bei Bauchbinden &amp; Texttafeln) – Öffnet den Editor (für Bauchbinden mit 3 Broadcast-Templates bzw. den <b>mehrzeiligen Text- &amp; Folien-Editor</b> mit 5 Hintergrund-Stilen, Farbschemata, Folientrennern <span class="key">---</span> und Lauftext-Modus).</li>
    <li><span class="key">⏮</span> / <span class="key">📄 #1/2 ▾</span> / <span class="key">⏭</span> / <span class="key">📜</span> (bei Texttafeln) – Blättert zwischen mehreren Textfolien (getrennt durch <span class="key">---</span>) oder schaltet den vertikalen Lauftext / Teleprompter-Modus (<span class="key">📜</span>) ein/aus.</li>
    <li><span class="key">⇄</span> (bei Kameras) – Spiegelt das Kamerabild horizontal.</li>
    <li><span class="key">🌐</span> (bei Browser-Quellen) – Öffnet das interaktive Browserfenster zum Bedienen/Scrollen.</li>
    <li><span class="key">▶/⏸</span>, <span class="key">⏹</span>, <span class="key">🔁</span>, <span class="key">↩</span> – Transportsteuerung, Endlosschleife (<span class="key">🔁</span>) und Auto-Rücksprung zur Vorschau (<span class="key">↩</span>).</li>
    <li><span class="key">🔊</span> / <span class="key">🔇</span> + Regler – Individuelle Lautstärke (0–150 %) und Stummschaltung pro Quelle.</li>
    <li><span class="key">✕</span> (oben rechts auf der Kachel) – Entfernt die Quelle aus dem Set.</li>
  </ul>
</div>

<h2>🧭 5. Untere Funktionsleiste (Footer-Icons)</h2>
<div class="box">
  <ul>
    <li><span class="key">➕</span> – <b>Quelle hinzufügen:</b> Kamera, Video-Datei, Audio-Datei, Bild/Logo, Bauchbinde, Bildschirm/Fenster, Browser, Mikrofon, System-Audio, Letztes Replay, Highlights, Testbild.</li>
    <li><span class="key">💾</span> – <b>Quellen-Set verwalten:</b> Komplettes Set speichern, laden oder auf Standard zurücksetzen.</li>
    <li><span class="key">⌨️</span> – <b>Tastenkürzel (Hotkeys):</b> Alle Regie-Funktionen frei per Tastendruck belegen.</li>
    <li><span class="key">📱</span> – <b>Web-Fernsteuerung (iPad / Tablet / Browser):</b> Zeigt den <b>QR-Code</b>, den Direkt-Link und das Sicherheits-Token an, um LiteMix HD drahtlos vom iPad aus zu bedienen.</li>
    <li><span class="key">🖥️</span> – <b>Externe PROGRAM-Ausgabe (Fenster / Monitor, <span class="key">F11</span>):</b> Gibt das reine Live-Bild (<span class="key">PROGRAM</span>) entweder als <b>eigenes 16:9-Fenster</b> (z.&nbsp;B. für Zoom/Teams/Discord) oder <b>randlos im Vollbild auf einem angeschlossenen Monitor/Beamer/HDMI</b> aus (Doppelklick: Fenster ⇄ Vollbild, <span class="key">Esc</span>: Schließen).</li>
    <li><span class="key">🔄</span> – <b>GitHub-Update:</b> Prüft auf GitHub (<span class="key">uWiiiDev/LiteMix-HD</span>), ob eine neue Version vorliegt, und aktualisiert das Projekt automatisch.</li>
    <li><span class="key">🌐 DE/EN</span> – <b>Sprache wechseln:</b> Schaltet Oberfläche und Hilfe live zwischen Deutsch und Englisch um.</li>
    <li><span class="key">❓</span> – <b>Hilfe &amp; Handbuch:</b> Öffnet diese Funktionsübersicht.</li>
    <li><span class="key">📡</span> / <span class="key">⏹📡</span> – <b>Live-Stream starten / stoppen</b> (RTMP, YouTube, Twitch, SRT, UDP).</li>
    <li><span class="key">⚙️</span> – <b>Stream- &amp; Video-Einstellungen:</b> Plattform, Server-URL, Stream-Schlüssel, Qualitätsfaktor (QP) und Bildrate (FPS).</li>
    <li><span class="key">🔴</span> / <span class="key">⏹🔴</span> – <b>Lokale Aufnahme starten / stoppen:</b> Speichert das Live-Programm als MP4-Video in <span class="key">~/Videos</span>.</li>
  </ul>
</div>
"""


HELP_HTML_EN = """
<style>
  body { background-color: #141821; color: #e4e9f2; font-family: 'Sans Serif'; font-size: 12px; line-height: 1.45; }
  h2 { color: #38b6ff; margin-top: 14px; margin-bottom: 6px; border-bottom: 1px solid #2b3548; padding-bottom: 4px; }
  h3 { color: #20d660; margin-top: 10px; margin-bottom: 4px; }
  .box { background-color: #1c2230; border: 1px solid #2e384d; border-radius: 6px; padding: 8px 12px; margin-bottom: 8px; }
  .key { background-color: #283246; border: 1px solid #485878; border-radius: 4px; padding: 1px 6px; font-weight: bold; color: #ffffff; font-family: monospace; }
  ul { margin-top: 4px; margin-bottom: 6px; padding-left: 20px; }
  li { margin-bottom: 4px; }
</style>

<h2>🎬 1. Preview (PREVIEW) &amp; Live Output (PROGRAM)</h2>
<div class="box">
  <ul>
    <li><b>PREVIEW (Green, left):</b> Prepare and inspect your next source before taking it live.
      When a playable source (Video, Audio, Replay, or Highlights) is loaded in Preview, an <b>interactive transport bar</b> appears at the bottom:
      <ul>
        <li><span class="key">▶</span> / <span class="key">⏸</span> Start or pause playback directly in Preview.</li>
        <li><span class="key">⏹</span> Stop playback and rewind to <span class="key">00:00</span>.</li>
        <li><span class="key">🔁</span> <b>Loop:</b> Highlighted in blue = clip repeats endlessly; Off = clip stops cleanly at the end.</li>
        <li><span class="key">↩</span> <b>Auto-Return to Preview:</b> Highlighted in green = when the clip finishes playing in Live Program, LiteMix automatically cuts back to the previous source and returns the finished clip to Preview.</li>
      </ul>
    </li>
    <li><b>PROGRAM (Red, right):</b> The active live broadcast output sent to the recorder (<span class="key">🔴</span>) and live stream (<span class="key">📡</span>).</li>
  </ul>
</div>

<h2>🔀 2. Transitions, Fade-to-Black &amp; Instant Replay (Center Column)</h2>
<div class="box">
  <ul>
    <li><span class="key">CUT</span> – Instant hard cut swapping <b>PREVIEW</b> and <b>PROGRAM</b>.</li>
    <li><span class="key">FADE</span> – Smooth crossfade transition between Preview and Program (duration in ms is configurable in the spinner below, default: <span class="key">600 ms</span>).</li>
    <li><span class="key">FTB</span> – <b>Fade to Black:</b> Fades the live Program output to black (and mutes Program video audio) until clicked again.</li>
    <li><b>T-Bar Slider:</b> Manual transition fader from 0% to 100%.</li>
    <li><span class="key">⏺ REPLAY</span> – <b>Manual Instant Replay Recorder:</b>
      <ul>
        <li>1st click starts hardware-accelerated recording of the live Program output.</li>
        <li>2nd click (<span class="key">■ 00:xx</span>) stops recording, loads the clip into <b>⏪ Last Replay</b>, places it <b>paused at 00:00</b> into the Preview monitor, and appends it to <b>⭐ Highlights</b>.</li>
        <li>Use <span class="key">⏱ Default Speed</span> to select the slow-motion playback rate (<span class="key">0.25×</span>, <span class="key">0.5×</span>, <span class="key">0.75×</span>, <span class="key">1.0×</span>).</li>
      </ul>
    </li>
  </ul>
</div>

<h2>🖼️ 3. Interactive Mouse Overlays (OV1 &amp; OV2)</h2>
<div class="box">
  <ul>
    <li>Any video, camera, image, or lower-third source can be layered over the live Program via <span class="key">OV1</span> (Blue, e.g., Picture-in-Picture) or <span class="key">OV2</span> (Purple, e.g., Lower Third / Fullscreen graphic).</li>
    <li><b>Direct Mouse Control inside the PROGRAM Monitor:</b>
      <ul>
        <li><b>Drag:</b> Move the overlay freely (with edge snapping).</li>
        <li><b>8 Handles (Corners &amp; Edges):</b> Resize the overlay interactively.</li>
        <li><b>Mouse Wheel:</b> Scale the overlay smoothly.</li>
        <li><b>Right-Click / Double-Click:</b> Context menu with layout presets (Bottom-Right, Bottom-Left, Top, Fullscreen, 16:9 aspect snap, colored border on/off).</li>
      </ul>
    </li>
  </ul>
</div>

<h2>🎛️ 4. Input Tile Buttons</h2>
<div class="box">
  <ul>
    <li><span class="key">PRV</span> – Load this source into the left Preview monitor (Green border).</li>
    <li><span class="key">CUT</span> – Cut this source immediately to the live Program monitor (Red border).</li>
    <li><span class="key">OV1</span> / <span class="key">OV2</span> – Toggle this source on Overlay channel 1 or 2.</li>
    <li><span class="key">✎</span> (Lower Thirds &amp; Text Slides) – Opens the editor (Lower Third editor with 3 broadcast templates, or the <b>Multi-Line Text &amp; Slide Editor</b> with 5 background styles, color themes, slide breaks <span class="key">---</span>, and vertical scroller).</li>
    <li><span class="key">⏮</span> / <span class="key">📄 #1/2 ▾</span> / <span class="key">⏭</span> / <span class="key">📜</span> (Text Slides) – Flip between multiple text slides (separated by <span class="key">---</span>) or toggle the vertical Auto-Scroll / Teleprompter mode (<span class="key">📜</span>).</li>
    <li><span class="key">⇄</span> (Cameras) – Flip camera horizontally (mirror).</li>
    <li><span class="key">🌐</span> (Web Browser) – Open the interactive browser window to navigate or scroll.</li>
    <li><span class="key">▶/⏸</span>, <span class="key">⏹</span>, <span class="key">🔁</span>, <span class="key">↩</span> – Transport controls, Loop (<span class="key">🔁</span>), and Auto-Return to Preview (<span class="key">↩</span>).</li>
    <li><span class="key">🔊</span> / <span class="key">🔇</span> + Slider – Per-source volume (0–150%) and mute.</li>
    <li><span class="key">✕</span> (top-right corner of tile) – Remove source from the set.</li>
  </ul>
</div>

<h2>🧭 5. Bottom Footer Icon Bar</h2>
<div class="box">
  <ul>
    <li><span class="key">➕</span> – <b>Add Source:</b> Camera, Video File, Audio File, Image/Logo, Lower Third, Screen/Window (Wayland), Web Browser, Microphone, System Audio, Last Replay, Highlights, Test Pattern.</li>
    <li><span class="key">💾</span> – <b>Manage Set:</b> Save, load, or reset source sets.</li>
    <li><span class="key">⌨️</span> – <b>Keyboard Shortcuts:</b> Freely assign hotkeys to all switcher actions.</li>
    <li><span class="key">📱</span> – <b>Web Remote Control (iPad / Tablet / Browser):</b> Displays the <b>QR code</b>, direct link, and security token to control LiteMix HD wirelessly from an iPad or browser.</li>
    <li><span class="key">🖥️</span> – <b>External PROGRAM Output (Window / Monitor, <span class="key">F11</span>):</b> Outputs the clean live <span class="key">PROGRAM</span> feed either as a <b>separate 16:9 window</b> (e.g. for Zoom/Teams/Discord screen sharing) or <b>borderless fullscreen on any connected monitor/projector/HDMI</b> (Double-click: Window ⇄ Fullscreen, <span class="key">Esc</span>: Close).</li>
    <li><span class="key">🔄</span> – <b>GitHub Updater:</b> Checks GitHub (<span class="key">uWiiiDev/LiteMix-HD</span>) for newer versions and updates the application automatically.</li>
    <li><span class="key">🌐 DE/EN</span> – <b>Switch Language:</b> Toggles the UI and Help language live between German and English.</li>
    <li><span class="key">❓</span> – <b>Help &amp; Manual:</b> Opens this comprehensive reference guide.</li>
    <li><span class="key">📡</span> / <span class="key">⏹📡</span> – <b>Start / Stop Live Stream</b> (RTMP, YouTube, Twitch, SRT, UDP).</li>
    <li><span class="key">⚙️</span> – <b>Stream &amp; Video Settings:</b> Platform, Server URL, Stream Key, Quality (QP), and Frame Rate (FPS).</li>
    <li><span class="key">🔴</span> / <span class="key">⏹🔴</span> – <b>Start / Stop Local Recording:</b> Records live Program output as an MP4 file in <span class="key">~/Videos</span>.</li>
  </ul>
</div>
"""


class HelpDialog(QDialog):
    """Bilingual (German / English) help and reference dialog explaining all LiteMix HD controls."""

    def __init__(self, parent=None, on_language_changed=None):
        super().__init__(parent)
        self.on_language_changed = on_language_changed
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        self.lbl_header = QLabel()
        self.lbl_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #e4e9f2;")
        top_row.addWidget(self.lbl_header, 1)

        self.btn_switch_lang = QPushButton()
        self.btn_switch_lang.setObjectName("FooterIconBtn")
        self.btn_switch_lang.clicked.connect(self._on_toggle_lang)
        top_row.addWidget(self.btn_switch_lang)
        root.addLayout(top_row)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet(
            "background-color: #141821; border: 1px solid #2e384d; border-radius: 6px; padding: 6px;"
        )
        root.addWidget(self.browser, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("AddInputBtn")
        self.btn_close.clicked.connect(self.accept)
        foot.addWidget(self.btn_close)
        root.addLayout(foot)

        self._refresh_content()

    def _on_toggle_lang(self):
        toggle_lang()
        if callable(self.on_language_changed):
            self.on_language_changed()
        self._refresh_content()

    def _refresh_content(self):
        is_en = (get_lang() == "en")
        self.setWindowTitle(
            "❓ LiteMix HD – Help & Reference Guide" if is_en else "❓ LiteMix HD – Hilfe & Funktionsübersicht"
        )
        self.lbl_header.setText(
            "❓ LiteMix HD – Complete Button & Feature Guide"
            if is_en else "❓ LiteMix HD – Alle Buttons, Icons & Funktionen erklärt"
        )
        self.btn_switch_lang.setText(
            "🌐 Sprache: English ➔ Deutsch" if is_en else "🌐 Language: Deutsch ➔ English"
        )
        self.btn_close.setText("Close" if is_en else "Schließen")
        self.browser.setHtml(HELP_HTML_EN if is_en else HELP_HTML_DE)
