import os
import re
import io
import csv
import json
import time
import math
import threading
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
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
from i18n import tr

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

Gst.init(None)


class BaseInput:
    """Base class for all LiteMix video and audio input sources."""

    def __init__(self, name: str, width: int = 1280, height: int = 720):
        self.name = name
        self.width = width
        self.height = height
        self.has_audio = False
        self.volume = 1.0  # 0.0 to 1.5
        self.muted = False
        self.vu_level = 0.0  # 0.0 to 1.0 for VU meters
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
        """Called once per render tick for procedural or GStreamer bus updates."""
        pass

    def stop(self):
        self.active = False


class TestPatternInput(BaseInput):
    """Animated broadcast test pattern (SMPTE color bars + studio clock + sync indicator)."""

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
    Transparent lower-third graphic overlay for overlay channels OV1 / OV2
    with 3 selectable broadcast design templates.
    """

    TEMPLATES = [
        (0, "1: Studio Cyan (Classic)"),
        (1, "2: TV News / Live Banner (Red/White)"),
        (2, "3: Modern Minimal / Talk Pill (Emerald)"),
    ]

    @classmethod
    def get_templates(cls) -> list[tuple[int, str]]:
        return [
            (0, tr("1: Studio Cyan (Klassisch)", "1: Studio Cyan (Classic)")),
            (1, tr("2: TV News / Live-Banner (Rot/Weiß)", "2: TV News / Live Banner (Red/White)")),
            (2, tr("3: Modern Minimal / Talk-Pill (Smaragd)", "3: Modern Minimal / Talk Pill (Emerald)")),
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
            # Template 0: Studio Cyan (Classic dark broadcast gradient with cyan accent bar)
            grad = QLinearGradient(bx, by, bx + bw, by)
            grad.setColorAt(0.0, QColor(14, 20, 32, 238))
            grad.setColorAt(0.85, QColor(20, 30, 48, 220))
            grad.setColorAt(1.0, QColor(20, 30, 48, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 8, 8)

            # Left cyan accent bar
            p.setBrush(QColor(0, 195, 255))
            p.drawRoundedRect(QRectF(bx, by, 10, bh), 4, 4)

            # Texts
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
            # Template 1: TV News / Live Banner (Two-tier broadcast look in Red/White/Charcoal)
            top_h = 56
            bot_h = 40
            slant = 18

            # Upper white/light-gray bar with slanted right edge
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

            # Red LIVE badge on top-left with slanted edge
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

            # Primary headline (dark text on white bar)
            p.setPen(QColor(16, 20, 28))
            p.setFont(QFont("Sans Serif", 21, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx + tag_w + 8, by + 2, bw - tag_w - 30, top_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.title,
            )

            # Lower charcoal bar with gold divider line
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

            # Gold accent line between upper and lower bars
            p.setBrush(QColor(255, 185, 15))
            p.drawRect(QRectF(bx, bot_y - 2, bot_w, 3))

            # Subtitle (gold on charcoal)
            p.setPen(QColor(255, 210, 90))
            p.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx + 18, bot_y + 2, bot_w - 36, bot_h - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )

        else:
            # Template 2: Modern Minimal / Talk Pill (Rounded capsule with emerald border & monogram badge)
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

            # Circular emerald/blue badge on the left
            circle_d = pill_h - 16
            cx = bx + 8
            cy = pill_y + 8
            c_grad = QLinearGradient(cx, cy, cx + circle_d, cy + circle_d)
            c_grad.setColorAt(0.0, QColor(0, 220, 140))
            c_grad.setColorAt(1.0, QColor(0, 140, 215))
            p.setBrush(QBrush(c_grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx, cy, circle_d, circle_d))

            # Extract initials from the title
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

            # Texts to the right of the monogram circle
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


class _SelectiveHTMLScraper(HTMLParser):
    """Lightweight standard-library HTML parser for targeted tag, class, or #id scraping."""

    IGNORED_TAGS = {"script", "style", "noscript", "svg", "head", "meta", "link"}

    def __init__(self, selectors: list[str] | None = None):
        super().__init__(convert_charrefs=True)
        self.selectors = [s.strip() for s in (selectors or []) if s.strip()]
        self._stack: list[tuple[str, set[str], str]] = []
        self._ignored_depth = 0
        self._capture_depth = 0
        self._current_chunks: list[str] = []
        self.results: list[str] = []

    def _matches_any(self, tag: str, classes: set[str], elem_id: str) -> bool:
        if not self.selectors:
            return tag in ("h1", "h2", "h3", "h4", "li", "tr", "p")
        for sel in self.selectors:
            s = sel.lower()
            if s.startswith("."):
                if s[1:] in classes:
                    return True
            elif s.startswith("#"):
                if elem_id == s[1:]:
                    return True
            elif "." in s:
                t_part, c_part = s.split(".", 1)
                if (not t_part or tag == t_part) and c_part in classes:
                    return True
            elif "#" in s:
                t_part, i_part = s.split("#", 1)
                if (not t_part or tag == t_part) and elem_id == i_part:
                    return True
            else:
                if tag == s:
                    return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        t = tag.lower()
        if t in self.IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth > 0:
            return

        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        classes = {c.strip().lower() for c in attr_dict.get("class", "").split() if c.strip()}
        elem_id = attr_dict.get("id", "").strip().lower()
        self._stack.append((t, classes, elem_id))

        if self._capture_depth > 0:
            self._capture_depth += 1
            if t in ("td", "th"):
                self._current_chunks.append(" | ")
            elif t == "br":
                self._current_chunks.append(" ")
        elif self._matches_any(t, classes, elem_id):
            self._capture_depth = 1
            self._current_chunks = []

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t in self.IGNORED_TAGS:
            if self._ignored_depth > 0:
                self._ignored_depth -= 1
            return
        if self._ignored_depth > 0:
            return
        if self._stack:
            self._stack.pop()
        if self._capture_depth > 0:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                raw = "".join(self._current_chunks)
                cleaned = re.sub(r"\s+", " ", raw).strip(" |\t\r\n")
                cleaned = re.sub(r"(?:\s*\|\s*)+", " | ", cleaned)
                if cleaned and cleaned not in self.results:
                    self.results.append(cleaned)
                self._current_chunks = []

    def handle_data(self, data: str):
        if self._ignored_depth == 0 and self._capture_depth > 0:
            self._current_chunks.append(data)


class DataScraperEngine:
    """
    Fetches and extracts structured text items from either a local file (.txt, .csv, .json, .xml, .html)
    or a web URL (HTML page, RSS/Atom feed, JSON API, plain text).
    """

    @classmethod
    def get_modes(cls) -> list[tuple[str, str]]:
        return [
            (
                "auto",
                tr(
                    "Automatisch (Überschriften, Tabellen, Listen, RSS, JSON, CSV)",
                    "Automatic (Headings, Tables, Lists, RSS, JSON, CSV)",
                ),
            ),
            (
                "css_tag",
                tr(
                    "HTML-Element / CSS-Klasse / #ID (z.B. h2, tr, .score, #news)",
                    "HTML Tag / CSS Class / #ID (e.g. h2, tr, .score, #news)",
                ),
            ),
            (
                "json_rss",
                tr(
                    "JSON-Pfad / Schlüssel oder XML/RSS-Tag (z.B. title, data.score)",
                    "JSON Key / Path or XML/RSS Tag (e.g. title, data.score)",
                ),
            ),
            (
                "lines_regex",
                tr(
                    "Zeilenfilter / Suchwort / Regex (z.B. 1-10 oder Tor|Ergebnis)",
                    "Line Range / Keyword / Regex (e.g. 1-10 or Goal|Score)",
                ),
            ),
        ]

    @classmethod
    def fetch_raw_content(cls, source: str) -> tuple[bool, str, str]:
        """Returns (ok, raw_text, content_hint_or_error)."""
        src = (source or "").strip()
        if not src:
            return False, "", tr("Keine URL oder Datei angegeben.", "No URL or file path specified.")

        expanded = os.path.expanduser(src)
        if os.path.isfile(expanded):
            try:
                with open(expanded, "rb") as f:
                    raw_bytes = f.read(2 * 1024 * 1024)
                try:
                    text = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw_bytes.decode("latin-1", errors="replace")
                ext = os.path.splitext(expanded)[1].lower()
                return True, text, ext
            except Exception as e:
                return False, "", f"{e}"

        url = src
        if not url.startswith(("http://", "https://", "file://")):
            if os.path.exists(expanded):
                return False, "", tr("Pfad ist keine reguläre Datei.", "Path is not a regular file.")
            url = "https://" + url

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LiteMix-HD/0.5",
                    "Accept": "text/html,application/xhtml+xml,application/json,application/xml,text/plain,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_bytes = resp.read(2 * 1024 * 1024)
                ctype = (resp.headers.get("Content-Type") or "").lower()
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_bytes.decode("latin-1", errors="replace")
            return True, text, ctype
        except Exception as e:
            return False, "", f"{e}"

    @classmethod
    def scrape(cls, source: str, mode: str = "auto", selector: str = "") -> tuple[bool, list[str], str]:
        """Fetches source and extracts clean string items according to mode and selector."""
        ok, raw, hint_or_err = cls.fetch_raw_content(source)
        if not ok:
            return False, [], hint_or_err

        sel = (selector or "").strip()
        mode = mode if mode in ("auto", "css_tag", "json_rss", "lines_regex") else "auto"
        items: list[str] = []

        try:
            if mode == "css_tag":
                sels = [s.strip() for s in sel.split(",") if s.strip()] if sel else ["h1", "h2", "h3", "tr", "li", "p"]
                parser = _SelectiveHTMLScraper(sels)
                parser.feed(raw)
                items = parser.results

            elif mode == "json_rss":
                stripped = raw.lstrip()
                if stripped.startswith(("{", "[")):
                    data = json.loads(stripped)
                    items = cls._extract_json_items(data, sel)
                else:
                    items = cls._extract_xml_items(raw, sel)

            elif mode == "lines_regex":
                # First convert HTML to readable lines if raw looks like HTML
                if "<html" in raw.lower() or "<body" in raw.lower() or "<div" in raw.lower():
                    parser = _SelectiveHTMLScraper(["h1", "h2", "h3", "h4", "tr", "li", "p", "div"])
                    parser.feed(raw)
                    base_lines = parser.results
                else:
                    base_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

                m_range = re.match(r"^(\d+)\s*-\s*(\d+)$", sel)
                if m_range:
                    i_start = max(1, int(m_range.group(1)))
                    i_end = max(i_start, int(m_range.group(2)))
                    items = base_lines[i_start - 1 : i_end]
                elif sel:
                    rx = re.compile(sel, re.IGNORECASE)
                    items = [ln for ln in base_lines if rx.search(ln)]
                else:
                    items = base_lines

            else:
                # mode == "auto"
                stripped = raw.lstrip()
                if stripped.startswith(("{", "[")):
                    try:
                        data = json.loads(stripped)
                        items = cls._extract_json_items(data, sel)
                    except Exception:
                        pass
                if not items and (stripped.startswith("<?xml") or "<rss" in stripped[:400].lower() or "<feed" in stripped[:400].lower()):
                    items = cls._extract_xml_items(raw, sel)
                if not items and ("<html" in raw.lower() or "<body" in raw.lower() or "<table" in raw.lower() or "<h1" in raw.lower() or "<p" in raw.lower()):
                    sels = [s.strip() for s in sel.split(",") if s.strip()] if sel else None
                    parser = _SelectiveHTMLScraper(sels)
                    parser.feed(raw)
                    items = parser.results
                if not items:
                    if hint_or_err == ".csv" or ("," in raw and "\n" in raw and len(raw.splitlines()) > 1 and not "<" in raw[:100]):
                        reader = csv.reader(io.StringIO(raw))
                        for row in reader:
                            cleaned_row = " | ".join(c.strip() for c in row if c.strip())
                            if cleaned_row:
                                items.append(cleaned_row)
                    else:
                        items = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                    if sel:
                        rx = re.compile(sel, re.IGNORECASE)
                        items = [ln for ln in items if rx.search(ln)]
        except Exception as e:
            return False, [], f"{e}"

        items = [it for it in items if it][:80]
        if not items:
            return False, [], tr("Keine passenden Einträge gefunden.", "No matching entries found.")
        return (
            True,
            items,
            tr(
                f"✓ {len(items)} Einträge erfolgreich geladen ({time.strftime('%H:%M:%S')})",
                f"✓ {len(items)} entries loaded ({time.strftime('%H:%M:%S')})",
            ),
        )

    @classmethod
    def _extract_json_items(cls, data, selector: str = "") -> list[str]:
        out: list[str] = []
        if selector:
            # Traverse dot path if applicable, or recursively match key name
            parts = [p for p in selector.split(".") if p]
            cur = data
            path_ok = True
            for p in parts:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                elif isinstance(cur, list) and p.isdigit() and 0 <= int(p) < len(cur):
                    cur = cur[int(p)]
                else:
                    path_ok = False
                    break
            if path_ok and cur is not data:
                if isinstance(cur, list):
                    for elem in cur:
                        out.append(cls._fmt_json_val(elem))
                elif isinstance(cur, dict):
                    for k, v in cur.items():
                        out.append(f"{k}: {cls._fmt_json_val(v)}")
                else:
                    out.append(str(cur))
                return [x for x in out if x]

            # Otherwise search recursively for keys matching selector
            key_low = selector.lower()

            def _walk(node):
                if isinstance(node, dict):
                    for k, v in node.items():
                        if key_low in str(k).lower() and not isinstance(v, (dict, list)):
                            out.append(f"{v}")
                        else:
                            _walk(v)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(data)
            return [x for x in out if x]

        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)):
                    out.append(f"{k}: {v}")
                elif isinstance(v, list):
                    for elem in v[:30]:
                        out.append(cls._fmt_json_val(elem))
                elif isinstance(v, dict):
                    summary = " | ".join(f"{sk}: {sv}" for sk, sv in list(v.items())[:5] if not isinstance(sv, (dict, list)))
                    if summary:
                        out.append(f"{k} -> {summary}")
        elif isinstance(data, list):
            for elem in data[:50]:
                out.append(cls._fmt_json_val(elem))
        return [x for x in out if x]

    @staticmethod
    def _fmt_json_val(val) -> str:
        if isinstance(val, dict):
            parts = []
            for k, v in list(val.items())[:6]:
                if not isinstance(v, (dict, list)):
                    parts.append(f"{k}: {v}")
            return " | ".join(parts) if parts else json.dumps(val, ensure_ascii=False)
        return str(val).strip()

    @classmethod
    def _extract_xml_items(cls, raw_xml: str, selector: str = "") -> list[str]:
        out: list[str] = []
        root = ET.fromstring(raw_xml)
        tag_filter = selector.strip().lower() if selector else ""
        if tag_filter:
            for elem in root.iter():
                local_name = elem.tag.split("}")[-1].lower()
                if local_name == tag_filter:
                    txt = "".join(elem.itertext()).strip()
                    txt = re.sub(r"\s+", " ", txt)
                    if txt:
                        out.append(txt)
            return out

        # Default RSS / Atom item extraction
        for elem in root.iter():
            local_name = elem.tag.split("}")[-1].lower()
            if local_name in ("item", "entry"):
                title_txt = ""
                desc_txt = ""
                for child in elem:
                    cname = child.tag.split("}")[-1].lower()
                    if cname == "title" and child.text:
                        title_txt = re.sub(r"\s+", " ", child.text).strip()
                    elif cname in ("description", "summary") and child.text:
                        # Strip inline HTML from RSS description
                        p = _SelectiveHTMLScraper(["p", "div", "span"])
                        p.feed(child.text)
                        raw_d = " ".join(p.results) if p.results else re.sub(r"<[^>]+>", " ", child.text)
                        desc_txt = re.sub(r"\s+", " ", raw_d).strip()
                if title_txt and desc_txt and desc_txt != title_txt:
                    out.append(f"{title_txt} — {desc_txt[:140]}")
                elif title_txt:
                    out.append(title_txt)
        if not out:
            for elem in root.iter():
                txt = (elem.text or "").strip()
                if txt and len(txt) > 1:
                    local_name = elem.tag.split("}")[-1]
                    out.append(f"{local_name}: {txt}")
        return out


class TextSlideInput(BaseInput):
    """
    Multi-line text, slide, ticker & web/file scraper source ('📝 Texttafel / Lauftext / Ticker'):
    Supports three display modes:
      1. Static / Multi-Slide Mode ('none' - split multiple slides via a line containing '---', 0% ongoing CPU load)
      2. Smooth Vertical Auto-Scroll / Teleprompter / Credits Mode ('vertical')
      3. Smooth Horizontal News Ticker / Crawl Mode ('horizontal' - right-to-left crawl)
    Includes an integrated File & Website Scraper with optional background auto-refresh and {1}, {2}, {all}, {ticker} placeholders.
    """

    @classmethod
    def get_bg_styles(cls) -> list[tuple[int, str]]:
        return [
            (0, tr("1: Transparente Overlay-Box (Alpha – ideal für OV1/OV2)", "1: Transparent Overlay Box (Alpha – ideal for OV1/OV2)")),
            (1, tr("2: Komplett Transparent (Nur Text mit Schatten – für Untertitel/Lyrics)", "2: Fully Transparent (Floating Text with Shadow – Lyrics/Subtitles)")),
            (2, tr("3: Studio Dunkelblau (Vollbild-Tafel)", "3: Studio Dark Blue (Fullscreen Slate)")),
            (3, tr("4: Broadcast Rot / Anthrazit (News- & Info-Tafel)", "4: Broadcast Red / Charcoal (News & Info Slate)")),
            (4, tr("5: Smaragd / Modern Grün (Talk- & Event-Tafel)", "5: Emerald / Modern Green (Talk & Event Slate)")),
            (5, tr("6: Nachrichten-Ticker / Laufband unten (Alpha – ideal für OV1/OV2)", "6: News Ticker / Bottom Crawl Bar (Alpha – ideal for OV1/OV2)")),
        ]

    @classmethod
    def get_scroll_modes(cls) -> list[tuple[str, str]]:
        return [
            ("none", tr("📄 Statisch / Folien-Modus (0% CPU)", "📄 Static / Slide Mode (0% CPU)")),
            ("vertical", tr("📜 Vertikaler Lauftext / Abspann (Von unten nach oben)", "📜 Vertical Auto-Scroll / Credits (Bottom to Top)")),
            ("horizontal", tr("📰 Horizontaler Nachrichten-Ticker (Von rechts nach links)", "📰 Horizontal News Ticker / Crawl (Right to Left)")),
        ]

    @classmethod
    def get_color_presets(cls) -> list[tuple[int, str, QColor, QColor]]:
        # (preset_id, label, body_color, accent_headline_color)
        return [
            (0, tr("Weiß & Cyan-Akzent", "White & Cyan Accent"), QColor(245, 248, 255), QColor(0, 212, 255)),
            (1, tr("Warmweiß & Gold-Akzent", "Warm White & Gold Accent"), QColor(255, 250, 238), QColor(255, 196, 35)),
            (2, tr("Mintweiß & Smaragd-Akzent", "Mint White & Emerald Accent"), QColor(240, 255, 248), QColor(40, 228, 145)),
            (3, tr("Weiß & Korallrot-Akzent", "White & Coral Red Accent"), QColor(255, 246, 246), QColor(255, 82, 98)),
            (4, tr("Reinweiß (Klassisch)", "Pure White (Classic)"), QColor(255, 255, 255), QColor(255, 255, 255)),
        ]

    @classmethod
    def get_align_options(cls) -> list[tuple[str, str]]:
        return [
            ("center", tr("Zentriert", "Centered")),
            ("left", tr("Linksbündig", "Left-aligned")),
            ("right", tr("Rechtsbündig", "Right-aligned")),
        ]

    def __init__(
        self,
        name: str = "",
        headline: str = "",
        body_text: str = "",
        width: int = 1280,
        height: int = 720,
        bg_style: int = 0,
        align_mode: str = "center",
        font_size: int = 32,
        color_preset: int = 0,
        scroll_enabled: bool = False,
        scroll_mode: str | None = None,
        scroll_speed: int = 65,
        loop_enabled: bool = True,
        return_to_preview_on_eos: bool = False,
        scraper_source: str = "",
        scraper_mode: str = "auto",
        scraper_selector: str = "",
        scraper_auto_refresh: bool = False,
        scraper_interval_sec: int = 30,
    ):
        default_name = name.strip() or tr("📝 Texttafel", "📝 Text Slide")
        super().__init__(default_name, width, height)
        self.headline = headline if headline != "" else tr("Information & Programm", "Information & Schedule")
        self.body_text = (
            body_text
            if body_text != ""
            else tr(
                "Willkommen bei der Live-Übertragung!\n"
                "• Punkt 1: Begrüßung & Einführung\n"
                "• Punkt 2: Hauptthema & Live-Demo\n"
                "• Punkt 3: Fragen & Antworten\n"
                "---\n"
                "Zweite Folie (durch --- getrennt):\n"
                "Vielen Dank fürs Zuschauen!",
                "Welcome to the Live Broadcast!\n"
                "• Part 1: Welcome & Introduction\n"
                "• Part 2: Main Topic & Live Demo\n"
                "• Part 3: Q&A Session\n"
                "---\n"
                "Second Slide (separated by ---):\n"
                "Thank you for watching!",
            )
        )
        self.bg_style = int(bg_style) % 6
        self.align_mode = align_mode if align_mode in ("center", "left", "right") else "center"
        self.font_size = max(16, min(72, int(font_size)))
        self.color_preset = int(color_preset) % 5

        if scroll_mode in ("none", "vertical", "horizontal"):
            self.scroll_mode = scroll_mode
        else:
            self.scroll_mode = "vertical" if scroll_enabled else "none"
        self.scroll_enabled = self.scroll_mode in ("vertical", "horizontal")
        self.scroll_speed = max(15, min(300, int(scroll_speed)))
        self.loop_enabled = bool(loop_enabled)
        self.return_to_preview_on_eos = bool(return_to_preview_on_eos)
        self.eos_return_pending = False

        # File / Website Data Scraper state
        self.scraper_source = str(scraper_source or "").strip()
        self.scraper_mode = scraper_mode if scraper_mode in ("auto", "css_tag", "json_rss", "lines_regex") else "auto"
        self.scraper_selector = str(scraper_selector or "").strip()
        self.scraper_auto_refresh = bool(scraper_auto_refresh)
        self.scraper_interval_sec = max(5, min(3600, int(scraper_interval_sec)))
        self.scraped_items: list[str] = []
        self.last_scrape_status: str = ""
        self._scrape_in_progress = False
        self._scrape_dirty = False
        self._last_scrape_time = 0.0

        self.current_slide_idx = 0
        self.paused = True
        self.scroll_offset = 0.0
        self._total_scroll_distance = 600.0
        self._last_tick_time = time.monotonic()
        self._render_slide_frame()
        if self.scraper_source and self.scraper_auto_refresh:
            self.trigger_scrape_async()

    def _resolve_placeholders(self, text: str) -> str:
        """Substitutes {1}, {2}, ..., {all}, {ticker}, {slides} with the latest scraped items."""
        if not text or not self.scraped_items or "{" not in text:
            return text
        out = text
        if "{all}" in out:
            out = out.replace("{all}", "\n".join(self.scraped_items))
        if "{ticker}" in out:
            out = out.replace("{ticker}", "   +++   ".join(self.scraped_items))
        if "{slides}" in out:
            out = out.replace("{slides}", "\n---\n".join(self.scraped_items))

        def _repl_num(match):
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(self.scraped_items):
                return self.scraped_items[idx]
            return match.group(0)

        return re.sub(r"\{(\d+)\}", _repl_num, out)

    def trigger_scrape_sync(self) -> tuple[bool, list[str], str]:
        """Synchronously scrapes the configured URL or local file and updates the frame."""
        ok, items, msg = DataScraperEngine.scrape(
            self.scraper_source, self.scraper_mode, self.scraper_selector
        )
        self._last_scrape_time = time.monotonic()
        self.last_scrape_status = msg
        if ok:
            self.scraped_items = items
            self._render_slide_frame()
        return ok, items, msg

    def trigger_scrape_async(self):
        """Runs the file/website scraper in a background daemon thread without blocking the 30 FPS render loop."""
        if self._scrape_in_progress or not self.scraper_source.strip():
            return
        self._scrape_in_progress = True
        self._last_scrape_time = time.monotonic()
        src = self.scraper_source
        mode = self.scraper_mode
        sel = self.scraper_selector

        def _worker():
            try:
                ok, items, msg = DataScraperEngine.scrape(src, mode, sel)
                self.last_scrape_status = msg
                if ok and items != self.scraped_items:
                    self.scraped_items = items
                    self._scrape_dirty = True
            finally:
                self._scrape_in_progress = False

        threading.Thread(target=_worker, daemon=True).start()

    def get_slides(self) -> list[str]:
        """Splits resolved body_text into slides by lines containing '---'."""
        resolved_body = self._resolve_placeholders(self.body_text or "")
        raw_lines = resolved_body.splitlines()
        slides: list[list[str]] = [[]]
        for line in raw_lines:
            if line.strip() == "---":
                slides.append([])
            else:
                slides[-1].append(line)
        cleaned = ["\n".join(chunk).strip("\r\n") for chunk in slides]
        return cleaned if cleaned else [""]

    def get_active_text(self) -> str:
        slides = self.get_slides()
        self.current_slide_idx = max(0, min(len(slides) - 1, self.current_slide_idx))
        if self.scroll_mode == "vertical" and len(slides) > 1:
            return "\n\n───  ✦  ───\n\n".join(s for s in slides if s.strip())
        if self.scroll_mode == "horizontal":
            # Flatten all non-empty lines into a single horizontal ticker line separated by '   +++   '
            all_lines = []
            for s in slides:
                for ln in s.splitlines():
                    c = ln.strip()
                    if c:
                        all_lines.append(c)
            return "   +++   ".join(all_lines) if all_lines else ""
        return slides[self.current_slide_idx]

    def select_slide(self, idx: int):
        slides = self.get_slides()
        self.current_slide_idx = max(0, min(len(slides) - 1, int(idx)))
        self.scroll_offset = 0.0
        self._render_slide_frame()

    def next_slide(self):
        slides = self.get_slides()
        if slides:
            self.current_slide_idx = (self.current_slide_idx + 1) % len(slides)
            self.scroll_offset = 0.0
            self._render_slide_frame()

    def prev_slide(self):
        slides = self.get_slides()
        if slides:
            self.current_slide_idx = (self.current_slide_idx - 1) % len(slides)
            self.scroll_offset = 0.0
            self._render_slide_frame()

    def cycle_scroll_mode(self) -> str:
        """Cycles between 'none' (Static) -> 'vertical' (Vertical Scroll) -> 'horizontal' (Horizontal Ticker)."""
        order = ["none", "vertical", "horizontal"]
        nxt = order[(order.index(self.scroll_mode) + 1) % len(order)] if self.scroll_mode in order else "vertical"
        self.set_config(scroll_mode=nxt)
        return self.scroll_mode

    def set_config(
        self,
        name: str | None = None,
        headline: str | None = None,
        body_text: str | None = None,
        bg_style: int | None = None,
        align_mode: str | None = None,
        font_size: int | None = None,
        color_preset: int | None = None,
        scroll_enabled: bool | None = None,
        scroll_mode: str | None = None,
        scroll_speed: int | None = None,
        scraper_source: str | None = None,
        scraper_mode: str | None = None,
        scraper_selector: str | None = None,
        scraper_auto_refresh: bool | None = None,
        scraper_interval_sec: int | None = None,
    ):
        if name is not None and name.strip():
            self.name = name.strip()
        if headline is not None:
            self.headline = headline
        if body_text is not None:
            self.body_text = body_text
        if bg_style is not None:
            self.bg_style = int(bg_style) % 6
        if align_mode in ("center", "left", "right"):
            self.align_mode = align_mode
        if font_size is not None:
            self.font_size = max(16, min(72, int(font_size)))
        if color_preset is not None:
            self.color_preset = int(color_preset) % 5

        prev_mode = self.scroll_mode
        if scroll_mode in ("none", "vertical", "horizontal"):
            self.scroll_mode = scroll_mode
            self.scroll_enabled = self.scroll_mode in ("vertical", "horizontal")
        elif scroll_enabled is not None:
            self.scroll_enabled = bool(scroll_enabled)
            if not self.scroll_enabled:
                self.scroll_mode = "none"
            elif self.scroll_mode == "none":
                self.scroll_mode = "horizontal" if self.bg_style == 5 else "vertical"

        if self.scroll_mode != prev_mode:
            self.scroll_offset = 0.0
            self._last_tick_time = time.monotonic()

        if scroll_speed is not None:
            self.scroll_speed = max(15, min(300, int(scroll_speed)))

        if scraper_source is not None:
            self.scraper_source = scraper_source.strip()
        if scraper_mode in ("auto", "css_tag", "json_rss", "lines_regex"):
            self.scraper_mode = scraper_mode
        if scraper_selector is not None:
            self.scraper_selector = scraper_selector.strip()
        if scraper_auto_refresh is not None:
            self.scraper_auto_refresh = bool(scraper_auto_refresh)
        if scraper_interval_sec is not None:
            self.scraper_interval_sec = max(5, min(3600, int(scraper_interval_sec)))

        slides = self.get_slides()
        self.current_slide_idx = max(0, min(len(slides) - 1, self.current_slide_idx))
        self._render_slide_frame()

    def play(self):
        if self.scroll_mode == "none":
            self.scroll_mode = "horizontal" if self.bg_style == 5 else "vertical"
            self.scroll_enabled = True
        if self._total_scroll_distance > 1.0 and self.scroll_offset >= self._total_scroll_distance - 2.0:
            self.scroll_offset = 0.0
        self.paused = False
        self._last_tick_time = time.monotonic()
        self._render_slide_frame()

    def pause(self):
        self.paused = True
        self._render_slide_frame()

    def toggle_pause(self):
        if self.paused:
            self.play()
        else:
            self.pause()

    def stop_playback(self):
        self.paused = True
        self.scroll_offset = 0.0
        self._render_slide_frame()

    def seek_seconds(self, target_sec: float):
        dur = max(0.5, self._total_scroll_distance / max(15.0, float(self.scroll_speed)))
        ratio = max(0.0, min(1.0, float(target_sec) / dur))
        self.scroll_offset = ratio * self._total_scroll_distance
        self._last_tick_time = time.monotonic()
        self._render_slide_frame()

    def get_position_duration(self) -> tuple[float, float]:
        if not self.scroll_enabled:
            return 0.0, 0.0
        spd = max(15.0, float(self.scroll_speed))
        dur = max(1.0, self._total_scroll_distance / spd)
        pos = max(0.0, min(dur, self.scroll_offset / spd))
        return pos, dur

    def update(self):
        now = time.monotonic()
        # Check background scraper auto-refresh timer
        if (
            self.scraper_auto_refresh
            and self.scraper_source
            and not self._scrape_in_progress
            and (now - self._last_scrape_time) >= float(self.scraper_interval_sec)
        ):
            self.trigger_scrape_async()

        if self._scrape_dirty:
            self._scrape_dirty = False
            self._render_slide_frame()

        if not self.scroll_enabled or self.paused:
            self._last_tick_time = now
            return
        dt = max(0.0, min(0.2, now - self._last_tick_time))
        self._last_tick_time = now
        if dt <= 0.0:
            return

        self.scroll_offset += float(self.scroll_speed) * dt
        if self.scroll_offset >= self._total_scroll_distance:
            if self.loop_enabled:
                self.scroll_offset = 0.0
            else:
                self.scroll_offset = self._total_scroll_distance
                self.paused = True
                if self.return_to_preview_on_eos:
                    self.eos_return_pending = True
        self._render_slide_frame()

    def _render_slide_frame(self):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        presets = self.get_color_presets()
        _, _, body_col, accent_col = presets[self.color_preset % len(presets)]
        headline_str = self._resolve_placeholders((self.headline or "").strip())
        active_text = self.get_active_text()

        # Special Broadcast Bottom News Ticker Bar (bg_style == 5)
        if self.bg_style == 5:
            bar_h = max(52.0, min(96.0, float(self.font_size + 24)))
            bar_y = float(self.height) - bar_h - 26.0
            bar_x = 0.0
            bar_w = float(self.width)

            bar_grad = QLinearGradient(0.0, bar_y, 0.0, bar_y + bar_h)
            bar_grad.setColorAt(0.0, QColor(14, 20, 32, 242))
            bar_grad.setColorAt(1.0, QColor(8, 12, 20, 248))
            p.fillRect(QRectF(bar_x, bar_y, bar_w, bar_h), bar_grad)

            # Top and bottom accent lines
            p.setPen(QPen(accent_col, 2.5))
            p.drawLine(QPointF(0.0, bar_y), QPointF(bar_w, bar_y))
            p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 140), 1.5))
            p.drawLine(QPointF(0.0, bar_y + bar_h), QPointF(bar_w, bar_y + bar_h))

            ticker_left = 24.0
            if headline_str:
                head_font = QFont("Sans Serif", max(14, int(self.font_size * 0.72)), QFont.Weight.Bold)
                p.setFont(head_font)
                hm = p.boundingRect(QRectF(0, 0, 500, bar_h), Qt.AlignmentFlag.AlignCenter, headline_str)
                badge_w = max(110.0, min(380.0, float(hm.width()) + 44.0))
                p.fillRect(QRectF(0.0, bar_y, badge_w, bar_h), accent_col)
                p.setPen(QColor(10, 14, 22))
                p.drawText(QRectF(14.0, bar_y, badge_w - 28.0, bar_h), Qt.AlignmentFlag.AlignCenter, headline_str)
                ticker_left = badge_w + 18.0

            ticker_w = max(120.0, bar_w - ticker_left - 18.0)
            ticker_rect = QRectF(ticker_left, bar_y, ticker_w, bar_h)

            body_font = QFont("Sans Serif", self.font_size, QFont.Weight.DemiBold)
            p.setFont(body_font)
            single_line = "   +++   ".join(ln.strip() for ln in active_text.splitlines() if ln.strip())
            m_rect = p.boundingRect(QRectF(0.0, 0.0, 100000.0, bar_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
            text_w = max(80.0, float(m_rect.width()))

            start_x_offset = ticker_w * 0.85
            self._total_scroll_distance = max(160.0, start_x_offset + text_w + 40.0)

            p.save()
            p.setClipRect(ticker_rect)
            if self.scroll_mode == "horizontal":
                draw_x = ticker_left + start_x_offset - self.scroll_offset
                draw_r = QRectF(draw_x, bar_y, text_w + 60.0, bar_h)
                p.setPen(QColor(0, 0, 0, 210))
                p.drawText(draw_r.translated(2.0, 2.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
                p.setPen(body_col)
                p.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
            else:
                p.setPen(QColor(0, 0, 0, 210))
                p.drawText(ticker_rect.translated(2.0, 2.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
                p.setPen(body_col)
                p.drawText(ticker_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
            p.restore()
            p.end()
            with self._lock:
                self._frame = img
            return

        bx, by = 76.0, 52.0
        bw, bh = float(self.width) - 152.0, float(self.height) - 104.0

        # 1. Render background style (0..4)
        if self.bg_style == 0:
            grad = QLinearGradient(bx, by, bx, by + bh)
            grad.setColorAt(0.0, QColor(14, 20, 32, 228))
            grad.setColorAt(1.0, QColor(10, 14, 24, 236))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 210), 2.5))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 16.0, 16.0)
        elif self.bg_style == 1:
            pass
        elif self.bg_style == 2:
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(12, 18, 34))
            bg_grad.setColorAt(0.5, QColor(20, 32, 56))
            bg_grad.setColorAt(1.0, QColor(10, 14, 26))
            p.fillRect(0, 0, self.width, self.height, bg_grad)

            p.setBrush(QColor(14, 22, 38, 215))
            p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 190), 2.0))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 16.0, 16.0)
        elif self.bg_style == 3:
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(38, 12, 18))
            bg_grad.setColorAt(0.5, QColor(24, 20, 30))
            bg_grad.setColorAt(1.0, QColor(12, 12, 18))
            p.fillRect(0, 0, self.width, self.height, bg_grad)

            p.setBrush(QColor(20, 16, 24, 220))
            p.setPen(QPen(QColor(235, 55, 65, 210), 2.5))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 16.0, 16.0)
        else:
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(10, 32, 26))
            bg_grad.setColorAt(0.5, QColor(16, 38, 42))
            bg_grad.setColorAt(1.0, QColor(10, 18, 24))
            p.fillRect(0, 0, self.width, self.height, bg_grad)

            p.setBrush(QColor(14, 26, 28, 220))
            p.setPen(QPen(QColor(40, 220, 145, 200), 2.0))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 16.0, 16.0)

        if self.align_mode == "left":
            h_align = Qt.AlignmentFlag.AlignLeft
        elif self.align_mode == "right":
            h_align = Qt.AlignmentFlag.AlignRight
        else:
            h_align = Qt.AlignmentFlag.AlignHCenter

        pad_x = 48.0
        inner_x = bx + pad_x
        inner_w = bw - 2.0 * pad_x
        body_top = by + 34.0

        # 2. Optional Headline at top
        if headline_str:
            head_font_sz = max(20, min(60, int(self.font_size * 1.18)))
            head_font = QFont("Sans Serif", head_font_sz, QFont.Weight.Bold)
            p.setFont(head_font)
            head_rect = QRectF(inner_x, by + 22.0, inner_w, float(head_font_sz + 24))

            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(head_rect.translated(2.0, 2.0), h_align | Qt.AlignmentFlag.AlignVCenter, headline_str)

            p.setPen(accent_col)
            p.drawText(head_rect, h_align | Qt.AlignmentFlag.AlignVCenter, headline_str)

            div_y = head_rect.bottom() + 8.0
            p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 145), 2.0))
            p.drawLine(QPointF(inner_x, div_y), QPointF(inner_x + inner_w, div_y))
            body_top = div_y + 18.0

        body_bottom = by + bh - 28.0
        body_h = max(80.0, body_bottom - body_top)
        body_rect = QRectF(inner_x, body_top, inner_w, body_h)

        # 3. Render body text (Static vs. Vertical Auto-Scroll vs. Horizontal Ticker)
        body_font = QFont("Sans Serif", self.font_size, QFont.Weight.DemiBold)
        p.setFont(body_font)

        p.save()
        p.setClipRect(body_rect)

        if self.scroll_mode == "horizontal":
            single_line = "   +++   ".join(ln.strip() for ln in active_text.splitlines() if ln.strip())
            m_rect = p.boundingRect(
                QRectF(0.0, 0.0, 100000.0, body_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                single_line,
            )
            text_w = max(80.0, float(m_rect.width()))
            start_x_offset = inner_w * 0.85
            self._total_scroll_distance = max(160.0, start_x_offset + text_w + 40.0)
            draw_x = inner_x + start_x_offset - self.scroll_offset
            draw_r = QRectF(draw_x, body_top, text_w + 60.0, body_h)
            p.setPen(QColor(0, 0, 0, 210))
            p.drawText(draw_r.translated(2.0, 2.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
            p.setPen(body_col)
            p.drawText(draw_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, single_line)
        elif self.scroll_mode == "vertical":
            wrap_flags = h_align | Qt.TextFlag.TextWordWrap
            measured = p.boundingRect(QRectF(0.0, 0.0, inner_w, 20000.0), wrap_flags, active_text)
            text_h = max(float(self.font_size + 10), float(measured.height()))
            start_y_offset = body_h * 0.72
            self._total_scroll_distance = max(120.0, start_y_offset + text_h + 24.0)
            draw_y = body_top + start_y_offset - self.scroll_offset
            draw_rect = QRectF(inner_x, draw_y, inner_w, text_h + 40.0)
            p.setPen(QColor(0, 0, 0, 210))
            p.drawText(draw_rect.translated(2.0, 2.0), wrap_flags | Qt.AlignmentFlag.AlignTop, active_text)
            p.setPen(body_col)
            p.drawText(draw_rect, wrap_flags | Qt.AlignmentFlag.AlignTop, active_text)
        else:
            wrap_flags = h_align | Qt.TextFlag.TextWordWrap
            measured = p.boundingRect(QRectF(0.0, 0.0, inner_w, 20000.0), wrap_flags, active_text)
            text_h = max(float(self.font_size + 10), float(measured.height()))
            v_align = Qt.AlignmentFlag.AlignVCenter if text_h <= body_h else Qt.AlignmentFlag.AlignTop
            p.setPen(QColor(0, 0, 0, 210))
            p.drawText(body_rect.translated(2.0, 2.0), wrap_flags | v_align, active_text)
            p.setPen(body_col)
            p.drawText(body_rect, wrap_flags | v_align, active_text)

        p.restore()

        # 4. Slide counter badge if multiple slides exist in static mode
        slides = self.get_slides()
        if len(slides) > 1 and self.scroll_mode == "none":
            badge_txt = f"{self.current_slide_idx + 1} / {len(slides)}"
            p.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
            b_rect = QRectF(bx + bw - 86.0, by + bh - 34.0, 68.0, 24.0)
            p.setBrush(QColor(10, 14, 22, 190))
            p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 150), 1.2))
            p.drawRoundedRect(b_rect, 6.0, 6.0)
            p.setPen(accent_col)
            p.drawText(b_rect, Qt.AlignmentFlag.AlignCenter, badge_txt)

        p.end()
        with self._lock:
            self._frame = img


class SplitScreenInput(BaseInput):
    """
    2-Way Split-Screen / Interview Multi-View source ('👥 2er Split-Screen / Interview'):
    Combines any two live sources from the input grid side-by-side in real time.
    Supports 4 broadcast layouts (50/50 16:9 Cards, 50/50 Fullscreen Center-Crop, 65/35 Host+Guest, 35/65 Guest+Host),
    4 background themes (including Alpha transparency), speaker name badges, and one-click Left/Right swap (⇄).
    """

    @classmethod
    def get_layout_styles(cls) -> list[tuple[int, str]]:
        return [
            (0, tr("1: Klassisch 50 / 50 (Zwei 16:9-Fenster mit Studio-Hintergrund)", "1: Classic 50 / 50 (Two 16:9 Windows on Studio Background)")),
            (1, tr("2: Vollbild 50 / 50 (Nahtlos geteilter Bildschirm – Crop-Fill)", "2: Fullscreen 50 / 50 (Seamless Split Screen – Center Crop)")),
            (2, tr("3: Moderator + Gast 65 / 35 (Groß links + Kompakt rechts)", "3: Host + Guest 65 / 35 (Large Left + Compact Right)")),
            (3, tr("4: Gast + Moderator 35 / 65 (Kompakt links + Groß rechts)", "4: Guest + Host 35 / 65 (Compact Left + Large Right)")),
        ]

    get_layouts = get_layout_styles

    @classmethod
    def get_bg_styles(cls) -> list[tuple[int, str]]:
        return [
            (0, tr("1: Studio Dunkelblau (Cyan-Akzent)", "1: Studio Dark Blue (Cyan Accent)")),
            (1, tr("2: Broadcast Rot / Anthrazit (News-Design)", "2: Broadcast Red / Charcoal (News Theme)")),
            (2, tr("3: Smaragd / Modern Grün (Talk-Design)", "3: Emerald / Modern Green (Talk Theme)")),
            (3, tr("4: Transparent (Alpha – ideal für OV1/OV2 über Video)", "4: Transparent (Alpha – ideal for OV1/OV2 over video)")),
        ]

    def __init__(
        self,
        name: str = "",
        left_idx: int = 0,
        right_idx: int = 1,
        layout_style: int = 0,
        bg_style: int = 0,
        headline: str = "",
        left_label: str = "",
        right_label: str = "",
        show_labels: bool = True,
        show_borders: bool = True,
        width: int = 1280,
        height: int = 720,
    ):
        default_name = name.strip() or tr("👥 2er Split-Screen", "👥 2-Way Split-Screen")
        super().__init__(default_name, width, height)
        self.left_idx = max(0, int(left_idx))
        self.right_idx = max(0, int(right_idx))
        self.layout_style = int(layout_style) % 4
        self.bg_style = int(bg_style) % 4
        self.headline = headline if headline != "" else tr("LIVE • INTERVIEW", "LIVE • INTERVIEW")
        self.left_label = left_label
        self.right_label = right_label
        self.show_labels = bool(show_labels)
        self.show_borders = bool(show_borders)
        self.source_provider = None  # Callable returning list[BaseInput]
        self.render_from_sources([])

    def swap_sides(self):
        """Swaps Left and Right sources and their custom speaker labels."""
        self.left_idx, self.right_idx = self.right_idx, self.left_idx
        self.left_label, self.right_label = self.right_label, self.left_label
        if callable(self.source_provider):
            self.render_from_sources(self.source_provider())

    def set_config(
        self,
        name: str | None = None,
        left_idx: int | None = None,
        right_idx: int | None = None,
        layout_style: int | None = None,
        bg_style: int | None = None,
        headline: str | None = None,
        left_label: str | None = None,
        right_label: str | None = None,
        show_labels: bool | None = None,
        show_borders: bool | None = None,
    ):
        if name is not None and name.strip():
            self.name = name.strip()
        if left_idx is not None:
            self.left_idx = max(0, int(left_idx))
        if right_idx is not None:
            self.right_idx = max(0, int(right_idx))
        if layout_style is not None:
            self.layout_style = int(layout_style) % 4
        if bg_style is not None:
            self.bg_style = int(bg_style) % 4
        if headline is not None:
            self.headline = headline
        if left_label is not None:
            self.left_label = left_label
        if right_label is not None:
            self.right_label = right_label
        if show_labels is not None:
            self.show_labels = bool(show_labels)
        if show_borders is not None:
            self.show_borders = bool(show_borders)
        if callable(self.source_provider):
            self.render_from_sources(self.source_provider())
        else:
            self.render_from_sources([])

    def update(self):
        if callable(self.source_provider):
            self.render_from_sources(self.source_provider())

    def _get_safe_source_frame(self, sources: list[BaseInput], idx: int) -> tuple[QImage | None, str]:
        if 0 <= idx < len(sources):
            src = sources[idx]
            if src is not self and not isinstance(src, SplitScreenInput):
                return src.get_frame(), src.name
        return None, tr(f"Quelle {idx + 1}", f"Source {idx + 1}")

    def render_from_sources(self, sources: list[BaseInput]):
        img = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if self.bg_style == 0:
            accent_col = QColor(0, 210, 255)
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(12, 18, 34))
            bg_grad.setColorAt(0.5, QColor(22, 34, 60))
            bg_grad.setColorAt(1.0, QColor(10, 14, 24))
        elif self.bg_style == 1:
            accent_col = QColor(245, 60, 75)
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(36, 12, 18))
            bg_grad.setColorAt(0.5, QColor(24, 20, 30))
            bg_grad.setColorAt(1.0, QColor(12, 12, 18))
        elif self.bg_style == 2:
            accent_col = QColor(40, 228, 145)
            bg_grad = QLinearGradient(0, 0, self.width, self.height)
            bg_grad.setColorAt(0.0, QColor(10, 32, 26))
            bg_grad.setColorAt(0.5, QColor(16, 40, 44))
            bg_grad.setColorAt(1.0, QColor(10, 18, 24))
        else:
            accent_col = QColor(0, 210, 255)
            bg_grad = None

        if bg_grad is not None and self.layout_style != 1:
            p.fillRect(0, 0, self.width, self.height, bg_grad)

        left_frm, left_src_name = self._get_safe_source_frame(sources, self.left_idx)
        right_frm, right_src_name = self._get_safe_source_frame(sources, self.right_idx)
        lbl_l = self.left_label.strip() or left_src_name
        lbl_r = self.right_label.strip() or right_src_name

        # Layout 1: Seamless 50/50 Fullscreen Center-Crop
        if self.layout_style == 1:
            half_w = self.width // 2
            h = self.height
            for side_i, (frm, dest_x) in enumerate([(left_frm, 0), (right_frm, half_w)]):
                dest_rect = QRectF(float(dest_x), 0.0, float(half_w), float(h))
                p.fillRect(dest_rect, QColor(14, 18, 26))
                if frm is not None and not frm.isNull():
                    fw, fh = frm.width(), frm.height()
                    crop_w = max(1, fw // 2)
                    crop_x = (fw - crop_w) // 2
                    sub = frm.copy(crop_x, 0, crop_w, fh)
                    p.drawImage(dest_rect, sub)
            if self.show_borders:
                p.setPen(QPen(accent_col, 4.0))
                p.drawLine(QPointF(float(half_w), 0.0), QPointF(float(half_w), float(h)))
            if self.show_labels:
                self._draw_speaker_pill(p, QRectF(28.0, float(h - 68), float(half_w - 56), 42.0), lbl_l, accent_col)
                self._draw_speaker_pill(p, QRectF(float(half_w + 28), float(h - 68), float(half_w - 56), 42.0), lbl_r, accent_col)
            if self.headline.strip():
                self._draw_top_header_pill(p, self.headline.strip(), accent_col)
            p.end()
            with self._lock:
                self._frame = img
            return

        # Layouts 0, 2, 3: Framed 16:9 Broadcast Boxes
        if self.layout_style == 0:
            r_left = QRectF(42.0, 178.0, 576.0, 324.0)
            r_right = QRectF(662.0, 178.0, 576.0, 324.0)
        elif self.layout_style == 2:
            r_left = QRectF(42.0, 142.0, 720.0, 405.0)
            r_right = QRectF(794.0, 220.0, 444.0, 250.0)
        else:
            r_left = QRectF(42.0, 220.0, 444.0, 250.0)
            r_right = QRectF(518.0, 142.0, 720.0, 405.0)

        if self.headline.strip():
            self._draw_top_header_pill(p, self.headline.strip(), accent_col)

        for box_rect, frm, spk_lbl in [(r_left, left_frm, lbl_l), (r_right, right_frm, lbl_r)]:
            # Drop shadow
            p.setBrush(QColor(0, 0, 0, 135))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(box_rect.translated(6.0, 8.0), 10.0, 10.0)

            p.fillRect(box_rect, QColor(12, 16, 24))
            if frm is not None and not frm.isNull():
                p.drawImage(box_rect, frm)

            if self.show_borders:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(accent_col, 3.0))
                p.drawRoundedRect(box_rect, 8.0, 8.0)

            if self.show_labels and spk_lbl:
                pill_r = QRectF(box_rect.left() + 14.0, box_rect.bottom() + 14.0, box_rect.width() - 28.0, 38.0)
                self._draw_speaker_pill(p, pill_r, spk_lbl, accent_col)

        p.end()
        with self._lock:
            self._frame = img

    def _draw_top_header_pill(self, p: QPainter, text: str, accent_col: QColor):
        p.setFont(QFont("Sans Serif", 18, QFont.Weight.Bold))
        m = p.boundingRect(QRectF(0, 0, 900, 50), Qt.AlignmentFlag.AlignCenter, text)
        pw = max(240.0, min(760.0, float(m.width()) + 70.0))
        ph = 46.0
        px = (self.width - pw) * 0.5
        py = 34.0
        p.setBrush(QColor(12, 16, 26, 232))
        p.setPen(QPen(accent_col, 2.0))
        p.drawRoundedRect(QRectF(px, py, pw, ph), 23.0, 23.0)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(px + 16.0, py, pw - 32.0, ph), Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _draw_speaker_pill(p: QPainter, rect: QRectF, label: str, accent_col: QColor):
        p.setBrush(QColor(12, 16, 26, 228))
        p.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 190), 1.8))
        p.drawRoundedRect(rect, 8.0, 8.0)
        p.setBrush(accent_col)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), 8.0, rect.height()), 4.0, 4.0)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Sans Serif", 14, QFont.Weight.Bold))
        p.drawText(
            QRectF(rect.left() + 18.0, rect.top(), rect.width() - 28.0, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )


class ImageInput(BaseInput):
    """Static image source (PNG/JPG/SVG) including alpha transparency for overlays or fullscreen."""

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
    """Common base class for all GStreamer-powered video/audio sources (including slow-motion control)."""

    def __init__(self, name: str, width: int = 1280, height: int = 720):
        super().__init__(name, width, height)
        self.pipeline = None
        self.vsink = None
        self.vol_element = None
        self.loop_enabled = False
        self.return_to_preview_on_eos = False
        self.eos_return_pending = False
        self.paused = False
        self.playback_rate = 1.0  # 1.0 = real-time, 0.5 = 50% slow-mo, 0.25 = 25% super slow-mo
        self._pending_rate_apply = False
        self.afv_gain = 1.0  # Audio-Follow-Video factor (1.0 = live/active, 0.0 = muted in Preview/grid)

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
        """Change playback speed (e.g., 0.25, 0.5, 0.75, 1.0) while preserving current position."""
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
                    # Noise gate below -38 dB (filters out background noise floor)
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
        """Stop playback and rewind to the beginning (00:00)."""
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
        """Seek accurately to the specified position in seconds."""
        if not self.pipeline:
            return
        target_ns = max(0, int(target_sec * Gst.SECOND))
        self._seek_with_rate(target_ns, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE)

    def get_position_duration(self) -> tuple[float, float]:
        """Return (current_position_seconds, total_duration_seconds)."""
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
    """Plays MP4/MKV/WebM video files with lip-sync via playbin, Loop, Audio-Follow-Video, and live VU meter."""

    def __init__(self, filepath: str, width: int = 1280, height: int = 720):
        name = f"Video: {os.path.basename(filepath)}"
        super().__init__(name, width, height)
        self.filepath = os.path.abspath(filepath)
        self.has_audio = True
        self.afv_gain = 0.0  # Audible only when active in Program (Live), Preview (playing), or Overlay
        uri = Gst.filename_to_uri(self.filepath)

        try:
            self.paused = True
            self.pipeline = Gst.ElementFactory.make("playbin", "player")
            self.pipeline.set_property("uri", uri)
            # flags=0x00000003: Decode only 1 video track + 1 audio track (ignores subtitles & secondary tracks)
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
            print(f"[VideoFileInput] Failed to start pipeline: {e}")


class V4L2CameraInput(GStreamerBaseInput):
    """Captures webcams or USB capture cards via Video4Linux2 (/dev/videoX) with horizontal mirror option."""

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
    Captures any application/browser window or monitor under Wayland
    via the official XDG Desktop Portal (ScreenCast) + PipeWire.
    """

    def __init__(self, name: str = "Fenster / Browser (Wayland)", width: int = 1280, height: int = 720):
        super().__init__(name, width, height)
        self.loop_enabled = False
        self._portal_session = None
        self._render_waiting_message(
            tr("Fenster-Auswahl im Systemdialog geöffnet...", "Window selection opened in system dialog...")
        )
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
                # types=3 allows both monitor (1) and individual window/browser (2)
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
                    self._render_waiting_message(tr("Keine Quelle ausgewählt.", "No source selected."))
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
                    self._render_waiting_message(
                        tr("Fenster-Aufnahme vom Nutzer abgebrochen.", "Window capture cancelled by user.")
                    )
                    return
                streams = results['streams']
                if not streams:
                    self._render_waiting_message(
                        tr("Kein PipeWire-Stream erhalten.", "No PipeWire stream received.")
                    )
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
            self._render_waiting_message(f"Portal Error: {e}")

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
            self._render_waiting_message(f"PipeWire Error: {e}")


class WebBrowserWindow(QWidget):
    """Dedicated interactive browser window whose rendered surface is captured as a LiteMix input."""

    def __init__(self, url: str, width: int = 1280, height: int = 720):
        super().__init__()
        self.setWindowTitle(f"LiteMix Browser – {url}")
        self.resize(1024, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        nav = QHBoxLayout()
        self.url_edit = QLineEdit(url)
        btn_go = QPushButton(tr("Laden", "Go"))
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
    """Integrated web browser input powered by QtWebEngine with audio mute control."""

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
    Base class for audio-only sources (microphones, system audio, music/jingles).
    Renders a live audio level visualization onto the preview frame.
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
                status = tr("🔇 STUMMGESCHALTET (MUTE)", "🔇 MUTED")
                scol = QColor(240, 70, 70)
            elif self.paused:
                status = tr("⏸ PAUSIERT", "⏸ PAUSED")
                scol = QColor(240, 190, 50)
            else:
                status = tr(
                    f"● AKTIV  |  Lautstärke: {int(self.volume * 100)}%",
                    f"● ACTIVE  |  Volume: {int(self.volume * 100)}%",
                )
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
    """Captures a specific microphone / line-in / USB audio interface as an individual source."""

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
            print(f"[MicDeviceInput] Error: {e}")


class SystemAudioInput(AudioInputBase):
    """Captures desktop/system audio (e.g., browser, YouTube, Zoom) via a PipeWire/PulseAudio monitor source."""

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
            print(f"[SystemAudioInput] Error: {e}")


class AudioFileInput(AudioInputBase):
    """Plays music, jingles, or sound effects (MP3, WAV, FLAC, OGG) with Play/Pause/Loop/Auto-Return controls."""

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
            print(f"[AudioFileInput] Error: {e}")


class ReplaySourceInput(GStreamerBaseInput):
    """
    Special source '⏪ Letztes Replay' / '⏪ Last Replay':
    Automatically provides the most recently recorded instant replay clip
    (defaults to 0.5x slow motion, switchable between 0.25x / 0.5x / 0.75x / 1.0x).
    """

    SPEED_OPTIONS = [
        (0.25, "0.25× (Super Slow-Mo)"),
        (0.50, "0.50× (Half Speed)"),
        (0.75, "0.75× (Slow Motion)"),
        (1.00, "1.00× (Normal Speed)"),
    ]

    @classmethod
    def get_speed_options(cls) -> list[tuple[float, str]]:
        return [
            (0.25, tr("0.25× (Super-Zeitlupe / Viertel-Tempo)", "0.25× (Super Slow-Mo / Quarter Speed)")),
            (0.50, tr("0.50× (Halbes Tempo – Standard)", "0.50× (Half Speed – Default)")),
            (0.75, tr("0.75× (Leichte Zeitlupe)", "0.75× (Light Slow Motion)")),
            (1.00, tr("1.00× (Echtzeit / Normaltempo)", "1.00× (Real-Time / Normal Speed)")),
        ]

    def __init__(self, filepath: str = "", width: int = 1280, height: int = 720, playback_rate: float = 0.5):
        super().__init__(tr("⏪ Letztes Replay", "⏪ Last Replay"), width, height)
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
        p.drawText(
            QRectF(cx, cy + 26, card_w, 42),
            Qt.AlignmentFlag.AlignCenter,
            tr("⏪ Letztes Replay", "⏪ Last Replay"),
        )

        p.setPen(QColor(150, 165, 190))
        p.setFont(QFont("Sans Serif", 13))
        p.drawText(
            QRectF(cx + 20, cy + 82, card_w - 40, 48),
            Qt.AlignmentFlag.AlignCenter,
            tr(
                "Klicke in der Mittelspalte auf [⏺ REPLAY], um eine Szene aufzuzeichnen.",
                "Click [⏺ REPLAY] in the center column to record a live scene.",
            ),
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
            self.pipeline.set_property("flags", 0x00000001)  # Video-only decoding (optimal for smooth slow motion)

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
            print(f"[ReplaySourceInput] Failed to load replay clip: {e}")


class HighlightsInput(GStreamerBaseInput):
    """
    Special source '⭐ Highlights':
    Automatically collects all recorded instant replays as a playlist / highlight archive
    and plays them individually or sequentially (including slow motion 0.25x / 0.5x / 0.75x / 1.0x).
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
        p.drawText(
            QRectF(cx, cy + 26, card_w, 42),
            Qt.AlignmentFlag.AlignCenter,
            tr("⭐ Highlights (Archiv)", "⭐ Highlights (Archive)"),
        )

        p.setPen(QColor(185, 175, 155))
        p.setFont(QFont("Sans Serif", 13))
        p.drawText(
            QRectF(cx + 20, cy + 82, card_w - 40, 48),
            Qt.AlignmentFlag.AlignCenter,
            tr(
                "Alle aufgezeichneten Replays werden hier automatisch als Highlights gesammelt.",
                "All recorded replays are automatically collected here as highlights.",
            ),
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
        # If no clip was loaded yet, load the first clip into paused state immediately:
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
    """Serialize an input source into a dictionary for saving in a .litemix preset file."""
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
    elif isinstance(inp, TextSlideInput):
        d["headline"] = inp.headline
        d["body_text"] = inp.body_text
        d["bg_style"] = inp.bg_style
        d["align_mode"] = inp.align_mode
        d["font_size"] = inp.font_size
        d["color_preset"] = inp.color_preset
        d["scroll_enabled"] = bool(inp.scroll_enabled)
        d["scroll_mode"] = inp.scroll_mode
        d["scroll_speed"] = int(inp.scroll_speed)
        d["loop_enabled"] = bool(inp.loop_enabled)
        d["return_to_preview_on_eos"] = bool(inp.return_to_preview_on_eos)
        d["current_slide_idx"] = int(inp.current_slide_idx)
        d["scraper_source"] = inp.scraper_source
        d["scraper_mode"] = inp.scraper_mode
        d["scraper_selector"] = inp.scraper_selector
        d["scraper_auto_refresh"] = bool(inp.scraper_auto_refresh)
        d["scraper_interval_sec"] = int(inp.scraper_interval_sec)
    elif isinstance(inp, SplitScreenInput):
        d["left_idx"] = int(inp.left_idx)
        d["right_idx"] = int(inp.right_idx)
        d["layout_style"] = int(inp.layout_style)
        d["bg_style"] = int(inp.bg_style)
        d["headline"] = inp.headline
        d["left_label"] = inp.left_label
        d["right_label"] = inp.right_label
        d["show_labels"] = bool(inp.show_labels)
        d["show_borders"] = bool(inp.show_borders)
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
    """Instantiate an input source from a saved preset dictionary."""
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
    elif t == "TextSlideInput":
        inp = TextSlideInput(
            name=name,
            headline=data.get("headline", ""),
            body_text=data.get("body_text", ""),
            width=width,
            height=height,
            bg_style=int(data.get("bg_style", 0)),
            align_mode=str(data.get("align_mode", "center")),
            font_size=int(data.get("font_size", 32)),
            color_preset=int(data.get("color_preset", 0)),
            scroll_enabled=bool(data.get("scroll_enabled", False)),
            scroll_mode=data.get("scroll_mode"),
            scroll_speed=int(data.get("scroll_speed", 65)),
            loop_enabled=bool(data.get("loop_enabled", True)),
            return_to_preview_on_eos=bool(data.get("return_to_preview_on_eos", False)),
            scraper_source=str(data.get("scraper_source", "")),
            scraper_mode=str(data.get("scraper_mode", "auto")),
            scraper_selector=str(data.get("scraper_selector", "")),
            scraper_auto_refresh=bool(data.get("scraper_auto_refresh", False)),
            scraper_interval_sec=int(data.get("scraper_interval_sec", 30)),
        )
        if "current_slide_idx" in data:
            inp.select_slide(int(data.get("current_slide_idx", 0)))
    elif t == "SplitScreenInput":
        inp = SplitScreenInput(
            name=name,
            left_idx=int(data.get("left_idx", 0)),
            right_idx=int(data.get("right_idx", 1)),
            layout_style=int(data.get("layout_style", 0)),
            bg_style=int(data.get("bg_style", 0)),
            headline=data.get("headline", ""),
            left_label=data.get("left_label", ""),
            right_label=data.get("right_label", ""),
            show_labels=bool(data.get("show_labels", True)),
            show_borders=bool(data.get("show_borders", True)),
            width=width,
            height=height,
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


