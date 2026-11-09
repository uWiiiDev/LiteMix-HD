import json
import subprocess
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst
from i18n import tr


def list_audio_devices():
    """
    Enumerate available microphones (Audio/Source) and system outputs (Audio/Sink as .monitor)
    via PipeWire (pw-dump).
    Returns (sources, sink_monitors) as lists of (device_id, label) tuples.
    """
    sources = []
    sink_monitors = []
    try:
        out = subprocess.check_output(["pw-dump"], text=True, timeout=2.0)
        data = json.loads(out)
        for obj in data:
            props = obj.get("info", {}).get("props", {})
            mc = props.get("media.class", "")
            node_name = props.get("node.name", "")
            desc = props.get("node.description") or node_name
            if not node_name:
                continue
            if mc == "Audio/Source":
                sources.append((node_name, f"🎙️ {desc}"))
            elif mc == "Audio/Sink":
                suffix = tr("Desktop-Ton", "Desktop Audio")
                sink_monitors.append((f"{node_name}.monitor", f"🔊 {desc} ({suffix})"))
    except Exception as e:
        print(f"[list_audio_devices] Fallback to default: {e}")

    if not sources:
        sources.append(("default", tr("🎙️ Standard-Mikrofon (Default)", "🎙️ Default Microphone")))
    if not sink_monitors:
        sink_monitors.append(("default", tr("🔊 Standard System-Audio", "🔊 Default System Audio")))

    return sources, sink_monitors


class MicAudioMonitor:
    """Monitors the default microphone input in real time to drive the audio mixer VU meter."""

    def __init__(self, device: str = "default"):
        self.device = device
        self.vu_level = 0.0
        self.volume = 0.85
        self.muted = False
        self.pipeline = None
        self._start()

    def set_volume(self, vol: float):
        self.volume = max(0.0, min(1.5, vol))
        try:
            subprocess.Popen(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{self.volume:.2f}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def set_muted(self, muted: bool):
        self.muted = muted
        try:
            subprocess.Popen(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "1" if muted else "0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def _start(self):
        dev_prop = f'device="{self.device}"' if self.device and self.device != "default" else ""
        pipe_str = (
            f"pulsesrc {dev_prop} ! audioconvert ! "
            f"level interval=50000000 post-messages=true ! fakesink sync=false"
        )
        try:
            self.pipeline = Gst.parse_launch(pipe_str)
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_message)
            self.pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[MicAudioMonitor] Info: {e}")

    def _on_message(self, bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            struct = message.get_structure()
            if struct and struct.get_name() == "level":
                rms_list = struct.get_value("rms")
                if rms_list and len(rms_list) > 0:
                    db = rms_list[0]
                    norm = max(0.0, min(1.0, (db + 50.0) / 50.0))
                    self.vu_level = 0.0 if self.muted else min(1.0, norm * self.volume)

    def stop(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
