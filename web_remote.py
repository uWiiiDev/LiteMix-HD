import os
import io
import json
import time
import socket
import secrets
import threading
import collections
import urllib.parse
import ctypes
from ctypes import c_char_p, c_int, c_ubyte, POINTER, Structure
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PyQt6.QtCore import Qt, QBuffer, QIODevice, QRectF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QPen
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QCheckBox, QFrame, QApplication, QMessageBox
)
from i18n import tr, get_lang, toggle_lang


def get_local_lan_ip() -> str:
    """Reliably determine the local LAN/Wi-Fi IPv4 address of this machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


class _QRcodeStruct(Structure):
    _fields_ = [
        ("version", c_int),
        ("width", c_int),
        ("data", POINTER(c_ubyte)),
    ]


def generate_qr_qimage(text: str, box_size: int = 240, border_modules: int = 3) -> QImage:
    """
    Generate a crisp QR Code QImage via libqrencode.so.4 (with fallback).
    Any smartphone or iPad can scan this QR code directly using the built-in camera app.
    """
    matrix: list[list[bool]] | None = None
    try:
        lib = ctypes.CDLL("libqrencode.so.4")
        lib.QRcode_encodeString.argtypes = [c_char_p, c_int, c_int, c_int, c_int]
        lib.QRcode_encodeString.restype = POINTER(_QRcodeStruct)
        lib.QRcode_free.argtypes = [POINTER(_QRcodeStruct)]
        lib.QRcode_free.restype = None

        # QR_ECLEVEL_M = 1, QR_MODE_8 = 2, casesensitive = 1
        ptr = lib.QRcode_encodeString(text.encode("utf-8"), 0, 1, 2, 1)
        if ptr:
            try:
                qr = ptr.contents
                w = int(qr.width)
                if w > 0:
                    matrix = []
                    for y in range(w):
                        row = [bool(qr.data[y * w + x] & 1) for x in range(w)]
                        matrix.append(row)
            finally:
                lib.QRcode_free(ptr)
    except Exception as e:
        print(f"[WebRemote] libqrencode note: {e}")

    img = QImage(box_size, box_size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    if matrix:
        n = len(matrix)
        total_modules = n + border_modules * 2
        scale = box_size / float(total_modules)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 16, 24))
        for y, row in enumerate(matrix):
            for x, is_dark in enumerate(row):
                if is_dark:
                    rx = int(round((x + border_modules) * scale))
                    ry = int(round((y + border_modules) * scale))
                    rx2 = int(round((x + border_modules + 1) * scale))
                    ry2 = int(round((y + border_modules + 1) * scale))
                    p.fillRect(rx, ry, max(1, rx2 - rx), max(1, ry2 - ry), QColor(12, 16, 24))
    else:
        p.setPen(QColor(20, 25, 35))
        p.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        p.drawText(QRectF(12, 12, box_size - 24, box_size - 24), Qt.AlignmentFlag.AlignCenter, text)

    p.end()
    return img


WEB_REMOTE_HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>LiteMix HD – Web Remote</title>
<style>
  :root {
    --bg: #11141b;
    --panel: #1b202b;
    --border: #2c3446;
    --text: #e6ebf5;
    --muted: #929db3;
    --prv: #1eb854;
    --pgm: #e02828;
    --ov1: #0095e8;
    --ov2: #9b38d8;
    --accent: #1e6b9e;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; user-select: none; }
  body {
    margin: 0; padding: 8px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
  }
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 12px; margin-bottom: 8px; gap: 8px; flex-wrap: wrap;
  }
  .brand { font-weight: 800; font-size: 15px; display: flex; align-items: center; gap: 8px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #20d660; display: inline-block; box-shadow: 0 0 8px #20d660; }
  .dot.off { background: #e03030; box-shadow: 0 0 8px #e03030; }
  .telemetry { color: #00d890; font-weight: 700; font-size: 12px; font-family: monospace; }

  .monitors-grid {
    display: grid; grid-template-columns: 1fr 185px 1fr; gap: 8px; margin-bottom: 8px;
  }
  @media (max-width: 900px) {
    .monitors-grid { grid-template-columns: 1fr 1fr; }
    .center-deck { grid-column: 1 / -1; order: 3; }
  }
  @media (max-width: 600px) {
    .monitors-grid { grid-template-columns: 1fr; }
  }

  .mon-card {
    background: #0c0e13; border: 2px solid var(--border); border-radius: 8px;
    overflow: hidden; display: flex; flex-direction: column;
  }
  .mon-card.prv { border-color: var(--prv); }
  .mon-card.pgm { border-color: var(--pgm); }
  .mon-head {
    padding: 5px 10px; font-weight: 800; font-size: 12px;
    display: flex; justify-content: space-between; align-items: center;
    background: #171b24;
  }
  .mon-card.prv .mon-head { color: #32e875; }
  .mon-card.pgm .mon-head { color: #ff5252; }
  .mon-img-wrap {
    position: relative; width: 100%; aspect-ratio: 16 / 9; background: #07090c;
    display: flex; align-items: center; justify-content: center;
  }
  .mon-img-wrap img { width: 100%; height: 100%; object-fit: contain; display: block; }

  .prv-transport {
    background: #161b24; border-top: 1px solid #283142; padding: 6px 8px;
    display: none; flex-direction: column; gap: 5px;
  }
  .prv-transport.visible { display: flex; }
  .trans-row { display: flex; align-items: center; gap: 5px; }
  .trans-row input[type=range] { flex: 1; accent-color: #20d660; height: 22px; }
  .timecode { font-family: monospace; font-size: 11px; color: #b8c4d8; min-width: 74px; text-align: right; }

  .center-deck {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px; display: flex; flex-direction: column; gap: 6px; justify-content: space-between;
  }
  .deck-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .btn {
    background: #283042; color: var(--text); border: 1px solid #3c4760;
    border-radius: 6px; padding: 9px 10px; font-weight: 800; font-size: 13px;
    cursor: pointer; text-align: center; transition: transform 0.05s, background 0.12s;
    display: inline-flex; align-items: center; justify-content: center; gap: 5px;
  }
  .btn:active { transform: scale(0.96); }
  .btn-cut { background: #c22525; border-color: #ef4444; font-size: 15px; padding: 12px 8px; color: #fff; }
  .btn-fade { background: #1c6ca1; border-color: #38a3eb; font-size: 15px; padding: 12px 8px; color: #fff; }
  .btn-ftb { background: #262c3a; border-color: #505c78; }
  .btn-ftb.active { background: #e02020; border-color: #ff6868; color: #fff; animation: pulse 1s infinite; }
  .btn-replay { background: #193a54; border-color: #2888c8; color: #90dcff; }
  .btn-replay.active { background: #c92020; border-color: #ff6060; color: #fff; }
  .btn-rec.active { background: #d62020; border-color: #ff6060; color: #fff; }
  .btn-stream.active { background: #e06010; border-color: #ff9848; color: #fff; }

  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.65; } }

  .section-title {
    font-size: 11px; font-weight: 800; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.6px; margin: 8px 2px 5px; display: flex; justify-content: space-between;
  }
  .inputs-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(225px, 1fr)); gap: 8px;
  }
  .tile {
    background: var(--panel); border: 2px solid var(--border); border-radius: 8px;
    padding: 8px; display: flex; flex-direction: column; gap: 6px;
  }
  .tile.pgm { background: #2a171b; border-color: var(--pgm); }
  .tile.prv { background: #15261d; border-color: var(--prv); }
  .tile-head { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
  .tile-title { font-weight: 800; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .badge { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 800; }
  .badge.pgm { background: var(--pgm); color: #fff; }
  .badge.prv { background: var(--prv); color: #081c0e; }

  .tile-btns { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
  .tbtn {
    padding: 8px 4px; font-size: 12px; font-weight: 800; border-radius: 5px;
    border: 1px solid #3c465c; background: #262d3d; color: #e4e9f2; cursor: pointer;
  }
  .tbtn.prv-act { background: var(--prv); color: #07190c; border-color: #48f080; }
  .tbtn.pgm-act { background: var(--pgm); color: #fff; border-color: #ff6060; }
  .tbtn.ov1-act { background: var(--ov1); color: #fff; border-color: #55c5ff; }
  .tbtn.ov2-act { background: var(--ov2); color: #fff; border-color: #ca78ff; }

  .mini-trans { display: flex; align-items: center; gap: 4px; }
  .ibtn {
    padding: 5px 8px; font-size: 12px; font-weight: 800; border-radius: 5px;
    border: 1px solid #3c465c; background: #262d3d; color: #e4e9f2; cursor: pointer;
  }
  .ibtn.on-loop { background: #1e6b9e; border-color: #46aef7; color: #fff; }
  .ibtn.on-ret { background: #1a824a; border-color: #36d878; color: #fff; }
  .ibtn.on-spd { background: #0088cc; border-color: #38c8ff; color: #fff; }
  .ibtn.on-mute { background: #c82828; border-color: #ff6060; color: #fff; }

  .vu-wrap { height: 6px; background: #0f131a; border-radius: 3px; overflow: hidden; border: 1px solid #262e3e; }
  .vu-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #20d660 0%, #f0c020 75%, #f03030 100%); transition: width 0.08s; }
  .aud-row { display: flex; align-items: center; gap: 6px; }
  .aud-row input[type=range] { flex: 1; accent-color: #00b0ff; }

  /* Lower-third editor modal */
  .modal-bg {
    position: fixed; inset: 0; background: rgba(0,0,0,0.72);
    display: none; align-items: center; justify-content: center; z-index: 99; padding: 16px;
  }
  .modal-bg.open { display: flex; }
  .modal {
    background: var(--panel); border: 1px solid #44506a; border-radius: 10px;
    padding: 16px; width: 100%; max-width: 400px; display: flex; flex-direction: column; gap: 10px;
  }
  .modal input, .modal select {
    width: 100%; padding: 9px 10px; background: #12161f; border: 1px solid #38435a;
    color: #fff; border-radius: 6px; font-size: 14px; user-select: text;
  }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <span id="connDot" class="dot"></span>
    <span id="appTitle">LiteMix HD – iPad &amp; Web Remote</span>
  </div>
  <div style="display:flex; align-items:center; gap:8px;">
    <button class="ibtn" onclick="sendAction({cmd:'toggle_lang'})" id="btnLang">🌐 DE</button>
    <button class="ibtn" onclick="toggleMonitors()" id="btnToggleMon">📺 Vorschau: AN</button>
    <span id="telemetry" class="telemetry">Verbinde...</span>
  </div>
</div>

<div class="monitors-grid">
  <!-- PREVIEW MONITOR -->
  <div class="mon-card prv" id="prvCard">
    <div class="mon-head">
      <span id="prvHeadTitle">● PREVIEW (VORSCHAU)</span>
      <span id="prvLabel" style="color:#d4dce8;font-weight:600;">--</span>
    </div>
    <div class="mon-img-wrap" id="prvImgWrap" onclick="sendAction({cmd:'prv_play_pause'})">
      <img id="prvImg" alt="Preview">
    </div>
    <div class="prv-transport" id="prvTransport">
      <div class="trans-row">
        <button class="ibtn" id="prvBtnPlay" onclick="sendAction({cmd:'prv_play_pause'})">▶</button>
        <button class="ibtn" onclick="sendAction({cmd:'prv_stop'})">⏹</button>
        <button class="ibtn" id="prvBtnLoop" onclick="sendAction({cmd:'prv_toggle_loop'})">🔁</button>
        <button class="ibtn" id="prvBtnRet" onclick="sendAction({cmd:'prv_toggle_return'})">↩</button>
        <input type="range" id="prvScrubber" min="0" max="1000" value="0"
               oninput="onPrvScrubInput(this.value)" onchange="onPrvScrubCommit(this.value)">
        <span class="timecode" id="prvTimecode">00:00/00:00</span>
      </div>
      <div class="trans-row" id="prvSpeedRow" style="display:none;">
        <span style="font-size:11px;color:#929db3;">⏱</span>
        <button class="ibtn" id="spd025" onclick="sendAction({cmd:'prv_rate', rate:0.25})">0.25×</button>
        <button class="ibtn" id="spd050" onclick="sendAction({cmd:'prv_rate', rate:0.50})">0.5×</button>
        <button class="ibtn" id="spd075" onclick="sendAction({cmd:'prv_rate', rate:0.75})">0.75×</button>
        <button class="ibtn" id="spd100" onclick="sendAction({cmd:'prv_rate', rate:1.00})">1.0×</button>
      </div>
    </div>
  </div>

  <!-- CENTER SWITCHER DECK -->
  <div class="center-deck">
    <div class="deck-row">
      <button class="btn btn-cut" onclick="sendAction({cmd:'cut'})">CUT</button>
      <button class="btn btn-fade" onclick="sendAction({cmd:'fade'})">FADE</button>
    </div>
    <button class="btn btn-ftb" id="btnFtb" onclick="sendAction({cmd:'ftb'})">FTB</button>
    <div style="display:flex;align-items:center;gap:6px;">
      <span style="font-size:11px;color:#929db3;">T-Bar</span>
      <input type="range" id="tbarSlider" min="0" max="100" value="0" style="flex:1;accent-color:#38a3eb;"
             oninput="sendAction({cmd:'tbar', value:parseInt(this.value)})">
    </div>
    <button class="btn btn-replay" id="btnReplay" onclick="sendAction({cmd:'replay_toggle'})">⏺ REPLAY</button>
    <div class="deck-row">
      <button class="btn btn-rec" id="btnRec" onclick="sendAction({cmd:'rec_toggle'})">🔴 REC</button>
      <button class="btn btn-stream" id="btnStream" onclick="sendAction({cmd:'stream_toggle'})">📡 STREAM</button>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;">
      <button class="ibtn" id="btnMicMute" onclick="sendAction({cmd:'mic_mute'})">🎙️ MIC</button>
      <button class="ibtn" id="btnClipMute" onclick="sendAction({cmd:'clip_mute'})">🎬 VID</button>
      <button class="ibtn" id="btnExtOut" onclick="sendAction({cmd:'toggle_ext_output'})">🖥️ OUT</button>
    </div>
  </div>

  <!-- PROGRAM MONITOR -->
  <div class="mon-card pgm" id="pgmCard">
    <div class="mon-head">
      <span id="pgmHeadTitle">● PROGRAM (LIVE)</span>
      <span id="pgmLabel" style="color:#d4dce8;font-weight:600;">--</span>
    </div>
    <div class="mon-img-wrap" id="pgmImgWrap">
      <img id="pgmImg" alt="Program">
    </div>
    <div style="padding:5px 10px;background:#161b24;font-size:11px;color:#98a4bc;display:flex;justify-content:space-between;">
      <span id="recStatusLbl">Bereit</span>
      <span id="ovlStatusLbl"></span>
    </div>
  </div>
</div>

<div class="section-title">
  <span id="matrixTitleLbl">Quellen-Matrix &amp; Audio-Steuerung</span>
  <span id="sourceCountLbl"></span>
</div>
<div class="inputs-grid" id="inputsGrid"></div>

<!-- Lower-Third Editor Modal -->
<div class="modal-bg" id="ltModal">
  <div class="modal">
    <div style="font-weight:800;font-size:15px;" id="ltModalTitle">🏷️ Bauchbinde bearbeiten</div>
    <input type="hidden" id="ltIdx">
    <label style="font-size:12px;color:#98a4bc;">Design-Template:</label>
    <select id="ltTpl">
      <option value="0">1 – Studio Cyan (Classic)</option>
      <option value="1">2 – TV News / Live Banner (Red/White)</option>
      <option value="2">3 – Modern Minimal / Talk Pill (Emerald)</option>
    </select>
    <label style="font-size:12px;color:#98a4bc;" id="ltLblMain">Hauptzeile (Name / Titel):</label>
    <input type="text" id="ltTitle" placeholder="Max Mustermann">
    <label style="font-size:12px;color:#98a4bc;" id="ltLblSub">Unterzeile (Info / Funktion):</label>
    <input type="text" id="ltSub" placeholder="Live Studio">
    <div style="display:flex;gap:8px;margin-top:4px;">
      <button class="btn" style="flex:1;" onclick="closeLtModal()" id="ltBtnCancel">Abbrechen</button>
      <button class="btn" style="flex:1;background:#1b5e3c;border-color:#289c60;" onclick="saveLtModal()" id="ltBtnSave">✓ Übernehmen</button>
    </div>
  </div>
</div>

<script>
const urlParams = new URLSearchParams(window.location.search);
const TOKEN = urlParams.get('token') || '';
let showMonitors = true;
let prvScrubDragging = false;
let prvDuration = 0.0;
let lastInputsSig = '';
let currentLang = 'de';

function apiUrl(path) {
  const sep = path.includes('?') ? '&' : '?';
  return TOKEN ? `${path}${sep}token=${encodeURIComponent(TOKEN)}` : path;
}

async function sendAction(payload) {
  try {
    await fetch(apiUrl('/api/action'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    setTimeout(pollState, 40);
  } catch (e) {}
}

function updateMonBtnText() {
  const isEn = (currentLang === 'en');
  document.getElementById('btnToggleMon').textContent = showMonitors
    ? (isEn ? '📺 Monitors: ON' : '📺 Vorschau: AN')
    : (isEn ? '📺 Monitors: OFF' : '📺 Vorschau: AUS');
}

function toggleMonitors() {
  showMonitors = !showMonitors;
  document.getElementById('prvImgWrap').style.display = showMonitors ? 'flex' : 'none';
  document.getElementById('pgmImgWrap').style.display = showMonitors ? 'flex' : 'none';
  updateMonBtnText();
}

function fmtTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`;
}

function onPrvScrubInput(val) {
  prvScrubDragging = true;
  if (prvDuration > 0.1) {
    const t = (val / 1000.0) * prvDuration;
    document.getElementById('prvTimecode').textContent = `${fmtTime(t)}/${fmtTime(prvDuration)}`;
  }
}

function onPrvScrubCommit(val) {
  prvScrubDragging = false;
  if (prvDuration > 0.1) {
    sendAction({cmd: 'prv_seek_ratio', ratio: parseFloat(val) / 1000.0});
  }
}

function openLtModal(idx, title, sub, tpl) {
  document.getElementById('ltIdx').value = idx;
  document.getElementById('ltTitle').value = title || '';
  document.getElementById('ltSub').value = sub || '';
  document.getElementById('ltTpl').value = String(tpl || 0);
  document.getElementById('ltModal').classList.add('open');
}

function closeLtModal() {
  document.getElementById('ltModal').classList.remove('open');
}

function saveLtModal() {
  const idx = parseInt(document.getElementById('ltIdx').value);
  const title = document.getElementById('ltTitle').value;
  const sub = document.getElementById('ltSub').value;
  const tpl = parseInt(document.getElementById('ltTpl').value);
  closeLtModal();
  sendAction({cmd: 'set_lower_third', index: idx, title: title, subtitle: sub, template_id: tpl});
}

function renderInputsGrid(st) {
  const isEn = (currentLang === 'en');
  const grid = document.getElementById('inputsGrid');
  const sig = currentLang + '|' + st.inputs.map(i => `${i.index}:${i.type}:${i.name}:${i.playable}:${i.has_audio}:${i.is_lt}`).join('|');
  if (sig !== lastInputsSig) {
    lastInputsSig = sig;
    grid.innerHTML = '';
    st.inputs.forEach(inp => {
      const card = document.createElement('div');
      card.className = 'tile';
      card.id = `tile_${inp.index}`;

      let btnsHtml = '';
      if (inp.is_audio_only && inp.type !== 'AudioFileInput') {
        btnsHtml = `<div style="font-size:11px;color:#929db3;">🎧 ${isEn ? 'Live Audio Input' : 'Live Audio-Eingang'}</div>`;
      } else if (inp.type === 'AudioFileInput') {
        btnsHtml = `
          <div class="tile-btns" style="grid-template-columns: 1fr 1fr;">
            <button class="tbtn" id="b_prv_${inp.index}" onclick="sendAction({cmd:'set_prv', index:${inp.index}})">PRV</button>
            <button class="tbtn" id="b_pgm_${inp.index}" onclick="sendAction({cmd:'cut_idx', index:${inp.index}})">CUT</button>
          </div>`;
      } else {
        btnsHtml = `
          <div class="tile-btns">
            <button class="tbtn" id="b_prv_${inp.index}" onclick="sendAction({cmd:'set_prv', index:${inp.index}})">PRV</button>
            <button class="tbtn" id="b_pgm_${inp.index}" onclick="sendAction({cmd:'cut_idx', index:${inp.index}})">CUT</button>
            <button class="tbtn" id="b_ov1_${inp.index}" onclick="sendAction({cmd:'ovl', channel:1, index:${inp.index}})">OV1</button>
            <button class="tbtn" id="b_ov2_${inp.index}" onclick="sendAction({cmd:'ovl', channel:2, index:${inp.index}})">OV2</button>
          </div>`;
      }

      let mediaHtml = '';
      if (inp.playable) {
        const loopRetBtns = inp.has_loop_ret ? `
          <button class="ibtn" id="b_loop_${inp.index}" onclick="sendAction({cmd:'tile_loop', index:${inp.index}})">🔁</button>
          <button class="ibtn" id="b_ret_${inp.index}" onclick="sendAction({cmd:'tile_ret', index:${inp.index}})">↩</button>
        ` : '';
        mediaHtml = `
          <div class="mini-trans">
            <button class="ibtn" id="b_play_${inp.index}" onclick="sendAction({cmd:'tile_play_pause', index:${inp.index}})">▶</button>
            <button class="ibtn" onclick="sendAction({cmd:'tile_stop', index:${inp.index}})">⏹</button>
            ${loopRetBtns}
            <span class="timecode" id="b_tc_${inp.index}" style="flex:1;">00:00/00:00</span>
          </div>`;
      }

      let ltHtml = '';
      if (inp.is_lt) {
        ltHtml = `<button class="ibtn" id="b_lt_${inp.index}">✎ ${isEn ? 'Edit Lower Third' : 'Bauchbinden-Text ändern'}</button>`;
      }

      let audHtml = '';
      if (inp.has_audio) {
        audHtml = `
          <div class="vu-wrap"><div class="vu-bar" id="vu_${inp.index}"></div></div>
          <div class="aud-row">
            <button class="ibtn" id="b_mute_${inp.index}" onclick="sendAction({cmd:'tile_mute', index:${inp.index}})">🔊</button>
            <input type="range" id="vol_${inp.index}" min="0" max="150" value="${inp.vol_pct}"
                   oninput="sendAction({cmd:'tile_vol', index:${inp.index}, value:parseInt(this.value)})">
            <span id="vol_lbl_${inp.index}" style="font-size:11px;min-width:34px;text-align:right;color:#98a4bc;">${inp.vol_pct}%</span>
          </div>`;
      }

      card.innerHTML = `
        <div class="tile-head">
          <span class="tile-title">${inp.index + 1}: ${inp.name}</span>
          <span class="badge" id="badge_${inp.index}" style="display:none;"></span>
        </div>
        ${btnsHtml}
        ${mediaHtml}
        ${ltHtml}
        ${audHtml}
      `;
      grid.appendChild(card);
    });
  }

  st.inputs.forEach(inp => {
    const isPgm = (inp.index === st.pgm_idx);
    const isPrv = (inp.index === st.prv_idx);
    const isOv1 = (inp.index === st.ovl1_idx);
    const isOv2 = (inp.index === st.ovl2_idx);

    const card = document.getElementById(`tile_${inp.index}`);
    if (card) {
      card.className = 'tile' + (isPgm ? ' pgm' : (isPrv ? ' prv' : ''));
    }
    const badge = document.getElementById(`badge_${inp.index}`);
    if (badge) {
      if (isPgm) { badge.style.display = 'inline-block'; badge.className = 'badge pgm'; badge.textContent = 'LIVE'; }
      else if (isPrv) { badge.style.display = 'inline-block'; badge.className = 'badge prv'; badge.textContent = 'PRV'; }
      else { badge.style.display = 'none'; }
    }
    const bPrv = document.getElementById(`b_prv_${inp.index}`);
    if (bPrv) bPrv.className = 'tbtn' + (isPrv ? ' prv-act' : '');
    const bPgm = document.getElementById(`b_pgm_${inp.index}`);
    if (bPgm) bPgm.className = 'tbtn' + (isPgm ? ' pgm-act' : '');
    const bOv1 = document.getElementById(`b_ov1_${inp.index}`);
    if (bOv1) bOv1.className = 'tbtn' + (isOv1 ? ' ov1-act' : '');
    const bOv2 = document.getElementById(`b_ov2_${inp.index}`);
    if (bOv2) bOv2.className = 'tbtn' + (isOv2 ? ' ov2-act' : '');

    if (inp.playable) {
      const bPlay = document.getElementById(`b_play_${inp.index}`);
      if (bPlay) bPlay.textContent = inp.paused ? '▶' : '⏸';
      const bLoop = document.getElementById(`b_loop_${inp.index}`);
      if (bLoop) bLoop.className = 'ibtn' + (inp.loop_enabled ? ' on-loop' : '');
      const bRet = document.getElementById(`b_ret_${inp.index}`);
      if (bRet) bRet.className = 'ibtn' + (inp.return_to_preview_on_eos ? ' on-ret' : '');
      const bTc = document.getElementById(`b_tc_${inp.index}`);
      if (bTc) bTc.textContent = `${fmtTime(inp.pos_s)}/${fmtTime(inp.dur_s)}`;
    }
    if (inp.is_lt) {
      const bLt = document.getElementById(`b_lt_${inp.index}`);
      if (bLt) bLt.onclick = () => openLtModal(inp.index, inp.lt_title, inp.lt_sub, inp.lt_tpl);
    }
    if (inp.has_audio) {
      const vu = document.getElementById(`vu_${inp.index}`);
      if (vu) vu.style.width = `${Math.min(100, Math.round((inp.vu || 0) * 100))}%`;
      const bMute = document.getElementById(`b_mute_${inp.index}`);
      if (bMute) {
        bMute.textContent = inp.muted ? '🔇' : '🔊';
        bMute.className = 'ibtn' + (inp.muted ? ' on-mute' : '');
      }
      const volLbl = document.getElementById(`vol_lbl_${inp.index}`);
      if (volLbl) volLbl.textContent = `${inp.vol_pct}%`;
    }
  });
}

async function pollState() {
  try {
    const resp = await fetch(apiUrl('/api/state'), {cache: 'no-store'});
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const st = await resp.json();
    currentLang = st.lang || 'de';
    const isEn = (currentLang === 'en');

    document.getElementById('connDot').className = 'dot';
    document.getElementById('appTitle').textContent = `LiteMix HD v${st.version} – Remote`;
    document.getElementById('btnLang').textContent = isEn ? '🌐 EN' : '🌐 DE';
    updateMonBtnText();
    document.getElementById('prvHeadTitle').textContent = isEn ? '● PREVIEW' : '● PREVIEW (VORSCHAU)';
    document.getElementById('matrixTitleLbl').textContent = isEn ? 'Input Sources & Audio Control' : 'Quellen-Matrix & Audio-Steuerung';
    document.getElementById('ltModalTitle').textContent = isEn ? '🏷️ Edit Lower Third' : '🏷️ Bauchbinde bearbeiten';
    document.getElementById('ltLblMain').textContent = isEn ? 'Headline (Name / Title):' : 'Hauptzeile (Name / Titel):';
    document.getElementById('ltLblSub').textContent = isEn ? 'Subtitle (Role / Info):' : 'Unterzeile (Info / Funktion):';
    document.getElementById('ltBtnCancel').textContent = isEn ? 'Cancel' : 'Abbrechen';
    document.getElementById('ltBtnSave').textContent = isEn ? '✓ Apply' : '✓ Übernehmen';

    document.getElementById('telemetry').textContent = st.stats_text || '';
    document.getElementById('recStatusLbl').textContent = st.rec_status || '';
    document.getElementById('prvLabel').textContent = st.prv_label || '--';
    document.getElementById('pgmLabel').textContent = st.pgm_label || '--';
    document.getElementById('sourceCountLbl').textContent = isEn ? `${st.inputs.length} Sources` : `${st.inputs.length} Quellen`;

    document.getElementById('btnFtb').className = 'btn btn-ftb' + (st.ftb_active ? ' active' : '');
    const btnRep = document.getElementById('btnReplay');
    btnRep.className = 'btn btn-replay' + (st.replay_recording ? ' active' : '');
    btnRep.textContent = st.replay_btn_text || '⏺ REPLAY';

    const btnRec = document.getElementById('btnRec');
    btnRec.className = 'btn btn-rec' + (st.recording ? ' active' : '');
    btnRec.textContent = st.recording ? '⏹🔴 REC' : '🔴 REC';

    const btnStr = document.getElementById('btnStream');
    btnStr.className = 'btn btn-stream' + (st.streaming ? ' active' : '');
    btnStr.textContent = st.streaming ? '⏹📡 ON AIR' : '📡 STREAM';

    document.getElementById('btnMicMute').className = 'ibtn' + (st.mic_muted ? ' on-mute' : '');
    document.getElementById('btnMicMute').textContent = st.mic_muted ? '🔇 MIC' : '🎙️ MIC';
    document.getElementById('btnClipMute').className = 'ibtn' + (st.clip_muted ? ' on-mute' : '');
    document.getElementById('btnClipMute').textContent = st.clip_muted ? '🔇 VID' : '🎬 VID';
    const btnExt = document.getElementById('btnExtOut');
    if (btnExt) {
      btnExt.className = 'ibtn' + (st.ext_output_active ? ' on-ret' : '');
    }

    const prvInp = st.inputs[st.prv_idx];
    const prvTrans = document.getElementById('prvTransport');
    if (prvInp && prvInp.playable) {
      prvTrans.classList.add('visible');
      document.getElementById('prvBtnPlay').textContent = prvInp.paused ? '▶' : '⏸';
      document.getElementById('prvBtnLoop').className = 'ibtn' + (prvInp.loop_enabled ? ' on-loop' : '');
      document.getElementById('prvBtnRet').className = 'ibtn' + (prvInp.return_to_preview_on_eos ? ' on-ret' : '');
      prvDuration = prvInp.dur_s || 0.0;
      if (!prvScrubDragging) {
        const ratio = prvDuration > 0.1 ? Math.min(1000, Math.round((prvInp.pos_s / prvDuration) * 1000)) : 0;
        document.getElementById('prvScrubber').value = ratio;
        document.getElementById('prvTimecode').textContent = `${fmtTime(prvInp.pos_s)}/${fmtTime(prvDuration)}`;
      }
      const spdRow = document.getElementById('prvSpeedRow');
      if (prvInp.has_speed) {
        spdRow.style.display = 'flex';
        [[0.25,'spd025'],[0.5,'spd050'],[0.75,'spd075'],[1.0,'spd100']].forEach(([rv, bid]) => {
          const el = document.getElementById(bid);
          if (el) el.className = 'ibtn' + (Math.abs((prvInp.playback_rate || 1.0) - rv) < 0.03 ? ' on-spd' : '');
        });
      } else {
        spdRow.style.display = 'none';
      }
    } else {
      prvTrans.classList.remove('visible');
    }

    renderInputsGrid(st);
  } catch (e) {
    document.getElementById('connDot').className = 'dot off';
    document.getElementById('telemetry').textContent = (currentLang === 'en') ? 'Disconnected' : 'Verbindung getrennt';
  }
}

function refreshMonitorFrames() {
  if (!showMonitors) return;
  const now = Date.now();
  document.getElementById('prvImg').src = apiUrl(`/api/frame/prv?t=${now}`);
  document.getElementById('pgmImg').src = apiUrl(`/api/frame/pgm?t=${now}`);
}

setInterval(pollState, 250);
setInterval(refreshMonitorFrames, 240);
pollState();
refreshMonitorFrames();
</script>
</body>
</html>
"""


class WebRemoteController:
    """
    Lightweight, token-protected HTTP web remote controller for iPad, tablet, and browsers.
    Synchronizes commands thread-safely via a queue with the 30 FPS main loop of LiteMix HD.
    """

    def __init__(self, main_win):
        self.main_win = main_win
        self.enabled = True
        self.port = 8088
        self.token = secrets.token_urlsafe(6).replace("-", "A").replace("_", "B")[:8]
        self._load_config()

        self._lock = threading.Lock()
        self._state_json_bytes = b"{}"
        self._prv_jpeg_bytes = b""
        self._pgm_jpeg_bytes = b""
        self._last_client_poll = 0.0
        self._cmd_queue = collections.deque()

        self._httpd: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

        if self.enabled:
            self.start_server()

    def _config_path(self) -> str:
        cfg_dir = os.path.expanduser("~/.config/litemix")
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, "web_remote.json")

    def _load_config(self):
        p = self._config_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.enabled = bool(d.get("enabled", True))
                self.port = max(1024, min(65535, int(d.get("port", 8088))))
                tok = str(d.get("token", "")).strip()
                if len(tok) >= 4:
                    self.token = tok
            except Exception:
                pass
        else:
            self._save_config()

    def _save_config(self):
        try:
            with open(self._config_path(), "w", encoding="utf-8") as f:
                json.dump(
                    {"enabled": self.enabled, "port": self.port, "token": self.token},
                    f,
                    indent=2,
                )
        except Exception:
            pass

    def regenerate_token(self) -> str:
        self.token = secrets.token_urlsafe(6).replace("-", "X").replace("_", "Y")[:8]
        self._save_config()
        return self.token

    def get_access_url(self) -> str:
        ip = get_local_lan_ip()
        return f"http://{ip}:{self.port}/?token={self.token}"

    def is_running(self) -> bool:
        return self._httpd is not None

    def start_server(self) -> tuple[bool, str]:
        self.stop_server()
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress console spam during polling

            def _check_auth(self, parsed) -> bool:
                qs = urllib.parse.parse_qs(parsed.query)
                q_tok = (qs.get("token") or [""])[0]
                if q_tok and secrets.compare_digest(q_tok, controller.token):
                    return True
                cookie_hdr = self.headers.get("Cookie", "")
                for part in cookie_hdr.split(";"):
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        if k == "litemix_token" and secrets.compare_digest(v, controller.token):
                            return True
                hdr_tok = self.headers.get("X-LiteMix-Token", "")
                if hdr_tok and secrets.compare_digest(hdr_tok, controller.token):
                    return True
                return False

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if not self._check_auth(parsed):
                    self.send_response(403)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body style='background:#12151e;color:#e4e8f0;font-family:sans-serif;"
                        b"text-align:center;padding:40px;'><h2>&#128274; LiteMix HD Web Remote</h2>"
                        b"<p>Access denied: Valid security token required / G&uuml;ltiges Zugangs-Token erforderlich.</p>"
                        b"<p>Please scan the QR code in LiteMix HD (Button &#128241; in the bottom bar).</p>"
                        b"</body></html>"
                    )
                    return

                controller._last_client_poll = time.time()

                if parsed.path in ("/", "/index.html"):
                    body = WEB_REMOTE_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Set-Cookie", f"litemix_token={controller.token}; Path=/; SameSite=Lax")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif parsed.path == "/api/state":
                    with controller._lock:
                        data = controller._state_json_bytes
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif parsed.path in ("/api/frame/prv", "/api/frame/pgm"):
                    with controller._lock:
                        jpg = controller._prv_jpeg_bytes if parsed.path.endswith("prv") else controller._pgm_jpeg_bytes
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(jpg)))
                    self.end_headers()
                    if jpg:
                        self.wfile.write(jpg)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if not self._check_auth(parsed):
                    self.send_response(403)
                    self.end_headers()
                    return
                if parsed.path == "/api/action":
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    raw = self.rfile.read(min(length, 65536)) if length > 0 else b"{}"
                    try:
                        cmd_obj = json.loads(raw.decode("utf-8"))
                        if isinstance(cmd_obj, dict):
                            controller._cmd_queue.append(cmd_obj)
                    except Exception:
                        pass
                    resp = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                else:
                    self.send_response(404)
                    self.end_headers()

        try:
            ThreadingHTTPServer.allow_reuse_address = True
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
            self._server_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._server_thread.start()
            self.enabled = True
            self._save_config()
            return True, self.get_access_url()
        except Exception as e:
            self._httpd = None
            self._server_thread = None
            return False, str(e)

    def stop_server(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._server_thread = None

    @staticmethod
    def _qimage_to_jpeg_bytes(img: QImage, width: int = 426, height: int = 240, quality: int = 68) -> bytes:
        if img is None or img.isNull():
            return b""
        scaled = img.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(buf, "JPG", quality)
        return bytes(buf.data())

    def tick_from_main_thread(self, prv_frame: QImage, pgm_canvas: QImage, tick_count: int):
        """
        Called by the 30 FPS render loop in LiteMixMainWindow:
        1. Executes all pending commands received from iPad/browser clients on the Qt main thread.
        2. Updates the JSON state snapshot and JPEG monitor thumbnails when a client is connected.
        """
        while self._cmd_queue:
            try:
                cmd = self._cmd_queue.popleft()
                self._execute_command_on_main_thread(cmd)
            except Exception as e:
                print(f"[WebRemote] Command error: {e}")

        if not self._httpd:
            return

        # Update JSON state snapshot every 3 ticks (~10 Hz)
        if tick_count % 3 == 0:
            st = self._build_state_dict()
            raw_json = json.dumps(st, ensure_ascii=False).encode("utf-8")
            with self._lock:
                self._state_json_bytes = raw_json

        # Encode JPEG thumbnails only when a web client has polled within the last 3 seconds (~6 FPS)
        if (time.time() - self._last_client_poll) < 3.0 and (tick_count % 5 == 0):
            prv_jpg = self._qimage_to_jpeg_bytes(prv_frame)
            pgm_jpg = self._qimage_to_jpeg_bytes(pgm_canvas)
            with self._lock:
                self._prv_jpeg_bytes = prv_jpg
                self._pgm_jpeg_bytes = pgm_jpg

    def _build_state_dict(self) -> dict:
        win = self.main_win
        inputs_list = []
        for idx, inp in enumerate(win.inputs):
            cls_name = inp.__class__.__name__
            playable = hasattr(inp, "toggle_pause") and hasattr(inp, "get_position_duration")
            has_loop_ret = cls_name in ("VideoFileInput", "AudioFileInput", "ReplaySourceInput")
            has_speed = cls_name in ("ReplaySourceInput", "HighlightsInput")
            pos_s, dur_s = inp.get_position_duration() if playable else (0.0, 0.0)
            is_lt = (cls_name == "LowerThirdInput")
            is_audio_only = hasattr(inp, "icon_text")
            item = {
                "index": idx,
                "name": inp.name,
                "type": cls_name,
                "playable": bool(playable),
                "has_loop_ret": bool(has_loop_ret),
                "has_speed": bool(has_speed),
                "paused": bool(getattr(inp, "paused", True)),
                "loop_enabled": bool(getattr(inp, "loop_enabled", False)),
                "return_to_preview_on_eos": bool(getattr(inp, "return_to_preview_on_eos", False)),
                "playback_rate": float(getattr(inp, "playback_rate", 1.0)),
                "pos_s": round(float(pos_s), 2),
                "dur_s": round(float(dur_s), 2),
                "has_audio": bool(inp.has_audio),
                "muted": bool(inp.muted),
                "vol_pct": int(round(inp.volume * 100)),
                "vu": round(float(inp.vu_level), 3),
                "is_lt": is_lt,
                "is_audio_only": is_audio_only,
            }
            if is_lt:
                item["lt_title"] = getattr(inp, "title", "")
                item["lt_sub"] = getattr(inp, "subtitle", "")
                item["lt_tpl"] = int(getattr(inp, "template_id", 0))
            inputs_list.append(item)

        prv_inp = win.inputs[win.prv_idx] if 0 <= win.prv_idx < len(win.inputs) else None
        pgm_inp = win.inputs[win.pgm_idx] if 0 <= win.pgm_idx < len(win.inputs) else None

        return {
            "version": win.APP_VERSION,
            "lang": get_lang(),
            "prv_idx": win.prv_idx,
            "pgm_idx": win.pgm_idx,
            "ovl1_idx": win.ovl1_idx,
            "ovl2_idx": win.ovl2_idx,
            "prv_label": f"Input {win.prv_idx + 1}: {prv_inp.name}" if prv_inp else "",
            "pgm_label": f"Input {win.pgm_idx + 1}: {pgm_inp.name}" if pgm_inp else "",
            "ftb_active": bool(win.ftb_active),
            "recording": bool(win.recorder.recording),
            "streaming": bool(win.streamer.streaming),
            "replay_recording": bool(win.replay_recorder.recording),
            "replay_btn_text": win.btn_replay.text(),
            "mic_muted": bool(win.mic_muted),
            "clip_muted": bool(win.btn_clip_mute.isChecked()),
            "ext_output_active": bool(win.is_ext_output_active()) if hasattr(win, "is_ext_output_active") else False,
            "rec_status": win.lbl_rec_status.text(),
            "stats_text": win.lbl_stats.text(),
            "inputs": inputs_list,
        }

    def _execute_command_on_main_thread(self, cmd: dict):
        win = self.main_win
        action = str(cmd.get("cmd", ""))
        if action == "cut":
            win.do_cut()
        elif action == "fade":
            win.do_fade()
        elif action == "ftb":
            win.toggle_ftb()
        elif action == "toggle_lang":
            win.toggle_ui_language()
        elif action == "toggle_ext_output":
            if hasattr(win, "toggle_external_program_output"):
                win.toggle_external_program_output()
        elif action == "tbar":
            val = max(0, min(100, int(cmd.get("value", 0))))
            win.tbar_slider.setValue(val)
        elif action == "replay_toggle":
            win.toggle_replay_recording()
        elif action == "rec_toggle":
            win.toggle_recording()
        elif action == "stream_toggle":
            win.toggle_streaming()
        elif action == "mic_mute":
            win.btn_mic_mute.click()
        elif action == "clip_mute":
            win.btn_clip_mute.click()
        elif action == "set_prv":
            win.set_preview(int(cmd.get("index", 0)))
        elif action == "cut_idx":
            win.cut_input_to_program(int(cmd.get("index", 0)))
        elif action == "ovl":
            win.toggle_overlay(int(cmd.get("channel", 1)), int(cmd.get("index", 0)))
        elif action == "prv_play_pause":
            win.toggle_preview_media_play()
        elif action == "prv_stop":
            win.stop_preview_media()
        elif action == "prv_toggle_loop":
            if 0 <= win.prv_idx < len(win.inputs):
                inp = win.inputs[win.prv_idx]
                if hasattr(inp, "loop_enabled"):
                    inp.loop_enabled = not bool(inp.loop_enabled)
                    if inp.loop_enabled and hasattr(inp, "return_to_preview_on_eos"):
                        inp.return_to_preview_on_eos = False
                    win._save_last_preset_silent()
        elif action == "prv_toggle_return":
            if 0 <= win.prv_idx < len(win.inputs):
                inp = win.inputs[win.prv_idx]
                if hasattr(inp, "return_to_preview_on_eos"):
                    inp.return_to_preview_on_eos = not bool(inp.return_to_preview_on_eos)
                    if inp.return_to_preview_on_eos and hasattr(inp, "loop_enabled"):
                        inp.loop_enabled = False
                    win._save_last_preset_silent()
        elif action == "prv_seek_ratio":
            if 0 <= win.prv_idx < len(win.inputs):
                inp = win.inputs[win.prv_idx]
                if hasattr(inp, "get_position_duration") and hasattr(inp, "seek_seconds"):
                    _, dur_s = inp.get_position_duration()
                    if dur_s > 0.1:
                        ratio = max(0.0, min(1.0, float(cmd.get("ratio", 0.0))))
                        inp.seek_seconds(ratio * dur_s)
        elif action == "prv_rate":
            if 0 <= win.prv_idx < len(win.inputs):
                inp = win.inputs[win.prv_idx]
                if hasattr(inp, "set_playback_rate"):
                    inp.set_playback_rate(float(cmd.get("rate", 0.5)))
                    win._save_last_preset_silent()
        elif action == "tile_play_pause":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.inputs) and hasattr(win.inputs[idx], "toggle_pause"):
                win.inputs[idx].toggle_pause()
        elif action == "tile_stop":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.inputs) and hasattr(win.inputs[idx], "stop_playback"):
                win.inputs[idx].stop_playback()
        elif action == "tile_loop":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.input_tiles) and win.input_tiles[idx].btn_loop:
                win.input_tiles[idx].btn_loop.click()
        elif action == "tile_ret":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.input_tiles) and win.input_tiles[idx].btn_return_prv:
                win.input_tiles[idx].btn_return_prv.click()
        elif action == "tile_mute":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.input_tiles) and win.input_tiles[idx].btn_mute_tile:
                win.input_tiles[idx].btn_mute_tile.click()
        elif action == "tile_vol":
            idx = int(cmd.get("index", -1))
            val = max(0, min(150, int(cmd.get("value", 100))))
            if 0 <= idx < len(win.input_tiles) and win.input_tiles[idx].vol_slider:
                win.input_tiles[idx].vol_slider.setValue(val)
        elif action == "set_lower_third":
            idx = int(cmd.get("index", -1))
            if 0 <= idx < len(win.inputs):
                inp = win.inputs[idx]
                if hasattr(inp, "set_texts"):
                    inp.set_texts(
                        str(cmd.get("title", "")),
                        str(cmd.get("subtitle", "")),
                        template_id=int(cmd.get("template_id", 0)),
                    )
                    win._save_last_preset_silent()


class WebRemoteDialog(QDialog):
    """
    Dialog window for the iPad/browser Web Remote displaying QR code, direct URL, and security token.
    """

    def __init__(self, parent, controller: WebRemoteController):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(
            tr(
                "📱 LiteMix HD – Web-Fernsteuerung (iPad / Tablet / Browser)",
                "📱 LiteMix HD – Web Remote Control (iPad / Tablet / Browser)",
            )
        )
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info = QLabel(
            tr(
                "Steuern Sie <b>LiteMix HD</b> bequem über das WLAN von einem <b>iPad, Smartphone oder Zweitrechner</b> aus.<br>"
                "Scannen Sie einfach den <b>QR-Code</b> mit der iPad-Kamera – das Zugangs-Token ist im Link bereits enthalten.",
                "Control <b>LiteMix HD</b> wirelessly over Wi-Fi/LAN from an <b>iPad, smartphone, or second computer</b>.<br>"
                "Simply scan the <b>QR code</b> with your iPad camera — the security token is already embedded in the link.",
            )
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #c8d2e4; font-size: 11px;")
        root.addWidget(info)

        # Middle section: QR code on the left + connection details on the right
        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)

        qr_frame = QFrame()
        qr_frame.setStyleSheet("background-color: #ffffff; border: 2px solid #38a3eb; border-radius: 8px; padding: 6px;")
        qr_vbox = QVBoxLayout(qr_frame)
        qr_vbox.setContentsMargins(6, 6, 6, 6)
        self.lbl_qr = QLabel()
        self.lbl_qr.setFixedSize(210, 210)
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_vbox.addWidget(self.lbl_qr)
        mid_row.addWidget(qr_frame)

        details_vbox = QVBoxLayout()
        details_vbox.setSpacing(8)

        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold;")
        details_vbox.addWidget(self.lbl_status)

        form = QFormLayout()
        form.setSpacing(6)

        self.edit_url = QLineEdit()
        self.edit_url.setReadOnly(True)
        self.edit_url.setStyleSheet("font-family: monospace; font-size: 11px; color: #20d660; background: #12161f; padding: 5px;")
        form.addRow(tr("Direkt-Link:", "Direct URL:"), self.edit_url)

        self.edit_token = QLineEdit()
        self.edit_token.setReadOnly(True)
        self.edit_token.setStyleSheet("font-family: monospace; font-size: 12px; font-weight: bold; color: #ffca40; background: #12161f; padding: 5px;")
        form.addRow(tr("Sicherheits-Token:", "Security Token:"), self.edit_token)

        port_row = QHBoxLayout()
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(self.controller.port)
        btn_apply_port = QPushButton(tr("Port übernehmen", "Apply Port"))
        btn_apply_port.clicked.connect(self._on_apply_port)
        port_row.addWidget(self.spin_port)
        port_row.addWidget(btn_apply_port)
        port_row.addStretch()
        form.addRow("TCP Port:", port_row)

        details_vbox.addLayout(form)

        act_row1 = QHBoxLayout()
        btn_copy = QPushButton(tr("📋 Link kopieren", "📋 Copy Link"))
        btn_copy.clicked.connect(self._on_copy_link)
        btn_new_token = QPushButton(tr("🔑 Neues Token erzeugen", "🔑 Generate New Token"))
        btn_new_token.setToolTip(
            tr(
                "Erzeugt ein neues Sicherheits-Token und macht alte QR-Codes ungültig",
                "Generates a new security token and invalidates previous QR codes",
            )
        )
        btn_new_token.clicked.connect(self._on_new_token)
        act_row1.addWidget(btn_copy)
        act_row1.addWidget(btn_new_token)
        details_vbox.addLayout(act_row1)

        self.btn_toggle_srv = QPushButton()
        self.btn_toggle_srv.clicked.connect(self._on_toggle_server)
        details_vbox.addWidget(self.btn_toggle_srv)

        details_vbox.addStretch()
        mid_row.addLayout(details_vbox, 1)
        root.addLayout(mid_row)

        foot = QHBoxLayout()
        foot.addStretch()
        btn_close = QPushButton(tr("Schließen", "Close"))
        btn_close.setObjectName("AddInputBtn")
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)
        root.addLayout(foot)

        self._refresh_ui()

    def _refresh_ui(self):
        running = self.controller.is_running()
        url = self.controller.get_access_url()
        self.edit_url.setText(url)
        self.edit_token.setText(self.controller.token)

        if running:
            self.lbl_status.setText(
                tr(
                    "🟢 Web-Server aktiv – Bereit für iPad / Browser",
                    "🟢 Web Server Active – Ready for iPad / Browser",
                )
            )
            self.lbl_status.setStyleSheet("color: #20d660; font-size: 12px; font-weight: bold;")
            self.btn_toggle_srv.setText(
                tr("⏹ Web-Fernsteuerung deaktivieren", "⏹ Disable Web Remote")
            )
        else:
            self.lbl_status.setText(
                tr(
                    "⚪ Web-Fernsteuerung ist derzeit pausiert",
                    "⚪ Web Remote is currently paused",
                )
            )
            self.lbl_status.setStyleSheet("color: #f08030; font-size: 12px; font-weight: bold;")
            self.btn_toggle_srv.setText(
                tr("▶ Web-Fernsteuerung jetzt starten", "▶ Start Web Remote Now")
            )

        qr_img = generate_qr_qimage(url, box_size=210, border_modules=3)
        self.lbl_qr.setPixmap(QPixmap.fromImage(qr_img))

    def _on_copy_link(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.controller.get_access_url())
        self.lbl_status.setText(
            tr("✅ Link in die Zwischenablage kopiert!", "✅ Link copied to clipboard!")
        )

    def _on_new_token(self):
        self.controller.regenerate_token()
        self._refresh_ui()

    def _on_apply_port(self):
        new_port = int(self.spin_port.value())
        self.controller.port = new_port
        ok, msg = self.controller.start_server()
        if not ok:
            QMessageBox.warning(
                self,
                tr("Port-Fehler", "Port Error"),
                tr(
                    f"Server konnte auf Port {new_port} nicht gestartet werden:\n{msg}",
                    f"Failed to start server on port {new_port}:\n{msg}",
                ),
            )
        self._refresh_ui()

    def _on_toggle_server(self):
        if self.controller.is_running():
            self.controller.stop_server()
            self.controller.enabled = False
            self.controller._save_config()
        else:
            ok, msg = self.controller.start_server()
            if not ok:
                QMessageBox.warning(
                    self,
                    tr("Server-Fehler", "Server Error"),
                    tr(
                        f"Web-Fernsteuerung konnte nicht gestartet werden:\n{msg}",
                        f"Failed to start Web Remote server:\n{msg}",
                    ),
                )
        self._refresh_ui()
