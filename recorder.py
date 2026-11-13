import os
import time
import collections
import subprocess
import threading
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst
from PyQt6.QtGui import QImage
from audio_mixer import list_audio_devices
from i18n import tr


def _create_sink_keepalive():
    """
    Keep the PipeWire audio sink active with an inaudible dither (-72 dB) so the .monitor
    loopback device continuously delivers 48 kHz audio packets to FFmpeg even when all
    video/audio clips are paused or stopped (prevents A/V drift during live streams).
    """
    try:
        pipe = Gst.parse_launch(
            "audiotestsrc wave=red-noise volume=0.00025 is-live=true ! "
            "audioconvert ! audioresample ! audio/x-raw,format=S16LE,rate=48000,channels=2 ! "
            "pulsesink buffer-time=40000 latency-time=10000 sync=true"
        )
        pipe.set_state(Gst.State.PLAYING)
        return pipe
    except Exception:
        return None


def resolve_audio_capture_devices(inputs: list = None) -> tuple[str | None, str | None]:
    """
    Determine which PulseAudio/PipeWire capture devices should be used for recording/streaming
    based on the active sources in the current set:
    - sys_monitor: Desktop/system audio (.monitor) when a Video, Audio file, Browser, or SystemAudio source is present.
    - mic_source: Microphone source when a MicDeviceInput source is present and active.
    """
    sources, monitors = list_audio_devices()
    default_monitor = monitors[0][0] if monitors else "default"
    default_mic = sources[0][0] if sources else "default"

    if not inputs:
        return None, None

    need_sys_monitor = False
    sys_device = default_monitor
    need_mic = False
    mic_device = default_mic

    for inp in inputs:
        if not getattr(inp, "has_audio", False):
            continue
        cls_name = inp.__class__.__name__
        if cls_name in ("VideoFileInput", "AudioFileInput", "WebBrowserInput"):
            need_sys_monitor = True
        elif cls_name == "SystemAudioInput":
            need_sys_monitor = True
            dev = getattr(inp, "device_id", "")
            if dev and dev != "default":
                sys_device = dev
        elif cls_name == "MicDeviceInput":
            if not getattr(inp, "muted", False) and getattr(inp, "volume", 1.0) > 0.01:
                need_mic = True
                dev = getattr(inp, "device_id", "")
                if dev and dev != "default":
                    mic_device = dev

    return (sys_device if need_sys_monitor else None), (mic_device if need_mic else None)


_DETECTED_HW_BACKEND: str | None = None
_PROBE_CACHE: dict[str, bool] = {}
_ENCODER_PREFERENCE: str = "auto"  # "auto", "nvenc", "vaapi", "x264"


def _probe_ffmpeg_encoder(enc_type: str) -> bool:
    """Tests whether the specified hardware encoder ('nvenc' or 'vaapi') is functional on this system."""
    if enc_type in _PROBE_CACHE:
        return _PROBE_CACHE[enc_type]

    ok = False
    try:
        if enc_type == "nvenc":
            if os.path.exists("/dev/nvidia0") or os.path.exists("/dev/nvidiactl"):
                res = subprocess.run(
                    [
                        "ffmpeg", "-v", "error",
                        "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.04",
                        "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.5,
                )
                ok = (res.returncode == 0)
        elif enc_type == "vaapi":
            if os.path.exists("/dev/dri/renderD128"):
                res = subprocess.run(
                    [
                        "ffmpeg", "-v", "error",
                        "-vaapi_device", "/dev/dri/renderD128",
                        "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.04",
                        "-frames:v", "1", "-vf", "format=nv12,hwupload",
                        "-c:v", "h264_vaapi", "-f", "null", "-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2.5,
                )
                ok = (res.returncode == 0)
    except Exception:
        ok = False

    _PROBE_CACHE[enc_type] = ok
    return ok


def detect_hardware_encoder(force_refresh: bool = False) -> str:
    """
    Auto-detects the best available hardware H.264 encoder in priority order:
    1. 'nvenc' (NVIDIA GeForce / RTX via h264_nvenc)
    2. 'vaapi' (Intel HD / Iris Xe / Arc & AMD Radeon via h264_vaapi)
    3. 'x264'  (CPU fallback via libx264)
    """
    global _DETECTED_HW_BACKEND
    if force_refresh:
        _PROBE_CACHE.clear()
        _DETECTED_HW_BACKEND = None
    if _DETECTED_HW_BACKEND is not None:
        return _DETECTED_HW_BACKEND

    if _probe_ffmpeg_encoder("nvenc"):
        _DETECTED_HW_BACKEND = "nvenc"
    elif _probe_ffmpeg_encoder("vaapi"):
        _DETECTED_HW_BACKEND = "vaapi"
    else:
        _DETECTED_HW_BACKEND = "x264"
    return _DETECTED_HW_BACKEND


def set_encoder_preference(pref: str):
    """Sets the global encoder preference ('auto', 'nvenc', 'vaapi', or 'x264')."""
    global _ENCODER_PREFERENCE
    p = str(pref or "auto").strip().lower()
    _ENCODER_PREFERENCE = p if p in ("auto", "nvenc", "vaapi", "x264") else "auto"


def get_encoder_preference() -> str:
    return _ENCODER_PREFERENCE


def resolve_active_encoder(preferred: str | None = None) -> tuple[str, str]:
    """
    Resolves (backend_key, human_readable_label) according to user preference
    with automatic fallback if the requested hardware is not present.
    """
    pref = (preferred or _ENCODER_PREFERENCE or "auto").strip().lower()
    if pref == "nvenc" and _probe_ffmpeg_encoder("nvenc"):
        return "nvenc", "NVIDIA NVENC (h264_nvenc GPU)"
    if pref == "vaapi" and _probe_ffmpeg_encoder("vaapi"):
        return "vaapi", "Intel/AMD VA-API (h264_vaapi GPU)"
    if pref == "x264":
        return "x264", "CPU Software (libx264)"

    best = detect_hardware_encoder()
    if best == "nvenc":
        return "nvenc", "NVIDIA NVENC (h264_nvenc GPU)"
    if best == "vaapi":
        return "vaapi", "Intel/AMD VA-API (h264_vaapi GPU)"
    return "x264", "CPU Fallback (libx264)"


def build_video_encoder_args(
    backend: str,
    qp: int = 22,
    gop: int | None = None,
    low_latency_cpu: bool = False,
) -> tuple[list[str], list[str]]:
    """Returns (ffmpeg_global_hw_args, ffmpeg_video_codec_args) for 'nvenc', 'vaapi', or 'x264'."""
    gop_args = ["-g", str(int(gop))] if gop else []
    if backend == "nvenc":
        return (
            [],
            [
                "-vf", "format=yuv420p",
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-tune", "ll",
                "-rc", "constqp",
                "-qp", str(int(qp)),
            ] + gop_args,
        )
    if backend == "vaapi":
        return (
            ["-vaapi_device", "/dev/dri/renderD128"],
            [
                "-vf", "format=nv12,hwupload",
                "-c:v", "h264_vaapi",
                "-qp", str(int(qp)),
            ] + gop_args,
        )
    # CPU libx264 fallback
    cpu_args = [
        "-vf", "format=yuv420p",
        "-c:v", "libx264",
        "-preset", "veryfast" if low_latency_cpu else "ultrafast",
    ]
    if low_latency_cpu:
        cpu_args += ["-tune", "zerolatency"]
    cpu_args += ["-crf", str(int(qp))] + gop_args
    return [], cpu_args


class VAAPIRecorder:
    """
    Lightweight hardware video recorder supporting NVIDIA NVENC (h264_nvenc),
    Intel/AMD VA-API (h264_vaapi), and CPU fallback (libx264).
    Records the composited Program video output (BGRA) along with optional microphone/system audio.
    """

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.recording = False
        self.output_path = ""
        _, self.encoder_name = resolve_active_encoder()
        self.start_time = 0.0
        self.bitrate_kbps = 0.0
        self.bitrate_str = "0 kbit/s"
        self._proc = None
        self._keepalive_pipe = None
        self._latest_frame_bytes = None
        self._worker_thread = None
        self._stats_thread = None

    def start(
        self,
        output_path: str,
        record_audio: bool = True,
        audio_gain: float = 0.85,
        audio_muted: bool = False,
        inputs: list = None,
    ) -> bool:
        if self.recording:
            return False

        self.output_path = output_path
        backend, self.encoder_name = resolve_active_encoder()
        hw_global_args, vcodec_args = build_video_encoder_args(backend, qp=22, gop=None, low_latency_cpu=False)

        cmd = ["ffmpeg", "-y"] + hw_global_args

        # Video input via stdin pipe (constant real-time frame rate paced by _write_loop)
        cmd += [
            "-thread_queue_size", "1024",
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
        ]

        sys_dev, mic_dev = resolve_audio_capture_devices(inputs)
        if record_audio and not sys_dev and not mic_dev:
            # Fallback when no specific audio source was passed
            _, monitors = list_audio_devices()
            sys_dev = monitors[0][0] if monitors else "default"

        if record_audio and sys_dev:
            self._keepalive_pipe = _create_sink_keepalive()

        if record_audio:
            if sys_dev and mic_dev:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", sys_dev,
                ]
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", mic_dev,
                ]
            elif sys_dev:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", sys_dev,
                ]
            elif mic_dev:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", mic_dev,
                ]

        cmd += vcodec_args

        if record_audio:
            eff_vol = 0.0 if audio_muted else max(0.0, min(1.5, audio_gain))
            if sys_dev and mic_dev:
                fc = (
                    f"[1:a]adelay=90|90,aresample=async=1000[sys];"
                    f"[2:a]aresample=async=1000,highpass=f=80[mic];"
                    f"[sys][mic]amix=inputs=2:duration=first:dropout_transition=0,"
                    f"volume={eff_vol:.2f},alimiter=limit=0.89:attack=5:release=50:level=disabled[aout]"
                )
                cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
            elif sys_dev:
                af_chain = (
                    f"adelay=90|90,aresample=async=1000,"
                    f"volume={eff_vol:.2f},"
                    f"alimiter=limit=0.89:attack=5:release=50:level=disabled"
                )
                cmd += ["-af", af_chain]
            else:
                af_chain = (
                    f"aresample=async=1000,"
                    f"highpass=f=80,"
                    f"volume={eff_vol:.2f},"
                    f"alimiter=limit=0.89:attack=5:release=50:level=disabled"
                )
                cmd += ["-af", af_chain]
            cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]

        cmd.append(output_path)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.recording = True
            self.start_time = time.time()
            self._worker_thread = threading.Thread(target=self._write_loop, daemon=True)
            self._worker_thread.start()
            return True
        except Exception as e:
            print(f"[VAAPIRecorder] Failed to start: {e}")
            self.recording = False
            return False

    def push_frame(self, img: QImage):
        if not self.recording or not self._proc:
            return
        if img.width() != self.width or img.height() != self.height:
            img = img.scaled(self.width, self.height)
        if img.format() not in (
            QImage.Format.Format_ARGB32,
            QImage.Format.Format_ARGB32_Premultiplied,
            QImage.Format.Format_RGB32,
        ):
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        ptr = img.constBits()
        ptr.setsize(self.width * self.height * 4)
        self._latest_frame_bytes = bytes(ptr)

    def _write_loop(self):
        interval = 1.0 / max(1, self.fps)
        # 1. Wait for the first frame and write it to FFmpeg so Input #0 (pipe:0)
        # initializes immediately and FFmpeg opens Input #1 (-f pulse) right after.
        while self.recording and self._proc and self._proc.stdin and self._latest_frame_bytes is None:
            time.sleep(0.005)
        if not (self.recording and self._proc and self._proc.stdin):
            return
        try:
            self._proc.stdin.write(self._latest_frame_bytes)
            self._proc.stdin.flush()
        except Exception:
            return

        # 2. From this instant on, PulseAudio buffers in real time. A precision sampler thread
        # pushes live frames at exact intervals into a FIFO queue so no video frames are dropped
        # during encoder/muxer initialization (prevents video leading audio).
        fifo = collections.deque(maxlen=int(self.fps * 5))

        def _sampler():
            next_t = time.monotonic() + interval
            while self.recording and self._proc:
                now = time.monotonic()
                sleep_s = next_t - now
                if sleep_s > 0.001:
                    time.sleep(sleep_s)
                next_t += interval
                if time.monotonic() - next_t > 0.25:
                    next_t = time.monotonic() + interval
                fb = self._latest_frame_bytes
                if fb is not None:
                    fifo.append(fb)

        threading.Thread(target=_sampler, daemon=True).start()

        while self.recording and self._proc and self._proc.stdin:
            if not fifo:
                time.sleep(0.002)
                continue
            raw_bytes = fifo.popleft()
            try:
                self._proc.stdin.write(raw_bytes)
            except Exception:
                break

    def _stats_loop(self):
        last_bytes = None
        last_time = None
        avg_kbps = 0.0
        while self.streaming and self._proc and self._proc.stdout:
            try:
                raw_line = self._proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line.startswith("total_size="):
                    val_str = line.split("=", 1)[1].strip()
                    if val_str.isdigit():
                        cur_bytes = int(val_str)
                        now = time.monotonic()
                        if last_bytes is not None and last_time is not None:
                            dt = now - last_time
                            if dt >= 0.25 and cur_bytes >= last_bytes:
                                inst_kbps = ((cur_bytes - last_bytes) * 8.0 / 1000.0) / dt
                                self.bitrate_kbps = (
                                    inst_kbps if self.bitrate_kbps <= 1.0
                                    else (0.6 * inst_kbps + 0.4 * self.bitrate_kbps)
                                )
                                self._update_bitrate_str(self.bitrate_kbps)
                        last_bytes = cur_bytes
                        last_time = now
                elif line.startswith("bitrate="):
                    val_str = line.split("=", 1)[1].strip().replace("kbits/s", "").strip()
                    try:
                        avg_kbps = float(val_str)
                        if self.bitrate_kbps <= 1.0 and avg_kbps > 0:
                            self.bitrate_kbps = avg_kbps
                            self._update_bitrate_str(avg_kbps)
                    except ValueError:
                        pass
            except Exception:
                break

    def _update_bitrate_str(self, kbps: float):
        if kbps >= 1000.0:
            self.bitrate_str = f"{kbps / 1000.0:.2f} Mbit/s"
        else:
            self.bitrate_str = f"{int(round(kbps))} kbit/s"

    def elapsed_str(self) -> str:
        if not self.recording:
            return "00:00:00"
        secs = int(time.time() - self.start_time)
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def stop(self):
        if not self.recording:
            return
        self.recording = False
        if self._worker_thread:
            self._worker_thread.join(timeout=1.5)
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=3.0)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._keepalive_pipe:
            self._keepalive_pipe.set_state(Gst.State.NULL)
            self._keepalive_pipe = None


class VAAPIStreamer:
    """
    Lightweight live streaming engine (RTMP / RTMPS / SRT / UDP)
    using Intel HD Graphics hardware encoding (h264_vaapi).
    Supports YouTube Live, Twitch, Restream, Owncast, and local SRT/UDP streams.
    """

    PRESET_SERVERS = {
        "YouTube Live (RTMP)": "rtmp://a.rtmp.youtube.com/live2",
        "Twitch (RTMP)": "rtmp://live.twitch.tv/app",
        "Eigener RTMP / RTMPS Server": "rtmp://localhost/live",
        "Lokaler Netzwerk-Stream (UDP für VLC)": "udp://127.0.0.1:9999?pkt_size=1316",
        "Lokaler SRT-Stream (Listener)": "srt://0.0.0.0:9999?mode=listener",
    }

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.streaming = False
        self.platform = "YouTube Live (RTMP)"
        self.server_url = "rtmp://a.rtmp.youtube.com/live2"
        self.stream_key = ""
        self.qp = 23  # Quality parameter for NVENC/VA-API CQP (18=very high, 23=optimal for streaming, 28=low bitrate)
        _, self.encoder_name = resolve_active_encoder()
        self.start_time = 0.0
        self.bitrate_kbps = 0.0
        self.bitrate_str = "0 kbit/s"
        self._proc = None
        self._keepalive_pipe = None
        self._latest_frame_bytes = None
        self._worker_thread = None
        self._stats_thread = None

    def get_full_target_url(self) -> str:
        base = self.server_url.strip().rstrip("/")
        key = self.stream_key.strip()
        if base.startswith(("rtmp://", "rtmps://")) and key:
            return f"{base}/{key}"
        return base

    def start(
        self,
        has_live_audio: bool = True,
        audio_gain: float = 0.85,
        audio_muted: bool = False,
        inputs: list = None,
    ) -> tuple[bool, str]:
        if self.streaming:
            return False, tr("Stream läuft bereits.", "Stream is already running.")

        target_url = self.get_full_target_url()
        if not target_url:
            return False, tr(
                "Bitte Server-URL in den Stream-Einstellungen angeben.",
                "Please enter a Server URL in the Stream Settings.",
            )
        if self.platform in ("YouTube Live (RTMP)", "Twitch (RTMP)") and not self.stream_key.strip():
            return False, tr(
                "Bitte einen Stream-Schlüssel (Stream Key) in den Stream-Einstellungen eintragen.",
                "Please enter a Stream Key in the Stream Settings.",
            )

        backend, self.encoder_name = resolve_active_encoder()
        gop = self.fps * 2
        hw_global_args, vcodec_args = build_video_encoder_args(
            backend, qp=self.qp, gop=gop, low_latency_cpu=True
        )
        cmd = ["ffmpeg", "-y"] + hw_global_args

        # 1. Raw BGRA Video Input via Pipe (constant real-time frame rate paced by _write_loop)
        cmd += [
            "-thread_queue_size", "1024",
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
        ]

        # 2. Audio Input: Desktop monitor (.monitor) with keep-alive to prevent PipeWire suspend when paused
        use_real_audio = has_live_audio and not audio_muted
        sys_dev, mic_dev = resolve_audio_capture_devices(inputs) if use_real_audio else (None, None)
        if use_real_audio and not sys_dev and not mic_dev:
            _, monitors = list_audio_devices()
            sys_dev = monitors[0][0] if monitors else "default"

        if use_real_audio and sys_dev:
            self._keepalive_pipe = _create_sink_keepalive()

        if use_real_audio:
            if sys_dev and mic_dev:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", sys_dev,
                ]
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", mic_dev,
                ]
            elif sys_dev:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", sys_dev,
                ]
            else:
                cmd += [
                    "-thread_queue_size", "1024", "-wallclock", "0", "-fragment_size", "2048",
                    "-f", "pulse", "-i", mic_dev,
                ]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]

        # 3. Video Encoder (keyframe interval every 2 seconds: -g 60 at 30 FPS)
        cmd += vcodec_args

        # 4. Audio filter & AAC encoder (adelay=90|90 compensates for ~90ms PipeWire/PulseAudio buffer latency)
        if use_real_audio:
            eff_vol = max(0.0, min(1.5, audio_gain))
            if sys_dev and mic_dev:
                fc = (
                    f"[1:a]adelay=90|90,aresample=async=1000[sys];"
                    f"[2:a]aresample=async=1000,highpass=f=80[mic];"
                    f"[sys][mic]amix=inputs=2:duration=first:dropout_transition=0,"
                    f"volume={eff_vol:.2f},alimiter=limit=0.89:attack=5:release=50:level=disabled[aout]"
                )
                cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
            elif sys_dev:
                af_chain = (
                    f"adelay=90|90,aresample=async=1000,"
                    f"volume={eff_vol:.2f},"
                    f"alimiter=limit=0.89:attack=5:release=50:level=disabled"
                )
                cmd += ["-af", af_chain]
            else:
                af_chain = (
                    f"aresample=async=1000,"
                    f"highpass=f=80,"
                    f"volume={eff_vol:.2f},"
                    f"alimiter=limit=0.89:attack=5:release=50:level=disabled"
                )
                cmd += ["-af", af_chain]

        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest"]
        cmd += ["-progress", "pipe:1", "-stats_period", "0.5"]

        # 5. Output format (FLV for RTMP/RTMPS, MPEG-TS for UDP/SRT)
        if target_url.startswith(("udp://", "srt://")):
            cmd += ["-f", "mpegts", target_url]
        else:
            cmd += ["-f", "flv", target_url]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            self.streaming = True
            self.start_time = time.time()
            self.bitrate_kbps = 0.0
            self.bitrate_str = "0 kbit/s"
            self._worker_thread = threading.Thread(target=self._write_loop, daemon=True)
            self._worker_thread.start()
            self._stats_thread = threading.Thread(target=self._stats_loop, daemon=True)
            self._stats_thread.start()
            return True, tr("Stream gestartet", "Stream started")
        except Exception as e:
            self.streaming = False
            return False, f"Stream Error: {e}"

    def is_alive(self) -> bool:
        if not self.streaming or not self._proc:
            return False
        if self._proc.poll() is not None:
            self.streaming = False
            return False
        return True

    def push_frame(self, img: QImage):
        if not self.streaming or not self._proc:
            return
        if img.width() != self.width or img.height() != self.height:
            img = img.scaled(self.width, self.height)
        if img.format() not in (
            QImage.Format.Format_ARGB32,
            QImage.Format.Format_ARGB32_Premultiplied,
            QImage.Format.Format_RGB32,
        ):
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        ptr = img.constBits()
        ptr.setsize(self.width * self.height * 4)
        self._latest_frame_bytes = bytes(ptr)

    def _write_loop(self):
        interval = 1.0 / max(1, self.fps)
        # 1. Wait for the first frame and write it to FFmpeg so Input #0 (pipe:0)
        # initializes immediately and FFmpeg opens Input #1 (-f pulse) right after.
        while self.streaming and self._proc and self._proc.stdin and self._latest_frame_bytes is None:
            time.sleep(0.005)
        if not (self.streaming and self._proc and self._proc.stdin):
            return
        try:
            self._proc.stdin.write(self._latest_frame_bytes)
            self._proc.stdin.flush()
        except Exception:
            self.streaming = False
            return

        # 2. From this moment on, PulseAudio buffers in real time while FFmpeg performs
        # the RTMP handshake (350-800ms). A precision sampler thread places live frames
        # at exact frame intervals into a FIFO queue so no video frames are skipped
        # during the RTMP handshake.
        fifo = collections.deque(maxlen=int(self.fps * 5))

        def _sampler():
            next_t = time.monotonic() + interval
            while self.streaming and self._proc:
                now = time.monotonic()
                sleep_s = next_t - now
                if sleep_s > 0.001:
                    time.sleep(sleep_s)
                next_t += interval
                if time.monotonic() - next_t > 0.25:
                    next_t = time.monotonic() + interval
                fb = self._latest_frame_bytes
                if fb is not None:
                    fifo.append(fb)

        threading.Thread(target=_sampler, daemon=True).start()

        while self.streaming and self._proc and self._proc.stdin:
            if not fifo:
                time.sleep(0.002)
                continue
            raw_bytes = fifo.popleft()
            try:
                self._proc.stdin.write(raw_bytes)
            except Exception:
                self.streaming = False
                break

    def _stats_loop(self):
        last_bytes = None
        last_time = None
        avg_kbps = 0.0
        while self.streaming and self._proc and self._proc.stdout:
            try:
                raw_line = self._proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line.startswith("total_size="):
                    val_str = line.split("=", 1)[1].strip()
                    if val_str.isdigit():
                        cur_bytes = int(val_str)
                        now = time.monotonic()
                        if last_bytes is not None and last_time is not None:
                            dt = now - last_time
                            if dt >= 0.25 and cur_bytes >= last_bytes:
                                inst_kbps = ((cur_bytes - last_bytes) * 8.0 / 1000.0) / dt
                                self.bitrate_kbps = (
                                    inst_kbps if self.bitrate_kbps <= 1.0
                                    else (0.6 * inst_kbps + 0.4 * self.bitrate_kbps)
                                )
                                self._update_bitrate_str(self.bitrate_kbps)
                        last_bytes = cur_bytes
                        last_time = now
                elif line.startswith("bitrate="):
                    val_str = line.split("=", 1)[1].strip().replace("kbits/s", "").strip()
                    try:
                        avg_kbps = float(val_str)
                        if self.bitrate_kbps <= 1.0 and avg_kbps > 0:
                            self.bitrate_kbps = avg_kbps
                            self._update_bitrate_str(avg_kbps)
                    except ValueError:
                        pass
            except Exception:
                break

    def _update_bitrate_str(self, kbps: float):
        if kbps >= 1000.0:
            self.bitrate_str = f"{kbps / 1000.0:.2f} Mbit/s"
        else:
            self.bitrate_str = f"{int(round(kbps))} kbit/s"

    def elapsed_str(self) -> str:
        if not self.streaming:
            return "00:00:00"
        secs = int(time.time() - self.start_time)
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def stop(self):
        if not self.streaming and not self._proc:
            return
        self.streaming = False
        if self._worker_thread:
            self._worker_thread.join(timeout=1.5)
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=2.5)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self._keepalive_pipe:
            self._keepalive_pipe.set_state(Gst.State.NULL)
            self._keepalive_pipe = None


class VAAPIReplayRecorder:
    """
    Ultra-fast hardware instant replay recorder (Intel VA-API h264_vaapi, 0 MB RAM overhead).
    Records the live Program output on demand with short keyframe intervals (-g 10)
    as an MP4 clip to SSD so it is immediately available in 'Last Replay' and 'Highlights'
    with smooth slow-motion playback.
    """

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.recording = False
        self.output_path = ""
        self.start_time = 0.0
        self.clip_counter = 0
        self._proc = None
        self._latest_frame_bytes = None
        self._worker_thread = None

    @staticmethod
    def get_replays_dir() -> str:
        base = os.path.expanduser("~/Videos/LiteMix_Replays")
        try:
            os.makedirs(base, exist_ok=True)
            return base
        except Exception:
            fallback = os.path.expanduser("~/.cache/litemix/replays")
            os.makedirs(fallback, exist_ok=True)
            return fallback

    def start(self) -> bool:
        if self.recording:
            return False

        self.clip_counter += 1
        ts = time.strftime("%H-%M-%S")
        out_dir = self.get_replays_dir()
        self.output_path = os.path.join(out_dir, f"Replay_{self.clip_counter:02d}_{ts}.mp4")
        backend, self.encoder_name = resolve_active_encoder()
        hw_global_args, vcodec_args = build_video_encoder_args(
            backend, qp=22, gop=10, low_latency_cpu=False
        )

        cmd = ["ffmpeg", "-y"] + hw_global_args

        cmd += [
            "-thread_queue_size", "512",
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
        ]

        # Short keyframe intervals (-g 10) for responsive slow-motion & scrubbing in GStreamer
        cmd += vcodec_args

        cmd += ["-movflags", "+faststart", self.output_path]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.recording = True
            self.start_time = time.time()
            self._worker_thread = threading.Thread(target=self._write_loop, daemon=True)
            self._worker_thread.start()
            return True
        except Exception as e:
            print(f"[VAAPIReplayRecorder] Failed to start: {e}")
            self.recording = False
            return False

    def push_frame(self, img: QImage):
        if not self.recording or not self._proc:
            return
        if img.width() != self.width or img.height() != self.height:
            img = img.scaled(self.width, self.height)
        if img.format() not in (
            QImage.Format.Format_ARGB32,
            QImage.Format.Format_ARGB32_Premultiplied,
            QImage.Format.Format_RGB32,
        ):
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        ptr = img.constBits()
        ptr.setsize(self.width * self.height * 4)
        self._latest_frame_bytes = bytes(ptr)

    def _write_loop(self):
        interval = 1.0 / max(1, self.fps)
        next_t = time.monotonic()
        while self.recording and self._proc and self._proc.stdin:
            now = time.monotonic()
            sleep_s = next_t - now
            if sleep_s > 0.001:
                time.sleep(sleep_s)
            next_t += interval
            if time.monotonic() - next_t > 0.25:
                next_t = time.monotonic() + interval

            raw_bytes = self._latest_frame_bytes
            if raw_bytes is None:
                continue
            try:
                self._proc.stdin.write(raw_bytes)
            except Exception:
                break

    def elapsed_short_str(self) -> str:
        if not self.recording:
            return "00:00"
        secs = int(time.time() - self.start_time)
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def stop(self) -> str | None:
        if not self.recording:
            return None
        self.recording = False
        if self._worker_thread:
            self._worker_thread.join(timeout=1.5)
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=3.0)
            except Exception:
                self._proc.kill()
            self._proc = None
        if self.output_path and os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 1024:
            return self.output_path
        return None
