"""Main-system Pedro start/stop API; shares its existing RSM and audio mixers."""
import threading

from context import house
from pedro import ASSETS, PedroShow
from utils.tools import log_event

DEFAULT_CHANNEL = "Pedro"
DEFAULT_QUIPS = ASSETS / "SoundDir" / "Quips"
_lock = threading.RLock()
_show = None


def start_pedro(channel=DEFAULT_CHANNEL, *, gain=None, quips=DEFAULT_QUIPS,
                background=None, background_channel=None, background_gain=0.89,
                interval=(10, 15)):
    """Start independently while ONLINE, like play_audio(channel, file, gain=...).

    Returns True if started/already running, False on invalid settings/offline.
    Stop before changing the channel or other settings. Never initializes RSM.
    """
    global _show
    with _lock:
        if house.systemState != "ONLINE":
            log_event("[Pedro] Cannot start while the main system is offline")
            return False
        if _show and _show.running:
            return True
        try:
            if _show and _show.thread and _show.thread.is_alive():
                raise RuntimeError("Pedro is still stopping")
            if interval[0] < 0 or interval[1] < interval[0]:
                raise ValueError("Pedro interval must be a nonnegative (minimum, maximum) pair")
            controller = _show.controller if _show else None
            candidate = PedroShow(channel, gain=gain, quips=quips, background=background,
                                  background_channel=background_channel, background_gain=background_gain,
                                  interval=interval, enabled=lambda: house.systemState == "ONLINE",
                                  controller=controller)
            candidate.start()
            _show = candidate
            log_event(f"[Pedro] Started on {channel}")
            return True
        except Exception as error:
            log_event(f"[Pedro] Start failed: {error}")
            return False


def stop_pedro():
    """Stop only Pedro's audio/show; retain off heartbeats for a solid red LED."""
    with _lock:
        if _show:
            _show.stop()


def pedro_status():
    # UI polling must not wait for a concurrent stop/join or asset validation.
    show = _show
    return {"running": bool(show and show.running),
            "channel": show.channel if show else DEFAULT_CHANNEL,
            "connected": bool(show and show.controller.connected.is_set()),
            "error": show.last_error if show else None}
