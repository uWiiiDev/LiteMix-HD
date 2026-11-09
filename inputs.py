import os
import time
import math
import threading
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer, QUrl
from PyQt6.QtGui import (
    QImage, QPainter, QColor, QFont, QLinearGradient, QPen, QBrush, QPolygonF
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

Gst.init(None)


class BaseInput:
    """Basisklasse für alle vMix-Inputs."""

    def __init__(self, name: str, width: int = 1280, height: int = 720):
        self.name = name
        self.width = width
        self.height = height
        self.has_audio = False
        self.volume = 1.0  # 0.0 bis 1.0
        self.muted = False
        self.vu_level = 0.0  # 0.0 bis 1.0 für VU-Meter
        self.active = True
        self._lock = threading.Lock()
        self._frame = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        self._frame.fill(QColor(20, 20, 25))

    def get_frame(self) -> QImage:
        with self._lock:
            return self._frame

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.5, vol))

    def set_muted(self, muted: bool):
        self.muted = muted

    def update(self):
        """Wird pro Render-Tick aufgerufen, falls prozedural."""
        pass

    def stop(self):
        self.active = False


class TestPatternInput(BaseInput):
    """Animiertes Broadcast-Testbild (SMPTE-Style + Studio-Uhr + Live-Radar)."""

    def __init__(self, name: str = "Studio Testbild", width: int = 1280, height: int = 720, pattern_style: int = 0):
        super().__init__(name, width, height)
        self.pattern_style = pattern_style
        self.start_time = time.time()
        self.has_audio = False
        self._static_bg = self._create_static_bg()
        with self._lock:
            self._frame = self._static_bg.copy()

    def _create_static_bg(self) -> QImage:
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.pattern_style == 0:
            # Broadcast Color Bars
            colors = [
                QColor(210, 210, 210),
                QColor(210, 210, 20),
                QColor(20, 210, 210),
                QColor(20, 210, 20),
                QColor(210, 20, 210),
                QColor(210, 20, 20),
                QColor(20, 20, 210),
            ]
            bar_w = self.width / len(colors)
            for i, col in enumerate(colors):
                p.fillRect(QRectF(i * bar_w, 0, bar_w + 1, self.height * 0.72), col)

            # Bottom gradient strip
            grad = QLinearGradient(0, 0, self.width, 0)
            grad.setColorAt(0.0, QColor(15, 15, 20))
            grad.setColorAt(1.0, QColor(240, 240, 245))
            p.fillRect(QRectF(0, self.height * 0.72, self.width, self.height * 0.28), grad)
        else:
            # Studio Dark Grid
            grad = QLinearGradient(0, 0, self.width, self.height)
            grad.setColorAt(0.0, QColor(18, 28, 48))
            grad.setColorAt(1.0, QColor(8, 12, 22))
            p.fillRect(0, 0, self.width, self.height, grad)
            pen = QPen(QColor(255, 255, 255, 25), 1)
            p.setPen(pen)
            for x in range(0, self.width, 64):
                p.drawLine(x, 0, x, self.height)
            for y in range(0, self.height, 64):
                p.drawLine(0, y, self.width, y)

        p.end()
        return img

    def update(self):
        t = time.time() - self.start_time
        with self._lock:
            p = QPainter(self._frame)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Center overlay card
            card_w, card_h = 500, 170
            cx = (self.width - card_w) / 2
            cy = (self.height - card_h) / 2
            p.setBrush(QColor(12, 14, 18))
            p.setPen(QPen(QColor(0, 200, 255), 2))
            p.drawRoundedRect(QRectF(cx, cy, card_w, card_h), 12, 12)

            # Title
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
            p.drawText(QRectF(cx, cy + 18, card_w, 40), Qt.AlignmentFlag.AlignCenter, self.name)

            # Timecode
            tc_str = time.strftime("%H:%M:%S") + f".{int((t % 1) * 30):02d}"
            p.setPen(QColor(0, 230, 140))
            p.setFont(QFont("Monospace", 28, QFont.Weight.Bold))
            p.drawText(QRectF(cx, cy + 68, card_w, 45), Qt.AlignmentFlag.AlignCenter, tc_str)

            # Moving sync indicator bar
            bar_margin = 50
            bar_len = card_w - 2 * bar_margin
            pos = (math.sin(t * 3.0) * 0.5 + 0.5) * (bar_len - 40)
            p.setBrush(QColor(40, 45, 55))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(cx + bar_margin, cy + 128, bar_len, 14), 7, 7)
            p.setBrush(QColor(0, 200, 255))
            p.drawRoundedRect(QRectF(cx + bar_margin + pos, cy + 128, 40, 14), 7, 7)

            p.end()


class LowerThirdInput(BaseInput):
    """
    Transparente Bauchbinde (Lower Third) für Overlay-Kanäle OVL 1 / OVL 2
    mit 3 auswählbaren Broadcast-Design-Templates.
    """

    TEMPLATES = [
        (0, "1: Studio Cyan (Klassisch)"),
        (1, "2: TV News / Live-Banner (Rot/Weiß)"),
        (2, "3: Modern Minimal / Talk-Pill (Smaragd)"),
    ]

    def __init__(
        self,
        name: str = "Bauchbinde (Overlay)",
        title: str = "Max Mustermann",
        subtitle: str = "Live aus dem Studio • LiteMix HD",
        width: int = 1280,
        height: int = 720,
        template_id: int = 0,
    ):
        super().__init__(name, width, height)
        self.title = title
        self.subtitle = subtitle
        self.template_id = int(template_id) % 3
        self._render_lower_third()

    def set_texts(self, title: str, subtitle: str, template_id: int | None = None):
        self.title = title
        self.subtitle = subtitle
        if template_id is not None:
            self.template_id = int(template_id) % 3
        self._render_lower_third()

    def _render_lower_third(self):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bx = 70
        by = self.height - 158
        bw = 660
        bh = 104

        if self.template_id == 0:
            # Template 0: Studio Cyan (Klassischer dunkler Broadcast-Verlauf mit Cyan-Akzent)
            grad = QLinearGradient(bx, by, bx + bw, by)
            grad.setColorAt(0.0, QColor(14, 20, 32, 238))
            grad.setColorAt(0.85, QColor(20, 30, 48, 220))
            grad.setColorAt(1.0, QColor(20, 30, 48, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 8, 8)

            # Linker Cyan-Balken
            p.setBrush(QColor(0, 195, 255))
            p.drawRoundedRect(QRectF(bx, by, 10, bh), 4, 4)

            # Texte
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx + 26, by + 12, bw - 40, 42),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.title,
            )

            p.setPen(QColor(0, 210, 255))
            p.setFont(QFont("Sans Serif", 14, QFont.Weight.Medium))
            p.drawText(
                QRectF(bx + 26, by + 54, bw - 40, 34),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )

        elif self.template_id == 1:
            # Template 1: TV News / Live-Banner (Zweistufiger Nachrichten-Look Rot/Weiß/Anthrazit)
            top_h = 56
            bot_h = 40
            slant = 18

            # Oberer weißer/hellgrauer Hauptbalken mit schräger rechter Kante
            top_poly = QPolygonF([
                QPointF(bx, by),
                QPointF(bx + bw, by),
                QPointF(bx + bw - slant, by + top_h),
                QPointF(bx, by + top_h),
            ])
            top_grad = QLinearGradient(bx, by, bx + bw, by)
            top_grad.setColorAt(0.0, QColor(246, 248, 252, 248))
            top_grad.setColorAt(1.0, QColor(222, 228, 238, 242))
            p.setBrush(QBrush(top_grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(top_poly)

            # Rotes LIVE-Tag links oben mit schräger Kante
            tag_w = 96
            tag_poly = QPolygonF([
                QPointF(bx, by),
                QPointF(bx + tag_w, by),
                QPointF(bx + tag_w - slant, by + top_h),
                QPointF(bx, by + top_h),
            ])
            red_grad = QLinearGradient(bx, by, bx + tag_w, by + top_h)
            red_grad.setColorAt(0.0, QColor(225, 28, 38))
            red_grad.setColorAt(1.0, QColor(168, 14, 22))
            p.setBrush(QBrush(red_grad))
            p.drawPolygon(tag_poly)

            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx, by, tag_w - 10, top_h),
                Qt.AlignmentFlag.AlignCenter,
                "● LIVE",
            )

            # Hauptzeile (Dunkel auf Weiß)
            p.setPen(QColor(16, 20, 28))
            p.setFont(QFont("Sans Serif", 21, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx + tag_w + 8, by + 2, bw - tag_w - 30, top_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.title,
            )

            # Unterer Anthrazit-Balken mit Gold-Trennlinie
            bot_y = by + top_h
            bot_w = bw - 35
            bot_poly = QPolygonF([
                QPointF(bx, bot_y),
                QPointF(bx + bot_w, bot_y),
                QPointF(bx + bot_w - 12, bot_y + bot_h),
                QPointF(bx, bot_y + bot_h),
            ])
            p.setBrush(QColor(18, 22, 32, 242))
            p.drawPolygon(bot_poly)

            # Gold-Akzentlinie zwischen Ober- und Unterbalken
            p.setBrush(QColor(255, 185, 15))
            p.drawRect(QRectF(bx, bot_y - 2, bot_w, 3))

            # Unterzeile (Weiß/Gold auf Anthrazit)
            p.setPen(QColor(255, 210, 90))
            p.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx + 18, bot_y + 2, bot_w - 36, bot_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )

        else:
            # Template 2: Modern Minimal / Talk-Pill (Abgerundete Kapsel mit Smaragd-Rahmen & Monogramm-Kreis)
            pill_h = 94
            pill_y = by + 5
            radius = pill_h * 0.5

            grad = QLinearGradient(bx, pill_y, bx + bw, pill_y + pill_h)
            grad.setColorAt(0.0, QColor(14, 22, 28, 238))
            grad.setColorAt(0.75, QColor(18, 30, 38, 225))
            grad.setColorAt(1.0, QColor(18, 30, 38, 90))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(0, 230, 150, 210), 2.5))
            p.drawRoundedRect(QRectF(bx, pill_y, bw, pill_h), radius, radius)

            #Runder Smaragd/Blau-Badge links
            circle_d = pill_h - 16
            cx = bx + 8
            cy = pill_y + 8
            c_grad = QLinearGradient(cx, cy, cx + circle_d, cy + circle_d)
            c_grad.setColorAt(0.0, QColor(0, 220, 140))
            c_grad.setColorAt(1.0, QColor(0, 140, 215))
            p.setBrush(QBrush(c_grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx, cy, circle_d, circle_d))

            # Initialen aus dem Titel extrahieren
            words = [w for w in self.title.strip().split() if w and w[0].isalnum()]
            if len(words) >= 2:
                initials = (words[0][0] + words[1][0]).upper()
            elif words:
                initials = words[0][:2].upper()
            else:
                initials = "TV"

            p.setPen(QColor(10, 16, 22))
            p.setFont(QFont("Sans Serif", 20, QFont.Weight.Bold))
            p.drawText(QRectF(cx, cy, circle_d, circle_d), Qt.AlignmentFlag.AlignCenter, initials)

            # Texte rechts neben dem Kreis
            tx = cx + circle_d + 16
            tw = bw - (tx - bx) - 24
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Sans Serif", 21, QFont.Weight.Bold))
            p.drawText(
                QRectF(tx, pill_y + 10, tw, 40),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.title,
            )

            p.setPen(QColor(80, 240, 175))
            p.setFont(QFont("Sans Serif", 13, QFont.Weight.Medium))
            p.drawText(
                QRectF(tx, pill_y + 48, tw, 32),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )

        p.end()
        with self._lock:
            self._frame = img


class ImageInput(BaseInput):
    """Statisches Bild (PNG/JPG/SVG) inkl. Alpha-Transparenz für Overlays oder Vollbild."""

    def __init__(self, filepath: str, width: int = 1280, height: int = 720):
        name = f"Bild: {os.path.basename(filepath)}"
        super().__init__(name, width, height)
        self.filepath = filepath
        loaded = QImage(filepath)
        if not loaded.isNull():
            canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.GlobalColor.transparent)
            scaled = loaded.scaled(
                width, height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            p = QPainter(canvas)
            x = (width - scaled.width()) // 2
            y = (height - scaled.height()) // 2
            p.drawImage(x, y, scaled)
            p.end()
            with self._lock:
                self._frame = canvas


class GStreamerBaseInput(BaseInput):
    """Gemeinsame Basis für alle GStreamer-basierten Video/Audio-Quellen (inkl. Zeitlupen-Steuerung)."""

    def __init__(self, name: str, width: int = 1280, height: int = 720):
        super().__init__(name, width, height)
        self.pipeline = None
        self.vsink = None
        self.vol_element = None
        self.loop_enabled = False
        self.return_to_preview_on_eos = False
        self.eos_return_pending = False
        self.paused = False
        self.playback_rate = 1.0  # 1.0 = Echtzeit, 0.5 = 50% Zeitlupe, 0.25 = 25% Super-Zeitlupe
        self._pending_rate_apply = False
        self.afv_gain = 1.0  # Audio-Follow-Video Faktor (1.0 = Live/Aktiv, 0.0 = Stumm in Preview/Grid)

    def _apply_effective_volume(self):
        eff = 0.0 if (self.muted or self.paused) else (self.volume * self.afv_gain)
        if self.vol_element:
            self.vol_element.set_property("volume", eff)
        if eff <= 0.001:
            self.vu_level = 0.0

    def set_afv_gain(self, gain: float):
        gain = max(0.0, min(1.0, gain))
        if abs(self.afv_gain - gain) > 0.01:
            self.afv_gain = gain
            self._apply_effective_volume()

    def _seek_with_rate(self, target_ns: int, flags=None):
        if not self.pipeline:
            return False
        if flags is None:
            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE
        rate = max(0.1, min(2.0, float(self.playback_rate)))
        return self.pipeline.seek(
            rate,
            Gst.Format.TIME,
            flags,
            Gst.SeekType.SET,
            max(0, int(target_ns)),
            Gst.SeekType.NONE,
            -1,
        )

    def set_playback_rate(self, rate: float):
        """Ändert die Abspielgeschwindigkeit (z.B. 0.25, 0.5, 0.75, 1.0) unter Beibehaltung der aktuellen Position."""
        self.playback_rate = max(0.1, min(2.0, float(rate)))
        if not self.pipeline:
            return
        ok_p, pos = self.pipeline.query_position(Gst.Format.TIME)
        cur_ns = pos if (ok_p and pos >= 0) else 0
        if not self._seek_with_rate(cur_ns, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE):
            self._pending_rate_apply = True

    def _attach_bus_and_sink(self):
        if not self.pipeline:
            return
        sink = self.vsink or self.pipeline.get_by_name("vsink")
        if sink:
            self.vsink = sink
            sink.connect("new-sample", self._on_new_sample)
            sink.connect("new-preroll", self._on_new_preroll)

        if not self.vol_element:
            self.vol_element = self.pipeline.get_by_name("avol")

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _extract_sample_frame(self, sample):
        if not sample:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps()
        if not buf or not caps or caps.get_size() == 0:
            return Gst.FlowReturn.OK
        struct = caps.get_structure(0)
        w = struct.get_value("width")
        h = struct.get_value("height")

        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                # BGRA bytes on little-endian x86_64 map directly to Format_ARGB32
                img = QImage(mapinfo.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
                with self._lock:
                    self._frame = img
            finally:
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def _on_new_sample(self, sink):
        return self._extract_sample_frame(sink.emit("pull-sample"))

    def _on_new_preroll(self, sink):
        return self._extract_sample_frame(sink.emit("pull-preroll"))

    def update(self):
        if not self.pipeline:
            return
        bus = self.pipeline.get_bus()
        if not bus:
            return
        while True:
            msg = bus.pop()
            if msg is None:
                break
            self._on_bus_message(bus, msg)

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ASYNC_DONE and self._pending_rate_apply and self.pipeline:
            self._pending_rate_apply = False
            if abs(self.playback_rate - 1.0) > 0.01:
                self._seek_with_rate(0, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE)
        elif t == Gst.MessageType.EOS and self.pipeline:
            if hasattr(self, "_on_eos") and callable(self._on_eos):
                self._on_eos()
            elif self.loop_enabled:
                self._seek_with_rate(0, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT)
            else:
                self._on_eos_stop_main_thread()
        elif t == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            if struct and struct.get_name() == "level":
                rms_list = struct.get_value("rms")
                if rms_list and len(rms_list) > 0:
                    db = rms_list[0]
                    # Noise-Gate unter -38 dB (filtert Grundrauschen aus)
                    if db < -38.0 or self.muted or self.paused or self.afv_gain <= 0.001:
                        self.vu_level = 0.0
                    else:
                        norm = max(0.0, min(1.0, (db + 38.0) / 38.0))
                        self.vu_level = min(1.0, norm * self.volume * self.afv_gain)

    def set_volume(self, vol: float):
        super().set_volume(vol)
        self._apply_effective_volume()

    def set_muted(self, muted: bool):
        super().set_muted(muted)
        self._apply_effective_volume()

    def _on_eos_stop_main_thread(self):
        self.stop_playback()
        if getattr(self, "return_to_preview_on_eos", False):
            self.eos_return_pending = True
        return False

    def play(self):
        if not self.pipeline:
            return
        pos_s, dur_s = self.get_position_duration()
        if dur_s > 0.2 and pos_s >= dur_s - 0.15:
            self._seek_with_rate(0, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT)
        self.paused = False
        self._apply_effective_volume()
        self.pipeline.set_state(Gst.State.PLAYING)

    def pause(self):
        if not self.pipeline:
            return
        self.paused = True
        self._apply_effective_volume()
        self.pipeline.set_state(Gst.State.PAUSED)
        self.vu_level = 0.0

    def toggle_pause(self):
        if self.paused:
            self.play()
        else:
            self.pause()

    def stop_playback(self):
        """Stoppt die Wiedergabe und spult an den Anfang (00:00) zurück."""
        if not self.pipeline:
            return
        self.paused = True
        self._apply_effective_volume()
        self.pipeline.set_state(Gst.State.PAUSED)
        self._seek_with_rate(0, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT)
        self.vu_level = 0.0

    def restart(self):
        if self.pipeline:
            self.paused = False
            self._apply_effective_volume()
            self.pipeline.set_state(Gst.State.PLAYING)
            self._seek_with_rate(0, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT)

    def seek_seconds(self, target_sec: float):
        """Spult framegenau zur angegebenen Position in Sekunden."""
        if not self.pipeline:
            return
        target_ns = max(0, int(target_sec * Gst.SECOND))
        self._seek_with_rate(target_ns, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE)

    def get_position_duration(self) -> tuple[float, float]:
        """Liefert (aktuelle Position in s, Gesamtdauer in s)."""
        if not self.pipeline:
            return 0.0, 0.0
        ok_p, pos = self.pipeline.query_position(Gst.Format.TIME)
        if not ok_p and self.vsink:
            ok_p, pos = self.vsink.query_position(Gst.Format.TIME)
        ok_d, dur = self.pipeline.query_duration(Gst.Format.TIME)
        pos_sec = (pos / Gst.SECOND) if (ok_p and pos >= 0) else 0.0
        dur_sec = (dur / Gst.SECOND) if (ok_d and dur > 0) else 0.0
        return pos_sec, dur_sec

    def stop(self):
        super().stop()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None


class VideoFileInput(GStreamerBaseInput):
    """Spielt MP4/MKV/WebM-Videos lippensynchron via playbin mit Loop, Audio-Follow-Video und Live-VU-Meter ab."""

    def __init__(self, filepath: str, width: int = 1280, height: int = 720):
        name = f"Video: {os.path.basename(filepath)}"
        super().__init__(name, width, height)
        self.filepath = os.path.abspath(filepath)
        self.has_audio = True
        self.afv_gain = 0.0  # Erst hörbar/Pegel, wenn in Program (Live) oder Overlay geschaltet!
        uri = Gst.filename_to_uri(self.filepath)

        try:
            self.paused = True
            self.pipeline = Gst.ElementFactory.make("playbin", "player")
            self.pipeline.set_property("uri", uri)
            # flags=0x00000003: Nur 1 Video-Track + 1 Audio-Track dekodieren (ignoriert Untertitel & 2. Tonspur!)
            self.pipeline.set_property("flags", 0x00000003)

            vbin = Gst.parse_bin_from_description(
                f"videoconvert n-threads=2 ! videoscale method=nearest-neighbour ! "
                f"video/x-raw,format=BGRA,width={width},height={height} ! "
                f"appsink name=vsink emit-signals=true max-buffers=2 drop=true sync=true qos=true",
                True
            )
            abin = Gst.parse_bin_from_description(
                "audioconvert ! audioresample ! audio/x-raw,channels=2 ! "
                "volume name=avol volume=0.0 ! level interval=50000000 post-messages=true ! "
                "pulsesink name=asink buffer-time=60000 latency-time=15000 sync=true",
                True
            )
            self.pipeline.set_property("video-sink", vbin)
            self.pipeline.set_property("audio-sink", abin)

            self.vsink = vbin.get_by_name("vsink")
            self.vol_element = abin.get_by_name("avol")
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PAUSED)
        except Exception as e:
            print(f"[VideoFileInput] Fehler beim Starten der Pipeline: {e}")


class V4L2CameraInput(GStreamerBaseInput):
    """Erfasst Webcams oder USB-Capture-Cards über Video4Linux2 (/dev/videoX) inkl. Spiegel-Option."""

    def __init__(self, device: str = "/dev/video0", width: int = 1280, height: int = 720, mirror: bool = True):
        name = f"Kamera ({device})"
        super().__init__(name, width, height)
        self.device = device
        self.loop_enabled = False
        self.mirrored = mirror
        self.flip_element = None

        flip_method = "horizontal-flip" if mirror else "none"
        pipe_str = (
            f'v4l2src device="{device}" ! videoconvert ! '
            f'videoflip name=vflip method={flip_method} ! videoscale ! '
            f'video/x-raw,format=BGRA,width={width},height={height} ! '
            f'appsink name=vsink emit-signals=true max-buffers=2 drop=true sync=false'
        )
        try:
            self.pipeline = Gst.parse_launch(pipe_str)
            self.flip_element = self.pipeline.get_by_name("vflip")
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[V4L2CameraInput] Fehler: {e}")

    def toggle_mirror(self):
        self.mirrored = not self.mirrored
        if self.flip_element:
            # 4 = horizontal-flip, 0 = none (Identity)
            self.flip_element.set_property("method", 4 if self.mirrored else 0)


class WaylandPortalInput(GStreamerBaseInput):
    """
    Erfasst ein beliebiges Anwendungs-/Browserfenster oder den Bildschirm unter Wayland
    über das offizielle XDG Desktop Portal (ScreenCast) + PipeWire.
    """

    def __init__(self, name: str = "Fenster / Browser (Wayland)", width: int = 1280, height: int = 720):
        super().__init__(name, width, height)
        self.loop_enabled = False
        self._portal_session = None
        self._render_waiting_message("Fenster-Auswahl im Systemdialog geöffnet...")
        QTimer.singleShot(100, self._request_screencast_portal)

    def _render_waiting_message(self, msg: str):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(18, 22, 30))
        p = QPainter(img)
        p.setPen(QColor(0, 200, 255))
        p.setFont(QFont("Sans Serif", 18, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, self.width, self.height), Qt.AlignmentFlag.AlignCenter, msg)
        p.end()
        with self._lock:
            self._frame = img

    def _request_screencast_portal(self):
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            DBusGMainLoop(set_as_default=True)

            bus = dbus.SessionBus()
            portal = bus.get_object('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop')
            screencast = dbus.Interface(portal, 'org.freedesktop.portal.ScreenCast')

            sender_name = bus.get_unique_name().lstrip(':').replace('.', '_')
            token_counter = [int(time.time() * 1000) % 100000]

            def new_request_path():
                token_counter[0] += 1
                tok = f"litemix_{token_counter[0]}"
                path = f"/org/freedesktop/portal/desktop/request/{sender_name}/{tok}"
                return tok, path

            tok1, req_path1 = new_request_path()

            def on_create_session(response, results):
                if response != 0:
                    self._render_waiting_message("Fenster-Auswahl abgebrochen.")
                    return
                self._portal_session = results['session_handle']
                tok2, req_path2 = new_request_path()
                bus.add_signal_receiver(
                    on_select_sources,
                    signal_name='Response',
                    dbus_interface='org.freedesktop.portal.Request',
                    path=req_path2
                )
                # types=3 erlaubt sowohl Monitor (1) als auch einzelnes Fenster/Browser (2)
                screencast.SelectSources(
                    self._portal_session,
                    dbus.Dictionary({
                        'handle_token': tok2,
                        'types': dbus.UInt32(3),
                        'multiple': False,
                        'cursor_mode': dbus.UInt32(2),
                    }, signature='sv')
                )

            def on_select_sources(response, results):
                if response != 0:
                    self._render_waiting_message("Keine Quelle ausgewählt.")
                    return
                tok3, req_path3 = new_request_path()
                bus.add_signal_receiver(
                    on_start,
                    signal_name='Response',
                    dbus_interface='org.freedesktop.portal.Request',
                    path=req_path3
                )
                screencast.Start(
                    self._portal_session,
                    '',
                    dbus.Dictionary({'handle_token': tok3}, signature='sv')
                )

            def on_start(response, results):
                if response != 0 or 'streams' not in results:
                    self._render_waiting_message("Fenster-Aufnahme vom Nutzer abgebrochen.")
                    return
                streams = results['streams']
                if not streams:
                    self._render_waiting_message("Kein PipeWire-Stream erhalten.")
                    return
                node_id = int(streams[0][0])
                fd_obj = screencast.OpenPipeWireRemote(
                    self._portal_session,
                    dbus.Dictionary({}, signature='sv')
                )
                fd = fd_obj.take()
                self._start_pipewire_pipeline(fd, node_id)

            bus.add_signal_receiver(
                on_create_session,
                signal_name='Response',
                dbus_interface='org.freedesktop.portal.Request',
                path=req_path1
            )
            screencast.CreateSession(
                dbus.Dictionary({
                    'handle_token': tok1,
                    'session_handle_token': f"sess_{tok1}"
                }, signature='sv')
            )
        except Exception as e:
            self._render_waiting_message(f"Portal-Fehler: {e}")

    def _start_pipewire_pipeline(self, fd: int, node_id: int):
        pipe_str = (
            f'pipewiresrc fd={fd} path={node_id} do-timestamp=true ! '
            f'videoconvert ! videoscale ! '
            f'video/x-raw,format=BGRA,width={self.width},height={self.height} ! '
            f'appsink name=vsink emit-signals=true max-buffers=2 drop=true sync=false'
        )
        try:
            self.pipeline = Gst.parse_launch(pipe_str)
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            self._render_waiting_message(f"PipeWire-Fehler: {e}")


class WebBrowserWindow(QWidget):
    """Eigenes interaktives Browserfenster, dessen Inhalt als vMix-Input abgegriffen wird."""

    def __init__(self, url: str, width: int = 1280, height: int = 720):
        super().__init__()
        self.setWindowTitle(f"LiteMix Browser-Quelle – {url}")
        self.resize(1024, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        nav = QHBoxLayout()
        self.url_edit = QLineEdit(url)
        btn_go = QPushButton("Laden")
        nav.addWidget(self.url_edit)
        nav.addWidget(btn_go)
        layout.addLayout(nav)

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl(url))
        layout.addWidget(self.webview, 1)

        btn_go.clicked.connect(self._load_url)
        self.url_edit.returnPressed.connect(self._load_url)

    def _load_url(self):
        u = self.url_edit.text().strip()
        if not u.startswith(("http://", "https://", "file://")):
            u = "https://" + u
        self.webview.setUrl(QUrl(u))


class WebBrowserInput(BaseInput):
    """Integrierter Web-Browser Input auf Basis von QtWebEngine inkl. Audio-Steuerung."""

    def __init__(self, url: str = "https://de.wikipedia.org", width: int = 1280, height: int = 720):
        super().__init__(f"Browser: {url}", width, height)
        self.url = url
        self.has_audio = True
        self.browser_win = None
        if HAS_WEBENGINE:
            self.browser_win = WebBrowserWindow(url, width, height)
            self.browser_win.show()

    def set_muted(self, muted: bool):
        super().set_muted(muted)
        if self.browser_win and self.browser_win.webview:
            self.browser_win.webview.page().setAudioMuted(muted)

    def show_browser(self):
        if self.browser_win:
            self.browser_win.show()
            self.browser_win.raise_()
            self.browser_win.activateWindow()

    def update(self):
        if not self.browser_win or not self.browser_win.webview:
            return
        pix = self.browser_win.webview.grab()
        if not pix.isNull():
            scaled = pix.toImage().scaled(
                self.width, self.height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation
            ).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            with self._lock:
                self._frame = scaled

    def stop(self):
        super().stop()
        if self.browser_win:
            self.browser_win.close()
            self.browser_win = None


class AudioInputBase(GStreamerBaseInput):
    """
    Basisklasse für reine Audio-Quellen (Mikrofone, System-Audio, Musik/Jingles).
    Zeichnet eine Live-Audio-Visualisierung mit Pegelanzeige auf die Vorschau-Kachel.
    """

    def __init__(self, name: str, icon_text: str = "🎙️", width: int = 1280, height: int = 720):
        super().__init__(name, width, height)
        self.has_audio = True
        self.is_pure_audio = True
        self.icon_text = icon_text
        self._bg_frame = self._create_audio_bg()
        with self._lock:
            self._frame = self._bg_frame.copy()

    def _create_audio_bg(self) -> QImage:
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        grad = QLinearGradient(0, 0, 0, self.height)
        grad.setColorAt(0.0, QColor(20, 26, 38))
        grad.setColorAt(1.0, QColor(12, 15, 22))
        p = QPainter(img)
        p.fillRect(0, 0, self.width, self.height, grad)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Sans Serif", 32, QFont.Weight.Bold))
        p.drawText(
            QRectF(0, self.height * 0.16, self.width, 80),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.icon_text}  {self.name}"
        )
        p.end()
        return img

    def update(self):
        super().update()
        lvl = 0.0 if self.muted else min(1.0, self.vu_level)
        with self._lock:
            p = QPainter(self._frame)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Clear meter region
            bx = int(self.width * 0.15)
            by = int(self.height * 0.45)
            bw = int(self.width * 0.70)
            bh = 170
            p.fillRect(bx - 10, by - 10, bw + 20, bh + 40, QColor(15, 19, 28))

            # Status label
            if self.muted:
                status = "🔇 STUMMGESCHALTET (MUTE)"
                scol = QColor(240, 70, 70)
            elif self.paused:
                status = "⏸ PAUSIERT"
                scol = QColor(240, 190, 50)
            else:
                status = f"● AKTIV  |  Lautstärke: {int(self.volume * 100)}%"
                scol = QColor(0, 220, 140)

            p.setPen(scol)
            p.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
            p.drawText(QRectF(bx, by, bw, 45), Qt.AlignmentFlag.AlignCenter, status)

            # Horizontal VU meter bar
            bar_y = by + 70
            bar_h = 54
            p.setBrush(QColor(28, 34, 46))
            p.setPen(QPen(QColor(60, 72, 96), 2))
            p.drawRoundedRect(QRectF(bx, bar_y, bw, bar_h), 10, 10)

            active_w = int((bw - 8) * lvl)
            if active_w > 4:
                meter_grad = QLinearGradient(bx, 0, bx + bw, 0)
                meter_grad.setColorAt(0.0, QColor(30, 215, 100))
                meter_grad.setColorAt(0.7, QColor(240, 200, 40))
                meter_grad.setColorAt(1.0, QColor(245, 50, 50))
                p.setBrush(QBrush(meter_grad))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(bx + 4, bar_y + 4, active_w, bar_h - 8), 7, 7)

            p.end()


class MicDeviceInput(AudioInputBase):
    """Binden ein bestimmtes Mikrofon / Line-In / USB-Audio-Interface als eigene Quelle ein."""

    def __init__(self, device_id: str = "default", label: str = "Mikrofon", width: int = 1280, height: int = 720):
        clean_label = label.replace("🎙️", "").strip()
        super().__init__(f"Mic: {clean_label}", "🎙️", width, height)
        self.device_id = device_id
        self.loop_enabled = False
        dev_prop = f'device="{device_id}"' if device_id and device_id != "default" else ""
        pipe_str = (
            f"pulsesrc {dev_prop} ! audioconvert ! "
            f"volume name=avol volume=1.0 ! "
            f"level interval=50000000 post-messages=true ! fakesink sync=false"
        )
        try:
            self.pipeline = Gst.parse_launch(pipe_str)
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[MicDeviceInput] Fehler: {e}")


class SystemAudioInput(AudioInputBase):
    """Greift den Desktop-/System-Ton (z.B. Browser, YouTube, Zoom) über PipeWire/Pulse-Monitor ab."""

    def __init__(self, monitor_id: str = "default", label: str = "System-Audio", width: int = 1280, height: int = 720):
        clean_label = label.replace("🔊", "").strip()
        super().__init__(f"Sys: {clean_label}", "🔊", width, height)
        self.monitor_id = monitor_id
        self.loop_enabled = False
        dev_prop = f'device="{monitor_id}"' if monitor_id and monitor_id != "default" else ""
        pipe_str = (
            f"pulsesrc {dev_prop} ! audioconvert ! "
            f"volume name=avol volume=1.0 ! "
            f"level interval=50000000 post-messages=true ! fakesink sync=false"
        )
        try:
            self.pipeline = Gst.parse_launch(pipe_str)
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[SystemAudioInput] Fehler: {e}")


class AudioFileInput(AudioInputBase):
    """Spielt Musik, Jingles oder Soundeffekte (MP3, WAV, FLAC, OGG) mit Play/Pause/Loop ab."""

    def __init__(self, filepath: str, width: int = 1280, height: int = 720):
        name = f"Audio: {os.path.basename(filepath)}"
        super().__init__(name, "🎵", width, height)
        self.filepath = os.path.abspath(filepath)
        uri = Gst.filename_to_uri(self.filepath)
        pipe_str = (
            f'uridecodebin uri="{uri}" ! queue max-size-buffers=0 max-size-bytes=0 max-size-time=3000000000 ! '
            f'audioconvert ! audioresample ! '
            f'volume name=avol volume=1.0 ! '
            f'level interval=50000000 post-messages=true ! '
            f'pulsesink buffer-time=200000 latency-time=40000 sync=true'
        )
        try:
            self.paused = True
            self.pipeline = Gst.parse_launch(pipe_str)
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PAUSED)
        except Exception as e:
            print(f"[AudioFileInput] Fehler: {e}")


class ReplaySourceInput(GStreamerBaseInput):
    """
    Spezial-Quelle '⏪ Letztes Replay':
    Bietet nach jedem manuellen Replay-Stopp automatisch das zuletzt aufgezeichnete Replay
    an (standardmäßig in 0.5x Zeitlupe, umschaltbar zwischen 0.25x / 0.5x / 0.75x / 1.0x).
    """

    SPEED_OPTIONS = [
        (0.25, "0.25× (Super-Zeitlupe)"),
        (0.50, "0.50× (Halbes Tempo)"),
        (0.75, "0.75× (Leichte Zeitlupe)"),
        (1.00, "1.00× (Originaltempo)"),
    ]

    def __init__(self, filepath: str = "", width: int = 1280, height: int = 720, playback_rate: float = 0.5):
        super().__init__("⏪ Letztes Replay", width, height)
        self.filepath = os.path.abspath(filepath) if filepath else ""
        self.has_audio = False
        self.playback_rate = max(0.25, min(1.0, float(playback_rate)))
        self.paused = True
        self._render_placeholder()
        if self.filepath and os.path.exists(self.filepath):
            self.set_replay_clip(self.filepath)

    def _render_placeholder(self):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, self.width, self.height)
        grad.setColorAt(0.0, QColor(18, 22, 32))
        grad.setColorAt(1.0, QColor(10, 12, 18))
        p.fillRect(0, 0, self.width, self.height, grad)

        card_w, card_h = 560, 160
        cx = (self.width - card_w) * 0.5
        cy = (self.height - card_h) * 0.5
        p.setBrush(QColor(16, 20, 28, 230))
        p.setPen(QPen(QColor(0, 200, 255), 2))
        p.drawRoundedRect(QRectF(cx, cy, card_w, card_h), 12, 12)

        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
        p.drawText(QRectF(cx, cy + 26, card_w, 42), Qt.AlignmentFlag.AlignCenter, "⏪ Letztes Replay")

        p.setPen(QColor(150, 165, 190))
        p.setFont(QFont("Sans Serif", 13))
        p.drawText(
            QRectF(cx + 20, cy + 82, card_w - 40, 48),
            Qt.AlignmentFlag.AlignCenter,
            "Klicke in der Mittelspalte auf [⏺ REPLAY], um eine Szene aufzuzeichnen.",
        )
        p.end()
        with self._lock:
            self._frame = img

    def _decorate_frame_with_badge(self, img: QImage):
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bw, bh = 225, 38
        bx = img.width() - bw - 28
        by = 24
        p.setBrush(QColor(14, 18, 26, 220))
        p.setPen(QPen(QColor(0, 205, 255, 230), 2))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 6, 6)

        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        p.drawText(
            QRectF(bx + 12, by, bw - 24, bh),
            Qt.AlignmentFlag.AlignCenter,
            f"⏪ REPLAY • {self.playback_rate:g}×",
        )
        p.end()

    def _extract_sample_frame(self, sample):
        if not sample:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps()
        if not buf or not caps or caps.get_size() == 0:
            return Gst.FlowReturn.OK
        struct = caps.get_structure(0)
        w = struct.get_value("width")
        h = struct.get_value("height")
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                img = QImage(mapinfo.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
                self._decorate_frame_with_badge(img)
                with self._lock:
                    self._frame = img
            finally:
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def set_replay_clip(self, filepath: str):
        if not filepath or not os.path.exists(filepath):
            return
        self.filepath = os.path.abspath(filepath)
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        uri = Gst.filename_to_uri(self.filepath)
        try:
            self.paused = True
            self._pending_rate_apply = True
            self.pipeline = Gst.ElementFactory.make("playbin", "replay_player")
            self.pipeline.set_property("uri", uri)
            self.pipeline.set_property("flags", 0x00000001)  # Nur Video dekodieren (ideal für Zeitlupe)

            vbin = Gst.parse_bin_from_description(
                f"videoconvert n-threads=2 ! videoscale method=nearest-neighbour ! "
                f"video/x-raw,format=BGRA,width={self.width},height={self.height} ! "
                f"appsink name=vsink emit-signals=true max-buffers=2 drop=true sync=true qos=true",
                True,
            )
            self.pipeline.set_property("video-sink", vbin)
            self.vsink = vbin.get_by_name("vsink")
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PAUSED)
        except Exception as e:
            print(f"[ReplaySourceInput] Fehler beim Laden des Replays: {e}")


class HighlightsInput(GStreamerBaseInput):
    """
    Spezial-Quelle '⭐ Highlights':
    Sammelt automatisch alle vergangenen Replays als Playlist / Highlight-Archiv
    und kann sie einzeln oder nacheinander (inkl. Zeitlupe 0.25x / 0.5x / 0.75x / 1.0x) abspielen.
    """

    def __init__(
        self,
        clips: list[str] | None = None,
        width: int = 1280,
        height: int = 720,
        playback_rate: float = 0.5,
        auto_advance: bool = True,
    ):
        super().__init__("⭐ Highlights", width, height)
        self.has_audio = False
        self.playback_rate = max(0.25, min(1.0, float(playback_rate)))
        self.auto_advance = bool(auto_advance)
        self.clips: list[str] = [
            os.path.abspath(c) for c in (clips or []) if c and os.path.exists(c)
        ]
        self.current_clip_idx = max(0, len(self.clips) - 1) if self.clips else 0
        self.paused = True
        self._render_placeholder()
        if self.clips:
            self.select_clip(self.current_clip_idx, auto_play=False)

    def _render_placeholder(self):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, self.width, self.height)
        grad.setColorAt(0.0, QColor(24, 20, 14))
        grad.setColorAt(1.0, QColor(12, 10, 14))
        p.fillRect(0, 0, self.width, self.height, grad)

        card_w, card_h = 560, 160
        cx = (self.width - card_w) * 0.5
        cy = (self.height - card_h) * 0.5
        p.setBrush(QColor(22, 20, 16, 230))
        p.setPen(QPen(QColor(255, 185, 25), 2))
        p.drawRoundedRect(QRectF(cx, cy, card_w, card_h), 12, 12)

        p.setPen(QColor(255, 215, 80))
        p.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
        p.drawText(QRectF(cx, cy + 26, card_w, 42), Qt.AlignmentFlag.AlignCenter, "⭐ Highlights (Archiv)")

        p.setPen(QColor(185, 175, 155))
        p.setFont(QFont("Sans Serif", 13))
        p.drawText(
            QRectF(cx + 20, cy + 82, card_w - 40, 48),
            Qt.AlignmentFlag.AlignCenter,
            "Alle aufgezeichneten Replays werden hier automatisch als Highlights gesammelt.",
        )
        p.end()
        with self._lock:
            self._frame = img

    def _decorate_frame_with_badge(self, img: QImage):
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bw, bh = 265, 38
        bx = img.width() - bw - 28
        by = 24
        p.setBrush(QColor(18, 16, 12, 225))
        p.setPen(QPen(QColor(255, 190, 30, 235), 2))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 6, 6)

        total = max(1, len(self.clips))
        cur = min(total, self.current_clip_idx + 1)
        p.setPen(QColor(255, 225, 110))
        p.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        p.drawText(
            QRectF(bx + 10, by, bw - 20, bh),
            Qt.AlignmentFlag.AlignCenter,
            f"⭐ HIGHLIGHT #{cur}/{total} • {self.playback_rate:g}×",
        )
        p.end()

    def _extract_sample_frame(self, sample):
        if not sample:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps()
        if not buf or not caps or caps.get_size() == 0:
            return Gst.FlowReturn.OK
        struct = caps.get_structure(0)
        w = struct.get_value("width")
        h = struct.get_value("height")
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                img = QImage(mapinfo.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
                self._decorate_frame_with_badge(img)
                with self._lock:
                    self._frame = img
            finally:
                buf.unmap(mapinfo)
        return Gst.FlowReturn.OK

    def add_highlight_clip(self, filepath: str):
        if not filepath or not os.path.exists(filepath):
            return
        ap = os.path.abspath(filepath)
        if ap not in self.clips:
            self.clips.append(ap)
        # Falls noch kein Clip geladen war oder das aktuelle Highlight pausiert ist,
        # bei erstem Clip sofort als Vorschau laden:
        if len(self.clips) == 1 or self.pipeline is None:
            self.select_clip(len(self.clips) - 1, auto_play=False)

    def select_clip(self, idx: int, auto_play: bool = False):
        if not self.clips:
            self._render_placeholder()
            return
        idx = max(0, min(len(self.clips) - 1, int(idx)))
        self.current_clip_idx = idx
        filepath = self.clips[idx]
        if not os.path.exists(filepath):
            return

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        uri = Gst.filename_to_uri(filepath)
        try:
            self.paused = not auto_play
            self._pending_rate_apply = True
            self.pipeline = Gst.ElementFactory.make("playbin", "highlights_player")
            self.pipeline.set_property("uri", uri)
            self.pipeline.set_property("flags", 0x00000001)

            vbin = Gst.parse_bin_from_description(
                f"videoconvert n-threads=2 ! videoscale method=nearest-neighbour ! "
                f"video/x-raw,format=BGRA,width={self.width},height={self.height} ! "
                f"appsink name=vsink emit-signals=true max-buffers=2 drop=true sync=true qos=true",
                True,
            )
            self.pipeline.set_property("video-sink", vbin)
            self.vsink = vbin.get_by_name("vsink")
            self._attach_bus_and_sink()
            self.pipeline.set_state(Gst.State.PLAYING if auto_play else Gst.State.PAUSED)
        except Exception as e:
            print(f"[HighlightsInput] Fehler beim Laden von Highlight #{idx + 1}: {e}")

    def _on_eos(self):
        if self.auto_advance and len(self.clips) > 1 and self.current_clip_idx < len(self.clips) - 1:
            next_idx = self.current_clip_idx + 1
            self._deferred_select_next(next_idx)
        else:
            self._on_eos_stop_main_thread()

    def _deferred_select_next(self, next_idx: int):
        self.select_clip(next_idx, auto_play=True)
        return False


def serialize_input(inp: BaseInput) -> dict:
    """Serialisiert eine Input-Quelle als Dictionary zum Speichern in einer .litemix Set-Datei."""
    d = {
        "type": inp.__class__.__name__,
        "name": inp.name,
        "volume": round(float(inp.volume), 3),
        "muted": bool(inp.muted),
    }
    if isinstance(inp, TestPatternInput):
        d["pattern_style"] = inp.pattern_style
    elif isinstance(inp, LowerThirdInput):
        d["title"] = inp.title
        d["subtitle"] = inp.subtitle
        d["template_id"] = inp.template_id
    elif isinstance(inp, ImageInput):
        d["filepath"] = inp.filepath
    elif isinstance(inp, VideoFileInput):
        d["filepath"] = inp.filepath
        d["paused"] = inp.paused
        d["loop_enabled"] = bool(inp.loop_enabled)
        d["return_to_preview_on_eos"] = bool(inp.return_to_preview_on_eos)
    elif isinstance(inp, V4L2CameraInput):
        d["device"] = inp.device
        d["mirrored"] = inp.mirrored
    elif isinstance(inp, WebBrowserInput):
        d["url"] = inp.url
    elif isinstance(inp, MicDeviceInput):
        d["device_id"] = inp.device_id
    elif isinstance(inp, SystemAudioInput):
        d["monitor_id"] = inp.monitor_id
    elif isinstance(inp, AudioFileInput):
        d["filepath"] = inp.filepath
        d["paused"] = inp.paused
        d["loop_enabled"] = bool(inp.loop_enabled)
        d["return_to_preview_on_eos"] = bool(inp.return_to_preview_on_eos)
    elif isinstance(inp, ReplaySourceInput):
        d["filepath"] = inp.filepath
        d["playback_rate"] = inp.playback_rate
        d["loop_enabled"] = bool(inp.loop_enabled)
        d["return_to_preview_on_eos"] = bool(inp.return_to_preview_on_eos)
    elif isinstance(inp, HighlightsInput):
        d["clips"] = inp.clips
        d["playback_rate"] = inp.playback_rate
        d["auto_advance"] = inp.auto_advance
    return d


def deserialize_input(data: dict, width: int = 1280, height: int = 720) -> BaseInput | None:
    """Erstellt eine Input-Quelle aus einem gespeicherten Set-Dictionary."""
    t = data.get("type", "")
    name = data.get("name", "Quelle")
    inp = None

    if t == "TestPatternInput":
        inp = TestPatternInput(name, width, height, pattern_style=int(data.get("pattern_style", 0)))
    elif t == "LowerThirdInput":
        inp = LowerThirdInput(
            name,
            data.get("title", "Titel"),
            data.get("subtitle", "Untertitel"),
            width,
            height,
            template_id=int(data.get("template_id", 0)),
        )
    elif t == "ImageInput":
        fp = data.get("filepath", "")
        if fp and os.path.exists(fp):
            inp = ImageInput(fp, width, height)
    elif t == "VideoFileInput":
        fp = data.get("filepath", "")
        if fp and os.path.exists(fp):
            inp = VideoFileInput(fp, width, height)
    elif t == "V4L2CameraInput":
        dev = data.get("device", "/dev/video0")
        mir = bool(data.get("mirrored", True))
        inp = V4L2CameraInput(dev, width, height, mirror=mir)
    elif t == "WaylandPortalInput":
        inp = WaylandPortalInput(name, width, height)
    elif t == "WebBrowserInput":
        inp = WebBrowserInput(data.get("url", "https://de.wikipedia.org"), width, height)
    elif t == "MicDeviceInput":
        dev_id = data.get("device_id", "default")
        inp = MicDeviceInput(dev_id, name.replace("Mic:", "").strip(), width, height)
    elif t == "SystemAudioInput":
        mon_id = data.get("monitor_id", "default")
        inp = SystemAudioInput(mon_id, name.replace("Sys:", "").strip(), width, height)
    elif t == "AudioFileInput":
        fp = data.get("filepath", "")
        if fp and os.path.exists(fp):
            inp = AudioFileInput(fp, width, height)
    elif t == "ReplaySourceInput":
        inp = ReplaySourceInput(
            filepath=data.get("filepath", ""),
            width=width,
            height=height,
            playback_rate=float(data.get("playback_rate", 0.5)),
        )
    elif t == "HighlightsInput":
        inp = HighlightsInput(
            clips=data.get("clips", []),
            width=width,
            height=height,
            playback_rate=float(data.get("playback_rate", 0.5)),
            auto_advance=bool(data.get("auto_advance", True)),
        )

    if inp is not None:
        inp.set_volume(float(data.get("volume", 1.0)))
        inp.set_muted(bool(data.get("muted", False)))
        if "loop_enabled" in data and hasattr(inp, "loop_enabled"):
            inp.loop_enabled = bool(data["loop_enabled"])
        if "return_to_preview_on_eos" in data and hasattr(inp, "return_to_preview_on_eos"):
            inp.return_to_preview_on_eos = bool(data["return_to_preview_on_eos"])
    return inp


