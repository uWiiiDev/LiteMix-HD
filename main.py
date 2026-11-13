import os
import sys
import glob
import json
import time
import shutil
import tarfile
import tempfile
import subprocess
import urllib.request
import urllib.error
import collections
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QFont, QPen, QAction, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QSlider, QSpinBox, QFileDialog,
    QInputDialog, QFrame, QScrollArea, QMessageBox, QDialog, QFormLayout,
    QLineEdit, QMenu, QComboBox, QKeySequenceEdit, QSizePolicy,
    QPlainTextEdit, QCheckBox, QListWidget, QListWidgetItem
)

from inputs import (
    BaseInput, TestPatternInput, LowerThirdInput, TextSlideInput, DataScraperEngine,
    ImageInput, VideoFileInput, V4L2CameraInput, WaylandPortalInput, WebBrowserInput,
    AudioInputBase, MicDeviceInput, SystemAudioInput, AudioFileInput,
    ReplaySourceInput, HighlightsInput,
    serialize_input, deserialize_input, HAS_WEBENGINE
)
from audio_mixer import MicAudioMonitor, list_audio_devices
from recorder import VAAPIRecorder, VAAPIStreamer, VAAPIReplayRecorder
from web_remote import WebRemoteController, WebRemoteDialog
from i18n import tr, get_lang, set_lang, toggle_lang, HelpDialog


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #14171d;
    color: #e4e8f0;
    font-family: 'Sans Serif';
    font-size: 11px;
}
QFrame#PanelFrame {
    background-color: #1c2029;
    border: 1px solid #2b3140;
    border-radius: 5px;
}
QPushButton {
    background-color: #282e3d;
    color: #e4e8f0;
    border: 1px solid #384154;
    border-radius: 4px;
    padding: 3px 8px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #343c50;
}
QPushButton:pressed {
    background-color: #1e2330;
}
QPushButton#AddInputBtn {
    background-color: #1b5e3c;
    border: 1px solid #289c60;
    color: #ffffff;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QPushButton#AddInputBtn:hover {
    background-color: #23784d;
}
QPushButton#FooterIconBtn {
    background-color: #262c3a;
    border: 1px solid #3c455c;
    color: #e4e8f0;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QPushButton#FooterIconBtn:hover {
    background-color: #343c50;
}
QPushButton#CutBtn {
    background-color: #b82828;
    border: 1px solid #e04040;
    font-size: 12px;
    padding: 5px;
}
QPushButton#CutBtn:hover {
    background-color: #d63030;
}
QPushButton#FadeBtn {
    background-color: #1e6b9e;
    border: 1px solid #2fa0eb;
    font-size: 12px;
    padding: 5px;
}
QPushButton#FadeBtn:hover {
    background-color: #2582bf;
}
QPushButton#RecBtn {
    background-color: #2b3344;
    border: 1px solid #48546e;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QPushButton#RecBtnActive {
    background-color: #d92020;
    color: #ffffff;
    border: 1px solid #ff5050;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QPushButton#StreamBtn {
    background-color: #1c3d5e;
    border: 1px solid #2e6da4;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QPushButton#StreamBtn:hover {
    background-color: #244f7a;
}
QPushButton#StreamBtnActive {
    background-color: #e06010;
    color: #ffffff;
    border: 1px solid #ff9040;
    font-size: 16px;
    padding: 2px 10px;
    min-width: 38px;
    min-height: 28px;
}
QMenu {
    background-color: #1c2029;
    color: #e4e8f0;
    border: 1px solid #384154;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 3px;
}
QMenu::item:selected {
    background-color: #2582bf;
    color: #ffffff;
}
QSlider::groove:vertical {
    background: #282e3d;
    width: 8px;
    border-radius: 4px;
}
QSlider::handle:vertical {
    background: #00c8ff;
    height: 18px;
    margin: 0 -5px;
    border-radius: 4px;
}
QSlider::groove:horizontal {
    background: #282e3d;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #00c8ff;
    width: 12px;
    margin: -4px 0;
    border-radius: 4px;
}
"""


class VideoMonitorWidget(QWidget):
    """
    Displays a 16:9 video monitor (Preview or Program) with a broadcast border.
    In the Program monitor, active overlays (OV1 & OV2) can be freely dragged with
    the mouse, resized via 8 corner/edge handles or the mouse wheel, and aligned
    via right-click or double-click.
    """

    def __init__(self, title: str, border_color: QColor, main_win=None, interactive_overlays: bool = False):
        super().__init__()
        self.title = title
        self.border_color = border_color
        self.main_win = main_win
        self.interactive_overlays = interactive_overlays
        self.source_label = ""
        self.frame_img = None
        self.setMinimumSize(280, 175)

        self._hover_inside = False
        self._selected_ovl = 1
        self._drag_ovl = None
        self._drag_mode = None  # 'move' or handle ('nw','n','ne','e','se','s','sw','w')
        self._drag_start_mix = (0.0, 0.0)
        self._drag_orig_rect = [0.0, 0.0, 100.0, 100.0]
        self._gizmo_flash_until = 0.0
        self._preview_seeking = False

        self.setMouseTracking(True)
        self.refresh_language()

    def refresh_language(self):
        if self.interactive_overlays:
            self.setToolTip(
                tr(
                    "Tipp: Aktive Overlays (OV1/OV2) direkt mit der Maus ziehen, an den Ecken/Kanten "
                    "skalieren, mit dem Mausrad vergrößern/verkleinern oder rechtsklicken.",
                    "Tip: Drag active overlays (OV1/OV2) directly with the mouse, resize via "
                    "corners/edges, scale with the mouse wheel, or right-click for presets.",
                )
            )
        else:
            self.setToolTip(
                tr(
                    "Vorschau (PREVIEW): Abspielbare Videos, Audiodateien und Replays können hier "
                    "direkt über ▶/⏸ und ⏹ gestartet, gestoppt oder gespult werden.",
                    "Preview (PREVIEW): Playable videos, audio files, and replays can be started, "
                    "stopped, or scrubbed directly here via ▶/⏸ and ⏹.",
                )
            )
        self.update()

    def _get_preview_playable_input(self):
        if self.interactive_overlays or not self.main_win:
            return None
        if 0 <= self.main_win.prv_idx < len(self.main_win.inputs):
            inp = self.main_win.inputs[self.main_win.prv_idx]
            if hasattr(inp, "toggle_pause") and hasattr(inp, "stop_playback") and hasattr(inp, "get_position_duration"):
                return inp
        return None

    def _preview_transport_rects(self, vx: int, vy: int, target_w: int, target_h: int):
        bar_h = 26
        by = vy + target_h - bar_h
        bar_rect = QRectF(vx + 1, by, target_w - 2, bar_h - 1)
        btn_play_rect = QRectF(vx + 6, by + 3, 25, 20)
        btn_stop_rect = QRectF(vx + 34, by + 3, 25, 20)
        btn_loop_rect = QRectF(vx + 62, by + 3, 25, 20)
        btn_ret_rect = QRectF(vx + 90, by + 3, 25, 20)
        time_w = 78
        time_rect = QRectF(vx + target_w - time_w - 6, by + 3, time_w, 20)
        seek_x = vx + 121
        seek_w = max(24, int(time_rect.x()) - seek_x - 8)
        seek_rect = QRectF(seek_x, by + 5, seek_w, 16)
        return bar_rect, btn_play_rect, btn_stop_rect, btn_loop_rect, btn_ret_rect, seek_rect, time_rect

    @staticmethod
    def _fmt_mm_ss(sec: float) -> str:
        s = max(0, int(sec))
        return f"{s // 60:02d}:{s % 60:02d}"

    def flash_overlay_gizmos(self, channel: int = 1):
        self._selected_ovl = channel
        self._gizmo_flash_until = time.time() + 3.0
        self.update()

    def set_frame(self, img: QImage, source_label: str = ""):
        self.frame_img = img
        self.source_label = source_label
        self.update()

    def _get_viewport_rect(self) -> tuple[int, int, int, int]:
        w, h = self.width(), self.height()
        header_h = 20
        avail_w = max(16, w - 4)
        avail_h = max(9, h - header_h - 4)
        target_w = avail_w
        target_h = int(target_w * 9 / 16)
        if target_h > avail_h:
            target_h = avail_h
            target_w = int(target_h * 16 / 9)
        vx = (w - target_w) // 2
        vy = header_h + (avail_h - target_h) // 2
        return vx, vy, max(1, target_w), max(1, target_h)

    def _widget_to_mix(self, wx: float, wy: float) -> tuple[float, float]:
        vx, vy, tw, th = self._get_viewport_rect()
        mw = self.main_win.mix_w if self.main_win else 1280
        mh = self.main_win.mix_h if self.main_win else 720
        mx = (wx - vx) * (mw / tw)
        my = (wy - vy) * (mh / th)
        return mx, my

    def _mix_to_widget_rect(self, rect: list[float]) -> QRectF:
        vx, vy, tw, th = self._get_viewport_rect()
        mw = self.main_win.mix_w if self.main_win else 1280
        mh = self.main_win.mix_h if self.main_win else 720
        rx = vx + (rect[0] / mw) * tw
        ry = vy + (rect[1] / mh) * th
        rw = (rect[2] / mw) * tw
        rh = (rect[3] / mh) * th
        return QRectF(rx, ry, rw, rh)

    def _active_overlays(self) -> list[tuple[int, list[float]]]:
        if not self.interactive_overlays or not self.main_win:
            return []
        res = []
        n = len(self.main_win.inputs)
        if 0 <= self.main_win.ovl1_idx < n:
            res.append((1, self.main_win.ovl1_rect))
        if 0 <= self.main_win.ovl2_idx < n:
            res.append((2, self.main_win.ovl2_rect))
        return res

    @staticmethod
    def _handle_points(wrect: QRectF) -> dict[str, tuple[float, float]]:
        x1, y1, w, h = wrect.x(), wrect.y(), wrect.width(), wrect.height()
        x2, y2 = x1 + w, y1 + h
        xm, ym = x1 + w * 0.5, y1 + h * 0.5
        return {
            "nw": (x1, y1),
            "n": (xm, y1),
            "ne": (x2, y1),
            "e": (x2, ym),
            "se": (x2, y2),
            "s": (xm, y2),
            "sw": (x1, y2),
            "w": (x1, ym),
        }

    def _hit_test(self, wx: float, wy: float) -> tuple[int | None, str | None]:
        active = self._active_overlays()
        if not active:
            return None, None

        # Sort order: smaller overlay first (so a small PiP inside a full-screen
        # overlay can always be grabbed directly), or OV2 (top layer) first if similar in size.
        def _sort_key(item):
            ch, r = item
            area = max(1.0, r[2] * r[3])
            is_sel = 0 if ch == self._selected_ovl else 1
            return (area, is_sel, -ch)

        ordered_for_handles = sorted(active, key=lambda it: (0 if it[0] == self._selected_ovl else 1, it[1][2] * it[1][3]))
        handle_radius = 9.0
        for ch, rect in ordered_for_handles:
            wrect = self._mix_to_widget_rect(rect)
            for hname, (hx, hy) in self._handle_points(wrect).items():
                if abs(wx - hx) <= handle_radius and abs(wy - hy) <= handle_radius:
                    return ch, hname

        # Interior hit-test: if one overlay is significantly smaller (< 55% area), prioritize it;
        # otherwise prioritize the top layer (OV2 before OV1).
        if len(active) == 2:
            a1 = active[0][1][2] * active[0][1][3]
            a2 = active[1][1][2] * active[1][1][3]
            if a1 < a2 * 0.55:
                ordered_for_body = [active[0], active[1]]
            elif a2 < a1 * 0.55:
                ordered_for_body = [active[1], active[0]]
            else:
                ordered_for_body = [active[1], active[0]]  # OV2 sits above OV1
        else:
            ordered_for_body = active

        for ch, rect in ordered_for_body:
            wrect = self._mix_to_widget_rect(rect)
            if wrect.contains(wx, wy):
                return ch, "move"

        return None, None

    def _update_cursor_for_mode(self, mode: str | None):
        if mode in ("nw", "se"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif mode in ("ne", "sw"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif mode in ("n", "s"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif mode in ("e", "w"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif mode == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event):
        self._hover_inside = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_inside = False
        if not self._drag_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if not self.main_win:
            return super().mousePressEvent(event)
        if not self.interactive_overlays:
            prv_inp = self._get_preview_playable_input()
            if prv_inp is not None and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position()
                vx, vy, tw, th = self._get_viewport_rect()
                bar_rect, btn_play_rect, btn_stop_rect, btn_loop_rect, btn_ret_rect, seek_rect, _ = self._preview_transport_rects(vx, vy, tw, th)
                if btn_play_rect.contains(pos.x(), pos.y()):
                    prv_inp.toggle_pause()
                    self.update()
                    event.accept()
                    return
                if btn_stop_rect.contains(pos.x(), pos.y()):
                    prv_inp.stop_playback()
                    self.update()
                    event.accept()
                    return
                if btn_loop_rect.contains(pos.x(), pos.y()) and hasattr(prv_inp, "loop_enabled"):
                    prv_inp.loop_enabled = not bool(prv_inp.loop_enabled)
                    if prv_inp.loop_enabled and hasattr(prv_inp, "return_to_preview_on_eos"):
                        prv_inp.return_to_preview_on_eos = False
                    if self.main_win:
                        self.main_win._save_last_preset_silent()
                    self.update()
                    event.accept()
                    return
                if btn_ret_rect.contains(pos.x(), pos.y()) and hasattr(prv_inp, "return_to_preview_on_eos"):
                    prv_inp.return_to_preview_on_eos = not bool(prv_inp.return_to_preview_on_eos)
                    if prv_inp.return_to_preview_on_eos and hasattr(prv_inp, "loop_enabled"):
                        prv_inp.loop_enabled = False
                    if self.main_win:
                        self.main_win._save_last_preset_silent()
                    self.update()
                    event.accept()
                    return
                if seek_rect.contains(pos.x(), pos.y()):
                    self._preview_seeking = True
                    _, dur_s = prv_inp.get_position_duration()
                    if dur_s > 0.1 and hasattr(prv_inp, "seek_seconds"):
                        ratio = max(0.0, min(1.0, (pos.x() - seek_rect.x()) / max(1.0, seek_rect.width())))
                        prv_inp.seek_seconds(ratio * dur_s)
                    self.update()
                    event.accept()
                    return
                if QRectF(vx, vy, tw, th - bar_rect.height()).contains(pos.x(), pos.y()):
                    prv_inp.toggle_pause()
                    self.update()
                    event.accept()
                    return
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            ch, mode = self._hit_test(pos.x(), pos.y())
            if ch is not None and mode is not None:
                self._selected_ovl = ch
                self._drag_ovl = ch
                self._drag_mode = mode
                self._drag_start_mix = self._widget_to_mix(pos.x(), pos.y())
                target_rect = self.main_win.ovl1_rect if ch == 1 else self.main_win.ovl2_rect
                self._drag_orig_rect = list(target_rect)
                if mode == "move":
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.main_win:
            return super().mouseMoveEvent(event)
        if not self.interactive_overlays:
            prv_inp = self._get_preview_playable_input()
            if prv_inp is not None:
                pos = event.position()
                vx, vy, tw, th = self._get_viewport_rect()
                bar_rect, btn_play_rect, btn_stop_rect, btn_loop_rect, btn_ret_rect, seek_rect, _ = self._preview_transport_rects(vx, vy, tw, th)
                if self._preview_seeking:
                    _, dur_s = prv_inp.get_position_duration()
                    if dur_s > 0.1 and hasattr(prv_inp, "seek_seconds"):
                        ratio = max(0.0, min(1.0, (pos.x() - seek_rect.x()) / max(1.0, seek_rect.width())))
                        prv_inp.seek_seconds(ratio * dur_s)
                    self.update()
                    event.accept()
                    return
                if (
                    btn_play_rect.contains(pos.x(), pos.y())
                    or btn_stop_rect.contains(pos.x(), pos.y())
                    or btn_loop_rect.contains(pos.x(), pos.y())
                    or btn_ret_rect.contains(pos.x(), pos.y())
                    or seek_rect.contains(pos.x(), pos.y())
                    or QRectF(vx, vy, tw, th - bar_rect.height()).contains(pos.x(), pos.y())
                ):
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return super().mouseMoveEvent(event)
        pos = event.position()
        if self._drag_ovl is not None and self._drag_mode is not None:
            mx, my = self._widget_to_mix(pos.x(), pos.y())
            dx = mx - self._drag_start_mix[0]
            dy = my - self._drag_start_mix[1]
            ox, oy, ow, oh = self._drag_orig_rect
            mw, mh = float(self.main_win.mix_w), float(self.main_win.mix_h)
            min_w, min_h = 64.0, 36.0
            snap = 8.0 if not (event.modifiers() & Qt.KeyboardModifier.AltModifier) else 0.0

            if self._drag_mode == "move":
                nx = ox + dx
                ny = oy + dy
                # Soft snapping to screen edges (0 / 1280 / 720)
                if abs(nx) < snap:
                    nx = 0.0
                elif abs((nx + ow) - mw) < snap:
                    nx = mw - ow
                if abs(ny) < snap:
                    ny = 0.0
                elif abs((ny + oh) - mh) < snap:
                    ny = mh - oh
                nx = max(-ow + 48.0, min(mw - 48.0, nx))
                ny = max(-oh + 36.0, min(mh - 36.0, ny))
                new_rect = [nx, ny, ow, oh]
            else:
                x1, y1, x2, y2 = ox, oy, ox + ow, oy + oh
                mode = self._drag_mode
                if "w" in mode:
                    x1 = min(x2 - min_w, ox + dx)
                    if abs(x1) < snap:
                        x1 = 0.0
                if "e" in mode:
                    x2 = max(x1 + min_w, ox + ow + dx)
                    if abs(x2 - mw) < snap:
                        x2 = mw
                if "n" in mode:
                    y1 = min(y2 - min_h, oy + dy)
                    if abs(y1) < snap:
                        y1 = 0.0
                if "s" in mode:
                    y2 = max(y1 + min_h, oy + oh + dy)
                    if abs(y2 - mh) < snap:
                        y2 = mh

                nw = max(min_w, x2 - x1)
                nh = max(min_h, y2 - y1)

                # Optional: Hold Shift while dragging a corner to lock aspect ratio
                if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and len(mode) == 2:
                    aspect = max(0.2, ow / max(1.0, oh))
                    nh = max(min_h, nw / aspect)
                    if "n" in mode:
                        y1 = y2 - nh
                    else:
                        y2 = y1 + nh

                new_rect = [x1, y1, nw, nh]

            if self._drag_ovl == 1:
                self.main_win.ovl1_rect = [round(v, 1) for v in new_rect]
            else:
                self.main_win.ovl2_rect = [round(v, 1) for v in new_rect]
            self.update()
            event.accept()
            return

        ch, mode = self._hit_test(pos.x(), pos.y())
        self._update_cursor_for_mode(mode)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._preview_seeking and event.button() == Qt.MouseButton.LeftButton:
            self._preview_seeking = False
            self.update()
            event.accept()
            return
        if self._drag_ovl is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_ovl = None
            self._drag_mode = None
            pos = event.position()
            _, mode = self._hit_test(pos.x(), pos.y())
            self._update_cursor_for_mode(mode)
            if self.main_win:
                self.main_win._save_last_preset_silent()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.interactive_overlays or not self.main_win:
            return super().mouseDoubleClickEvent(event)
        pos = event.position()
        ch, _ = self._hit_test(pos.x(), pos.y())
        if ch is not None:
            self.main_win.reset_overlay_rect(ch)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if not self.interactive_overlays or not self.main_win:
            return super().wheelEvent(event)
        pos = event.position()
        ch, _ = self._hit_test(pos.x(), pos.y())
        if ch is not None:
            self._selected_ovl = ch
            delta = event.angleDelta().y()
            if delta != 0:
                factor = 1.06 if delta > 0 else (1.0 / 1.06)
                rect = self.main_win.ovl1_rect if ch == 1 else self.main_win.ovl2_rect
                ox, oy, ow, oh = rect
                cx = ox + ow * 0.5
                cy = oy + oh * 0.5
                nw = max(64.0, min(self.main_win.mix_w * 1.5, ow * factor))
                nh = max(36.0, min(self.main_win.mix_h * 1.5, oh * factor))
                nx = max(-nw + 48.0, min(self.main_win.mix_w - 48.0, cx - nw * 0.5))
                ny = max(-nh + 36.0, min(self.main_win.mix_h - 36.0, cy - nh * 0.5))
                new_r = [round(nx, 1), round(ny, 1), round(nw, 1), round(nh, 1)]
                if ch == 1:
                    self.main_win.ovl1_rect = new_r
                else:
                    self.main_win.ovl2_rect = new_r
                self._gizmo_flash_until = time.time() + 1.5
                self.main_win._save_last_preset_silent()
                self.update()
                event.accept()
                return
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        if not self.interactive_overlays or not self.main_win:
            return super().contextMenuEvent(event)
        active = self._active_overlays()
        if not active:
            return
        pos = event.pos()
        ch, _ = self._hit_test(pos.x(), pos.y())
        if ch is None:
            ch = self._selected_ovl if any(c == self._selected_ovl for c, _ in active) else active[-1][0]
        self._selected_ovl = ch

        menu = QMenu(self)
        mw, mh = self.main_win.mix_w, self.main_win.mix_h

        def _apply(target_ch: int, r: list[float]):
            if target_ch == 1:
                self.main_win.ovl1_rect = [ float(v) for v in r ]
            else:
                self.main_win.ovl2_rect = [ float(v) for v in r ]
            self.main_win._save_last_preset_silent()
            self.update()

        for target_ch, _ in active:
            sub = menu.addMenu(
                tr(f"🎛️ Overlay OV{target_ch} Layout & Größe", f"🎛️ Overlay OV{target_ch} Layout & Size")
            )
            sub.addAction(
                tr(
                    f"🔄 Standard-Größe für OV{target_ch} (Doppelklick)",
                    f"🔄 Default Size for OV{target_ch} (Double-Click)",
                ),
                lambda c=target_ch: self.main_win.reset_overlay_rect(c),
            )
            sub.addAction(
                tr("🖥️ Vollbild (1280×720)", "🖥️ Fullscreen (1280×720)"),
                lambda c=target_ch: _apply(c, [0.0, 0.0, mw, mh]),
            )
            sub.addSeparator()
            sub.addAction(
                tr("↘️ PiP Unten Rechts (360×202)", "↘️ PiP Bottom Right (360×202)"),
                lambda c=target_ch: _apply(c, [mw - 396.0, mh - 238.0, 360.0, 202.0]),
            )
            sub.addAction(
                tr("↙️ PiP Unten Links (360×202)", "↙️ PiP Bottom Left (360×202)"),
                lambda c=target_ch: _apply(c, [36.0, mh - 238.0, 360.0, 202.0]),
            )
            sub.addAction(
                tr("↗️ PiP Oben Rechts (360×202)", "↗️ PiP Top Right (360×202)"),
                lambda c=target_ch: _apply(c, [mw - 396.0, 36.0, 360.0, 202.0]),
            )
            sub.addAction(
                tr("↖️ PiP Oben Links (360×202)", "↖️ PiP Top Left (360×202)"),
                lambda c=target_ch: _apply(c, [36.0, 36.0, 360.0, 202.0]),
            )
            sub.addSeparator()
            sub.addAction(
                tr("📏 Seitenverhältnis auf 16:9 anpassen", "📏 Snap Aspect Ratio to 16:9"),
                lambda c=target_ch: self.main_win.snap_overlay_16_9(c),
            )
            border_on = self.main_win.ovl1_show_border if target_ch == 1 else self.main_win.ovl2_show_border
            act_border = sub.addAction(
                tr(
                    f"🖼️ Farbrahmen im Stream {'ausblenden' if border_on else 'einblenden'}",
                    f"🖼️ {'Hide' if border_on else 'Show'} Colored Border in Stream",
                ),
                lambda c=target_ch: self.main_win.toggle_overlay_border(c),
            )
        menu.exec(event.globalPos())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(10, 12, 16))

        header_h = 20
        vx, vy, target_w, target_h = self._get_viewport_rect()

        if self.frame_img and not self.frame_img.isNull():
            p.drawImage(QRectF(vx, vy, target_w, target_h), self.frame_img)

        # Interactive overlay handles (visible only in UI monitor, never in stream!)
        active_ovls = self._active_overlays()
        show_gizmos = (
            self._hover_inside
            or (self._drag_ovl is not None)
            or (time.time() < self._gizmo_flash_until)
        )
        if active_ovls and show_gizmos:
            p.save()
            p.setClipRect(vx, vy, target_w, target_h)
            for ch, rect in active_ovls:
                wrect = self._mix_to_widget_rect(rect)
                col = QColor(0, 210, 255) if ch == 1 else QColor(255, 165, 30)
                is_sel = (ch == self._selected_ovl) or (ch == self._drag_ovl)

                pen = QPen(col, 2.0 if is_sel else 1.2, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(wrect)

                # 8 handle squares at corners and edges
                p.setPen(QPen(QColor(15, 18, 24), 1))
                p.setBrush(col)
                hs = 7.0 if is_sel else 5.5
                for _, (hx, hy) in self._handle_points(wrect).items():
                    p.drawRect(QRectF(hx - hs * 0.5, hy - hs * 0.5, hs, hs))

                # Compact badge with overlay name & dimensions
                badge_txt = f"OV{ch}: {int(rect[2])}×{int(rect[3])}"
                p.setFont(QFont("Sans Serif", 8, QFont.Weight.Bold))
                fm = p.fontMetrics()
                bw = fm.horizontalAdvance(badge_txt) + 10
                bh = 15
                bx = max(vx + 2, min(vx + target_w - bw - 2, int(wrect.x()) + 3))
                by = max(vy + 2, min(vy + target_h - bh - 2, int(wrect.y()) + 3))
                p.fillRect(bx, by, bw, bh, QColor(14, 18, 26, 215))
                p.setPen(col)
                p.drawRect(bx, by, bw, bh)
                p.drawText(bx + 5, by + 11, badge_txt)
            p.restore()

        # Interactive media transport bar in PREVIEW monitor (for Video, Audio, Replay & Highlights)
        prv_inp = self._get_preview_playable_input()
        if prv_inp is not None:
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bar_rect, btn_play_rect, btn_stop_rect, btn_loop_rect, btn_ret_rect, seek_rect, time_rect = self._preview_transport_rects(
                vx, vy, target_w, target_h
            )
            p.fillRect(bar_rect, QColor(14, 18, 26, 220))
            p.setPen(QPen(QColor(50, 62, 82, 200), 1))
            p.drawLine(int(bar_rect.left()), int(bar_rect.top()), int(bar_rect.right()), int(bar_rect.top()))

            # Play / Pause button
            is_paused = getattr(prv_inp, "paused", True)
            play_bg = QColor(32, 165, 85) if not is_paused else QColor(42, 50, 68)
            p.setBrush(play_bg)
            p.setPen(QPen(QColor(80, 210, 120) if not is_paused else QColor(90, 105, 135), 1))
            p.drawRoundedRect(btn_play_rect, 3, 3)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
            p.drawText(btn_play_rect, Qt.AlignmentFlag.AlignCenter, "▶" if is_paused else "⏸")

            # Stop button
            p.setBrush(QColor(42, 50, 68))
            p.setPen(QPen(QColor(90, 105, 135), 1))
            p.drawRoundedRect(btn_stop_rect, 3, 3)
            p.setPen(QColor(235, 240, 250))
            p.drawText(btn_stop_rect, Qt.AlignmentFlag.AlignCenter, "⏹")

            # Loop button (infinite repeat on/off)
            is_loop = bool(getattr(prv_inp, "loop_enabled", False))
            p.setBrush(QColor(30, 107, 158) if is_loop else QColor(42, 50, 68))
            p.setPen(QPen(QColor(65, 168, 240) if is_loop else QColor(90, 105, 135), 1))
            p.drawRoundedRect(btn_loop_rect, 3, 3)
            p.setPen(QColor(255, 255, 255) if is_loop else QColor(175, 185, 205))
            p.drawText(btn_loop_rect, Qt.AlignmentFlag.AlignCenter, "🔁")

            # Return-to-Preview button (jump back to preview when clip finishes)
            is_ret = bool(getattr(prv_inp, "return_to_preview_on_eos", False))
            p.setBrush(QColor(26, 130, 74) if is_ret else QColor(42, 50, 68))
            p.setPen(QPen(QColor(50, 215, 115) if is_ret else QColor(90, 105, 135), 1))
            p.drawRoundedRect(btn_ret_rect, 3, 3)
            p.setPen(QColor(255, 255, 255) if is_ret else QColor(175, 185, 205))
            p.drawText(btn_ret_rect, Qt.AlignmentFlag.AlignCenter, "↩")

            # Seek / Progress Bar
            pos_s, dur_s = prv_inp.get_position_duration()
            ratio = max(0.0, min(1.0, pos_s / dur_s)) if dur_s > 0.1 else 0.0
            track_rect = QRectF(seek_rect.x(), seek_rect.center().y() - 3.0, seek_rect.width(), 6.0)
            p.setBrush(QColor(30, 36, 48))
            p.setPen(QPen(QColor(65, 78, 102), 1))
            p.drawRoundedRect(track_rect, 3, 3)

            if ratio > 0.005:
                fill_w = max(4.0, track_rect.width() * ratio)
                p.setBrush(QColor(32, 214, 96))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(track_rect.x(), track_rect.y(), fill_w, track_rect.height()), 3, 3)

            knob_x = track_rect.x() + track_rect.width() * ratio
            p.setBrush(QColor(240, 248, 255))
            p.setPen(QPen(QColor(20, 26, 36), 1))
            p.drawEllipse(QRectF(knob_x - 5.0, track_rect.center().y() - 5.0, 10.0, 10.0))

            # Timecode
            p.setPen(QColor(205, 215, 232))
            p.setFont(QFont("Monospace", 8, QFont.Weight.Bold))
            p.drawText(
                time_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{self._fmt_mm_ss(pos_s)}/{self._fmt_mm_ss(dur_s)}",
            )
            p.restore()

        # Broadcast border
        p.setPen(QPen(self.border_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(vx, vy, target_w, target_h)

        # Header badge
        p.fillRect(vx, vy - header_h, target_w, header_h - 1, QColor(20, 24, 32))
        p.setPen(self.border_color)
        p.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
        p.drawText(vx + 6, vy - 5, f"● {self.title}")

        p.setPen(QColor(220, 225, 235))
        p.setFont(QFont("Sans Serif", 9))
        p.drawText(vx + 110, vy - 5, self.source_label)

        if active_ovls and self.interactive_overlays:
            hint_txt = tr("🖱 OV1/OV2 ziehbar", "🖱 Drag OV1/OV2")
            p.setPen(QColor(0, 210, 255))
            p.setFont(QFont("Sans Serif", 8))
            hw = p.fontMetrics().horizontalAdvance(hint_txt)
            p.drawText(vx + target_w - hw - 6, vy - 5, hint_txt)
        p.end()


class ExternalProgramOutputWindow(QWidget):
    """
    Clean external 16:9 PROGRAM output window (Projector / Fullscreen Output).
    Can be displayed either as a freely resizable window (e.g. for screen-sharing into
    Zoom/Teams/Discord) or borderless fullscreen on any connected monitor/projector/HDMI.
    """

    def __init__(self, main_win):
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        self.main_win = main_win
        self.frame_img: QImage | None = None
        self.mode: str = "window"  # "window" or "fullscreen"
        self.screen_index: int = 0
        self.resize(854, 480)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background-color: #000000;")
        self.setMouseTracking(True)
        self.refresh_language()

    def refresh_language(self):
        self.setWindowTitle(
            tr(
                "LiteMix HD – PROGRAM-Ausgabe (Doppelklick: Vollbild, Esc: Schließen)",
                "LiteMix HD – PROGRAM Output (Double-click: Fullscreen, Esc: Close)",
            )
        )
        self.setToolTip(
            tr(
                "Doppelklick oder F11: Fenster ⇄ Vollbild | Rechtsklick: Monitor wählen | Esc: Schließen",
                "Double-click or F11: Window ⇄ Fullscreen | Right-click: Select Monitor | Esc: Close",
            )
        )

    def set_frame(self, img: QImage):
        self.frame_img = img
        if self.isVisible():
            self.update()

    def show_windowed(self):
        self.mode = "window"
        self.unsetCursor()
        if self.isFullScreen():
            self.showNormal()
        self.refresh_language()
        self.show()
        self.raise_()
        self.activateWindow()
        if self.main_win:
            self.main_win._refresh_ext_output_button_style()

    def show_fullscreen_on_screen(self, screen_idx: int = 0):
        screens = QApplication.screens()
        if not screens:
            self.show_windowed()
            return
        screen_idx = max(0, min(len(screens) - 1, int(screen_idx)))
        target_screen = screens[screen_idx]
        self.screen_index = screen_idx
        self.mode = "fullscreen"

        if self.isFullScreen():
            self.showNormal()

        geom = target_screen.geometry()
        self.setGeometry(geom)
        self.winId()
        wh = self.windowHandle()
        if wh is not None:
            try:
                wh.setScreen(target_screen)
            except Exception:
                pass
        self.setGeometry(geom)
        self.showFullScreen()
        self.raise_()
        if self.main_win:
            self.main_win._refresh_ext_output_button_style()

    def toggle_window_fullscreen(self):
        if self.mode == "fullscreen" or self.isFullScreen():
            self.show_windowed()
        else:
            self.show_fullscreen_on_screen(self.screen_index)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_window_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        if key == Qt.Key.Key_F11:
            self.toggle_window_fullscreen()
            event.accept()
            return
        if key == Qt.Key.Key_Space and self.main_win:
            self.main_win.do_cut()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.main_win:
            self.main_win.do_fade()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if not self.main_win:
            return
        menu = self.main_win._build_ext_output_menu(parent_widget=self)
        menu.exec(event.globalPos())

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.main_win:
            QTimer.singleShot(0, self.main_win._refresh_ext_output_button_style)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(0, 0, 0))

        if self.frame_img and not self.frame_img.isNull():
            tw = w
            th = int(tw * 9 / 16)
            if th > h:
                th = h
                tw = int(th * 16 / 9)
            vx = (w - tw) // 2
            vy = (h - th) // 2
            p.drawImage(QRectF(vx, vy, max(1, tw), max(1, th)), self.frame_img)
        p.end()


class VUMeterBar(QWidget):
    """Vertical real-time audio VU meter (Green / Yellow / Red)."""

    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.setFixedWidth(12)
        self.setMinimumHeight(65)

    def set_level(self, lvl: float):
        self.level = max(0.0, min(1.0, lvl))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(14, 16, 22))

        active_h = int(h * self.level)
        if active_h > 0:
            y_top = h - active_h
            for y in range(h - 2, y_top, -3):
                ratio = 1.0 - (y / h)
                if ratio > 0.85:
                    col = QColor(240, 50, 50)
                elif ratio > 0.65:
                    col = QColor(240, 200, 40)
                else:
                    col = QColor(40, 215, 100)
                p.fillRect(2, y - 2, w - 4, 2, col)

        p.setPen(QColor(50, 58, 75))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class MiniHorizVUBar(QWidget):
    """Compact horizontal live audio level bar inside an audio/video input tile."""

    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.setFixedHeight(5)

    def set_level(self, lvl: float):
        self.level = max(0.0, min(1.0, lvl))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(14, 16, 22))
        aw = int(w * self.level)
        if aw > 0:
            col = QColor(240, 50, 50) if self.level > 0.85 else (
                QColor(240, 200, 40) if self.level > 0.65 else QColor(40, 215, 100)
            )
            p.fillRect(0, 0, aw, h, col)
        p.end()


class InputTileWidget(QFrame):
    """Compact tile for an individual source in the vMix input grid (with per-source audio & media transport)."""

    def __init__(self, index: int, inp: BaseInput, main_win):
        super().__init__()
        self.index = index
        self.inp = inp
        self.main_win = main_win
        self.setFixedSize(176, 164)
        self.setObjectName("PanelFrame")

        self.btn_play_pause = None
        self.btn_stop_media = None
        self.seek_slider = None
        self.lbl_timecode = None
        self.lbl_aud_tag = None
        self.btn_cfg = None
        self.btn_flip = None
        self.btn_prev_hl = None
        self.btn_next_hl = None
        self._media_duration = 0.0
        self._seek_cooldown_until = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        # Header with number & title + close button
        top_row = QHBoxLayout()
        self.title_lbl = QLabel(f"{index + 1}: {inp.name[:18]}")
        self.title_lbl.setStyleSheet("font-weight: bold; font-size: 10px;")
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(16, 16)
        btn_close.setStyleSheet("padding: 0px; font-size: 9px; background: #322026; color: #ff8080;")
        btn_close.clicked.connect(lambda: self.main_win.remove_input(self.index))
        top_row.addWidget(self.title_lbl, 1)
        top_row.addWidget(btn_close)
        layout.addLayout(top_row)

        # Mini thumbnail area (16:9)
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(166, 64)
        self.thumb_lbl.setStyleSheet("background-color: #0d0f14; border: 1px solid #2b3140;")
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumb_lbl)

        # Action buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(2)

        self.btn_prv = QPushButton("PRV")
        self.btn_prv.clicked.connect(lambda: self.main_win.set_preview(self.index))

        self.btn_pgm = QPushButton("CUT")
        self.btn_pgm.clicked.connect(lambda: self.main_win.cut_input_to_program(self.index))

        self.btn_ovl1 = QPushButton("OV1")
        self.btn_ovl1.clicked.connect(lambda: self.main_win.toggle_overlay(1, self.index))

        self.btn_ovl2 = QPushButton("OV2")
        self.btn_ovl2.clicked.connect(lambda: self.main_win.toggle_overlay(2, self.index))

        if isinstance(inp, AudioInputBase):
            self.lbl_aud_tag = QLabel()
            self.lbl_aud_tag.setStyleSheet("color: #909ab0; font-size: 9px;")
            btn_row.addWidget(self.lbl_aud_tag, 1)
            if isinstance(inp, AudioFileInput):
                for b in (self.btn_prv, self.btn_pgm):
                    b.setStyleSheet("padding: 1px 4px; font-size: 9px;")
                    btn_row.addWidget(b)
        else:
            for b in (self.btn_prv, self.btn_pgm, self.btn_ovl1, self.btn_ovl2):
                b.setStyleSheet("padding: 1px 3px; font-size: 9px;")
                btn_row.addWidget(b)

            if isinstance(inp, LowerThirdInput):
                self.btn_cfg = QPushButton("✎")
                self.btn_cfg.setFixedWidth(18)
                self.btn_cfg.setStyleSheet("padding: 1px; font-size: 9px;")
                self.btn_cfg.clicked.connect(lambda: self.main_win.edit_lower_third(inp))
                btn_row.addWidget(self.btn_cfg)
            elif isinstance(inp, TextSlideInput):
                self.btn_cfg = QPushButton("✎")
                self.btn_cfg.setFixedWidth(18)
                self.btn_cfg.setStyleSheet("padding: 1px; font-size: 9px;")
                self.btn_cfg.clicked.connect(lambda: self.main_win.edit_text_slide(inp))
                btn_row.addWidget(self.btn_cfg)
            elif isinstance(inp, WebBrowserInput):
                self.btn_cfg = QPushButton("🌐")
                self.btn_cfg.setFixedWidth(18)
                self.btn_cfg.setStyleSheet("padding: 1px; font-size: 9px;")
                self.btn_cfg.clicked.connect(inp.show_browser)
                btn_row.addWidget(self.btn_cfg)
            elif isinstance(inp, V4L2CameraInput):
                self.btn_flip = QPushButton("⇄")
                self.btn_flip.setFixedWidth(18)
                self.btn_flip.setStyleSheet("padding: 1px; font-size: 9px;")
                self.btn_flip.clicked.connect(inp.toggle_mirror)
                btn_row.addWidget(self.btn_flip)

        layout.addLayout(btn_row)

        # Transport & scrubber row for playable media (Video, Audio, Replay, Highlights, TextSlideInput)
        self.speed_buttons: list[tuple[float, QPushButton]] = []
        self.btn_hl_select = None
        self.btn_hl_speed = None
        self.btn_loop = None
        self.btn_return_prv = None
        self.btn_prev_slide = None
        self.btn_slide_select = None
        self.btn_next_slide = None
        self.btn_scroll_toggle = None

        if isinstance(inp, (VideoFileInput, AudioFileInput, ReplaySourceInput, HighlightsInput, TextSlideInput)):
            trans_row = QHBoxLayout()
            trans_row.setSpacing(2)

            self.btn_play_pause = QPushButton("▶" if inp.paused else "⏸")
            self.btn_play_pause.setFixedSize(17, 16)
            self.btn_play_pause.setStyleSheet("padding: 0px; font-size: 9px;")
            self.btn_play_pause.clicked.connect(self._on_play_pause_clicked)
            trans_row.addWidget(self.btn_play_pause)

            self.btn_stop_media = QPushButton("⏹")
            self.btn_stop_media.setFixedSize(17, 16)
            self.btn_stop_media.setStyleSheet("padding: 0px; font-size: 9px;")
            self.btn_stop_media.clicked.connect(self._on_stop_clicked)
            trans_row.addWidget(self.btn_stop_media)

            if isinstance(inp, (VideoFileInput, AudioFileInput, ReplaySourceInput, TextSlideInput)):
                self.btn_loop = QPushButton("🔁")
                self.btn_loop.setCheckable(True)
                self.btn_loop.setChecked(bool(getattr(inp, "loop_enabled", False)))
                self.btn_loop.setFixedSize(17, 16)
                self._refresh_loop_button()
                self.btn_loop.toggled.connect(self._on_loop_toggled)
                trans_row.addWidget(self.btn_loop)

                self.btn_return_prv = QPushButton("↩")
                self.btn_return_prv.setCheckable(True)
                self.btn_return_prv.setChecked(bool(getattr(inp, "return_to_preview_on_eos", False)))
                self.btn_return_prv.setFixedSize(17, 16)
                self._refresh_return_prv_button()
                self.btn_return_prv.toggled.connect(self._on_return_prv_toggled)
                trans_row.addWidget(self.btn_return_prv)

            self.seek_slider = QSlider(Qt.Orientation.Horizontal)
            self.seek_slider.setRange(0, 1000)
            self.seek_slider.setValue(0)
            self.seek_slider.valueChanged.connect(self._on_seek_slider_changed)
            trans_row.addWidget(self.seek_slider, 1)

            self.lbl_timecode = QLabel("0:00/0:00")
            self.lbl_timecode.setFixedWidth(46)
            self.lbl_timecode.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.lbl_timecode.setStyleSheet("font-size: 8px; color: #98a2b8; font-family: monospace;")
            trans_row.addWidget(self.lbl_timecode)

            layout.addLayout(trans_row)

        # Slow-motion & clip control row for ReplaySourceInput and HighlightsInput
        if isinstance(inp, ReplaySourceInput):
            spd_row = QHBoxLayout()
            spd_row.setSpacing(2)
            lbl_s = QLabel("⏱")
            lbl_s.setStyleSheet("font-size: 9px; color: #909ab0;")
            spd_row.addWidget(lbl_s)
            for rate_val, rate_txt in [(0.25, "0.25×"), (0.5, "0.5×"), (0.75, "0.75×"), (1.0, "1.0×")]:
                b_spd = QPushButton(rate_txt)
                b_spd.setFixedHeight(17)
                b_spd.clicked.connect(lambda _, r=rate_val: self._on_set_playback_rate(r))
                spd_row.addWidget(b_spd, 1)
                self.speed_buttons.append((rate_val, b_spd))
            layout.addLayout(spd_row)
            self._refresh_speed_buttons()

        elif isinstance(inp, HighlightsInput):
            hl_row = QHBoxLayout()
            hl_row.setSpacing(2)

            self.btn_prev_hl = QPushButton("⏮")
            self.btn_prev_hl.setFixedSize(18, 17)
            self.btn_prev_hl.setStyleSheet("padding: 0px; font-size: 8px;")
            self.btn_prev_hl.clicked.connect(self._on_hl_prev)
            hl_row.addWidget(self.btn_prev_hl)

            self.btn_hl_select = QPushButton("🎬 #0/0 ▾")
            self.btn_hl_select.setFixedHeight(17)
            self.btn_hl_select.setStyleSheet("padding: 0px 3px; font-size: 8px;")
            self.btn_hl_select.clicked.connect(self._open_highlights_clip_menu)
            hl_row.addWidget(self.btn_hl_select, 1)

            self.btn_next_hl = QPushButton("⏭")
            self.btn_next_hl.setFixedSize(18, 17)
            self.btn_next_hl.setStyleSheet("padding: 0px; font-size: 8px;")
            self.btn_next_hl.clicked.connect(self._on_hl_next)
            hl_row.addWidget(self.btn_next_hl)

            self.btn_hl_speed = QPushButton(f"⏱{inp.playback_rate:g}×")
            self.btn_hl_speed.setFixedSize(40, 17)
            self.btn_hl_speed.setStyleSheet("padding: 0px 2px; font-size: 8px; background-color: #1e4d6b; color: white;")
            self.btn_hl_speed.clicked.connect(self._open_highlights_speed_menu)
            hl_row.addWidget(self.btn_hl_speed)

            layout.addLayout(hl_row)

        elif isinstance(inp, TextSlideInput):
            ts_row = QHBoxLayout()
            ts_row.setSpacing(2)

            self.btn_prev_slide = QPushButton("⏮")
            self.btn_prev_slide.setFixedSize(18, 17)
            self.btn_prev_slide.setStyleSheet("padding: 0px; font-size: 8px;")
            self.btn_prev_slide.clicked.connect(self._on_slide_prev)
            ts_row.addWidget(self.btn_prev_slide)

            slides = inp.get_slides()
            self.btn_slide_select = QPushButton(f"📄 #{inp.current_slide_idx + 1}/{len(slides)} ▾")
            self.btn_slide_select.setFixedHeight(17)
            self.btn_slide_select.setStyleSheet("padding: 0px 3px; font-size: 8px;")
            self.btn_slide_select.clicked.connect(self._open_text_slide_menu)
            ts_row.addWidget(self.btn_slide_select, 1)

            self.btn_next_slide = QPushButton("⏭")
            self.btn_next_slide.setFixedSize(18, 17)
            self.btn_next_slide.setStyleSheet("padding: 0px; font-size: 8px;")
            self.btn_next_slide.clicked.connect(self._on_slide_next)
            ts_row.addWidget(self.btn_next_slide)

            self.btn_scroll_toggle = QPushButton("📄")
            self.btn_scroll_toggle.setFixedSize(26, 17)
            self._refresh_scroll_toggle_button()
            self.btn_scroll_toggle.clicked.connect(self._on_scroll_mode_clicked)
            ts_row.addWidget(self.btn_scroll_toggle)

            layout.addLayout(ts_row)

        # Individual Audio Controls row inside the tile (if source has audio)
        self.mini_vu = None
        self.vol_slider = None
        self.btn_mute_tile = None
        self.lbl_vol_pct = None

        if inp.has_audio:
            self.mini_vu = MiniHorizVUBar()
            layout.addWidget(self.mini_vu)

            aud_row = QHBoxLayout()
            aud_row.setSpacing(3)

            self.btn_mute_tile = QPushButton("🔇" if inp.muted else "🔊")
            self.btn_mute_tile.setCheckable(True)
            self.btn_mute_tile.setChecked(inp.muted)
            self.btn_mute_tile.setFixedSize(22, 18)
            self.btn_mute_tile.setStyleSheet(
                "padding: 0px; font-size: 9px; background-color: #c82828; color: white;"
                if inp.muted else "padding: 0px; font-size: 9px;"
            )
            self.btn_mute_tile.toggled.connect(self._on_tile_mute)
            aud_row.addWidget(self.btn_mute_tile)

            self.vol_slider = QSlider(Qt.Orientation.Horizontal)
            self.vol_slider.setRange(0, 150)
            self.vol_slider.setValue(int(inp.volume * 100))
            self.vol_slider.valueChanged.connect(self._on_tile_vol_changed)
            aud_row.addWidget(self.vol_slider, 1)

            self.lbl_vol_pct = QLabel(f"{int(inp.volume * 100)}%")
            self.lbl_vol_pct.setFixedWidth(28)
            self.lbl_vol_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.lbl_vol_pct.setStyleSheet("font-size: 9px; color: #98a2b8;")
            aud_row.addWidget(self.lbl_vol_pct)

            layout.addLayout(aud_row)
        else:
            layout.addStretch()

        self.refresh_language()

    def refresh_language(self):
        self.btn_prv.setToolTip(tr("In Vorschau (Preview) laden", "Load into Preview (PRV)"))
        self.btn_pgm.setToolTip(tr("Direkt auf Live (Program) schalten", "Cut directly to Live (Program)"))
        self.btn_ovl1.setToolTip(tr("Overlay 1: Bild-in-Bild (PiP rechts unten)", "Overlay 1: Picture-in-Picture (PiP bottom-right)"))
        self.btn_ovl2.setToolTip(tr("Overlay 2: Vollbild-Overlay / Bauchbinde", "Overlay 2: Fullscreen Overlay / Lower Third"))
        if self.lbl_aud_tag:
            self.lbl_aud_tag.setText(
                tr("🎵 Audio-Datei", "🎵 Audio File")
                if isinstance(self.inp, AudioFileInput)
                else tr("🎧 Audio-Eingang", "🎧 Audio Input")
            )
        if self.btn_cfg:
            if isinstance(self.inp, LowerThirdInput):
                self.btn_cfg.setToolTip(tr("Bauchbinden-Text bearbeiten", "Edit Lower Third text & template"))
            elif isinstance(self.inp, TextSlideInput):
                self.btn_cfg.setToolTip(
                    tr(
                        "Mehrzeiligen Texteditor, Folien, Design & Lauftext bearbeiten",
                        "Edit multi-line text, slides, style & vertical scroll",
                    )
                )
            elif isinstance(self.inp, WebBrowserInput):
                self.btn_cfg.setToolTip(tr("Browserfenster öffnen/bedienen", "Open / interact with browser window"))
        if self.btn_flip:
            self.btn_flip.setToolTip(tr("Kamera horizontal spiegeln (Flip)", "Flip camera horizontally (Mirror)"))
        if self.btn_play_pause:
            self.btn_play_pause.setToolTip(tr("Start / Pause", "Play / Pause"))
        if self.btn_stop_media:
            self.btn_stop_media.setToolTip(tr("Stopp (Zurück zum Anfang 0:00)", "Stop (Rewind to 0:00)"))
        if self.btn_loop:
            self.btn_loop.setToolTip(tr("Endlosschleife (Loop) ein-/ausschalten", "Toggle infinite Loop on/off"))
        if self.btn_return_prv:
            self.btn_return_prv.setToolTip(
                tr(
                    "Nach Ende zurück zum Vorschaufenster springen (schaltet bei Live-Ende automatisch zurück)",
                    "Return to Preview on end (automatically cuts back when clip finishes on Program)",
                )
            )
        if self.seek_slider:
            self.seek_slider.setToolTip(tr("Im Video/Replay spulen (Scrubbing)", "Scrub / seek in video or replay"))
        for rval, b_spd in self.speed_buttons:
            b_spd.setToolTip(tr(f"Abspieltempo auf {rval:g}× setzen", f"Set playback speed to {rval:g}×"))
        if self.btn_prev_hl:
            self.btn_prev_hl.setToolTip(tr("Vorheriges Highlight", "Previous Highlight"))
        if self.btn_next_hl:
            self.btn_next_hl.setToolTip(tr("Nächstes Highlight", "Next Highlight"))
        if self.btn_hl_select:
            self.btn_hl_select.setToolTip(
                tr("Vergangenes Highlight auswählen oder Auto-Play umschalten", "Select recorded Highlight or toggle Auto-Play")
            )
        if self.btn_hl_speed:
            self.btn_hl_speed.setToolTip(tr("Zeitlupen-Geschwindigkeit für Highlights wählen", "Choose slow-motion speed for Highlights"))
        if self.btn_prev_slide:
            self.btn_prev_slide.setToolTip(tr("Vorherige Textfolie (durch --- getrennt)", "Previous text slide (separated by ---)"))
        if self.btn_next_slide:
            self.btn_next_slide.setToolTip(tr("Nächste Textfolie (durch --- getrennt)", "Next text slide (separated by ---)"))
        if self.btn_slide_select:
            self.btn_slide_select.setToolTip(
                tr("Textfolie auswählen oder mehrzeiligen Texteditor öffnen", "Select text slide or open multi-line text editor")
            )
        if self.btn_scroll_toggle:
            self.btn_scroll_toggle.setToolTip(
                tr(
                    "Modus umschalten: 📄 Statisch/Folien ➔ 📜 Vertikaler Lauftext ➔ 📰 Horizontaler Ticker",
                    "Cycle mode: 📄 Static/Slides ➔ 📜 Vertical Scroll ➔ 📰 Horizontal Ticker",
                )
            )
        if self.btn_mute_tile:
            self.btn_mute_tile.setToolTip(tr("Ton dieser Quelle stummschalten (Mute)", "Mute audio of this source"))
        if self.vol_slider:
            self.vol_slider.setToolTip(tr("Lautstärke dieser Quelle (0% - 150%)", "Volume of this source (0% - 150%)"))

    @staticmethod
    def _fmt_mm_ss(sec: float) -> str:
        s = max(0, int(sec))
        return f"{s // 60}:{s % 60:02d}"

    def _on_play_pause_clicked(self):
        if hasattr(self.inp, "toggle_pause"):
            self.inp.toggle_pause()
            if self.btn_play_pause:
                self.btn_play_pause.setText("▶" if self.inp.paused else "⏸")

    def _on_stop_clicked(self):
        if hasattr(self.inp, "stop_playback"):
            self.inp.stop_playback()
            if self.btn_play_pause:
                self.btn_play_pause.setText("▶")
            if self.seek_slider:
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(0)
                self.seek_slider.blockSignals(False)
            if self.lbl_timecode:
                dur_str = self._fmt_mm_ss(self._media_duration)
                self.lbl_timecode.setText(f"0:00/{dur_str}")

    def _on_loop_toggled(self, checked: bool):
        if hasattr(self.inp, "loop_enabled"):
            self.inp.loop_enabled = bool(checked)
            if checked and hasattr(self.inp, "return_to_preview_on_eos"):
                self.inp.return_to_preview_on_eos = False
                self._refresh_return_prv_button()
            self._refresh_loop_button()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _refresh_loop_button(self):
        if not self.btn_loop:
            return
        is_loop = bool(getattr(self.inp, "loop_enabled", False))
        if self.btn_loop.isChecked() != is_loop:
            self.btn_loop.blockSignals(True)
            self.btn_loop.setChecked(is_loop)
            self.btn_loop.blockSignals(False)
        self.btn_loop.setStyleSheet(
            "padding: 0px; font-size: 9px; background-color: #1e6b9e; color: white; border: 1px solid #40a8f0;"
            if is_loop else "padding: 0px; font-size: 9px;"
        )

    def _on_return_prv_toggled(self, checked: bool):
        if hasattr(self.inp, "return_to_preview_on_eos"):
            self.inp.return_to_preview_on_eos = bool(checked)
            if checked and hasattr(self.inp, "loop_enabled"):
                self.inp.loop_enabled = False
                self._refresh_loop_button()
            self._refresh_return_prv_button()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _refresh_return_prv_button(self):
        if not self.btn_return_prv:
            return
        is_ret = bool(getattr(self.inp, "return_to_preview_on_eos", False))
        if self.btn_return_prv.isChecked() != is_ret:
            self.btn_return_prv.blockSignals(True)
            self.btn_return_prv.setChecked(is_ret)
            self.btn_return_prv.blockSignals(False)
        self.btn_return_prv.setStyleSheet(
            "padding: 0px; font-size: 9px; background-color: #1a824a; color: white; border: 1px solid #32d673;"
            if is_ret else "padding: 0px; font-size: 9px;"
        )

    def _on_seek_slider_changed(self, val: int):
        if self._media_duration > 0.1 and hasattr(self.inp, "seek_seconds"):
            self._seek_cooldown_until = time.monotonic() + 0.35
            target_sec = (val / 1000.0) * self._media_duration
            self.inp.seek_seconds(target_sec)
            if self.lbl_timecode:
                self.lbl_timecode.setText(
                    f"{self._fmt_mm_ss(target_sec)}/{self._fmt_mm_ss(self._media_duration)}"
                )

    def _on_tile_vol_changed(self, val: int):
        self.inp.set_volume(val / 100.0)
        if self.lbl_vol_pct:
            self.lbl_vol_pct.setText(f"{val}%")

    def _on_tile_mute(self, muted: bool):
        self.inp.set_muted(muted)
        if self.btn_mute_tile:
            self.btn_mute_tile.setText("🔇" if muted else "🔊")
            self.btn_mute_tile.setStyleSheet(
                "padding: 0px; font-size: 9px; background-color: #c82828; color: white;"
                if muted else "padding: 0px; font-size: 9px;"
            )

    def _on_set_playback_rate(self, rate: float):
        if hasattr(self.inp, "set_playback_rate"):
            self.inp.set_playback_rate(rate)
            self._refresh_speed_buttons()
            if self.btn_hl_speed:
                self.btn_hl_speed.setText(f"⏱{self.inp.playback_rate:g}×")
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _refresh_speed_buttons(self):
        cur_rate = getattr(self.inp, "playback_rate", 1.0)
        for rval, btn in self.speed_buttons:
            is_act = abs(cur_rate - rval) < 0.02
            btn.setStyleSheet(
                "padding: 0px; font-size: 8px; background-color: #0088cc; color: white; border: 1px solid #00c8ff;"
                if is_act else "padding: 0px; font-size: 8px;"
            )

    def _on_hl_prev(self):
        if isinstance(self.inp, HighlightsInput) and self.inp.clips:
            n = len(self.inp.clips)
            new_idx = (self.inp.current_clip_idx - 1) % n
            self.inp.select_clip(new_idx, auto_play=not self.inp.paused)

    def _on_hl_next(self):
        if isinstance(self.inp, HighlightsInput) and self.inp.clips:
            n = len(self.inp.clips)
            new_idx = (self.inp.current_clip_idx + 1) % n
            self.inp.select_clip(new_idx, auto_play=not self.inp.paused)

    def _open_highlights_speed_menu(self):
        if not isinstance(self.inp, HighlightsInput):
            return
        menu = QMenu(self)
        for rval, rlabel in ReplaySourceInput.get_speed_options():
            prefix = "✓ " if abs(self.inp.playback_rate - rval) < 0.02 else "   "
            menu.addAction(
                f"{prefix}{rlabel}",
                lambda r=rval: self._on_set_playback_rate(r),
            )
        menu.exec(self.btn_hl_speed.mapToGlobal(self.btn_hl_speed.rect().bottomLeft()))

    def _open_highlights_clip_menu(self):
        if not isinstance(self.inp, HighlightsInput):
            return
        menu = QMenu(self)
        p_auto = "✓ " if self.inp.auto_advance else "   "
        menu.addAction(
            tr(
                f"{p_auto}🔄 Alle Highlights nacheinander abspielen (Playlist)",
                f"{p_auto}🔄 Play all Highlights sequentially (Playlist)",
            ),
            lambda: (setattr(self.inp, "auto_advance", not self.inp.auto_advance), self.main_win._save_last_preset_silent()),
        )
        menu.addSeparator()
        if not self.inp.clips:
            act_empty = menu.addAction(
                tr("(Noch keine Highlights aufgezeichnet)", "(No Highlights recorded yet)")
            )
            act_empty.setEnabled(False)
        else:
            for i, cpath in enumerate(self.inp.clips):
                prefix = "▶ " if i == self.inp.current_clip_idx else "   "
                bname = os.path.basename(cpath)
                menu.addAction(
                    f"{prefix}Highlight #{i + 1}: {bname}",
                    lambda idx=i: self.inp.select_clip(idx, auto_play=False),
                )
        menu.exec(self.btn_hl_select.mapToGlobal(self.btn_hl_select.rect().bottomLeft()))

    def _on_slide_prev(self):
        if isinstance(self.inp, TextSlideInput):
            self.inp.prev_slide()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _on_slide_next(self):
        if isinstance(self.inp, TextSlideInput):
            self.inp.next_slide()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _on_scroll_mode_clicked(self):
        if isinstance(self.inp, TextSlideInput):
            self.inp.cycle_scroll_mode()
            self._refresh_scroll_toggle_button()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _on_scroll_mode_toggled(self, checked: bool):
        if isinstance(self.inp, TextSlideInput):
            self.inp.set_config(scroll_mode="vertical" if checked else "none")
            self._refresh_scroll_toggle_button()
            if self.main_win:
                self.main_win._save_last_preset_silent()

    def _refresh_scroll_toggle_button(self):
        if not self.btn_scroll_toggle or not isinstance(self.inp, TextSlideInput):
            return
        sm = getattr(self.inp, "scroll_mode", "none")
        if sm == "horizontal":
            self.btn_scroll_toggle.setText("📰")
            self.btn_scroll_toggle.setStyleSheet(
                "padding: 0px 2px; font-size: 9px; background-color: #9e4b1e; color: white; border: 1px solid #ff944d;"
            )
        elif sm == "vertical":
            self.btn_scroll_toggle.setText("📜")
            self.btn_scroll_toggle.setStyleSheet(
                "padding: 0px 2px; font-size: 9px; background-color: #1e6b9e; color: white; border: 1px solid #40a8f0;"
            )
        else:
            self.btn_scroll_toggle.setText("📄")
            self.btn_scroll_toggle.setStyleSheet("padding: 0px 2px; font-size: 9px;")

    def _open_text_slide_menu(self):
        if not isinstance(self.inp, TextSlideInput):
            return
        menu = QMenu(self)
        menu.addAction(
            tr("✎ Mehrzeiligen Text- & Scraper-Editor öffnen...", "✎ Open Multi-Line Text & Scraper Editor..."),
            lambda: self.main_win.edit_text_slide(self.inp),
        )
        menu.addAction(
            tr("🌐 Datei- / Webseiten-Scraper öffnen...", "🌐 Open File / Website Scraper..."),
            lambda: self.main_win.edit_text_slide(self.inp, open_scraper_dialog=True),
        )
        if self.inp.scraper_source:
            menu.addAction(
                tr("🔄 Scraper-Daten jetzt neu abrufen", "🔄 Refresh Scraper Data Now"),
                self.inp.trigger_scrape_async,
            )
        menu.addSeparator()
        for m_key, m_label in TextSlideInput.get_scroll_modes():
            prefix = "✓ " if self.inp.scroll_mode == m_key else "   "
            menu.addAction(
                f"{prefix}{m_label}",
                lambda mk=m_key: (
                    self.inp.set_config(scroll_mode=mk),
                    self._refresh_scroll_toggle_button(),
                    self.main_win._save_last_preset_silent(),
                ),
            )
        menu.addSeparator()
        slides = self.inp.get_slides()
        for idx, s_txt in enumerate(slides):
            first_line = next((ln.strip() for ln in s_txt.splitlines() if ln.strip()), tr("(Leer)", "(Empty)"))
            if len(first_line) > 32:
                first_line = first_line[:32] + "…"
            prefix = "▶ " if idx == self.inp.current_slide_idx else "   "
            menu.addAction(
                f"{prefix}{tr('Folie', 'Slide')} #{idx + 1}: {first_line}",
                lambda i=idx: (self.inp.select_slide(i), self.main_win._save_last_preset_silent()),
            )
        menu.exec(self.btn_slide_select.mapToGlobal(self.btn_slide_select.rect().bottomLeft()))

    def set_index(self, index: int):
        self.index = index
        self.title_lbl.setText(f"{index + 1}: {self.inp.name[:18]}")

    def update_tile(self, is_prv: bool, is_pgm: bool, is_ovl1: bool, is_ovl2: bool):
        if is_pgm:
            self.setStyleSheet("QFrame#PanelFrame { background-color: #29181b; border: 2px solid #f03030; border-radius: 5px; }")
        elif is_prv:
            self.setStyleSheet("QFrame#PanelFrame { background-color: #16261d; border: 2px solid #20d660; border-radius: 5px; }")
        else:
            self.setStyleSheet("QFrame#PanelFrame { background-color: #1c2029; border: 1px solid #2b3140; border-radius: 5px; }")

        self.btn_ovl1.setStyleSheet(
            "padding: 1px 3px; font-size: 9px; background-color: #0088cc; color: white;"
            if is_ovl1 else "padding: 1px 3px; font-size: 9px;"
        )
        self.btn_ovl2.setStyleSheet(
            "padding: 1px 3px; font-size: 9px; background-color: #9933cc; color: white;"
            if is_ovl2 else "padding: 1px 3px; font-size: 9px;"
        )

        if self.mini_vu:
            self.mini_vu.set_level(self.inp.vu_level)

        if self.btn_hl_select and isinstance(self.inp, HighlightsInput):
            total = len(self.inp.clips)
            cur = (self.inp.current_clip_idx + 1) if total > 0 else 0
            txt = f"🎬 #{cur}/{total} ▾"
            if self.btn_hl_select.text() != txt:
                self.btn_hl_select.setText(txt)
        if self.btn_hl_speed and hasattr(self.inp, "playback_rate"):
            stxt = f"⏱{self.inp.playback_rate:g}×"
            if self.btn_hl_speed.text() != stxt:
                self.btn_hl_speed.setText(stxt)

        if self.btn_slide_select and isinstance(self.inp, TextSlideInput):
            slides = self.inp.get_slides()
            total_s = len(slides)
            cur_s = min(total_s, self.inp.current_slide_idx + 1) if total_s > 0 else 1
            if self.inp.scroll_mode == "horizontal":
                stxt = f"📰 {self.inp.scroll_speed}px/s ▾"
            elif self.inp.scroll_mode == "vertical":
                stxt = f"📜 {self.inp.scroll_speed}px/s ▾"
            else:
                stxt = f"📄 #{cur_s}/{total_s} ▾"
            if self.btn_slide_select.text() != stxt:
                self.btn_slide_select.setText(stxt)
        if self.btn_scroll_toggle and isinstance(self.inp, TextSlideInput):
            self._refresh_scroll_toggle_button()

        if self.seek_slider is not None and hasattr(self.inp, "get_position_duration"):
            if self.btn_play_pause:
                expected_icon = "▶" if self.inp.paused else "⏸"
                if self.btn_play_pause.text() != expected_icon:
                    self.btn_play_pause.setText(expected_icon)
            if self.btn_loop:
                self._refresh_loop_button()
            if self.btn_return_prv:
                self._refresh_return_prv_button()

            pos_s, dur_s = self.inp.get_position_duration()
            if dur_s > 0.1:
                self._media_duration = dur_s
            if (
                not self.seek_slider.isSliderDown()
                and time.monotonic() >= self._seek_cooldown_until
                and self._media_duration > 0.1
            ):
                ratio = max(0.0, min(1.0, pos_s / self._media_duration))
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(int(ratio * 1000))
                self.seek_slider.blockSignals(False)
                if self.lbl_timecode:
                    self.lbl_timecode.setText(
                        f"{self._fmt_mm_ss(pos_s)}/{self._fmt_mm_ss(self._media_duration)}"
                    )

        frame = self.inp.get_frame()
        if frame and not frame.isNull():
            if isinstance(self.inp, LowerThirdInput):
                crop = frame.copy(50, max(0, frame.height() - 175), min(720, frame.width() - 50), 140)
                scaled = crop.scaled(
                    164, 62,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                scaled = frame.scaled(
                    164, 62,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            self.thumb_lbl.setPixmap(QPixmap.fromImage(scaled))


class LiteMixMainWindow(QMainWindow):
    """Compact main window in vMix layout optimized for notebooks."""

    APP_VERSION = "0.6.1"
    GITHUB_REPO = "uWiiiDev/LiteMix-HD"
    GITHUB_BRANCH = "main"
    GRID_COLS = 5

    SHORTCUT_DEFINITIONS = [
        # (action_id, category_de, label_de, default_key_str)
        ("cut", "🎬 Regie & Übergänge", "CUT – Harter Schnitt (Preview ↔ Program)", "Space"),
        ("fade", "🎬 Regie & Übergänge", "FADE – Weiche Überblendung", "Return"),
        ("ftb", "🎬 Regie & Übergänge", "FTB – Schwarzblende (Fade to Black)", "B"),
        ("prv_play_pause", "🎬 Regie & Übergänge", "Vorschau-Medium (Video/Audio/Replay) Start / Pause", "P"),
        ("prv_stop", "🎬 Regie & Übergänge", "Vorschau-Medium stoppen & zum Anfang (00:00)", "S"),
        ("ovl1_prv", "🎬 Regie & Übergänge", "OV1 – Aktuelle Preview-Quelle als Overlay 1", "F7"),
        ("ovl2_prv", "🎬 Regie & Übergänge", "OV2 – Aktuelle Preview-Quelle als Overlay 2", "F8"),
        ("replay_toggle", "⏪ Replay, Aufnahme & Audio", "Replay-Aufnahme starten / stoppen", "Ctrl+R"),
        ("rec_toggle", "⏪ Replay, Aufnahme & Audio", "Lokale Aufnahme starten / stoppen (REC)", "F9"),
        ("stream_toggle", "⏪ Replay, Aufnahme & Audio", "Live-Stream starten / stoppen (STREAM)", "F10"),
        ("mic_mute", "⏪ Replay, Aufnahme & Audio", "Mikrofon stummschalten / aktivieren (MIC M)", "M"),
        ("clip_mute", "⏪ Replay, Aufnahme & Audio", "Video-Audio stummschalten / aktivieren (VID M)", "V"),
        ("prv_1", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 1 in PREVIEW laden", "1"),
        ("prv_2", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 2 in PREVIEW laden", "2"),
        ("prv_3", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 3 in PREVIEW laden", "3"),
        ("prv_4", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 4 in PREVIEW laden", "4"),
        ("prv_5", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 5 in PREVIEW laden", "5"),
        ("prv_6", "🔢 Quellen-Schnellwahl (Preview)", "Quelle 6 in PREVIEW laden", "6"),
        ("pgm_1", "🔴 Quellen-Schnellwahl (Program)", "Quelle 1 direkt in PROGRAM schalten (Cut)", "F1"),
        ("pgm_2", "🔴 Quellen-Schnellwahl (Program)", "Quelle 2 direkt in PROGRAM schalten (Cut)", "F2"),
        ("pgm_3", "🔴 Quellen-Schnellwahl (Program)", "Quelle 3 direkt in PROGRAM schalten (Cut)", "F3"),
        ("pgm_4", "🔴 Quellen-Schnellwahl (Program)", "Quelle 4 direkt in PROGRAM schalten (Cut)", "F4"),
        ("pgm_5", "🔴 Quellen-Schnellwahl (Program)", "Quelle 5 direkt in PROGRAM schalten (Cut)", "F5"),
        ("pgm_6", "🔴 Quellen-Schnellwahl (Program)", "Quelle 6 direkt in PROGRAM schalten (Cut)", "F6"),
        ("save_set", "💾 Set & Einstellungen", "Quellen-Set speichern unter...", "Ctrl+S"),
        ("load_set", "💾 Set & Einstellungen", "Quellen-Set laden...", "Ctrl+O"),
        ("open_shortcuts", "💾 Set & Einstellungen", "Tastenkürzel-Einstellungen öffnen", "Ctrl+K"),
        ("ext_output_toggle", "💾 Set & Einstellungen", "Externe PROGRAM-Ausgabe (Fenster/Monitor) ein/aus", "F11"),
        ("open_help", "💾 Set & Einstellungen", "Hilfe & Funktionsübersicht öffnen", "F12"),
    ]

    SHORTCUT_TRANSLATIONS_EN = {
        "🎬 Regie & Übergänge": "🎬 Directing & Transitions",
        "⏪ Replay, Aufnahme & Audio": "⏪ Replay, Recording & Audio",
        "🔢 Quellen-Schnellwahl (Preview)": "🔢 Quick Source Select (Preview)",
        "🔴 Quellen-Schnellwahl (Program)": "🔴 Quick Source Select (Program)",
        "💾 Set & Einstellungen": "💾 Set & Settings",
        "cut": "CUT – Hard Cut (Preview ↔ Program)",
        "fade": "FADE – Smooth Crossfade",
        "ftb": "FTB – Fade to Black",
        "prv_play_pause": "Preview Media (Video/Audio/Replay) Play / Pause",
        "prv_stop": "Stop Preview Media & Rewind (00:00)",
        "ovl1_prv": "OV1 – Toggle Current Preview Source as Overlay 1",
        "ovl2_prv": "OV2 – Toggle Current Preview Source as Overlay 2",
        "replay_toggle": "Start / Stop Replay Recording",
        "rec_toggle": "Start / Stop Local Recording (REC)",
        "stream_toggle": "Start / Stop Live Stream (STREAM)",
        "mic_mute": "Mute / Unmute Microphone (MIC M)",
        "clip_mute": "Mute / Unmute Video Audio (VID M)",
        "prv_1": "Load Source 1 into PREVIEW",
        "prv_2": "Load Source 2 into PREVIEW",
        "prv_3": "Load Source 3 into PREVIEW",
        "prv_4": "Load Source 4 into PREVIEW",
        "prv_5": "Load Source 5 into PREVIEW",
        "prv_6": "Load Source 6 into PREVIEW",
        "pgm_1": "Cut Source 1 directly to PROGRAM",
        "pgm_2": "Cut Source 2 directly to PROGRAM",
        "pgm_3": "Cut Source 3 directly to PROGRAM",
        "pgm_4": "Cut Source 4 directly to PROGRAM",
        "pgm_5": "Cut Source 5 directly to PROGRAM",
        "pgm_6": "Cut Source 6 directly to PROGRAM",
        "save_set": "Save Source Set As...",
        "load_set": "Load Source Set...",
        "open_shortcuts": "Open Hotkey Settings",
        "ext_output_toggle": "Toggle External PROGRAM Output (Window/Monitor)",
        "open_help": "Open Help & Function Guide",
    }

    def __init__(self):
        super().__init__()
        self._load_local_version_metadata()
        self.setWindowTitle(f"LiteMix HD v{self.APP_VERSION}")
        self.setMinimumSize(820, 500)
        self.resize(1120, 660)
        self.setStyleSheet(DARK_STYLESHEET)

        self.mix_w = 1280
        self.mix_h = 720
        self.fps = 30
        self._pgm_canvas = QImage(self.mix_w, self.mix_h, QImage.Format.Format_ARGB32_Premultiplied)

        self.inputs: list[BaseInput] = []
        self.input_tiles: list[InputTileWidget] = []
        self._active_shortcuts: list[QShortcut] = []
        self.shortcuts_map: dict[str, str] = self._default_shortcuts_map()
        self._load_shortcuts_config()

        self.prv_idx = 1
        self.pgm_idx = 0
        self.ovl1_idx = -1  # Overlay 1 (Default: PiP bottom-right, freely draggable & resizable)
        self.ovl2_idx = -1  # Overlay 2 (Default: 1280x720, freely draggable & resizable)
        self.ovl1_rect = [float(self.mix_w - 396), float(self.mix_h - 238), 360.0, 202.0]
        self.ovl2_rect = [0.0, 0.0, float(self.mix_w), float(self.mix_h)]
        self.ovl1_show_border = True
        self.ovl2_show_border = False

        # Transition state
        self.transition_alpha = 0.0  # 0.0 = 100% PGM, 1.0 = 100% PRV
        self.fading_active = False
        self.fade_duration_ms = 600
        self.fade_start_time = 0.0
        self.ftb_active = False

        # Manual replay recording (VA-API GPU -> SSD) + default slow-motion speed
        self.default_replay_rate = 0.5  # 0.25x, 0.5x, 0.75x, 1.0x
        self.replay_recorder = VAAPIReplayRecorder(self.mix_w, self.mix_h, self.fps)

        # Audio, Recorder & Streamer
        self.mic_volume = 0.85
        self.mic_muted = False
        self.recorder = VAAPIRecorder(self.mix_w, self.mix_h, self.fps)
        self.streamer = VAAPIStreamer(self.mix_w, self.mix_h, self.fps)
        self._load_stream_config()

        # FPS & CPU telemetry
        self._frame_count = 0
        self._last_fps_time = time.time()
        self._measured_fps = 30.0
        self._last_cpu_time = time.process_time()
        self._last_wall_time = time.time()
        self._cpu_percent = 0.0

        # External PROGRAM output window (Projector / Fullscreen on Monitor) - created lazily on demand
        self.ext_output_win: ExternalProgramOutputWindow | None = None
        self._last_ext_output_mode = "window"
        self._last_ext_output_screen = 1 if len(QApplication.screens()) > 1 else 0

        self._build_ui()
        last_p = self._last_preset_path()
        if not (os.path.exists(last_p) and self.load_preset_from_file(last_p, silent=True)):
            self._init_default_inputs()
        self._setup_shortcuts()

        # Built-in HTTP Web Controller for iPad / Tablet / Browser (with Token & QR Code)
        self.web_remote = WebRemoteController(self)
        self._refresh_remote_button_style()
        self._refresh_ext_output_button_style()
        self.apply_language()

        # 30 FPS Master Render Loop (PreciseTimer for jitter-free frame pacing)
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.render_timer.timeout.connect(self._on_render_tick)
        self.render_timer.start(int(1000 / self.fps))

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(5, 5, 5, 5)
        root_layout.setSpacing(5)

        # ================= TOP HALF: PREVIEW | TRANSITION | PROGRAM =================
        top_layout = QHBoxLayout()
        top_layout.setSpacing(5)

        self.preview_mon = VideoMonitorWidget(
            "PREVIEW", QColor(32, 214, 96), main_win=self, interactive_overlays=False
        )
        self.program_mon = VideoMonitorWidget(
            "PROGRAM", QColor(240, 48, 48), main_win=self, interactive_overlays=True
        )

        # Compact Center Transition Bar
        trans_frame = QFrame()
        trans_frame.setObjectName("PanelFrame")
        trans_frame.setFixedWidth(86)
        trans_layout = QVBoxLayout(trans_frame)
        trans_layout.setContentsMargins(5, 6, 5, 6)
        trans_layout.setSpacing(5)

        self.btn_cut = QPushButton("CUT")
        self.btn_cut.setObjectName("CutBtn")
        self.btn_cut.clicked.connect(self.do_cut)
        trans_layout.addWidget(self.btn_cut)

        self.btn_fade = QPushButton("FADE")
        self.btn_fade.setObjectName("FadeBtn")
        self.btn_fade.clicked.connect(self.do_fade)
        trans_layout.addWidget(self.btn_fade)

        self.btn_ftb = QPushButton("FTB")
        self.btn_ftb.clicked.connect(self.toggle_ftb)
        trans_layout.addWidget(self.btn_ftb)

        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(100, 3000)
        self.fade_spin.setSingleStep(100)
        self.fade_spin.setSuffix(" ms")
        self.fade_spin.setValue(600)
        self.fade_spin.valueChanged.connect(lambda v: setattr(self, "fade_duration_ms", v))
        trans_layout.addWidget(self.fade_spin)

        # T-Bar slider
        tbar_row = QHBoxLayout()
        tbar_row.addStretch()
        self.tbar_slider = QSlider(Qt.Orientation.Vertical)
        self.tbar_slider.setRange(0, 100)
        self.tbar_slider.setValue(0)
        self.tbar_slider.setMinimumHeight(60)
        self.tbar_slider.valueChanged.connect(self._on_tbar_changed)
        tbar_row.addWidget(self.tbar_slider)
        tbar_row.addStretch()
        trans_layout.addLayout(tbar_row, 1)

        # Manual replay recording (Start / Stop -> Latest Replay & Highlights)
        replay_row = QHBoxLayout()
        replay_row.setSpacing(2)
        self.btn_replay = QPushButton("⏺ REPLAY")
        self.btn_replay.setStyleSheet("padding: 4px 2px; font-size: 9px;")
        self.btn_replay.clicked.connect(self.toggle_manual_replay)

        self.btn_replay_cfg = QPushButton("▾")
        self.btn_replay_cfg.setFixedWidth(18)
        self.btn_replay_cfg.setStyleSheet("padding: 4px 1px; font-size: 9px;")
        self.btn_replay_cfg.clicked.connect(self._open_replay_menu)
        replay_row.addWidget(self.btn_replay, 1)
        replay_row.addWidget(self.btn_replay_cfg)
        trans_layout.addLayout(replay_row)

        top_layout.addWidget(self.preview_mon, 1)
        top_layout.addWidget(trans_frame)
        top_layout.addWidget(self.program_mon, 1)
        root_layout.addLayout(top_layout, 5)

        # ================= BOTTOM HALF: INPUTS GRID + COMPACT AUDIO MIXER =================
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(5)

        # Left: Scrollable Inputs Grid (anchored top-left)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.grid_container)
        bottom_layout.addWidget(scroll, 1)

        # Right: Compact Audio Mixer Panel
        audio_frame = QFrame()
        audio_frame.setObjectName("PanelFrame")
        audio_frame.setFixedWidth(185)
        audio_vbox = QVBoxLayout(audio_frame)
        audio_vbox.setContentsMargins(6, 5, 6, 5)
        audio_vbox.setSpacing(4)

        self.lbl_aud_header = QLabel("<b>AUDIO-MIXER</b>")
        self.lbl_aud_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_aud_header.setStyleSheet("font-size: 10px; color: #909ab0;")
        audio_vbox.addWidget(self.lbl_aud_header)

        strips_hbox = QHBoxLayout()
        strips_hbox.setSpacing(8)

        # Strip 1: Microphone / System Audio
        mic_strip = QVBoxLayout()
        lbl_mic = QLabel("MIC")
        lbl_mic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_mic.setStyleSheet("font-size: 10px;")
        mic_strip.addWidget(lbl_mic)

        mic_meter_row = QHBoxLayout()
        self.mic_vu = VUMeterBar()
        self.mic_slider = QSlider(Qt.Orientation.Vertical)
        self.mic_slider.setRange(0, 120)
        self.mic_slider.setValue(85)
        self.mic_slider.valueChanged.connect(self._on_mic_volume)
        mic_meter_row.addStretch()
        mic_meter_row.addWidget(self.mic_vu)
        mic_meter_row.addWidget(self.mic_slider)
        mic_meter_row.addStretch()
        mic_strip.addLayout(mic_meter_row, 1)

        self.btn_mic_mute = QPushButton("M")
        self.btn_mic_mute.setCheckable(True)
        self.btn_mic_mute.toggled.connect(self._on_mic_mute)
        mic_strip.addWidget(self.btn_mic_mute)
        strips_hbox.addLayout(mic_strip)

        # Strip 2: Video Clips / Sources Audio
        clip_strip = QVBoxLayout()
        lbl_clip = QLabel("VID")
        lbl_clip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_clip.setStyleSheet("font-size: 10px;")
        clip_strip.addWidget(lbl_clip)

        clip_meter_row = QHBoxLayout()
        self.clip_vu = VUMeterBar()
        self.clip_slider = QSlider(Qt.Orientation.Vertical)
        self.clip_slider.setRange(0, 150)
        self.clip_slider.setValue(100)
        self.clip_slider.valueChanged.connect(self._on_clip_volume)
        clip_meter_row.addStretch()
        clip_meter_row.addWidget(self.clip_vu)
        clip_meter_row.addWidget(self.clip_slider)
        clip_meter_row.addStretch()
        clip_strip.addLayout(clip_meter_row, 1)

        self.btn_clip_mute = QPushButton("M")
        self.btn_clip_mute.setCheckable(True)
        self.btn_clip_mute.toggled.connect(self._on_clip_mute)
        clip_strip.addWidget(self.btn_clip_mute)
        strips_hbox.addLayout(clip_strip)

        # Strip 3: Master VU
        mst_strip = QVBoxLayout()
        lbl_mst = QLabel("MST")
        lbl_mst.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_mst.setStyleSheet("font-size: 10px;")
        mst_strip.addWidget(lbl_mst)

        mst_meter_row = QHBoxLayout()
        self.mst_vu = VUMeterBar()
        mst_meter_row.addStretch()
        mst_meter_row.addWidget(self.mst_vu)
        mst_meter_row.addStretch()
        mst_strip.addLayout(mst_meter_row, 1)

        lbl_db = QLabel("0dB")
        lbl_db.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_db.setStyleSheet("font-size: 9px; color: #909ab0;")
        mst_strip.addWidget(lbl_db)
        strips_hbox.addLayout(mst_strip)

        audio_vbox.addLayout(strips_hbox, 1)
        bottom_layout.addWidget(audio_frame)
        root_layout.addLayout(bottom_layout, 4)

        # ================= SLIM FOOTER: ADD INPUT DROPDOWN + REC + TELEMETRY =================
        footer = QFrame()
        footer.setObjectName("PanelFrame")
        foot_layout = QHBoxLayout(footer)
        foot_layout.setContentsMargins(6, 4, 8, 4)
        foot_layout.setSpacing(6)

        # Dropdown button for adding sources (icon-only, saves horizontal space)
        self.btn_add_menu = QPushButton("➕")
        self.btn_add_menu.setObjectName("AddInputBtn")
        foot_layout.addWidget(self.btn_add_menu)

        # Dropdown button for saving/loading source sets (Presets)
        self.btn_set_menu = QPushButton("💾")
        self.btn_set_menu.setObjectName("FooterIconBtn")
        foot_layout.addWidget(self.btn_set_menu)

        self.btn_shortcuts = QPushButton("⌨️")
        self.btn_shortcuts.setObjectName("FooterIconBtn")
        self.btn_shortcuts.clicked.connect(self.open_shortcuts_dialog)
        foot_layout.addWidget(self.btn_shortcuts)

        self.btn_remote = QPushButton("📱")
        self.btn_remote.setObjectName("FooterIconBtn")
        self.btn_remote.clicked.connect(self.open_web_remote_dialog)
        foot_layout.addWidget(self.btn_remote)

        self.btn_ext_output = QPushButton("🖥️")
        self.btn_ext_output.setObjectName("FooterIconBtn")
        self.btn_ext_output.clicked.connect(self.open_ext_output_menu)
        foot_layout.addWidget(self.btn_ext_output)

        self.btn_update = QPushButton("🔄")
        self.btn_update.setObjectName("FooterIconBtn")
        self.btn_update.clicked.connect(self.check_for_updates)
        foot_layout.addWidget(self.btn_update)

        # Live streaming buttons (Start/Stop + Settings)
        self.btn_stream = QPushButton("📡")
        self.btn_stream.setObjectName("StreamBtn")
        self.btn_stream.clicked.connect(self.toggle_streaming)
        foot_layout.addWidget(self.btn_stream)

        self.btn_stream_cfg = QPushButton("⚙️")
        self.btn_stream_cfg.setObjectName("FooterIconBtn")
        self.btn_stream_cfg.clicked.connect(self.open_stream_settings)
        foot_layout.addWidget(self.btn_stream_cfg)

        self.btn_rec = QPushButton("🔴")
        self.btn_rec.setObjectName("RecBtn")
        self.btn_rec.clicked.connect(self.toggle_recording)
        foot_layout.addWidget(self.btn_rec)

        # Language switcher (DE / EN) and Help button (❓)
        self.btn_lang = QPushButton("🌐 DE" if get_lang() == "de" else "🌐 EN")
        self.btn_lang.setObjectName("FooterIconBtn")
        self.btn_lang.setStyleSheet(
            "font-size: 11px; font-weight: bold; padding: 2px 8px; min-width: 48px; min-height: 28px;"
        )
        self.btn_lang.clicked.connect(self.toggle_ui_language)
        foot_layout.addWidget(self.btn_lang)

        self.btn_help = QPushButton("❓")
        self.btn_help.setObjectName("FooterIconBtn")
        self.btn_help.clicked.connect(self.open_help_dialog)
        foot_layout.addWidget(self.btn_help)

        self.lbl_rec_status = QLabel(tr("Bereit (GPU: h264_vaapi)", "Ready (GPU: h264_vaapi)"))
        self.lbl_rec_status.setStyleSheet("color: #98a2b8; font-size: 10px;")
        # Use Ignored horizontal size policy so long status strings never increase the main window's minimum width
        self.lbl_rec_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_rec_status.setMinimumWidth(60)
        foot_layout.addWidget(self.lbl_rec_status, 1)

        self.lbl_stats = QLabel("720p30 | CPU: -- %")
        self.lbl_stats.setStyleSheet("color: #00d890; font-weight: bold; font-size: 11px;")
        self.lbl_stats.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        foot_layout.addWidget(self.lbl_stats)

        root_layout.addWidget(footer)
        self._rebuild_menus()

    def _rebuild_menus(self):
        """Rebuilds the Add-Source and Preset/Settings dropdown menus in the active language."""
        add_menu = QMenu(self)
        add_menu.addAction(
            tr("🪟  Browserfenster / Bildschirm (Wayland)", "🪟  Browser Window / Screen (Wayland)"),
            self.add_wayland_portal_input,
        )
        if HAS_WEBENGINE:
            add_menu.addAction(
                tr("🌐  Integrierter Browser (URL)", "🌐  Built-in Web Browser (URL)"),
                self.add_web_browser_input,
            )
        add_menu.addAction(
            tr("📷  Webcam / Capture Card (V4L2)", "📷  Webcam / Capture Card (V4L2)"),
            self.add_camera_input,
        )
        add_menu.addAction(
            tr("🎬  Video-Datei (MP4 / MKV)", "🎬  Video File (MP4 / MKV)"),
            self.add_video_input,
        )
        add_menu.addAction(
            tr("🖼️  Bild / Logo / Overlay (PNG / JPG)", "🖼️  Image / Logo / Overlay (PNG / JPG)"),
            self.add_image_input,
        )
        add_menu.addAction(
            tr("🏷️  Bauchbinde / Titel (Overlay)", "🏷️  Lower Third / Title (Overlay)"),
            self.add_lower_third_input,
        )
        add_menu.addAction(
            tr(
                "📝  Texttafel / Mehrzeiliger Text, Lauftext & Ticker (Editor)",
                "📝  Text Slide / Multi-Line Text, Scroller & Ticker (Editor)",
            ),
            self.add_text_slide_input,
        )
        add_menu.addAction(
            tr(
                "🌐  Datei- / Webseiten-Scraper (Daten gezielt in Editor / Ticker laden)",
                "🌐  File / Website Scraper (Extract Data into Editor / Ticker)",
            ),
            self.add_scraper_text_input,
        )
        add_menu.addSeparator()
        add_menu.addAction(
            tr("🎙️  Mikrofon / Audio-Eingang", "🎙️  Microphone / Audio Input"),
            self.add_mic_device_input,
        )
        add_menu.addAction(
            tr("🔊  System-Audio / Desktop-Ton (Browser/PC)", "🔊  System Audio / Desktop Sound (Loopback)"),
            self.add_system_audio_input,
        )
        add_menu.addAction(
            tr("🎵  Audio-Datei / Musik / Jingle (MP3/WAV)", "🎵  Audio File / Music / Jingle (MP3/WAV)"),
            self.add_audio_file_input,
        )
        add_menu.addSeparator()
        add_menu.addAction(
            tr("⏪  Letztes Replay (Zeitlupe-Quelle)", "⏪  Latest Replay (Slow-Motion Source)"),
            self.ensure_replay_source_tile,
        )
        add_menu.addAction(
            tr("⭐  Highlights-Quelle (Alle Replays)", "⭐  Highlights Source (All Replays)"),
            self.ensure_highlights_tile,
        )
        add_menu.addSeparator()
        add_menu.addAction(
            tr("📺  Studio-Testbild", "📺  Studio Test Pattern"),
            self.add_test_pattern_input,
        )
        self.btn_add_menu.setMenu(add_menu)

        set_menu = QMenu(self)
        set_menu.addAction(tr("💾  Set speichern unter...", "💾  Save Set As..."), self.save_preset_dialog)
        set_menu.addAction(tr("📂  Set laden...", "📂  Load Set..."), self.load_preset_dialog)
        set_menu.addAction(tr("🔄  Letztes gespeichertes Set laden", "🔄  Load Last Saved Set"), self.load_last_preset)
        set_menu.addSeparator()
        set_menu.addAction(tr("⌨️  Tastenkürzel frei belegen...", "⌨️  Customize Hotkeys..."), self.open_shortcuts_dialog)
        set_menu.addAction(
            tr("📱  Web-Fernsteuerung (iPad / QR-Code)...", "📱  Web Remote Control (iPad / QR Code)..."),
            self.open_web_remote_dialog,
        )
        set_menu.addAction(
            tr("🖥️  Externe PROGRAM-Ausgabe (Fenster / Monitor)...", "🖥️  External PROGRAM Output (Window / Monitor)..."),
            self.open_ext_output_menu,
        )
        set_menu.addAction(tr("❓  Hilfe & Funktionsübersicht...", "❓  Help & Function Guide..."), self.open_help_dialog)
        set_menu.addAction(
            tr("🌐  Sprache wechseln (Deutsch / English)", "🌐  Switch Language (Deutsch / English)"),
            self.toggle_ui_language,
        )
        set_menu.addAction(tr("🔄  Auf Updates prüfen (GitHub)...", "🔄  Check for Updates (GitHub)..."), self.check_for_updates)
        set_menu.addSeparator()
        set_menu.addAction(
            tr("🗑️  Alle Quellen schließen (Leeres Set)", "🗑️  Close All Sources (Empty Set)"),
            self.clear_to_empty_set,
        )
        set_menu.addAction(tr("✨  Standard-Set wiederherstellen", "✨  Restore Default Set"), self.reset_to_default_set)
        self.btn_set_menu.setMenu(set_menu)

    def toggle_ui_language(self):
        new_lang = toggle_lang()
        self.apply_language()
        self.lbl_rec_status.setText(
            "🌐 Sprache auf Deutsch umgestellt" if new_lang == "de" else "🌐 Language switched to English"
        )

    def apply_language(self):
        """Refreshes all UI labels, tooltips, menus, and input tiles to the current language (DE/EN)."""
        lang = get_lang()
        if hasattr(self, "btn_lang"):
            self.btn_lang.setText("🌐 DE" if lang == "de" else "🌐 EN")
            self.btn_lang.setToolTip(
                tr(
                    "Sprache der Oberfläche und Hilfe zwischen Deutsch (DE) und Englisch (EN) wechseln",
                    "Switch user interface and help language between German (DE) and English (EN)",
                )
            )
        if hasattr(self, "btn_help"):
            self.btn_help.setToolTip(
                tr(
                    "Hilfe & Funktionsübersicht öffnen (Erklärung aller Buttons, Icons & Funktionen)",
                    "Open Help & Function Guide (Explanation of all buttons, icons & features)",
                )
            )
        if hasattr(self, "btn_add_menu"):
            self.btn_add_menu.setToolTip(
                tr(
                    "Quelle hinzufügen (Kamera, Video, Audio, Browser, Bauchbinde, Replay ...)",
                    "Add Source (Camera, Video, Audio, Browser, Lower Third, Replay ...)",
                )
            )
        if hasattr(self, "btn_set_menu"):
            self.btn_set_menu.setToolTip(
                tr("Quellen-Set speichern oder laden", "Save or load Source Set (Preset)")
            )
        if hasattr(self, "btn_update"):
            self.btn_update.setToolTip(
                tr(
                    f"Auf GitHub ({self.GITHUB_REPO}) nach Updates suchen & LiteMix HD aktualisieren",
                    f"Check GitHub ({self.GITHUB_REPO}) for updates & update LiteMix HD",
                )
            )
        if hasattr(self, "btn_stream_cfg"):
            self.btn_stream_cfg.setToolTip(
                tr(
                    "Stream-Einstellungen (Server-URL, Stream-Schlüssel & FPS)",
                    "Stream Settings (Server URL, Stream Key & FPS)",
                )
            )
        if hasattr(self, "fade_spin"):
            self.fade_spin.setToolTip(
                tr("Überblenddauer in Millisekunden", "Crossfade duration in milliseconds")
            )
        if hasattr(self, "btn_replay_cfg"):
            self.btn_replay_cfg.setToolTip(
                tr(
                    "Replay-Einstellungen & Quellen (Letztes Replay / Highlights)",
                    "Replay Settings & Sources (Latest Replay / Highlights)",
                )
            )
        if hasattr(self, "mic_slider"):
            self.mic_slider.setToolTip(
                tr("Mikrofon-Pegel (Standard: 85%)", "Microphone volume (Default: 85%)")
            )
        if hasattr(self, "clip_slider"):
            self.clip_slider.setToolTip(
                tr("Video-/Quellen-Audiopegel (0% - 150%)", "Video / Sources audio volume (0% - 150%)")
            )
        if hasattr(self, "lbl_aud_header"):
            self.lbl_aud_header.setText(tr("<b>AUDIO-MIXER</b>", "<b>AUDIO MIXER</b>"))

        if hasattr(self, "preview_mon"):
            self.preview_mon.refresh_language()
        if hasattr(self, "program_mon"):
            self.program_mon.refresh_language()
        if hasattr(self, "ext_output_win") and self.ext_output_win:
            self.ext_output_win.refresh_language()

        self._rebuild_menus()
        self._apply_shortcuts()
        self._refresh_remote_button_style()
        self._refresh_ext_output_button_style()
        for tile in self.input_tiles:
            tile.refresh_language()

    def open_help_dialog(self):
        dlg = HelpDialog(self, on_language_changed=self.apply_language)
        dlg.exec()

    def _init_default_inputs(self):
        # 3 ready-to-use demo inputs just like a pre-configured vMix studio project
        self.add_input(
            TestPatternInput(
                tr("Kamera 1 (Farbbalken)", "Camera 1 (Color Bars)"),
                self.mix_w,
                self.mix_h,
                pattern_style=0,
            )
        )
        self.add_input(
            TestPatternInput(
                tr("Kamera 2 (Studio-Grid)", "Camera 2 (Studio Grid)"),
                self.mix_w,
                self.mix_h,
                pattern_style=1,
            )
        )
        lt = LowerThirdInput(
            tr("Bauchbinde (Overlay)", "Lower Third (Overlay)"),
            "Uwe • Live Studio",
            "LiteMix HD • Intel VA-API Hardware Engine",
            self.mix_w,
            self.mix_h,
        )
        self.add_input(lt)
        self.pgm_idx = 0
        self.prv_idx = 1
        self.ovl2_idx = 2  # Lower third enabled by default as demo!

    # ================= HOTKEY (SHORTCUTS) CONFIGURATION =================
    def _default_shortcuts_map(self) -> dict[str, str]:
        return {aid: default_key for aid, _, _, default_key in self.SHORTCUT_DEFINITIONS}

    def _shortcuts_config_path(self) -> str:
        cfg_dir = os.path.expanduser("~/.config/litemix")
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, "shortcuts.json")

    def _load_shortcuts_config(self):
        p = self._shortcuts_config_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for aid, _, _, _ in self.SHORTCUT_DEFINITIONS:
                        if aid in data and isinstance(data[aid], str):
                            self.shortcuts_map[aid] = data[aid].strip()
            except Exception:
                pass

    def _save_shortcuts_config(self):
        p = self._shortcuts_config_path()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.shortcuts_map, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def toggle_preview_playback(self):
        if 0 <= self.prv_idx < len(self.inputs):
            inp = self.inputs[self.prv_idx]
            if hasattr(inp, "toggle_pause"):
                inp.toggle_pause()
                self.preview_mon.update()

    def stop_preview_playback(self):
        if 0 <= self.prv_idx < len(self.inputs):
            inp = self.inputs[self.prv_idx]
            if hasattr(inp, "stop_playback"):
                inp.stop_playback()
                self.preview_mon.update()

    # Aliases used by web_remote.py
    toggle_preview_media_play = toggle_preview_playback
    stop_preview_media = stop_preview_playback

    def _get_action_callback(self, action_id: str):
        mapping = {
            "cut": self.do_cut,
            "fade": self.do_fade,
            "ftb": self.toggle_ftb,
            "prv_play_pause": self.toggle_preview_playback,
            "prv_stop": self.stop_preview_playback,
            "ovl1_prv": lambda: self.toggle_overlay(1, self.prv_idx),
            "ovl2_prv": lambda: self.toggle_overlay(2, self.prv_idx),
            "replay_toggle": self.toggle_manual_replay,
            "rec_toggle": self.toggle_recording,
            "stream_toggle": self.toggle_streaming,
            "mic_mute": lambda: self.btn_mic_mute.setChecked(not self.btn_mic_mute.isChecked()),
            "clip_mute": lambda: self.btn_clip_mute.setChecked(not self.btn_clip_mute.isChecked()),
            "prv_1": lambda: self.set_preview(0),
            "prv_2": lambda: self.set_preview(1),
            "prv_3": lambda: self.set_preview(2),
            "prv_4": lambda: self.set_preview(3),
            "prv_5": lambda: self.set_preview(4),
            "prv_6": lambda: self.set_preview(5),
            "pgm_1": lambda: self.cut_input_to_program(0),
            "pgm_2": lambda: self.cut_input_to_program(1),
            "pgm_3": lambda: self.cut_input_to_program(2),
            "pgm_4": lambda: self.cut_input_to_program(3),
            "pgm_5": lambda: self.cut_input_to_program(4),
            "pgm_6": lambda: self.cut_input_to_program(5),
            "save_set": self.save_preset_dialog,
            "load_set": self.load_preset_dialog,
            "open_shortcuts": self.open_shortcuts_dialog,
            "ext_output_toggle": self.toggle_external_program_output,
            "open_help": self.open_help_dialog,
        }
        return mapping.get(action_id)

    def _setup_shortcuts(self):
        self._apply_shortcuts()

    def _apply_shortcuts(self):
        for sc in self._active_shortcuts:
            try:
                sc.setEnabled(False)
                sc.setParent(None)
                sc.deleteLater()
            except Exception:
                pass
        self._active_shortcuts.clear()

        for aid, _, _, _ in self.SHORTCUT_DEFINITIONS:
            key_str = self.shortcuts_map.get(aid, "").strip()
            cb = self._get_action_callback(aid)
            if key_str and cb is not None:
                sc = QShortcut(QKeySequence(key_str), self)
                sc.activated.connect(cb)
                self._active_shortcuts.append(sc)

        # Dynamically update main button tooltips with their assigned shortcut key
        def _fmt_tip(base_text: str, aid: str) -> str:
            k = self.shortcuts_map.get(aid, "").strip()
            return f"{base_text} [{k}]" if k else base_text

        if hasattr(self, "btn_cut"):
            self.btn_cut.setToolTip(_fmt_tip(tr("Harter Schnitt", "Hard Cut"), "cut"))
        if hasattr(self, "btn_fade"):
            self.btn_fade.setToolTip(_fmt_tip(tr("Weiche Überblendung", "Smooth Crossfade"), "fade"))
        if hasattr(self, "btn_ftb"):
            self.btn_ftb.setToolTip(_fmt_tip(tr("Fade to Black (Schwarzblende)", "Fade to Black"), "ftb"))
        if hasattr(self, "btn_replay"):
            self.btn_replay.setToolTip(
                _fmt_tip(tr("Manuelle Replay-Aufnahme starten/stoppen", "Start/stop manual Replay recording"), "replay_toggle")
            )
        if hasattr(self, "btn_rec"):
            self.btn_rec.setToolTip(
                _fmt_tip(tr("Lokale Aufnahme in ~/Videos starten/stoppen", "Start/stop local recording to ~/Videos"), "rec_toggle")
            )
        if hasattr(self, "btn_stream"):
            self.btn_stream.setToolTip(
                _fmt_tip(tr("Live-Stream starten/stoppen", "Start/stop Live Stream"), "stream_toggle")
            )
        if hasattr(self, "btn_mic_mute"):
            self.btn_mic_mute.setToolTip(_fmt_tip(tr("Mikrofon stummschalten", "Mute Microphone"), "mic_mute"))
        if hasattr(self, "btn_clip_mute"):
            self.btn_clip_mute.setToolTip(_fmt_tip(tr("Video-Audio stummschalten", "Mute Video Audio"), "clip_mute"))
        if hasattr(self, "btn_shortcuts"):
            self.btn_shortcuts.setToolTip(
                _fmt_tip(
                    tr(
                        "Tastenkürzel (Hotkeys) für Buttons & Funktionen frei belegen",
                        "Freely assign keyboard shortcuts (Hotkeys) to buttons & functions",
                    ),
                    "open_shortcuts",
                )
            )
        if hasattr(self, "btn_help"):
            self.btn_help.setToolTip(
                _fmt_tip(
                    tr(
                        "Hilfe & Funktionsübersicht öffnen (Erklärung aller Buttons, Icons & Funktionen)",
                        "Open Help & Function Guide (Explanation of all buttons, icons & features)",
                    ),
                    "open_help",
                )
            )

    def open_shortcuts_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr("⌨️ Tastenkürzel (Hotkeys) frei zuordnen", "⌨️ Customize Keyboard Shortcuts (Hotkeys)")
        )
        dlg.resize(580, 530)
        dlg.setStyleSheet(DARK_STYLESHEET)

        vbox = QVBoxLayout(dlg)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        info_lbl = QLabel(
            tr(
                "Klicke in ein Feld und drücke die gewünschte Taste oder Tastenkombination "
                "(mit <b>✕</b> kannst du eine Belegung löschen):",
                "Click a field and press the desired key or key combination "
                "(use <b>✕</b> to clear a shortcut):",
            )
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #b0bcd0; font-size: 11px;")
        vbox.addWidget(info_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        editors: dict[str, QKeySequenceEdit] = {}
        current_cat = None
        row_idx = 0
        is_en = get_lang() == "en"

        for aid, cat_de, label_de, _ in self.SHORTCUT_DEFINITIONS:
            cat = self.SHORTCUT_TRANSLATIONS_EN.get(cat_de, cat_de) if is_en else cat_de
            label = self.SHORTCUT_TRANSLATIONS_EN.get(aid, label_de) if is_en else label_de
            if cat != current_cat:
                current_cat = cat
                cat_lbl = QLabel(f"<b>{cat}</b>")
                cat_lbl.setStyleSheet(
                    "color: #00d890; font-size: 11px; padding-top: 6px; padding-bottom: 2px;"
                )
                grid.addWidget(cat_lbl, row_idx, 0, 1, 3)
                row_idx += 1

            lbl = QLabel(label)
            ks_edit = QKeySequenceEdit(QKeySequence(self.shortcuts_map.get(aid, "")))
            if hasattr(ks_edit, "setMaximumSequenceLength"):
                ks_edit.setMaximumSequenceLength(1)
            ks_edit.setFixedWidth(135)
            editors[aid] = ks_edit

            btn_clear = QPushButton("✕")
            btn_clear.setFixedWidth(26)
            btn_clear.setToolTip(tr("Tastenkürzel löschen (keine Taste)", "Clear shortcut (no key)"))
            btn_clear.clicked.connect(lambda _, e=ks_edit: e.clear())

            # If a key is assigned twice, automatically clear the older duplicate assignment
            def _on_seq_changed(seq: QKeySequence, cur_aid=aid):
                s_txt = seq.toString().strip()
                if not s_txt:
                    return
                for other_aid, other_ed in editors.items():
                    if other_aid != cur_aid and other_ed.keySequence().toString().strip().lower() == s_txt.lower():
                        other_ed.blockSignals(True)
                        other_ed.clear()
                        other_ed.blockSignals(False)

            ks_edit.keySequenceChanged.connect(_on_seq_changed)

            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(ks_edit, row_idx, 1)
            grid.addWidget(btn_clear, row_idx, 2)
            row_idx += 1

        scroll.setWidget(container)
        vbox.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton(tr("↺ Standard wiederherstellen", "↺ Restore Defaults"))
        btn_reset.setToolTip(
            tr(
                "Alle Tastenkürzel auf die Werkseinstellungen zurücksetzen",
                "Reset all keyboard shortcuts to factory defaults",
            )
        )

        def _reset_defaults():
            defaults = self._default_shortcuts_map()
            for aid_k, ed in editors.items():
                ed.blockSignals(True)
                ed.setKeySequence(QKeySequence(defaults.get(aid_k, "")))
                ed.blockSignals(False)

        btn_reset.clicked.connect(_reset_defaults)

        btn_cancel = QPushButton(tr("Abbrechen", "Cancel"))
        btn_ok = QPushButton(tr("✓ Speichern & Übernehmen", "✓ Save & Apply"))
        btn_ok.setObjectName("AddInputBtn")
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        vbox.addLayout(btn_row)

        if dlg.exec():
            for aid_k, ed in editors.items():
                self.shortcuts_map[aid_k] = ed.keySequence().toString().strip()
            self._apply_shortcuts()
            self._save_shortcuts_config()
            self._save_last_preset_silent()
            self.lbl_rec_status.setText(
                tr("⌨️ Tastenkürzel aktualisiert & gespeichert", "⌨️ Hotkeys updated & saved")
            )

    # ================= SAVE & LOAD SOURCE SETS (PRESETS) =================
    def _last_preset_path(self) -> str:
        cfg_dir = os.path.expanduser("~/.config/litemix")
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, "last_set.litemix")

    def _clear_all_inputs(self):
        for inp in self.inputs:
            inp.stop()
        self.inputs.clear()
        for tile in self.input_tiles:
            self.grid_layout.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self.input_tiles.clear()
        self.pgm_idx = 0
        self.prv_idx = 0
        self.ovl1_idx = -1
        self.ovl2_idx = -1

    def _build_preset_dict(self) -> dict:
        return {
            "app": "LiteMix HD",
            "version": self.APP_VERSION,
            "fps": self.fps,
            "pgm_idx": self.pgm_idx,
            "prv_idx": self.prv_idx,
            "ovl1_idx": self.ovl1_idx,
            "ovl2_idx": self.ovl2_idx,
            "ovl1_rect": [round(v, 1) for v in self.ovl1_rect],
            "ovl2_rect": [round(v, 1) for v in self.ovl2_rect],
            "ovl1_show_border": self.ovl1_show_border,
            "ovl2_show_border": self.ovl2_show_border,
            "default_replay_rate": self.default_replay_rate,
            "fade_duration_ms": self.fade_duration_ms,
            "shortcuts": dict(self.shortcuts_map),
            "inputs": [serialize_input(inp) for inp in self.inputs],
        }

    def _save_last_preset_silent(self):
        try:
            data = self._build_preset_dict()
            with open(self._last_preset_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def save_preset_to_file(self, filepath: str) -> bool:
        data = self._build_preset_dict()
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Also remember as "Last Set"
            last_p = self._last_preset_path()
            if os.path.abspath(filepath) != os.path.abspath(last_p):
                with open(last_p, "w", encoding="utf-8") as f2:
                    json.dump(data, f2, indent=2, ensure_ascii=False)
            self.lbl_rec_status.setText(
                tr(
                    f"💾 Set gespeichert: {os.path.basename(filepath)}",
                    f"💾 Set saved: {os.path.basename(filepath)}",
                )
            )
            return True
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("Fehler beim Speichern", "Save Error"),
                tr(f"Set konnte nicht gespeichert werden:\n{e}", f"Could not save set:\n{e}"),
            )
            return False

    def load_preset_from_file(self, filepath: str, silent: bool = False) -> bool:
        if not os.path.exists(filepath):
            if not silent:
                QMessageBox.warning(
                    self,
                    tr("Set nicht gefunden", "Set Not Found"),
                    tr(f"Datei nicht gefunden:\n{filepath}", f"File not found:\n{filepath}"),
                )
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_inputs = data.get("inputs", [])
            new_inputs = []
            for item in raw_inputs:
                inp = deserialize_input(item, self.mix_w, self.mix_h)
                if inp is not None:
                    new_inputs.append(inp)

            if not new_inputs and raw_inputs:
                if not silent:
                    QMessageBox.warning(
                        self,
                        tr("Leeres Set", "Empty Set"),
                        tr(
                            "Keine gültigen Quellen in dieser Set-Datei gefunden.",
                            "No valid sources found in this set file.",
                        ),
                    )
                return False

            self._clear_all_inputs()
            for inp in new_inputs:
                self.add_input(inp)

            n = len(self.inputs)
            if n > 0:
                self.pgm_idx = max(0, min(n - 1, int(data.get("pgm_idx", 0))))
                self.prv_idx = max(0, min(n - 1, int(data.get("prv_idx", min(1, n - 1)))))
                ov1 = int(data.get("ovl1_idx", -1))
                ov2 = int(data.get("ovl2_idx", -1))
                self.ovl1_idx = ov1 if 0 <= ov1 < n else -1
                self.ovl2_idx = ov2 if 0 <= ov2 < n else -1
            else:
                self.pgm_idx = 0
                self.prv_idx = 0
                self.ovl1_idx = -1
                self.ovl2_idx = -1

            r1 = data.get("ovl1_rect")
            if isinstance(r1, list) and len(r1) == 4:
                self.ovl1_rect = [float(v) for v in r1]
            r2 = data.get("ovl2_rect")
            if isinstance(r2, list) and len(r2) == 4:
                self.ovl2_rect = [float(v) for v in r2]
            if "ovl1_show_border" in data:
                self.ovl1_show_border = bool(data["ovl1_show_border"])
            if "ovl2_show_border" in data:
                self.ovl2_show_border = bool(data["ovl2_show_border"])
            if "default_replay_rate" in data:
                self.default_replay_rate = max(0.1, min(2.0, float(data["default_replay_rate"])))
            elif "replay_speed" in data:
                self.default_replay_rate = max(0.1, min(2.0, float(data["replay_speed"])))

            sc_dict = data.get("shortcuts")
            if isinstance(sc_dict, dict) and (not silent or not os.path.exists(self._shortcuts_config_path())):
                for aid, _, _, _ in self.SHORTCUT_DEFINITIONS:
                    if aid in sc_dict and isinstance(sc_dict[aid], str):
                        self.shortcuts_map[aid] = sc_dict[aid].strip()
                self._apply_shortcuts()
                self._save_shortcuts_config()

            fdur = int(data.get("fade_duration_ms", 600))
            self.fade_spin.setValue(fdur)

            last_p = self._last_preset_path()
            if os.path.abspath(filepath) != os.path.abspath(last_p):
                self._save_last_preset_silent()

            self.lbl_rec_status.setText(
                tr(
                    f"📂 Set geladen: {os.path.basename(filepath)} ({n} Quellen)",
                    f"📂 Set loaded: {os.path.basename(filepath)} ({n} sources)",
                )
            )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(
                    self,
                    tr("Fehler beim Laden", "Load Error"),
                    tr(f"Set konnte nicht geladen werden:\n{e}", f"Could not load set:\n{e}"),
                )
            return False

    def save_preset_dialog(self):
        default_dir = os.path.expanduser("~/Dokumente")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Quellen-Set speichern", "Save Source Set"),
            os.path.join(default_dir, "MeinStudio.litemix"),
            "LiteMix Set (*.litemix);;JSON (*.json)",
        )
        if path:
            if not path.endswith((".litemix", ".json")):
                path += ".litemix"
            self.save_preset_to_file(path)

    def load_preset_dialog(self):
        default_dir = os.path.expanduser("~/Dokumente")
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Quellen-Set laden", "Load Source Set"),
            default_dir,
            tr("LiteMix Set (*.litemix *.json);;Alle Dateien (*)", "LiteMix Set (*.litemix *.json);;All Files (*)"),
        )
        if path:
            self.load_preset_from_file(path)

    def load_last_preset(self):
        self.load_preset_from_file(self._last_preset_path())

    def clear_to_empty_set(self):
        self._clear_all_inputs()
        self._save_last_preset_silent()
        self.lbl_rec_status.setText(
            tr("🗑️ Alle Quellen geschlossen (Leeres Set)", "🗑️ All sources closed (Empty Set)")
        )

    def reset_to_default_set(self):
        self._clear_all_inputs()
        self._init_default_inputs()
        self._save_last_preset_silent()
        self.lbl_rec_status.setText(
            tr("✨ Standard-Set wiederhergestellt", "✨ Default Set restored")
        )

    # ================= INPUT MANAGEMENT =================
    def add_input(self, inp: BaseInput):
        idx = len(self.inputs)
        self.inputs.append(inp)
        cols = self.GRID_COLS
        tile = InputTileWidget(idx, inp, self)
        self.input_tiles.append(tile)
        self.grid_layout.addWidget(tile, idx // cols, idx % cols)

    def remove_input(self, index: int):
        if not (0 <= index < len(self.inputs)):
            return
        inp = self.inputs.pop(index)
        inp.stop()

        removed_tile = self.input_tiles.pop(index)
        self.grid_layout.removeWidget(removed_tile)
        removed_tile.setParent(None)
        removed_tile.deleteLater()

        if self.pgm_idx > index:
            self.pgm_idx -= 1
        elif self.pgm_idx >= len(self.inputs):
            self.pgm_idx = max(0, len(self.inputs) - 1)

        if self.prv_idx > index:
            self.prv_idx -= 1
        elif self.prv_idx >= len(self.inputs):
            self.prv_idx = max(0, len(self.inputs) - 1)

        if self.ovl1_idx == index:
            self.ovl1_idx = -1
        elif self.ovl1_idx > index:
            self.ovl1_idx -= 1
        if self.ovl2_idx == index:
            self.ovl2_idx = -1
        elif self.ovl2_idx > index:
            self.ovl2_idx -= 1

        cols = self.GRID_COLS
        for idx in range(index, len(self.input_tiles)):
            tile = self.input_tiles[idx]
            tile.set_index(idx)
            self.grid_layout.addWidget(tile, idx // cols, idx % cols)
        self._save_last_preset_silent()

    def add_test_pattern_input(self):
        num = len(self.inputs) + 1
        self.add_input(
            TestPatternInput(
                tr(f"Testbild {num}", f"Test Pattern {num}"),
                self.mix_w,
                self.mix_h,
                pattern_style=num % 2,
            )
        )

    def add_wayland_portal_input(self):
        inp = WaylandPortalInput(
            tr("Browser / Fenster (PipeWire)", "Browser / Window (PipeWire)"),
            self.mix_w,
            self.mix_h,
        )
        self.add_input(inp)

    def add_web_browser_input(self):
        url, ok = QInputDialog.getText(
            self,
            tr("Integriertes Browserfenster hinzufügen", "Add Built-in Browser Window"),
            tr("Web-Adresse (URL):", "Web Address (URL):"),
            text=tr("https://de.wikipedia.org", "https://en.wikipedia.org"),
        )
        if ok and url.strip():
            u = url.strip()
            if not u.startswith(("http://", "https://", "file://")):
                u = "https://" + u
            inp = WebBrowserInput(u, self.mix_w, self.mix_h)
            self.add_input(inp)

    def add_camera_input(self):
        devs = sorted(glob.glob("/dev/video*"))
        if not devs:
            QMessageBox.warning(
                self,
                tr("Keine Kamera", "No Camera"),
                tr("Keine /dev/video* Geräte gefunden.", "No /dev/video* devices found."),
            )
            return
        dev, ok = QInputDialog.getItem(
            self,
            tr("Webcam / Capture Card wählen", "Select Webcam / Capture Card"),
            tr("Video4Linux2-Gerät:", "Video4Linux2 Device:"),
            devs,
            0,
            False,
        )
        if ok and dev:
            self.add_input(V4L2CameraInput(dev, self.mix_w, self.mix_h))

    def add_video_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Video-Datei auswählen", "Select Video File"),
            os.path.expanduser("~"),
            tr(
                "Videos (*.mp4 *.mkv *.webm *.avi *.mov);;Alle Dateien (*)",
                "Videos (*.mp4 *.mkv *.webm *.avi *.mov);;All Files (*)",
            ),
        )
        if path:
            self.add_input(VideoFileInput(path, self.mix_w, self.mix_h))

    def add_image_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Bild / Overlay auswählen", "Select Image / Overlay"),
            os.path.expanduser("~"),
            tr(
                "Bilder (*.png *.jpg *.jpeg *.svg *.webp);;Alle Dateien (*)",
                "Images (*.png *.jpg *.jpeg *.svg *.webp);;All Files (*)",
            ),
        )
        if path:
            self.add_input(ImageInput(path, self.mix_w, self.mix_h))

    def add_lower_third_input(self):
        lt = LowerThirdInput(
            tr("Bauchbinde", "Lower Third"),
            tr("Titel / Name", "Title / Name"),
            tr("Untertitel / Sendung", "Subtitle / Show"),
            self.mix_w,
            self.mix_h,
        )
        self.add_input(lt)
        self.edit_lower_third(lt)

    def add_text_slide_input(self):
        ts = TextSlideInput(width=self.mix_w, height=self.mix_h)
        self.add_input(ts)
        self.edit_text_slide(ts)

    def add_scraper_text_input(self):
        ts = TextSlideInput(
            name=tr("🌐 Live-Daten / Ticker", "🌐 Live Data / Ticker"),
            headline=tr("LIVE-DATEN", "LIVE DATA"),
            width=self.mix_w,
            height=self.mix_h,
        )
        self.add_input(ts)
        self.edit_text_slide(ts, open_scraper_dialog=True)

    def add_mic_device_input(self):
        sources, _ = list_audio_devices()
        labels = [lbl for _, lbl in sources]
        choice, ok = QInputDialog.getItem(
            self,
            tr("Mikrofon / Audio-Eingang wählen", "Select Microphone / Audio Input"),
            tr("Verfügbare Audio-Eingänge (PipeWire):", "Available Audio Inputs (PipeWire):"),
            labels,
            0,
            False,
        )
        if ok and choice:
            idx = labels.index(choice)
            dev_id, lbl = sources[idx]
            self.add_input(MicDeviceInput(dev_id, lbl, self.mix_w, self.mix_h))

    def add_system_audio_input(self):
        _, monitors = list_audio_devices()
        labels = [lbl for _, lbl in monitors]
        choice, ok = QInputDialog.getItem(
            self,
            tr("System-Audio / Desktop-Ton wählen", "Select System Audio / Desktop Sound"),
            tr("Verfügbare System-Ausgänge (Loopback):", "Available System Outputs (Loopback):"),
            labels,
            0,
            False,
        )
        if ok and choice:
            idx = labels.index(choice)
            mon_id, lbl = monitors[idx]
            self.add_input(SystemAudioInput(mon_id, lbl, self.mix_w, self.mix_h))

    def add_audio_file_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Audio-Datei / Musik / Jingle auswählen", "Select Audio File / Music / Jingle"),
            os.path.expanduser("~"),
            tr(
                "Audio-Dateien (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;Alle Dateien (*)",
                "Audio Files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;All Files (*)",
            ),
        )
        if path:
            self.add_input(AudioFileInput(path, self.mix_w, self.mix_h))

    def edit_lower_third(self, lt: LowerThirdInput):
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr("Bauchbinde (Lower Third) – Template & Text", "Lower Third – Template & Text")
        )
        dlg.setMinimumWidth(460)
        form = QFormLayout(dlg)

        orig_title = lt.title
        orig_sub = lt.subtitle
        orig_tpl = getattr(lt, "template_id", 0)

        combo_tpl = QComboBox()
        templates = LowerThirdInput.get_templates()
        for tpl_id, tpl_label in templates:
            combo_tpl.addItem(tpl_label, tpl_id)
        combo_tpl.setCurrentIndex(orig_tpl if 0 <= orig_tpl < len(templates) else 0)

        e_title = QLineEdit(lt.title)
        e_sub = QLineEdit(lt.subtitle)

        preview_lbl = QLabel()
        preview_lbl.setFixedSize(430, 96)
        preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_lbl.setStyleSheet(
            "background-color: #161b26; border: 1px solid #323c52; border-radius: 5px;"
        )

        def _update_live_preview():
            tid = int(combo_tpl.currentData() or 0)
            lt.set_texts(e_title.text(), e_sub.text(), template_id=tid)
            full_img = lt.get_frame()
            if not full_img.isNull():
                crop = full_img.copy(50, max(0, lt.height - 175), min(720, lt.width - 50), 140)
                scaled = crop.scaled(
                    422, 88,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                preview_lbl.setPixmap(QPixmap.fromImage(scaled))

        combo_tpl.currentIndexChanged.connect(lambda _: _update_live_preview())
        e_title.textChanged.connect(lambda _: _update_live_preview())
        e_sub.textChanged.connect(lambda _: _update_live_preview())
        _update_live_preview()

        form.addRow(tr("Design-Template:", "Design Template:"), combo_tpl)
        form.addRow(tr("Hauptzeile (Name/Titel):", "Main Line (Name/Title):"), e_title)
        form.addRow(tr("Unterzeile (Info):", "Subline (Info):"), e_sub)
        form.addRow(tr("Live-Vorschau:", "Live Preview:"), preview_lbl)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton(tr("Abbrechen", "Cancel"))
        btn_ok = QPushButton(tr("✓ Übernehmen", "✓ Apply"))
        btn_ok.setObjectName("AddInputBtn")
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok, 1)
        form.addRow(btn_row)

        if dlg.exec():
            tid = int(combo_tpl.currentData() or 0)
            lt.set_texts(e_title.text(), e_sub.text(), template_id=tid)
            self._save_last_preset_silent()
        else:
            lt.set_texts(orig_title, orig_sub, template_id=orig_tpl)

    def _open_scraper_inspector_dialog(
        self,
        parent_dlg: QWidget,
        ts: TextSlideInput,
        e_src: QLineEdit,
        combo_smode: QComboBox,
        e_sel: QLineEdit,
        e_body: QPlainTextEdit,
        combo_bg: QComboBox,
        combo_scroll_mode: QComboBox,
        on_applied,
    ):
        """
        Interactive File & Website Scraper Inspector:
        Fetches structured data items from the specified URL or local file, displays all extracted
        items with checkboxes ({1}, {2}, ...), and allows transferring selected items directly into
        the multi-line text editor as lines, slides (---), horizontal ticker (+++), or live placeholders.
        """
        ts.set_config(
            scraper_source=e_src.text().strip(),
            scraper_mode=str(combo_smode.currentData() or "auto"),
            scraper_selector=e_sel.text().strip(),
        )
        ok, items, msg = ts.trigger_scrape_sync()

        sdlg = QDialog(parent_dlg)
        sdlg.setWindowTitle(
            tr(
                "🌐 Datei- & Webseiten-Scraper – Daten gezielt auswählen & in Editor übernehmen",
                "🌐 File & Website Scraper – Select & Transfer Data to Editor",
            )
        )
        sdlg.setMinimumWidth(680)
        sdlg.setMinimumHeight(480)
        sv = QVBoxLayout(sdlg)
        sv.setSpacing(6)

        lbl_status = QLabel(msg)
        lbl_status.setStyleSheet(
            "color: #00d890; font-weight: bold; font-size: 11px;"
            if ok else "color: #ff6060; font-weight: bold; font-size: 11px;"
        )
        sv.addWidget(lbl_status)

        lbl_hint = QLabel(
            tr(
                "Hake die gewünschten Datenfelder an und wähle unten, wie sie in den mehrzeiligen Editor übernommen werden sollen:",
                "Check the desired data items and choose below how to transfer them into the multi-line editor:",
            )
        )
        lbl_hint.setStyleSheet("color: #b8c4d8; font-size: 10px;")
        sv.addWidget(lbl_hint)

        list_w = QListWidget()
        list_w.setStyleSheet(
            "QListWidget { background-color: #10141d; color: #f0f4fc; border: 1px solid #343e54; "
            "border-radius: 5px; font-size: 11px; padding: 4px; }"
        )
        for idx, item_txt in enumerate(items):
            li = QListWidgetItem(f"{{{idx + 1}}}  {item_txt}")
            li.setData(Qt.ItemDataRole.UserRole, (idx + 1, item_txt))
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            li.setCheckState(Qt.CheckState.Checked if idx < 10 else Qt.CheckState.Unchecked)
            list_w.addItem(li)
        sv.addWidget(list_w, 1)

        sel_btns = QHBoxLayout()
        btn_all = QPushButton(tr("☑ Alle auswählen", "☑ Select All"))
        btn_none = QPushButton(tr("☐ Auswahl aufheben", "☐ Select None"))
        btn_top5 = QPushButton(tr("Top 5 auswählen", "Select Top 5"))

        def _set_checks(mode_str: str):
            for i in range(list_w.count()):
                it = list_w.item(i)
                if mode_str == "all":
                    it.setCheckState(Qt.CheckState.Checked)
                elif mode_str == "none":
                    it.setCheckState(Qt.CheckState.Unchecked)
                elif mode_str == "top5":
                    it.setCheckState(Qt.CheckState.Checked if i < 5 else Qt.CheckState.Unchecked)

        btn_all.clicked.connect(lambda: _set_checks("all"))
        btn_none.clicked.connect(lambda: _set_checks("none"))
        btn_top5.clicked.connect(lambda: _set_checks("top5"))
        sel_btns.addWidget(btn_all)
        sel_btns.addWidget(btn_none)
        sel_btns.addWidget(btn_top5)
        sel_btns.addStretch()
        sv.addLayout(sel_btns)

        def _get_selected_pairs() -> list[tuple[int, str]]:
            chosen = []
            for i in range(list_w.count()):
                it = list_w.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    chosen.append(it.data(Qt.ItemDataRole.UserRole))
            if not chosen and list_w.currentItem() is not None:
                chosen.append(list_w.currentItem().data(Qt.ItemDataRole.UserRole))
            return chosen

        act_grid = QGridLayout()
        act_grid.setSpacing(6)

        btn_as_lines = QPushButton(tr("📥 Als Textzeilen übernehmen (Ersetzen)", "📥 Transfer as Lines (Replace)"))
        btn_as_slides = QPushButton(tr("📑 Als einzelne Folien (---) übernehmen", "📑 Transfer as Separate Slides (---)"))
        btn_as_ticker = QPushButton(tr("📰 Als Horizontal-Ticker (+++) übernehmen", "📰 Transfer as Horizontal Ticker (+++)"))
        btn_append = QPushButton(tr("➕ An Editor-Text anhängen", "➕ Append to Editor Text"))
        btn_placeholders = QPushButton(
            tr(
                "🔗 Als Live-Platzhalter {1}, {2}... übernehmen (Auto-Update)",
                "🔗 Insert as Live Placeholders {1}, {2}... (Auto-Update)",
            )
        )
        btn_close = QPushButton(tr("Schließen", "Close"))

        def _transfer(kind: str):
            pairs = _get_selected_pairs()
            if not pairs:
                return
            texts = [txt for _, txt in pairs]
            if kind == "lines":
                e_body.setPlainText("\n".join(texts))
            elif kind == "slides":
                e_body.setPlainText("\n---\n".join(texts))
                idx_none = combo_scroll_mode.findData("none")
                if idx_none >= 0:
                    combo_scroll_mode.setCurrentIndex(idx_none)
            elif kind == "ticker":
                e_body.setPlainText("\n".join(texts))
                idx_hor = combo_scroll_mode.findData("horizontal")
                if idx_hor >= 0:
                    combo_scroll_mode.setCurrentIndex(idx_hor)
                idx_bg5 = combo_bg.findData(5)
                if idx_bg5 >= 0:
                    combo_bg.setCurrentIndex(idx_bg5)
            elif kind == "append":
                cur_txt = e_body.toPlainText().rstrip()
                e_body.setPlainText((cur_txt + "\n" if cur_txt else "") + "\n".join(texts))
            elif kind == "placeholders":
                ph_lines = [f"{{{num}}}" for num, _ in pairs]
                e_body.setPlainText("\n".join(ph_lines))
            on_applied()
            sdlg.accept()

        btn_as_lines.clicked.connect(lambda: _transfer("lines"))
        btn_as_slides.clicked.connect(lambda: _transfer("slides"))
        btn_as_ticker.clicked.connect(lambda: _transfer("ticker"))
        btn_append.clicked.connect(lambda: _transfer("append"))
        btn_placeholders.clicked.connect(lambda: _transfer("placeholders"))
        btn_close.clicked.connect(sdlg.reject)

        act_grid.addWidget(btn_as_lines, 0, 0)
        act_grid.addWidget(btn_as_slides, 0, 1)
        act_grid.addWidget(btn_as_ticker, 0, 2)
        act_grid.addWidget(btn_append, 1, 0)
        act_grid.addWidget(btn_placeholders, 1, 1)
        act_grid.addWidget(btn_close, 1, 2)
        sv.addLayout(act_grid)

        sdlg.exec()

    def edit_text_slide(self, ts: TextSlideInput, open_scraper_dialog: bool = False):
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr(
                "📝 Mehrzeiliger Text-, Folien-, Ticker- & Scraper-Editor",
                "📝 Multi-Line Text, Slide, Ticker & Scraper Editor",
            )
        )
        dlg.setMinimumWidth(720)
        dlg.setMinimumHeight(600)
        root_v = QVBoxLayout(dlg)
        root_v.setSpacing(6)

        orig_state = {
            "name": ts.name,
            "headline": ts.headline,
            "body_text": ts.body_text,
            "bg_style": ts.bg_style,
            "align_mode": ts.align_mode,
            "font_size": ts.font_size,
            "color_preset": ts.color_preset,
            "scroll_mode": ts.scroll_mode,
            "scroll_speed": ts.scroll_speed,
            "slide_idx": ts.current_slide_idx,
            "scraper_source": ts.scraper_source,
            "scraper_mode": ts.scraper_mode,
            "scraper_selector": ts.scraper_selector,
            "scraper_auto_refresh": ts.scraper_auto_refresh,
            "scraper_interval_sec": ts.scraper_interval_sec,
        }

        form = QFormLayout()
        form.setSpacing(5)

        e_name = QLineEdit(ts.name)
        e_headline = QLineEdit(ts.headline)
        e_headline.setPlaceholderText(
            tr("Optionaler Titel / Ticker-Badge (z.B. LIVE-TICKER)", "Optional top headline / ticker badge (e.g. LIVE TICKER)")
        )
        form.addRow(tr("Quellen-Name:", "Source Name:"), e_name)
        form.addRow(tr("Überschrift / Badge:", "Headline / Badge:"), e_headline)
        root_v.addLayout(form)

        # ================= FILE & WEBSITE DATA SCRAPER PANEL =================
        scraper_frame = QFrame()
        scraper_frame.setObjectName("PanelFrame")
        sf_layout = QGridLayout(scraper_frame)
        sf_layout.setContentsMargins(6, 5, 6, 5)
        sf_layout.setSpacing(5)

        lbl_scr_title = QLabel(
            tr(
                "<b>🌐 Datei- & Webseiten-Scraper:</b> <i>(URL oder lokale Datei auslesen & gezielt in den Editor laden)</i>",
                "<b>🌐 File & Website Scraper:</b> <i>(Fetch URL or local file & load selected data into editor)</i>",
            )
        )
        lbl_scr_title.setStyleSheet("color: #38b6ff; font-size: 11px;")
        sf_layout.addWidget(lbl_scr_title, 0, 0, 1, 4)

        e_src = QLineEdit(ts.scraper_source)
        e_src.setPlaceholderText(
            tr(
                "Web-URL (https://...) oder Dateipfad (/pfad/datei.html, .json, .csv, .xml, .txt)",
                "Web URL (https://...) or local file path (/path/file.html, .json, .csv, .xml, .txt)",
            )
        )
        btn_pick_file = QPushButton(tr("📂 Datei...", "📂 File..."))

        def _pick_local_scrape_file():
            p, _ = QFileDialog.getOpenFileName(
                dlg,
                tr("Lokale Daten-Datei für Scraper wählen", "Select Local Data File for Scraper"),
                os.path.expanduser("~"),
                tr(
                    "Daten & Text (*.txt *.csv *.json *.xml *.rss *.html *.md);;Alle Dateien (*)",
                    "Data & Text (*.txt *.csv *.json *.xml *.rss *.html *.md);;All Files (*)",
                ),
            )
            if p:
                e_src.setText(p)

        btn_pick_file.clicked.connect(_pick_local_scrape_file)
        sf_layout.addWidget(QLabel(tr("Quelle (URL/Datei):", "Source (URL/File):")), 1, 0)
        sf_layout.addWidget(e_src, 1, 1, 1, 2)
        sf_layout.addWidget(btn_pick_file, 1, 3)

        combo_smode = QComboBox()
        for sm_key, sm_lbl in DataScraperEngine.get_modes():
            combo_smode.addItem(sm_lbl, sm_key)
        cur_sm_idx = next((i for i, (k, _) in enumerate(DataScraperEngine.get_modes()) if k == ts.scraper_mode), 0)
        combo_smode.setCurrentIndex(cur_sm_idx)

        e_sel = QLineEdit(ts.scraper_selector)
        e_sel.setPlaceholderText(
            tr(
                "Optionaler Filter: z.B. h2, tr, .score, #news, title oder 1-5",
                "Optional selector/filter: e.g. h2, tr, .score, #news, title, or 1-5",
            )
        )
        sf_layout.addWidget(QLabel(tr("Extraktion:", "Extraction:")), 2, 0)
        sf_layout.addWidget(combo_smode, 2, 1)
        sf_layout.addWidget(QLabel(tr("Gezielter Filter:", "Target Filter:")), 2, 2)
        sf_layout.addWidget(e_sel, 2, 3)

        chk_auto_scr = QCheckBox(
            tr("🔄 Live Auto-Update (für {1}, {2}, {all}, {ticker})", "🔄 Live Auto-Refresh (for {1}, {2}, {all}, {ticker})")
        )
        chk_auto_scr.setChecked(ts.scraper_auto_refresh)

        spin_scr_int = QSpinBox()
        spin_scr_int.setRange(5, 3600)
        spin_scr_int.setSingleStep(5)
        spin_scr_int.setSuffix(" s")
        spin_scr_int.setValue(ts.scraper_interval_sec)

        btn_fetch_inspect = QPushButton(
            tr("🔍 Daten abrufen & gezielt auswählen...", "🔍 Fetch & Select Data Items...")
        )
        btn_fetch_inspect.setObjectName("AddInputBtn")

        sf_layout.addWidget(chk_auto_scr, 3, 0, 1, 2)
        sf_layout.addWidget(spin_scr_int, 3, 2)
        sf_layout.addWidget(btn_fetch_inspect, 3, 3)
        root_v.addWidget(scraper_frame)

        # Toolbar above the multi-line text editor
        editor_tools = QHBoxLayout()
        lbl_editor_hint = QLabel(
            tr(
                "<b>Mehrzeiliger Editor:</b> <i>(<code>---</code> = neue Folie | Platzhalter: <code>{1}</code>, <code>{2}</code>, <code>{all}</code>, <code>{ticker}</code>)</i>",
                "<b>Multi-Line Editor:</b> <i>(<code>---</code> = new slide | Placeholders: <code>{1}</code>, <code>{2}</code>, <code>{all}</code>, <code>{ticker}</code>)</i>",
            )
        )
        lbl_editor_hint.setStyleSheet("color: #b8c4d8; font-size: 10px;")
        editor_tools.addWidget(lbl_editor_hint, 1)

        btn_add_bullet = QPushButton(tr("• Aufzählung", "• Bullet"))
        btn_add_SlideBreak = QPushButton(tr("➕ Folientrenner (---)", "➕ Slide Break (---)"))
        btn_ticker_preset = QPushButton(tr("📰 Als Ticker-Band unten", "📰 Bottom Ticker Preset"))
        editor_tools.addWidget(btn_add_bullet)
        editor_tools.addWidget(btn_add_SlideBreak)
        editor_tools.addWidget(btn_ticker_preset)
        root_v.addLayout(editor_tools)

        e_body = QPlainTextEdit()
        e_body.setPlainText(ts.body_text)
        e_body.setMinimumHeight(125)
        e_body.setStyleSheet(
            "QPlainTextEdit { background-color: #10141d; color: #f0f4fc; border: 1px solid #343e54; "
            "border-radius: 5px; font-size: 12px; padding: 6px; font-family: 'Sans Serif'; }"
        )
        root_v.addWidget(e_body, 1)

        def _insert_bullet():
            cur = e_body.textCursor()
            cur.insertText("• ")
            e_body.setFocus()

        def _insert_slide_break():
            cur = e_body.textCursor()
            cur.insertText("\n---\n")
            e_body.setFocus()

        btn_add_bullet.clicked.connect(_insert_bullet)
        btn_add_SlideBreak.clicked.connect(_insert_slide_break)

        # Style & Scroll / Ticker configuration grid
        cfg_grid = QGridLayout()
        cfg_grid.setSpacing(5)

        combo_bg = QComboBox()
        for bg_id, bg_label in TextSlideInput.get_bg_styles():
            combo_bg.addItem(bg_label, bg_id)
        combo_bg.setCurrentIndex(ts.bg_style if 0 <= ts.bg_style < combo_bg.count() else 0)

        combo_col = QComboBox()
        for cid, clabel, _, _ in TextSlideInput.get_color_presets():
            combo_col.addItem(clabel, cid)
        combo_col.setCurrentIndex(ts.color_preset if 0 <= ts.color_preset < combo_col.count() else 0)

        combo_align = QComboBox()
        align_opts = TextSlideInput.get_align_options()
        for a_key, a_lbl in align_opts:
            combo_align.addItem(a_lbl, a_key)
        cur_a_idx = next((i for i, (k, _) in enumerate(align_opts) if k == ts.align_mode), 0)
        combo_align.setCurrentIndex(cur_a_idx)

        spin_font = QSpinBox()
        spin_font.setRange(16, 72)
        spin_font.setSingleStep(2)
        spin_font.setSuffix(" px")
        spin_font.setValue(ts.font_size)

        combo_scroll_mode = QComboBox()
        for m_key, m_lbl in TextSlideInput.get_scroll_modes():
            combo_scroll_mode.addItem(m_lbl, m_key)
        cur_m_idx = next((i for i, (k, _) in enumerate(TextSlideInput.get_scroll_modes()) if k == ts.scroll_mode), 0)
        combo_scroll_mode.setCurrentIndex(cur_m_idx)

        spin_speed = QSpinBox()
        spin_speed.setRange(15, 300)
        spin_speed.setSingleStep(5)
        spin_speed.setSuffix(" px/s")
        spin_speed.setValue(ts.scroll_speed)

        def _activate_bottom_ticker_preset():
            idx_bg5 = combo_bg.findData(5)
            if idx_bg5 >= 0:
                combo_bg.setCurrentIndex(idx_bg5)
            idx_hor = combo_scroll_mode.findData("horizontal")
            if idx_hor >= 0:
                combo_scroll_mode.setCurrentIndex(idx_hor)
            if spin_font.value() > 30:
                spin_font.setValue(26)

        btn_ticker_preset.clicked.connect(_activate_bottom_ticker_preset)

        cfg_grid.addWidget(QLabel(tr("Hintergrund / Tafel:", "Background / Slate:")), 0, 0)
        cfg_grid.addWidget(combo_bg, 0, 1, 1, 3)

        cfg_grid.addWidget(QLabel(tr("Lauf- / Anzeigemodus:", "Display / Scroll Mode:")), 1, 0)
        cfg_grid.addWidget(combo_scroll_mode, 1, 1, 1, 2)
        cfg_grid.addWidget(spin_speed, 1, 3)

        cfg_grid.addWidget(QLabel(tr("Farbschema:", "Color Theme:")), 2, 0)
        cfg_grid.addWidget(combo_col, 2, 1)
        cfg_grid.addWidget(QLabel(tr("Ausrichtung & Schrift:", "Alignment & Font:")), 2, 2)
        align_font_row = QHBoxLayout()
        align_font_row.setSpacing(4)
        align_font_row.addWidget(combo_align, 1)
        align_font_row.addWidget(spin_font)
        cfg_grid.addLayout(align_font_row, 2, 3)
        root_v.addLayout(cfg_grid)

        # Live preview row (16:9 thumbnail + slide switcher)
        prv_row = QHBoxLayout()
        preview_lbl = QLabel()
        preview_lbl.setFixedSize(288, 162)
        preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_lbl.setStyleSheet(
            "background-color: #141923; border: 1px solid #38445e; border-radius: 6px;"
        )
        prv_row.addWidget(preview_lbl)

        prv_side = QVBoxLayout()
        lbl_slide_info = QLabel()
        lbl_slide_info.setStyleSheet("color: #00d890; font-weight: bold; font-size: 11px;")
        prv_side.addWidget(lbl_slide_info)

        slide_nav_row = QHBoxLayout()
        btn_prv_s = QPushButton(tr("⏮ Vorherige Folie", "⏮ Prev Slide"))
        btn_nxt_s = QPushButton(tr("Nächste Folie ⏭", "Next Slide ⏭"))
        slide_nav_row.addWidget(btn_prv_s)
        slide_nav_row.addWidget(btn_nxt_s)
        prv_side.addLayout(slide_nav_row)

        lbl_usage_tip = QLabel(
            tr(
                "• <b>Statisch / Folien (📄):</b> Ideal für Agenda, Liedtexte, Zitate & Vollbild-Tafeln.<br>"
                "• <b>Vertikal-Lauftext (📜):</b> Ideal für Abspann, lange Listen & Teleprompter.<br>"
                "• <b>Horizontal-Ticker (📰):</b> Ideal als Nachrichten-Laufband am unteren Bildrand über <b>OV1 / OV2</b>.",
                "• <b>Static / Slides (📄):</b> Ideal for agendas, lyrics, quotes & fullscreen slates.<br>"
                "• <b>Vertical Scroll (📜):</b> Ideal for credits, long lists & teleprompter.<br>"
                "• <b>Horizontal Ticker (📰):</b> Ideal as a bottom news crawl bar on <b>OV1 / OV2</b>.",
            )
        )
        lbl_usage_tip.setWordWrap(True)
        lbl_usage_tip.setStyleSheet("color: #98a4b8; font-size: 10px;")
        prv_side.addWidget(lbl_usage_tip)
        prv_side.addStretch()
        prv_row.addLayout(prv_side, 1)
        root_v.addLayout(prv_row)

        def _apply_current_to_source():
            ts.set_config(
                name=e_name.text().strip() or tr("📝 Texttafel", "📝 Text Slide"),
                headline=e_headline.text(),
                body_text=e_body.toPlainText(),
                bg_style=int(combo_bg.currentData() or 0),
                align_mode=str(combo_align.currentData() or "center"),
                font_size=int(spin_font.value()),
                color_preset=int(combo_col.currentData() or 0),
                scroll_mode=str(combo_scroll_mode.currentData() or "none"),
                scroll_speed=int(spin_speed.value()),
                scraper_source=e_src.text().strip(),
                scraper_mode=str(combo_smode.currentData() or "auto"),
                scraper_selector=e_sel.text().strip(),
                scraper_auto_refresh=bool(chk_auto_scr.isChecked()),
                scraper_interval_sec=int(spin_scr_int.value()),
            )
            slides = ts.get_slides()
            mode_desc = dict(TextSlideInput.get_scroll_modes()).get(ts.scroll_mode, "")
            lbl_slide_info.setText(
                tr(
                    f"Vorschau: Folie {ts.current_slide_idx + 1}/{len(slides)}  •  {mode_desc}",
                    f"Preview: Slide {ts.current_slide_idx + 1}/{len(slides)}  •  {mode_desc}",
                )
            )
            full_img = ts.get_frame()
            if not full_img.isNull():
                scaled = full_img.scaled(
                    284, 158,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                preview_lbl.setPixmap(QPixmap.fromImage(scaled))
            if ts in self.inputs:
                idx = self.inputs.index(ts)
                if 0 <= idx < len(self.input_tiles):
                    self.input_tiles[idx].set_index(idx)
                    self.input_tiles[idx]._refresh_scroll_toggle_button()

        btn_fetch_inspect.clicked.connect(
            lambda: self._open_scraper_inspector_dialog(
                dlg,
                ts,
                e_src,
                combo_smode,
                e_sel,
                e_body,
                combo_bg,
                combo_scroll_mode,
                _apply_current_to_source,
            )
        )
        btn_prv_s.clicked.connect(lambda: (ts.prev_slide(), _apply_current_to_source()))
        btn_nxt_s.clicked.connect(lambda: (ts.next_slide(), _apply_current_to_source()))
        e_name.textChanged.connect(lambda _: _apply_current_to_source())
        e_headline.textChanged.connect(lambda _: _apply_current_to_source())
        e_body.textChanged.connect(_apply_current_to_source)
        combo_bg.currentIndexChanged.connect(lambda _: _apply_current_to_source())
        combo_col.currentIndexChanged.connect(lambda _: _apply_current_to_source())
        combo_align.currentIndexChanged.connect(lambda _: _apply_current_to_source())
        spin_font.valueChanged.connect(lambda _: _apply_current_to_source())
        combo_scroll_mode.currentIndexChanged.connect(lambda _: _apply_current_to_source())
        spin_speed.valueChanged.connect(lambda _: _apply_current_to_source())
        chk_auto_scr.toggled.connect(lambda _: _apply_current_to_source())
        spin_scr_int.valueChanged.connect(lambda _: _apply_current_to_source())
        _apply_current_to_source()

        if open_scraper_dialog and e_src.text().strip():
            QTimer.singleShot(
                80,
                lambda: self._open_scraper_inspector_dialog(
                    dlg,
                    ts,
                    e_src,
                    combo_smode,
                    e_sel,
                    e_body,
                    combo_bg,
                    combo_scroll_mode,
                    _apply_current_to_source,
                ),
            )

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton(tr("Abbrechen", "Cancel"))
        btn_live_apply = QPushButton(tr("⚡ Sofort speichern (Editor offen lassen)", "⚡ Save Live (Keep Editor Open)"))
        btn_ok = QPushButton(tr("✓ Übernehmen & Schließen", "✓ Apply & Close"))
        btn_ok.setObjectName("AddInputBtn")
        btn_cancel.clicked.connect(dlg.reject)
        btn_live_apply.clicked.connect(lambda: (_apply_current_to_source(), self._save_last_preset_silent()))
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_live_apply)
        btn_row.addWidget(btn_ok, 1)
        root_v.addLayout(btn_row)

        if dlg.exec():
            _apply_current_to_source()
            self._save_last_preset_silent()
        else:
            ts.set_config(
                name=orig_state["name"],
                headline=orig_state["headline"],
                body_text=orig_state["body_text"],
                bg_style=orig_state["bg_style"],
                align_mode=orig_state["align_mode"],
                font_size=orig_state["font_size"],
                color_preset=orig_state["color_preset"],
                scroll_mode=orig_state["scroll_mode"],
                scroll_speed=orig_state["scroll_speed"],
                scraper_source=orig_state["scraper_source"],
                scraper_mode=orig_state["scraper_mode"],
                scraper_selector=orig_state["scraper_selector"],
                scraper_auto_refresh=orig_state["scraper_auto_refresh"],
                scraper_interval_sec=orig_state["scraper_interval_sec"],
            )
            ts.select_slide(orig_state["slide_idx"])
            if ts in self.inputs:
                idx = self.inputs.index(ts)
                if 0 <= idx < len(self.input_tiles):
                    self.input_tiles[idx].set_index(idx)
                    self.input_tiles[idx]._refresh_scroll_toggle_button()

    # ================= SWITCHING & TRANSITIONS =================
    def set_preview(self, idx: int):
        if 0 <= idx < len(self.inputs):
            self.prv_idx = idx

    def cut_input_to_program(self, idx: int):
        if 0 <= idx < len(self.inputs):
            self.prv_idx = self.pgm_idx
            self.pgm_idx = idx
            self.transition_alpha = 0.0
            self.fading_active = False
            self.tbar_slider.blockSignals(True)
            self.tbar_slider.setValue(0)
            self.tbar_slider.blockSignals(False)

    def do_cut(self):
        self.pgm_idx, self.prv_idx = self.prv_idx, self.pgm_idx
        self.transition_alpha = 0.0
        self.fading_active = False
        self.tbar_slider.blockSignals(True)
        self.tbar_slider.setValue(0)
        self.tbar_slider.blockSignals(False)

    def do_fade(self):
        if self.fading_active:
            return
        self.fading_active = True
        self.fade_start_time = time.time()

    def _on_tbar_changed(self, val: int):
        self.fading_active = False
        self.transition_alpha = val / 100.0
        if val >= 100:
            # T-Bar reached end -> complete swap
            self.pgm_idx, self.prv_idx = self.prv_idx, self.pgm_idx
            self.transition_alpha = 0.0
            self.tbar_slider.blockSignals(True)
            self.tbar_slider.setValue(0)
            self.tbar_slider.blockSignals(False)

    def toggle_overlay(self, channel: int, idx: int):
        if channel == 1:
            self.ovl1_idx = -1 if self.ovl1_idx == idx else idx
            if self.ovl1_idx >= 0 and hasattr(self, "program_mon"):
                self.program_mon.flash_overlay_gizmos(1)
        elif channel == 2:
            self.ovl2_idx = -1 if self.ovl2_idx == idx else idx
            if self.ovl2_idx >= 0 and hasattr(self, "program_mon"):
                self.program_mon.flash_overlay_gizmos(2)

    def reset_overlay_rect(self, channel: int):
        if channel == 1:
            self.ovl1_rect = [float(self.mix_w - 396), float(self.mix_h - 238), 360.0, 202.0]
        elif channel == 2:
            self.ovl2_rect = [0.0, 0.0, float(self.mix_w), float(self.mix_h)]
        if hasattr(self, "program_mon"):
            self.program_mon.flash_overlay_gizmos(channel)
        self._save_last_preset_silent()

    def snap_overlay_16_9(self, channel: int):
        rect = self.ovl1_rect if channel == 1 else self.ovl2_rect
        ox, oy, ow, _ = rect
        nh = round(max(36.0, ow * 9.0 / 16.0), 1)
        if channel == 1:
            self.ovl1_rect = [ox, oy, ow, nh]
        else:
            self.ovl2_rect = [ox, oy, ow, nh]
        if hasattr(self, "program_mon"):
            self.program_mon.flash_overlay_gizmos(channel)
        self._save_last_preset_silent()

    def toggle_overlay_border(self, channel: int):
        if channel == 1:
            self.ovl1_show_border = not self.ovl1_show_border
        elif channel == 2:
            self.ovl2_show_border = not self.ovl2_show_border
        self._save_last_preset_silent()

    def toggle_ftb(self):
        self.ftb_active = not self.ftb_active
        self.btn_ftb.setStyleSheet(
            "background-color: #d92020; color: white;" if self.ftb_active else ""
        )

    # ================= MANUAL REPLAY RECORDING & HIGHLIGHTS =================
    def ensure_replay_source_tile(self) -> ReplaySourceInput:
        """Finds the '⏪ Latest Replay' tile or creates it automatically in the input grid."""
        for inp in self.inputs:
            if isinstance(inp, ReplaySourceInput):
                return inp
        rep_inp = ReplaySourceInput(
            filepath="",
            width=self.mix_w,
            height=self.mix_h,
            playback_rate=self.default_replay_rate,
        )
        self.add_input(rep_inp)
        return rep_inp

    def ensure_highlights_tile(self) -> HighlightsInput:
        """Finds the '⭐ Highlights' tile or creates it automatically in the input grid."""
        for inp in self.inputs:
            if isinstance(inp, HighlightsInput):
                return inp
        hl_inp = HighlightsInput(
            clips=[],
            width=self.mix_w,
            height=self.mix_h,
            playback_rate=self.default_replay_rate,
        )
        self.add_input(hl_inp)
        return hl_inp

    def _set_default_replay_rate(self, rate: float):
        self.default_replay_rate = max(0.1, min(2.0, float(rate)))
        for idx, inp in enumerate(self.inputs):
            if isinstance(inp, (ReplaySourceInput, HighlightsInput)):
                inp.set_playback_rate(self.default_replay_rate)
                if 0 <= idx < len(self.input_tiles):
                    self.input_tiles[idx]._refresh_speed_buttons()
        self._save_last_preset_silent()

    def _open_replay_menu(self):
        menu = QMenu(self)

        if self.replay_recorder.recording:
            menu.addAction(
                tr(
                    f"■ Replay-Aufnahme jetzt stoppen ({self.replay_recorder.elapsed_short_str()})",
                    f"■ Stop Replay Recording Now ({self.replay_recorder.elapsed_short_str()})",
                ),
                self.toggle_manual_replay,
            )
        else:
            menu.addAction(
                tr(
                    "⏺ Manuelle Replay-Aufnahme starten (Strg+R)",
                    "⏺ Start Manual Replay Recording (Ctrl+R)",
                ),
                self.toggle_manual_replay,
            )

        menu.addSeparator()
        spd_menu = menu.addMenu(
            tr("⏱️ Standard-Zeitlupen-Tempo", "⏱️ Default Slow-Motion Speed")
        )
        for spd, label in ReplaySourceInput.get_speed_options():
            prefix = "✓ " if abs(self.default_replay_rate - spd) < 0.02 else "   "
            spd_menu.addAction(
                f"{prefix}{label}",
                lambda s=spd: self._set_default_replay_rate(s),
            )

        menu.addSeparator()
        menu.addAction(
            tr(
                "⏪ 'Letztes Replay'-Quelle einblenden / öffnen",
                "⏪ Show / Open 'Latest Replay' Source",
            ),
            self.ensure_replay_source_tile,
        )
        menu.addAction(
            tr(
                "⭐ 'Highlights'-Quelle einblenden / öffnen",
                "⭐ Show / Open 'Highlights' Source",
            ),
            self.ensure_highlights_tile,
        )

        menu.exec(self.btn_replay_cfg.mapToGlobal(self.btn_replay_cfg.rect().bottomLeft()))

    def toggle_manual_replay(self):
        """Starts or stops manual replay recording (GPU VA-API -> SSD)."""
        if not self.replay_recorder.recording:
            ok = self.replay_recorder.start()
            if ok:
                self.btn_replay.setText("■ 00:00")
                self.btn_replay.setStyleSheet(
                    "padding: 4px 2px; font-size: 9px; font-weight: bold; "
                    "background-color: #d9381e; color: white; border: 1px solid #ff9070;"
                )
                self.lbl_rec_status.setText(
                    tr(
                        "⏺ Replay-Aufnahme läuft... (Erneut auf ■ klicken oder Strg+R zum Stoppen)",
                        "⏺ Replay recording active... (Click ■ again or press Ctrl+R to stop)",
                    )
                )
            else:
                self.lbl_rec_status.setText(
                    tr(
                        "⚠️ Replay-Aufnahme konnte nicht gestartet werden",
                        "⚠️ Could not start Replay recording",
                    )
                )
        else:
            clip_path = self.replay_recorder.stop()
            self.btn_replay.setText("⏺ REPLAY")
            self.btn_replay.setStyleSheet("padding: 4px 2px; font-size: 9px;")
            if clip_path and os.path.exists(clip_path):
                rep_inp = self.ensure_replay_source_tile()
                rep_inp.set_replay_clip(clip_path)

                hl_inp = self.ensure_highlights_tile()
                hl_inp.add_highlight_clip(clip_path)

                if rep_inp in self.inputs:
                    self.set_preview(self.inputs.index(rep_inp))

                self._save_last_preset_silent()
                total_hl = len(hl_inp.clips)
                self.lbl_rec_status.setText(
                    tr(
                        f"⏪ Replay bereit in PREVIEW & 'Highlights' (#{total_hl}: {os.path.basename(clip_path)})",
                        f"⏪ Replay ready in PREVIEW & 'Highlights' (#{total_hl}: {os.path.basename(clip_path)})",
                    )
                )
            else:
                self.lbl_rec_status.setText(
                    tr(
                        "⚠️ Replay zu kurz oder keine Bilder aufgezeichnet",
                        "⚠️ Replay too short or no frames recorded",
                    )
                )

    # Alias used by web_remote.py
    toggle_replay_recording = toggle_manual_replay

    # ================= AUDIO CONTROLS =================
    def _on_mic_volume(self, val: int):
        self.mic_volume = val / 100.0
        for inp in self.inputs:
            if isinstance(inp, MicDeviceInput):
                inp.set_volume(self.mic_volume)

    def _on_mic_mute(self, muted: bool):
        self.mic_muted = muted
        for inp in self.inputs:
            if isinstance(inp, MicDeviceInput):
                inp.set_muted(muted)
        self.btn_mic_mute.setStyleSheet("background-color: #c82828;" if muted else "")

    def _on_clip_volume(self, val: int):
        for inp in self.inputs:
            if inp.has_audio and not isinstance(inp, MicDeviceInput):
                inp.set_volume(val / 100.0)

    def _on_clip_mute(self, muted: bool):
        for inp in self.inputs:
            if inp.has_audio and not isinstance(inp, MicDeviceInput):
                inp.set_muted(muted)
        self.btn_clip_mute.setStyleSheet("background-color: #c82828;" if muted else "")

    # ================= RECORDING =================
    def toggle_recording(self):
        if not self.recorder.recording:
            out_dir = os.path.expanduser("~/Videos")
            if not os.path.isdir(out_dir):
                out_dir = os.path.expanduser("~")
            ts = time.strftime("%Y-%m-%d_%H-%M-%S")
            out_file = os.path.join(out_dir, f"LiteMix_Aufnahme_{ts}.mp4")
            has_any_audio_source = any(inp.has_audio for inp in self.inputs)
            ok = self.recorder.start(
                out_file,
                record_audio=has_any_audio_source,
                audio_gain=1.0,
                audio_muted=self.mic_muted,
                inputs=self.inputs,
            )
            if ok:
                self.btn_rec.setText("⏹🔴")
                self.btn_rec.setObjectName("RecBtnActive")
                self.btn_rec.setStyle(self.btn_rec.style())
        else:
            self.recorder.stop()
            self.btn_rec.setText("🔴")
            self.btn_rec.setObjectName("RecBtn")
            self.btn_rec.setStyle(self.btn_rec.style())
            self.lbl_rec_status.setText(
                tr(
                    f"Gespeichert: {self.recorder.output_path}",
                    f"Saved: {self.recorder.output_path}",
                )
            )

    # ================= LIVE STREAMING =================
    def _stream_config_path(self) -> str:
        cfg_dir = os.path.expanduser("~/.config/litemix")
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, "stream_config.json")

    def set_fps(self, new_fps: int):
        new_fps = max(10, min(60, int(new_fps)))
        self.fps = new_fps
        self.recorder.fps = new_fps
        self.streamer.fps = new_fps
        if hasattr(self, "replay_recorder") and self.replay_recorder:
            self.replay_recorder.fps = new_fps
        if hasattr(self, "render_timer") and self.render_timer:
            self.render_timer.setInterval(max(10, int(1000 / self.fps)))

    def _load_stream_config(self):
        p = self._stream_config_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.streamer.platform = d.get("platform", self.streamer.platform)
                self.streamer.server_url = d.get("server_url", self.streamer.server_url)
                self.streamer.stream_key = d.get("stream_key", "")
                self.streamer.qp = int(d.get("qp", 23))
                saved_fps = int(d.get("fps", 30))
                self.set_fps(saved_fps)
            except Exception:
                pass

    def _save_stream_config(self):
        p = self._stream_config_path()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "platform": self.streamer.platform,
                    "server_url": self.streamer.server_url,
                    "stream_key": self.streamer.stream_key,
                    "qp": self.streamer.qp,
                    "fps": self.fps,
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def open_stream_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr(
                "Stream & Video Einstellungen (RTMP / SRT / FPS)",
                "Stream & Video Settings (RTMP / SRT / FPS)",
            )
        )
        dlg.setMinimumWidth(440)
        form = QFormLayout(dlg)

        combo_plat = QComboBox()
        platforms = list(VAAPIStreamer.PRESET_SERVERS.keys())
        combo_plat.addItems(platforms)
        if self.streamer.platform in platforms:
            combo_plat.setCurrentText(self.streamer.platform)

        edit_url = QLineEdit(self.streamer.server_url)

        key_row = QHBoxLayout()
        edit_key = QLineEdit(self.streamer.stream_key)
        edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        edit_key.setPlaceholderText(
            tr(
                "z.B. xxxx-xxxx-xxxx-xxxx (bei YouTube/Twitch)",
                "e.g. xxxx-xxxx-xxxx-xxxx (for YouTube/Twitch)",
            )
        )
        btn_show = QPushButton("👁")
        btn_show.setFixedWidth(28)
        btn_show.setCheckable(True)
        btn_show.setToolTip(
            tr("Stream-Schlüssel anzeigen/verbergen", "Show/hide stream key")
        )
        btn_show.toggled.connect(
            lambda checked: edit_key.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(edit_key, 1)
        key_row.addWidget(btn_show)

        combo_fps = QComboBox()
        fps_options = [
            (15, tr("15 FPS (Extrem CPU-sparend)", "15 FPS (Ultra Low CPU)")),
            (24, tr("24 FPS (Kino / Film)", "24 FPS (Cinema / Film)")),
            (25, tr("25 FPS (PAL Broadcast)", "25 FPS (PAL Broadcast)")),
            (30, tr("30 FPS (Standard HD – Empfohlen)", "30 FPS (Standard HD – Recommended)")),
            (50, tr("50 FPS (PAL Flüssig)", "50 FPS (PAL Smooth)")),
            (60, tr("60 FPS (High Frame Rate)", "60 FPS (High Frame Rate)")),
        ]
        selected_fps_idx = 3
        for i, (val, label) in enumerate(fps_options):
            combo_fps.addItem(label, val)
            if val == self.fps:
                selected_fps_idx = i
        combo_fps.setCurrentIndex(selected_fps_idx)

        spin_qp = QSpinBox()
        spin_qp.setRange(16, 32)
        spin_qp.setValue(self.streamer.qp)
        spin_qp.setToolTip(
            tr(
                "VA-API Qualitätsstufe QP (kleiner = höhere Qualität/Bitrate, Standard: 23)",
                "VA-API quality parameter QP (lower = higher quality/bitrate, default: 23)",
            )
        )

        def on_platform_changed(text):
            if text in VAAPIStreamer.PRESET_SERVERS:
                edit_url.setText(VAAPIStreamer.PRESET_SERVERS[text])

        combo_plat.currentTextChanged.connect(on_platform_changed)

        form.addRow(tr("Plattform / Ziel:", "Platform / Target:"), combo_plat)
        form.addRow(tr("Server-URL:", "Server URL:"), edit_url)
        form.addRow(tr("Stream-Schlüssel:", "Stream Key:"), key_row)
        form.addRow(tr("Bildrate (FPS):", "Frame Rate (FPS):"), combo_fps)
        form.addRow(tr("VA-API Qualität (QP):", "VA-API Quality (QP):"), spin_qp)

        btn_save = QPushButton(tr("Einstellungen speichern", "Save Settings"))
        btn_save.setObjectName("AddInputBtn")
        btn_save.clicked.connect(dlg.accept)
        form.addRow(btn_save)

        if dlg.exec():
            self.streamer.platform = combo_plat.currentText()
            self.streamer.server_url = edit_url.text().strip()
            self.streamer.stream_key = edit_key.text().strip()
            self.streamer.qp = spin_qp.value()
            chosen_fps = int(combo_fps.currentData())
            self.set_fps(chosen_fps)
            self._save_stream_config()
            self.lbl_rec_status.setText(
                tr(
                    f"📡 Bereit: {self.streamer.platform} ({self.fps} FPS)",
                    f"📡 Ready: {self.streamer.platform} ({self.fps} FPS)",
                )
            )

    def toggle_streaming(self):
        if not self.streamer.streaming:
            has_any_audio = any(inp.has_audio for inp in self.inputs)
            ok, msg = self.streamer.start(
                has_live_audio=has_any_audio,
                audio_gain=1.0,
                audio_muted=self.mic_muted,
                inputs=self.inputs,
            )
            if not ok:
                QMessageBox.information(
                    self,
                    tr("Stream-Konfiguration", "Stream Configuration"),
                    msg,
                )
                self.open_stream_settings()
                return
            self.btn_stream.setText("⏹📡")
            self.btn_stream.setObjectName("StreamBtnActive")
            self.btn_stream.setStyle(self.btn_stream.style())
        else:
            self.streamer.stop()
            self.btn_stream.setText("📡")
            self.btn_stream.setObjectName("StreamBtn")
            self.btn_stream.setStyle(self.btn_stream.style())
            self.lbl_rec_status.setText(tr("Stream beendet.", "Stream stopped."))

    # ================= MASTER RENDER LOOP (30 FPS) =================
    def _handle_input_eos_return(self, idx: int):
        """Automatically jumps back to the Preview monitor when a video/audio/replay clip ends."""
        if not (0 <= idx < len(self.inputs)):
            return
        if idx == self.pgm_idx:
            # Source was live on PROGRAM -> cut back to previous source from PREVIEW,
            # while placing the finished source back into the PREVIEW monitor.
            self.do_cut()
        elif idx == self.ovl1_idx:
            self.ovl1_idx = -1
            self.set_preview(idx)
        elif idx == self.ovl2_idx:
            self.ovl2_idx = -1
            self.set_preview(idx)
        else:
            self.set_preview(idx)

    def _on_render_tick(self):
        now = time.time()

        # 1. Update procedural / browser / GStreamer bus inputs
        for idx, inp in enumerate(self.inputs):
            inp.update()
            if getattr(inp, "eos_return_pending", False):
                inp.eos_return_pending = False
                if getattr(inp, "return_to_preview_on_eos", False):
                    self._handle_input_eos_return(idx)

        # 2. Handle active auto-fade transition
        if self.fading_active:
            elapsed_ms = (now - self.fade_start_time) * 1000.0
            progress = min(1.0, elapsed_ms / max(50, self.fade_duration_ms))
            self.transition_alpha = progress
            self.tbar_slider.blockSignals(True)
            self.tbar_slider.setValue(int(progress * 100))
            self.tbar_slider.blockSignals(False)
            if progress >= 1.0:
                self.fading_active = False
                self.pgm_idx, self.prv_idx = self.prv_idx, self.pgm_idx
                self.transition_alpha = 0.0
                self.tbar_slider.blockSignals(True)
                self.tbar_slider.setValue(0)
                self.tbar_slider.blockSignals(False)

        # 3. Get Preview & Program base frames
        prv_inp = self.inputs[self.prv_idx] if 0 <= self.prv_idx < len(self.inputs) else None
        pgm_inp = self.inputs[self.pgm_idx] if 0 <= self.pgm_idx < len(self.inputs) else None

        prv_frame = prv_inp.get_frame() if prv_inp else QImage()
        base_pgm = pgm_inp.get_frame() if pgm_inp else QImage()

        # 4. Composite Program output (Base + Crossfade + OVL1 PiP + OVL2 LowerThird + FTB)
        pgm_canvas = self._pgm_canvas
        p = QPainter(pgm_canvas)

        if not base_pgm.isNull():
            p.drawImage(0, 0, base_pgm)
        else:
            p.fillRect(0, 0, self.mix_w, self.mix_h, QColor(0, 0, 0))

        # Crossfade blend if in transition
        if self.transition_alpha > 0.005 and not prv_frame.isNull():
            p.setOpacity(self.transition_alpha)
            p.drawImage(0, 0, prv_frame)
            p.setOpacity(1.0)

        # Overlay 1: Freely positionable & resizable overlay (Default: PiP bottom-right)
        if 0 <= self.ovl1_idx < len(self.inputs):
            ovl1_img = self.inputs[self.ovl1_idx].get_frame()
            if not ovl1_img.isNull():
                ox, oy, ow, oh = self.ovl1_rect
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(QRectF(ox, oy, ow, oh), ovl1_img)
                if self.ovl1_show_border:
                    p.setPen(QPen(QColor(0, 200, 255), 3))
                    p.drawRect(int(round(ox)), int(round(oy)), int(round(ow)), int(round(oh)))

        # Overlay 2: Freely positionable & resizable overlay (Default: 1280x720 Fullscreen/Graphic)
        if 0 <= self.ovl2_idx < len(self.inputs):
            ovl2_img = self.inputs[self.ovl2_idx].get_frame()
            if not ovl2_img.isNull():
                ox, oy, ow, oh = self.ovl2_rect
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawImage(QRectF(ox, oy, ow, oh), ovl2_img)
                if self.ovl2_show_border:
                    p.setPen(QPen(QColor(255, 165, 30), 3))
                    p.drawRect(int(round(ox)), int(round(oy)), int(round(ow)), int(round(oh)))

        # Fade to Black (FTB)
        if self.ftb_active:
            p.fillRect(0, 0, self.mix_w, self.mix_h, QColor(0, 0, 0, 240))

        p.end()

        # 5. Update Preview & Program Monitors (+ External PROGRAM Output if open)
        self.preview_mon.set_frame(
            prv_frame,
            f"Input {self.prv_idx + 1}: {prv_inp.name}" if prv_inp else ""
        )
        self.program_mon.set_frame(
            pgm_canvas,
            f"Input {self.pgm_idx + 1}: {pgm_inp.name}" if pgm_inp else ""
        )
        if hasattr(self, "ext_output_win") and self.ext_output_win and self.ext_output_win.isVisible():
            self.ext_output_win.set_frame(pgm_canvas)

        # 6. Push to Hardware VA-API Recorder, Replay-Recorder & Live-Streamer
        status_parts = []
        if self.replay_recorder.recording:
            rep_src = base_pgm if not base_pgm.isNull() else pgm_canvas
            self.replay_recorder.push_frame(rep_src)
            short_t = self.replay_recorder.elapsed_short_str()
            btn_txt = f"■ {short_t}"
            if self.btn_replay.text() != btn_txt:
                self.btn_replay.setText(btn_txt)
            status_parts.append(f"⏺ REPLAY-REC [{short_t}]")

        if self.streamer.streaming:
            if self.streamer.is_alive():
                self.streamer.push_frame(pgm_canvas)
                status_parts.append(f"📡 ON AIR [{self.streamer.elapsed_str()}] → {self.streamer.platform}")
            else:
                self.streamer.stop()
                self.btn_stream.setText("📡")
                self.btn_stream.setObjectName("StreamBtn")
                self.btn_stream.setStyle(self.btn_stream.style())
                status_parts.append(tr("⚠️ Stream-Verbindung getrennt", "⚠️ Stream connection lost"))

        if self.recorder.recording:
            self.recorder.push_frame(pgm_canvas)
            status_parts.append(f"🔴 REC [{self.recorder.elapsed_str()}] → {os.path.basename(self.recorder.output_path)}")

        if status_parts:
            self.lbl_rec_status.setText("  |  ".join(status_parts))

        # 7. Update Input Tiles (every 2nd tick = 15 fps for thumbnails to save CPU!)
        if self._frame_count % 2 == 0:
            for idx, tile in enumerate(self.input_tiles):
                tile.update_tile(
                    is_prv=(idx == self.prv_idx),
                    is_pgm=(idx == self.pgm_idx),
                    is_ovl1=(idx == self.ovl1_idx),
                    is_ovl2=(idx == self.ovl2_idx),
                )

        # 8. Audio-Follow-Video (AFV) for video sources & Update Audio VU Meters
        for idx, inp in enumerate(self.inputs):
            if isinstance(inp, VideoFileInput):
                if self.ftb_active and idx != self.prv_idx:
                    inp.set_afv_gain(0.0)
                elif idx == self.pgm_idx:
                    inp.set_afv_gain(1.0 - self.transition_alpha)
                elif idx == self.prv_idx and self.transition_alpha > 0.01:
                    inp.set_afv_gain(self.transition_alpha)
                elif idx == self.prv_idx and not inp.paused:
                    inp.set_afv_gain(1.0)
                elif idx in (self.ovl1_idx, self.ovl2_idx):
                    inp.set_afv_gain(1.0)
                else:
                    # Video is only in the grid or paused in Preview -> muted & zero VU level!
                    inp.set_afv_gain(0.0)

        mic_lvl = max(
            (inp.vu_level for inp in self.inputs if isinstance(inp, MicDeviceInput) and not inp.muted),
            default=0.0
        )
        clip_lvl = max(
            (inp.vu_level for inp in self.inputs if inp.has_audio and not isinstance(inp, MicDeviceInput) and not inp.muted),
            default=0.0
        )
        mst_lvl = min(1.0, max(mic_lvl, clip_lvl))
        self.mic_vu.set_level(mic_lvl)
        self.clip_vu.set_level(clip_lvl)
        self.mst_vu.set_level(mst_lvl)

        # 8b. Web Remote Control (iPad / Browser): execute queued commands & refresh preview frames
        if hasattr(self, "web_remote") and self.web_remote:
            self.web_remote.tick_from_main_thread(prv_frame, pgm_canvas, self._frame_count)

        # 9. Update FPS & CPU Usage once per second
        self._frame_count += 1
        if now - self._last_fps_time >= 1.0:
            self._measured_fps = self._frame_count / (now - self._last_fps_time)
            self._frame_count = 0
            self._last_fps_time = now

            cpu_now = time.process_time()
            wall_dt = max(0.001, now - self._last_wall_time)
            # Divide by 4 logical threads on i5-6300U for system-wide percentage
            self._cpu_percent = ((cpu_now - self._last_cpu_time) / wall_dt) * 100.0 / 4.0
            self._last_cpu_time = cpu_now
            self._last_wall_time = now

            stream_speed_prefix = (
                f"📡 Upload: ⬆ {self.streamer.bitrate_str} | "
                if self.streamer.streaming else ""
            )
            self.lbl_stats.setText(
                f"{stream_speed_prefix}"
                f"{tr('Auflösung', 'Res')}: {self.mix_w}x{self.mix_h} | "
                f"Live: {self._measured_fps:.1f} FPS | "
                f"{tr('App CPU-Last', 'App CPU')}: {self._cpu_percent:.1f} %"
            )

    # ================= WEB REMOTE CONTROL (iPAD / TABLET / BROWSER) =================
    def _refresh_remote_button_style(self):
        if not hasattr(self, "btn_remote") or not self.btn_remote:
            return
        running = hasattr(self, "web_remote") and self.web_remote and self.web_remote.is_running()
        if running:
            url = self.web_remote.get_access_url()
            self.btn_remote.setToolTip(
                tr(
                    f"📱 Web-Fernsteuerung aktiv: {url}\nKlicken für QR-Code & Zugangs-Token",
                    f"📱 Web Remote active: {url}\nClick for QR Code & Access Token",
                )
            )
            self.btn_remote.setStyleSheet(
                "font-size: 16px; padding: 2px 10px; min-width: 38px; min-height: 28px; "
                "background-color: #164836; border: 1px solid #28b87a; color: #ffffff;"
            )
        else:
            self.btn_remote.setToolTip(
                tr(
                    "📱 Web-Fernsteuerung (pausiert) – Klicken zum Aktivieren & QR-Code anzeigen",
                    "📱 Web Remote (paused) – Click to enable & show QR Code",
                )
            )
            self.btn_remote.setStyleSheet("")

    def open_web_remote_dialog(self):
        dlg = WebRemoteDialog(self, self.web_remote)
        dlg.exec()
        self._refresh_remote_button_style()

    # ================= EXTERNAL PROGRAM OUTPUT (WINDOW / FULLSCREEN MONITOR) =================
    def is_ext_output_active(self) -> bool:
        return bool(hasattr(self, "ext_output_win") and self.ext_output_win and self.ext_output_win.isVisible())

    def open_external_program_window(self):
        was_maximized = self.isMaximized()
        saved_geom = self.geometry()
        if not hasattr(self, "ext_output_win") or not self.ext_output_win:
            self.ext_output_win = ExternalProgramOutputWindow(self)
        self._last_ext_output_mode = "window"
        self.ext_output_win.set_frame(self._pgm_canvas)
        self.ext_output_win.show_windowed()
        self._refresh_ext_output_button_style()
        self.lbl_rec_status.setText(
            tr(
                "🪟 PROGRAM-Fensterausgabe aktiv (Doppelklick: Vollbild, Esc: Schließen)",
                "🪟 PROGRAM window output active (Double-click: Fullscreen, Esc: Close)",
            )
        )
        if was_maximized and not self.isMaximized():
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        elif not was_maximized and self.geometry() != saved_geom:
            self.setGeometry(saved_geom)

    def open_external_program_fullscreen(self, screen_idx: int = 0):
        was_maximized = self.isMaximized()
        saved_geom = self.geometry()
        if not hasattr(self, "ext_output_win") or not self.ext_output_win:
            self.ext_output_win = ExternalProgramOutputWindow(self)
        screens = QApplication.screens()
        screen_idx = max(0, min(len(screens) - 1, int(screen_idx))) if screens else 0
        self._last_ext_output_mode = "fullscreen"
        self._last_ext_output_screen = screen_idx
        self.ext_output_win.set_frame(self._pgm_canvas)
        self.ext_output_win.show_fullscreen_on_screen(screen_idx)
        self._refresh_ext_output_button_style()
        scr_name = screens[screen_idx].name() if screens else f"#{screen_idx + 1}"
        self.lbl_rec_status.setText(
            tr(
                f"🖥️ PROGRAM-Vollbild aktiv auf Monitor {screen_idx + 1} ({scr_name}) – Esc: Schließen",
                f"🖥️ PROGRAM fullscreen active on Monitor {screen_idx + 1} ({scr_name}) – Esc: Close",
            )
        )
        if was_maximized and not self.isMaximized():
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        elif not was_maximized and self.geometry() != saved_geom:
            self.setGeometry(saved_geom)

    def close_external_program_output(self):
        if hasattr(self, "ext_output_win") and self.ext_output_win and self.ext_output_win.isVisible():
            self.ext_output_win.close()
        self._refresh_ext_output_button_style()
        self.lbl_rec_status.setText(
            tr("🖥️ Externe PROGRAM-Ausgabe geschlossen", "🖥️ External PROGRAM output closed")
        )

    def toggle_external_program_output(self):
        if self.is_ext_output_active():
            self.close_external_program_output()
        else:
            screens = QApplication.screens()
            if self._last_ext_output_mode == "fullscreen" or len(screens) > 1:
                target_idx = min(self._last_ext_output_screen, max(0, len(screens) - 1))
                self.open_external_program_fullscreen(target_idx)
            else:
                self.open_external_program_window()

    def _build_ext_output_menu(self, parent_widget=None) -> QMenu:
        menu = QMenu(parent_widget or self)
        active = self.is_ext_output_active()
        cur_mode = self.ext_output_win.mode if active else None
        cur_scr = self.ext_output_win.screen_index if active else -1

        p_win = "✓ " if (active and cur_mode == "window") else "   "
        menu.addAction(
            tr(
                f"{p_win}🪟 Als eigenes Fenster öffnen (16:9)",
                f"{p_win}🪟 Open as Separate Window (16:9)",
            ),
            self.open_external_program_window,
        )
        menu.addSeparator()

        screens = QApplication.screens()
        for idx, scr in enumerate(screens):
            g = scr.geometry()
            p_scr = "✓ " if (active and cur_mode == "fullscreen" and cur_scr == idx) else "   "
            menu.addAction(
                tr(
                    f"{p_scr}🖥️ Vollbild auf Monitor {idx + 1}: {scr.name()} ({g.width()}×{g.height()})",
                    f"{p_scr}🖥️ Fullscreen on Monitor {idx + 1}: {scr.name()} ({g.width()}×{g.height()})",
                ),
                lambda i=idx: self.open_external_program_fullscreen(i),
            )

        if active:
            menu.addSeparator()
            menu.addAction(
                tr(
                    "⏹ Externe PROGRAM-Ausgabe schließen (Esc)",
                    "⏹ Close External PROGRAM Output (Esc)",
                ),
                self.close_external_program_output,
            )
        return menu

    def open_ext_output_menu(self):
        menu = self._build_ext_output_menu(self)
        menu.exec(self.btn_ext_output.mapToGlobal(self.btn_ext_output.rect().topLeft()))

    def _refresh_ext_output_button_style(self):
        if not hasattr(self, "btn_ext_output") or not self.btn_ext_output:
            return
        active = self.is_ext_output_active()
        hk = self.shortcuts_map.get("ext_output_toggle", "").strip()
        hk_suffix = f" [{hk}]" if hk else ""
        if active:
            mode_txt = (
                tr("Vollbild", "Fullscreen")
                if self.ext_output_win.mode == "fullscreen"
                else tr("Fenster", "Window")
            )
            self.btn_ext_output.setToolTip(
                tr(
                    f"🖥️ Externe PROGRAM-Ausgabe aktiv ({mode_txt}){hk_suffix}\nKlicken zum Umschalten oder Schließen",
                    f"🖥️ External PROGRAM Output active ({mode_txt}){hk_suffix}\nClick to switch monitor/mode or close",
                )
            )
            self.btn_ext_output.setStyleSheet(
                "font-size: 16px; padding: 2px 10px; min-width: 38px; min-height: 28px; "
                "background-color: #164836; border: 1px solid #28b87a; color: #ffffff;"
            )
        else:
            self.btn_ext_output.setToolTip(
                tr(
                    f"🖥️ Externe PROGRAM-Ausgabe (eigenes Fenster oder Vollbild auf 2. Monitor/Beamer){hk_suffix}",
                    f"🖥️ External PROGRAM Output (separate window or fullscreen on 2nd monitor/projector){hk_suffix}",
                )
            )
            self.btn_ext_output.setStyleSheet("")

    # ================= GITHUB AUTO-UPDATER =================
    def _app_dir(self) -> str:
        return os.path.dirname(os.path.abspath(__file__))

    def _load_local_version_metadata(self):
        vfile = os.path.join(self._app_dir(), "version.json")
        if os.path.exists(vfile):
            try:
                with open(vfile, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("version"):
                    self.APP_VERSION = str(data["version"]).strip()
                if data.get("repo"):
                    self.GITHUB_REPO = str(data["repo"]).strip()
                if data.get("branch"):
                    self.GITHUB_BRANCH = str(data["branch"]).strip()
            except Exception:
                pass

    @staticmethod
    def _parse_version_tuple(vstr: str) -> tuple[int, ...]:
        cleaned = str(vstr or "0.0.0").strip().lstrip("vV")
        parts = []
        for token in cleaned.replace("-", ".").split("."):
            digits = "".join(ch for ch in token if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:4])

    def _fetch_remote_version_info(self) -> dict:
        """Queries version.json from the remote GitHub repository."""
        raw_url = (
            f"https://raw.githubusercontent.com/{self.GITHUB_REPO}/"
            f"{self.GITHUB_BRANCH}/version.json?t={int(time.time())}"
        )
        req = urllib.request.Request(
            raw_url,
            headers={"User-Agent": f"LiteMix-HD/{self.APP_VERSION}", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return data
        raise RuntimeError(
            tr(
                "Ungültige Versionsdaten vom GitHub-Server empfangen.",
                "Invalid version metadata received from GitHub server.",
            )
        )

    def check_for_updates(self, silent_if_up_to_date: bool = False):
        """Checks GitHub for a newer version and offers a direct one-click update."""
        if self.streamer.streaming or self.recorder.recording or self.replay_recorder.recording:
            if not silent_if_up_to_date:
                QMessageBox.warning(
                    self,
                    tr("Update während Live-Betrieb gesperrt", "Update Locked During Live Operation"),
                    tr(
                        "Während ein Live-Stream oder eine Aufnahme läuft, kann kein Update durchgeführt werden.\n\n"
                        "Bitte stoppen Sie zuerst Stream/Aufnahme.",
                        "Updates cannot be performed while a live stream or recording is active.\n\n"
                        "Please stop streaming/recording first.",
                    ),
                )
            return

        self._load_local_version_metadata()
        self.lbl_rec_status.setText(
            tr(
                f"🔄 Prüfe auf GitHub ({self.GITHUB_REPO}) nach Updates...",
                f"🔄 Checking GitHub ({self.GITHUB_REPO}) for updates...",
            )
        )
        QApplication.processEvents()

        try:
            remote_info = self._fetch_remote_version_info()
        except Exception as e:
            self.lbl_rec_status.setText(
                tr("⚠️ Update-Prüfung fehlgeschlagen", "⚠️ Update check failed")
            )
            if not silent_if_up_to_date:
                QMessageBox.warning(
                    self,
                    tr("GitHub Update-Prüfung", "GitHub Update Check"),
                    tr(
                        f"Das GitHub-Repository ({self.GITHUB_REPO}) konnte nicht abgefragt werden:\n\n{e}",
                        f"Could not query GitHub repository ({self.GITHUB_REPO}):\n\n{e}",
                    ),
                )
            return

        remote_ver = str(remote_info.get("version", self.APP_VERSION)).strip()
        changelog = str(remote_info.get("changelog", "")).strip()
        is_newer = self._parse_version_tuple(remote_ver) > self._parse_version_tuple(self.APP_VERSION)

        if is_newer:
            self.lbl_rec_status.setText(
                tr(f"✨ Neues Update verfügbar: v{remote_ver}", f"✨ New update available: v{remote_ver}")
            )
            msg = QMessageBox(self)
            msg.setWindowTitle(
                tr("LiteMix HD – Neues Update verfügbar", "LiteMix HD – New Update Available")
            )
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(
                tr(
                    f"<b>Eine neue Version von LiteMix HD ist auf GitHub verfügbar!</b><br><br>"
                    f"Installierte Version: <b>v{self.APP_VERSION}</b><br>"
                    f"Neue Version auf GitHub: <b style='color:#20d660;'>v{remote_ver}</b>",
                    f"<b>A new version of LiteMix HD is available on GitHub!</b><br><br>"
                    f"Installed version: <b>v{self.APP_VERSION}</b><br>"
                    f"Latest version on GitHub: <b style='color:#20d660;'>v{remote_ver}</b>",
                )
            )
            if changelog:
                msg.setInformativeText(
                    tr(
                        f"Neuerungen:\n{changelog}\n\nJetzt automatisch aktualisieren?",
                        f"Changelog:\n{changelog}\n\nUpdate automatically now?",
                    )
                )
            else:
                msg.setInformativeText(
                    tr(
                        "Möchten Sie LiteMix HD jetzt automatisch aktualisieren?",
                        "Would you like to update LiteMix HD automatically now?",
                    )
                )
            btn_yes = msg.addButton(
                tr("🔄 Jetzt aktualisieren", "🔄 Update Now"),
                QMessageBox.ButtonRole.AcceptRole,
            )
            msg.addButton(tr("Später", "Later"), QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == btn_yes:
                self.perform_github_update(remote_info)
        else:
            self.lbl_rec_status.setText(
                tr(
                    f"✅ LiteMix HD v{self.APP_VERSION} ist aktuell",
                    f"✅ LiteMix HD v{self.APP_VERSION} is up to date",
                )
            )
            if not silent_if_up_to_date:
                msg = QMessageBox(self)
                msg.setWindowTitle(
                    tr("LiteMix HD – Update-Prüfung", "LiteMix HD – Update Check")
                )
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setText(
                    tr(
                        f"<b>LiteMix HD ist auf dem neuesten Stand (v{self.APP_VERSION}).</b><br><br>"
                        f"GitHub-Repository: <code>https://github.com/{self.GITHUB_REPO}</code>",
                        f"<b>LiteMix HD is up to date (v{self.APP_VERSION}).</b><br><br>"
                        f"GitHub Repository: <code>https://github.com/{self.GITHUB_REPO}</code>",
                    )
                )
                msg.setInformativeText(
                    tr(
                        "Sie können bei Bedarf trotzdem den neuesten Stand direkt von GitHub erneut synchronisieren.",
                        "If needed, you can still force-synchronize the latest files directly from GitHub.",
                    )
                )
                btn_sync = msg.addButton(
                    tr("🔄 Trotzdem von GitHub synchronisieren", "🔄 Force Sync from GitHub"),
                    QMessageBox.ButtonRole.ActionRole,
                )
                msg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
                msg.exec()
                if msg.clickedButton() == btn_sync:
                    self.perform_github_update(remote_info)

    def perform_github_update(self, remote_info: dict | None = None) -> bool:
        """Downloads the latest version from GitHub (via git pull or tarball download) and offers a restart."""
        app_dir = self._app_dir()
        self._save_last_preset_silent()
        self.lbl_rec_status.setText(
            tr("⏳ Lade Update von GitHub herunter...", "⏳ Downloading update from GitHub...")
        )
        QApplication.processEvents()

        updated_ok = False
        err_details = []

        # Method 1: If .git exists -> git fetch & git reset --hard
        git_dir = os.path.join(app_dir, ".git")
        if os.path.isdir(git_dir) and shutil.which("git"):
            try:
                subprocess.run(
                    ["git", "-C", app_dir, "fetch", "origin", self.GITHUB_BRANCH],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                subprocess.run(
                    ["git", "-C", app_dir, "reset", "--hard", f"origin/{self.GITHUB_BRANCH}"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                updated_ok = True
            except Exception as e:
                err_details.append(f"Git-Update: {e}")

        # Method 2 (Fallback without .git): Download & extract official GitHub tarball
        if not updated_ok:
            tar_url = f"https://codeload.github.com/{self.GITHUB_REPO}/tar.gz/refs/heads/{self.GITHUB_BRANCH}"
            try:
                req = urllib.request.Request(tar_url, headers={"User-Agent": f"LiteMix-HD/{self.APP_VERSION}"})
                with tempfile.TemporaryDirectory(prefix="litemix_upd_") as tmpdir:
                    tar_path = os.path.join(tmpdir, "update.tar.gz")
                    with urllib.request.urlopen(req, timeout=20) as resp, open(tar_path, "wb") as out_f:
                        shutil.copyfileobj(resp, out_f)
                    with tarfile.open(tar_path, "r:gz") as tf:
                        tf.extractall(tmpdir)
                    extracted_roots = [
                        os.path.join(tmpdir, d)
                        for d in os.listdir(tmpdir)
                        if os.path.isdir(os.path.join(tmpdir, d))
                    ]
                    if not extracted_roots:
                        raise RuntimeError("Archive did not contain a project directory.")
                    src_root = extracted_roots[0]
                    for item in os.listdir(src_root):
                        if item in (".git", "__pycache__"):
                            continue
                        s_path = os.path.join(src_root, item)
                        d_path = os.path.join(app_dir, item)
                        if os.path.isfile(s_path):
                            shutil.copy2(s_path, d_path)
                updated_ok = True
            except Exception as e:
                err_details.append(f"Archive download: {e}")

        if not updated_ok:
            self.lbl_rec_status.setText(tr("❌ Update fehlgeschlagen", "❌ Update failed"))
            QMessageBox.critical(
                self,
                tr("Update fehlgeschlagen", "Update Failed"),
                tr(
                    "Das Update konnte nicht installiert werden:\n\n",
                    "The update could not be installed:\n\n",
                )
                + "\n".join(err_details),
            )
            return False

        self._load_local_version_metadata()
        self.setWindowTitle(f"LiteMix HD v{self.APP_VERSION}")
        self.lbl_rec_status.setText(
            tr(
                f"✅ Aktualisiert auf LiteMix HD v{self.APP_VERSION}",
                f"✅ Updated to LiteMix HD v{self.APP_VERSION}",
            )
        )

        ans = QMessageBox.question(
            self,
            tr("Update erfolgreich installiert", "Update Installed Successfully"),
            tr(
                f"LiteMix HD wurde erfolgreich auf Version v{self.APP_VERSION} aktualisiert!\n\n"
                f"Soll LiteMix HD jetzt automatisch neu gestartet werden, um alle Änderungen zu aktivieren?",
                f"LiteMix HD was successfully updated to version v{self.APP_VERSION}!\n\n"
                f"Restart LiteMix HD automatically now to apply all changes?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.restart_application()
        return True

    def restart_application(self):
        """Cleanly stops all media pipelines and restarts LiteMix HD."""
        self._save_last_preset_silent()
        self.render_timer.stop()
        if hasattr(self, "ext_output_win") and self.ext_output_win:
            self.ext_output_win.close()
        if hasattr(self, "web_remote") and self.web_remote:
            self.web_remote.stop_server()
        self.replay_recorder.stop()
        self.streamer.stop()
        self.recorder.stop()
        for inp in self.inputs:
            inp.stop()
        QApplication.processEvents()
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])

    def closeEvent(self, event):
        self._save_last_preset_silent()
        self.render_timer.stop()
        if hasattr(self, "ext_output_win") and self.ext_output_win:
            self.ext_output_win.close()
        if hasattr(self, "web_remote") and self.web_remote:
            self.web_remote.stop_server()
        self.replay_recorder.stop()
        self.streamer.stop()
        self.recorder.stop()
        for inp in self.inputs:
            inp.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LiteMixMainWindow()
    win.show()
    sys.exit(app.exec())
