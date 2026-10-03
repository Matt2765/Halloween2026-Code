"""Persistent, multi-device software mixer used by the haunt rooms.

The public playback API is compatible with the previous audio manager.  Edit
the device indexes and channel maps in the configuration section below when
the audio hardware changes; the mixer and room code should not need edits.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, TypeAlias, TypedDict, cast

import numpy as np
from numpy.typing import NDArray
import sounddevice as sd
import soundfile as sf

from context import house
from utils.tools import log_event

# =============================================================================
# Audio hardware and room-routing configuration
# =============================================================================
#
# Run `python utils/audio_mixer_diagnostic.py` from MainCode to list the output
# devices.  Set these to the corresponding *output* device indexes.  Do not use
# a microphone/input index: it has zero output channels.
PRIMARY_DEVICE_INDEX: int | None = 13  # Primary multichannel output
SECONDARY_DEVICE_INDEX: int | None = 30  # Secondary multichannel output

# If a configured device is unavailable, continue through Windows' default
# output.  That avoids a show-stopping exception, but routes audio to every
# default-device channel rather than its configured discrete room channel.
FALLBACK_TO_SYSTEM_DEFAULT = True

MULTICH_MIN_CHANNELS = 6
SHORT_CLIP_MAX_SECONDS = 30.0
SHORT_CLIP_CACHE_MAX_BYTES = 256 * 1024 * 1024
STREAM_READ_FRAMES = 16_384
STREAM_BUFFER_SECONDS = 3.0
MIX_BLOCKSIZE = 1_024

# A channel map entry has an output-channel `index` (zero based) and `gain`.
# For a stereo room, either use `"stereo_<room>": {"index": [L, R], ...}` or
# the equivalent two entries, `stereo_<room>_L` and `stereo_<room>_R`.  Calling
# `play_audio("<room>", "clip.wav")` automatically selects that stereo pair.
FloatArray: TypeAlias = NDArray[np.float32]
ChannelIndex: TypeAlias = int | list[int] | tuple[int, int]
DeviceKind: TypeAlias = Literal["primary", "secondary"]
PlaybackMode: TypeAlias = Literal["one", "stereo", "all"]
PlaybackTarget: TypeAlias = int | list[int]


class ChannelConfig(TypedDict):
    index: ChannelIndex
    gain: float


class NamedChannelInfo(TypedDict):
    index: ChannelIndex
    gain: float
    device: DeviceKind


ChannelMap: TypeAlias = dict[str, ChannelConfig]


class _AudioSource(Protocol):
    channels: int

    def read(self, frames: int) -> tuple[FloatArray, bool]: ...

    def close(self) -> None: ...

# Primary output channels. These generic template names are intentionally kept
# separate from any particular year's room or hardware names.
primary_channels: ChannelMap = {
    "CabinRoom_PA": {"index": 0, "gain": 1.0},
    "CabinRoom_Wall": {"index": 1, "gain": 1.0},
    "DynamicHallway": {"index": 2, "gain": 1.0},
    "primary_LFE": {"index": 3, "gain": 1.0},
    "Surround Back Left": {"index": 4, "gain": 1.0},
    "Surround Back Right": {"index": 5, "gain": 1.0},
    "Surround Left": {"index": 6, "gain": 1.0},
    "Surround Right": {"index": 7, "gain": 1.0},
    # "stereo_primary_pair": {"index": [0, 1], "gain": 1.0},
    # Or use stereo_primary_pair_L / stereo_primary_pair_R entries.
}

# Secondary output channels.
secondary_channels: ChannelMap = {
    "secondary_FL": {"index": 0, "gain": 1.0},
    "secondary_FR": {"index": 1, "gain": 1.0},
    "secondary_C": {"index": 2, "gain": 1.0},
    "secondary_LFE": {"index": 3, "gain": 1.0},
    "secondary_BL": {"index": 4, "gain": 1.0},
    "secondary_BR": {"index": 5, "gain": 1.0},
    "secondary_SL": {"index": 6, "gain": 1.0},
    "secondary_SR": {"index": 7, "gain": 1.0},
    # "stereo_secondary_pair": {"index": [0, 1], "gain": 1.0},
    # Or use stereo_secondary_pair_L / stereo_secondary_pair_R entries.
}

DEFAULT_SOUND_DIR = (Path(__file__).resolve().parents[3] / "Assets" / "SoundDir").resolve()
_play_epoch = 0
_cutoff_epoch = 0
_epoch_lock = threading.Lock()
_active_lock = threading.Lock()
_mixer_lock = threading.RLock()
_cache_lock = threading.Lock()
_stop_event = threading.Event()


class _Session:
    def __init__(self, epoch: int, label: str):
        self.epoch = epoch
        self.label = label
        self.done = threading.Event()


_active_sessions: list[_Session] = []

def text_to_wav(text: str, path: Path, rate: int = 0) -> None:
    """Generate an offline speech WAV file."""
    system = platform.system()
    if system in ("Linux", "Darwin"):
        subprocess.run(["espeak", f"-s{150 + rate * 10}", "-w", str(path), text], check=True)
    elif system == "Windows":
        rate = max(-10, min(10, rate))
        script = f'''Add-Type -AssemblyName System.Speech
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate={rate};$s.SetOutputToWaveFile('{str(path).replace("'", "''")}')
try {{ $s.Speak([Console]::In.ReadToEnd()) }} finally {{ $s.Dispose() }}'''
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            input=text, text=True, encoding="utf-8", check=True, capture_output=True,
        )
    else:
        raise RuntimeError(f"TTS not supported on {system}")


def _next_epoch() -> int:
    global _play_epoch
    with _epoch_lock:
        _play_epoch += 1
        return _play_epoch


def _resolve_sound_path(value: str | Path, base_folder: str | Path | None = None) -> Path:
    path = Path(value)
    base = Path(base_folder) if base_folder else DEFAULT_SOUND_DIR
    return path if path.is_absolute() else (base / path).resolve()


def _normalise(x: NDArray[Any]) -> FloatArray:
    x = cast(FloatArray, np.asarray(x, np.float32))
    x = x[:, None] if x.ndim == 1 else x
    if x.shape[1] <= 2:
        return x
    return np.repeat(x.mean(axis=1, keepdims=True, dtype=np.float32), 2, axis=1)


def _resample(x: FloatArray, src: int, dst: int) -> FloatArray:
    if src == dst or not len(x):
        return cast(FloatArray, np.asarray(x, np.float32))
    frames = max(1, round(len(x) * dst / src))
    positions = np.minimum(np.arange(frames, dtype=float) * src / dst, len(x) - 1)
    original = np.arange(len(x), dtype=float)
    return cast(
        FloatArray,
        np.column_stack([np.interp(positions, original, x[:, i]) for i in range(x.shape[1])]).astype(np.float32),
    )

class _CachedSource:
    def __init__(self, data: FloatArray, looping: bool):
        self.data = data
        self.looping = looping
        self.position = 0
        self.channels = data.shape[1]

    def read(self, frames: int) -> tuple[FloatArray, bool]:
        if not len(self.data):
            return np.zeros((frames, self.channels), np.float32), True
        if not self.looping:
            end = min(len(self.data), self.position + frames)
            block = self.data[self.position:end]
            self.position = end
            return block, end >= len(self.data)

        output = np.empty((frames, self.channels), np.float32)
        at = 0
        while at < frames:
            take = min(frames - at, len(self.data) - self.position)
            output[at : at + take] = self.data[self.position : self.position + take]
            at += take
            self.position = (self.position + take) % len(self.data)
        return output, False

    def close(self) -> None:
        pass

class _StreamedSource:
    """Reader thread owns SoundFile; callback sees only queued PCM."""
    def __init__(self, path: Path, src_fs: int, dst_fs: int, channels: int, looping: bool):
        self.path = path
        self.src_fs = src_fs
        self.dst_fs = dst_fs
        self.channels = channels
        self.looping = looping
        self.blocks: deque[FloatArray] = deque()
        self.offset = 0
        self.queued = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.eof = threading.Event()
        self.ready = threading.Event()
        self.underruns = 0
        self.maximum = max(dst_fs, int(dst_fs * STREAM_BUFFER_SECONDS))
        threading.Thread(target=self._reader, name=f"AudioReader:{path.name}", daemon=True).start()

    def _reader(self) -> None:
        try:
            with sf.SoundFile(str(self.path)) as audio_file:
                while not self.stop.is_set():
                    with self.lock:
                        full = self.queued >= self.maximum
                    if full:
                        time.sleep(0.01)
                        continue
                    raw = audio_file.read(STREAM_READ_FRAMES, dtype="float32", always_2d=True)
                    if not len(raw):
                        if self.looping and audio_file.frames > 0:
                            audio_file.seek(0)
                            continue
                        self.eof.set()
                        self.ready.set()
                        return
                    block = _resample(_normalise(raw), self.src_fs, self.dst_fs)
                    with self.lock:
                        self.blocks.append(block)
                        self.queued += len(block)
                        if self.queued >= min(self.dst_fs // 4, self.maximum):
                            self.ready.set()
        except Exception as error:
            self.eof.set()
            self.ready.set()
            log_event(f"[Audio] stream reader failed for '{self.path}': {error}")

    def read(self, frames: int) -> tuple[FloatArray, bool]:
        output = np.zeros((frames, self.channels), np.float32)
        at = 0
        with self.lock:
            while at < frames and self.blocks:
                block = self.blocks[0]
                take = min(frames - at, len(block) - self.offset)
                output[at : at + take] = block[self.offset : self.offset + take]
                self.offset += take
                at += take
                self.queued -= take
                if self.offset == len(block):
                    self.blocks.popleft()
                    self.offset = 0
        if at < frames and not self.eof.is_set():
            self.underruns += 1
        return (output[:at] if self.eof.is_set() else output), self.eof.is_set() and at < frames

    def close(self) -> None:
        self.stop.set()

@dataclass
class _Voice:
    source: _AudioSource
    mode: PlaybackMode
    target: PlaybackTarget
    gain: float
    session: _Session
    honor_shutdown: bool
    honor_breakcheck: bool
    stopped: bool = False

class DeviceMixer:
    def __init__(
        self,
        kind: DeviceKind,
        index: int,
        name: str,
        channels: int,
        samplerate: int,
        hostapi: str,
        fallback: bool = False,
    ) -> None:
        self.kind = kind
        self.device_index = index
        self.device_name = name
        self.channels = channels
        self.samplerate = samplerate
        self.hostapi = hostapi
        self.fallback_to_all = fallback
        self.voices: list[_Voice] = []
        self.lock = threading.Lock()
        self.stream: Any | None = None
        self.callback_status_count = 0
        self.stream_underruns = 0
        self.peak_voices = 0

    def start(self) -> None:
        def open_stream(extra_settings: Any | None) -> Any:
            return sd.OutputStream(
                device=self.device_index,
                samplerate=self.samplerate,
                channels=self.channels,
                dtype="float32",
                blocksize=MIX_BLOCKSIZE,
                latency=0.06,
                callback=self._callback,
                extra_settings=extra_settings,
            )

        def start_stream(extra_settings: Any | None) -> Any:
            stream = open_stream(extra_settings)
            try:
                stream.start()
            except Exception:
                # PortAudio can leave a failed stream holding the endpoint,
                # which prevents the next fallback attempt from opening it.
                try:
                    stream.close()
                finally:
                    raise
            return stream

        extra = None
        if "wasapi" in self.hostapi.lower() and self.channels >= MULTICH_MIN_CHANNELS:
            try:
                extra = sd.WasapiSettings(exclusive=True)
            except Exception:
                pass
        try:
            stream = start_stream(extra)
            self.stream = stream
        except Exception as error:
            if extra is None:
                raise
            log_event(f"[Audio] {self.kind} WASAPI exclusive failed; shared fallback: {error}")
            stream = start_stream(sd.WasapiSettings(exclusive=False))
            self.stream = stream
        log_event(
            f"[Audio] {self.kind.upper()} persistent mixer opened "
            f"idx={self.device_index} '{self.device_name}', "
            f"fs={self.samplerate}, ch={self.channels}"
        )

    def add(self, voice: _Voice) -> None:
        with self.lock:
            self.voices.append(voice)
            self.peak_voices = max(self.peak_voices, len(self.voices))
        log_event(
            f"[Audio] playback started '{voice.session.label}' on {self.kind.upper()}, "
            f"active={self.active_voice_count}"
        )

    @property
    def active_voice_count(self) -> int:
        with self.lock:
            return len(self.voices)

    def stop_matching(self, predicate: Callable[[_Voice], bool]) -> None:
        with self.lock:
            for voice in self.voices:
                if predicate(voice):
                    voice.stopped = True

    def _route(self, output: FloatArray, block: FloatArray, voice: _Voice) -> None:
        frames = len(block)
        if not frames:
            return
        block = block * voice.gain
        if self.channels == 1:
            output[:frames, 0] += block.mean(axis=1)
        elif voice.mode == "all":
            # Broadcasting a stereo source should include both channels rather
            # than silently discarding the right side.
            mono = block[:, :1] if block.shape[1] == 1 else block.mean(axis=1, keepdims=True)
            output[:frames] += mono
        elif voice.mode == "stereo":
            target = cast(list[int], voice.target)
            output[:frames, target[0]] += block[:, 0]
            right = 0 if block.shape[1] == 1 else 1
            output[:frames, target[1]] += block[:, right]
        else:
            # A single physical speaker should receive both halves of a stereo
            # source, not just its left channel.
            mono = block[:, 0] if block.shape[1] == 1 else block.mean(axis=1)
            target = cast(int, voice.target)
            output[:frames, min(target, self.channels - 1)] += mono

    def _callback(self, output: FloatArray, frames: int, time_info: Any, status: Any) -> None:
        output.fill(0)
        if status:
            self.callback_status_count += 1
            self.stream_underruns += int(bool(getattr(status, "output_underflow", False)))
        with self.lock:
            voices = tuple(self.voices)

        done: list[_Voice] = []
        for voice in voices:
            if voice.stopped:
                done.append(voice)
                continue
            block, finished = voice.source.read(frames)
            self._route(output, block, voice)
            if finished:
                done.append(voice)

        np.clip(output, -1, 1, out=output)  # Per-block hard safety; no AGC/pumping.
        if done:
            with self.lock:
                for voice in done:
                    if voice in self.voices:
                        self.voices.remove(voice)
                        voice.source.close()
                        voice.session.done.set()
                        with _active_lock:
                            if voice.session in _active_sessions:
                                _active_sessions.remove(voice.session)

    def diagnostics(self) -> dict[str, object]:
        with self.lock:
            voices = tuple(self.voices)
        return {
            "device": self.device_index,
            "channels": self.channels,
            "samplerate": self.samplerate,
            "active_voices": len(voices),
            "peak_voices": self.peak_voices,
            "callback_statuses": self.callback_status_count,
            "callback_underruns": self.stream_underruns,
            "stream_buffer_underruns": sum(getattr(v.source, "underruns", 0) for v in voices),
        }


class _FallbackMixerView:
    """Route a missing device through an already-open mixer stream."""

    fallback_to_all = True

    def __init__(self, kind: DeviceKind, backing: DeviceMixer) -> None:
        self.kind = kind
        self.backing = backing

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backing, name)

    def add(self, voice: _Voice) -> None:
        self.backing.add(voice)

    def stop_matching(self, predicate: Callable[[_Voice], bool]) -> None:
        self.backing.stop_matching(predicate)

    def diagnostics(self) -> dict[str, object]:
        result = self.backing.diagnostics()
        result["fallback_reuses"] = self.backing.kind
        return result

MixerLike: TypeAlias = DeviceMixer | _FallbackMixerView


def _host(index: int) -> str:
    try:
        hostapis = cast(list[Mapping[str, Any]], sd.query_hostapis())
        for hostapi in hostapis:
            if index in hostapi.get("devices", []):
                return hostapi.get("name", "unknown")
    except Exception:
        pass
    return "unknown"


def _fixed(kind: DeviceKind) -> tuple[int, int, int, str, str]:
    index = PRIMARY_DEVICE_INDEX if kind == "primary" else SECONDARY_DEVICE_INDEX
    if index is None:
        raise RuntimeError(f"{kind.upper()}_DEVICE_INDEX not set or disabled.")
    device = cast(Mapping[str, Any], sd.query_devices(index))
    channels = int(device["max_output_channels"])
    if channels <= 0:
        raise RuntimeError(f"Configured {kind} device {index} has no output channels")
    samplerate = int(round(float(device.get("default_samplerate", 48000))))
    return index, channels, samplerate, _host(index), str(device.get("name", "Unknown"))


_mixers: dict[DeviceKind, MixerLike] = {}


def _fallback_output_candidates(default_index: int) -> list[tuple[int, int, int, str, str]]:
    """Return the default output first, followed by other usable outputs."""
    indexes: list[int] = []
    if default_index >= 0:
        indexes.append(default_index)

    try:
        devices = cast(list[Mapping[str, Any]], sd.query_devices())
        indexes.extend(
            index
            for index, device in enumerate(devices)
            if int(device.get("max_output_channels", 0)) > 0
        )
    except Exception as error:
        log_event(f"[Audio] Could not enumerate fallback outputs: {error}")

    candidates: list[tuple[int, int, int, str, str]] = []
    for index in dict.fromkeys(indexes):
        try:
            device = cast(Mapping[str, Any], sd.query_devices(index))
            channels = int(device.get("max_output_channels", 0))
            if channels <= 0:
                continue
            candidates.append(
                (
                    index,
                    channels,
                    int(round(float(device.get("default_samplerate", 48000)))),
                    _host(index),
                    str(device.get("name", "System Output")),
                )
            )
        except Exception as error:
            log_event(f"[Audio] Skipping fallback output idx={index}: {error}")
    return candidates


def _fallback_channel_counts(max_channels: int) -> list[int]:
    """Try full device width, then common stereo/mono safe modes."""
    return list(dict.fromkeys((max_channels, min(2, max_channels), 1)))


def _make_mixer(kind: DeviceKind) -> MixerLike:
    try:
        index, channels, default_rate, host, name = _fixed(kind)
        samplerate = 48000 if "wasapi" in host.lower() and channels >= MULTICH_MIN_CHANNELS else default_rate
        mixer = DeviceMixer(kind, index, name, channels, samplerate, host)
        mixer.start()
        return mixer
    except Exception as error:
        if not FALLBACK_TO_SYSTEM_DEFAULT:
            raise RuntimeError(f"Failed to open configured {kind} mixer: {error}") from error

        # If the secondary device is missing, reuse the primary stream instead
        # of opening the same Windows endpoint a second time. A second stream
        # can fail when the primary mixer owns a WASAPI-exclusive device.
        if kind == "secondary":
            try:
                primary = _mixer("primary")
            except Exception as primary_error:
                log_event(f"[Audio] PRIMARY fallback mixer unavailable: {primary_error}")
            else:
                primary_index = getattr(primary, "device_index", "unknown")
                primary_name = getattr(primary, "device_name", "Primary output")
                log_event(
                    f"[Audio] SECONDARY mixer failed ({error}); "
                    f"reusing PRIMARY idx={primary_index} '{primary_name}'"
                )
                return _FallbackMixerView(kind, cast(DeviceMixer, primary))

        try:
            _, raw_default_index = cast(tuple[int, int], sd.default.device)
            default_index = int(raw_default_index)
        except Exception:
            default_index = -1

        failures: list[str] = []
        for candidate_index, max_channels, rate, host, name in _fallback_output_candidates(default_index):
            for channels in _fallback_channel_counts(max_channels):
                mixer = DeviceMixer(kind, candidate_index, name, channels, rate, host, True)
                try:
                    mixer.start()
                except Exception as fallback_error:
                    failures.append(f"idx={candidate_index}/ch={channels}: {fallback_error}")
                    log_event(
                        f"[Audio] {kind.upper()} fallback idx={candidate_index}, "
                        f"ch={channels} unavailable: {fallback_error}"
                    )
                    continue
                log_event(
                    f"[Audio] {kind.upper()} configured mixer failed ({error}); "
                    f"using fallback idx={candidate_index} '{name}', all {channels} channel(s)"
                )
                return mixer

        details = "; ".join(failures) if failures else "no output devices were available"
        raise RuntimeError(
            f"Failed to open configured {kind} mixer ({error}); fallback attempts: {details}"
        ) from error


def _mixer(kind: DeviceKind) -> MixerLike:
    with _mixer_lock:
        if kind not in _mixers:
            _mixers[kind] = _make_mixer(kind)
        return _mixers[kind]


def initialize_audio() -> None:
    """Open persistent device streams before room worker threads are started.

    PortAudio/WASAPI device creation is more reliable on the process's main
    thread. Playback remains thread-safe after these streams are running.
    """
    log_event(f"[Audio] Initializing persistent mixers on {threading.current_thread().name}")
    for kind in cast(tuple[DeviceKind, DeviceKind], ("primary", "secondary")):
        try:
            _mixer(kind)
        except Exception as error:
            # Keep system startup alive. A later playback request may retry if
            # an endpoint is connected or becomes available after startup.
            log_event(f"[Audio] Could not initialize {kind.upper()} mixer: {error}")


_cache: OrderedDict[tuple[str, int], FloatArray] = OrderedDict()
_cache_bytes = 0


def _cached(path: Path, rate: int) -> FloatArray:
    global _cache_bytes
    key = (str(path.resolve()), rate)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    raw, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
    data = _resample(_normalise(cast(NDArray[Any], raw)), int(samplerate), rate)
    with _cache_lock:
        # Another request can finish decoding this same clip concurrently.
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        _cache[key] = data
        _cache_bytes += data.nbytes
        while _cache and _cache_bytes > SHORT_CLIP_CACHE_MAX_BYTES:
            _, old = _cache.popitem(last=False)
            _cache_bytes -= old.nbytes
    return data


def _source(path: Path, rate: int, looping: bool, force_cached: bool = False) -> _AudioSource:
    info = sf.info(str(path))
    duration = info.frames / info.samplerate
    if force_cached or duration <= SHORT_CLIP_MAX_SECONDS:
        return _CachedSource(_cached(path, rate), looping)
    source = _StreamedSource(path, int(info.samplerate), rate, 1 if info.channels == 1 else 2, looping)
    source.ready.wait(2)
    return source

def _pair(name: str, channel_map: ChannelMap) -> list[int] | None:
    base = f"stereo_{name}"
    if base in channel_map:
        index = channel_map[base]["index"]
        if isinstance(index, (list, tuple)) and len(index) == 2:
            return [int(channel) for channel in index]
    left, right = f"{base}_L", f"{base}_R"
    if left in channel_map and right in channel_map:
        left_index = channel_map[left]["index"]
        right_index = channel_map[right]["index"]
        if isinstance(left_index, int) and isinstance(right_index, int):
            return [left_index, right_index]
    return None


def _resolve_named_target(name: str) -> tuple[DeviceKind, PlaybackMode, PlaybackTarget, float]:
    channel_maps: tuple[tuple[DeviceKind, ChannelMap], ...] = (
        ("primary", primary_channels),
        ("secondary", secondary_channels),
    )
    for kind, channel_map in channel_maps:
        pair = _pair(name, channel_map)
        if pair:
            base = f"stereo_{name}"
            if base in channel_map:
                gain = float(channel_map[base].get("gain", 1))
            else:
                gain = (
                    float(channel_map[f"{base}_L"].get("gain", 1))
                    + float(channel_map[f"{base}_R"].get("gain", 1))
                ) / 2
            return kind, "stereo", pair, gain
        if name in channel_map:
            entry = channel_map[name]
            index = entry["index"]
            if isinstance(index, (list, tuple)) and len(index) == 2:
                return kind, "stereo", list(index), float(entry.get("gain", 1))
            if isinstance(index, int):
                return kind, "one", index, float(entry.get("gain", 1))
            raise ValueError(f"Channel '{name}' must have one index or a two-channel stereo index.")
    raise ValueError(f"Unknown channel name '{name}'.")


def _submit(
    path: Path,
    name: str | None,
    mode: PlaybackMode,
    target: PlaybackTarget,
    gain: float,
    looping: bool,
    honor_shutdown: bool,
    honor_breakcheck: bool,
    threaded: bool,
    force_cached: bool = False,
) -> None:
    session = _Session(_next_epoch(), f"{path.name}@{name or 'all'}")
    if mode == "all":
        kind: DeviceKind = "primary"
    else:
        if name is None:
            raise ValueError("A named route requires a channel name.")
        kind = _resolve_named_target(name)[0]
    if mode != "all":
        assert name is not None
        kind, mode, target, _ = _resolve_named_target(name)
    mixer = _mixer(kind)
    if mixer.fallback_to_all:
        # Preserve stereo when the fallback device can reproduce it. Discrete
        # mono routes still broadcast because their original channel number
        # has no meaning on a different device.
        if mode == "stereo" and mixer.channels >= 2:
            target = [0, 1]
        else:
            mode, target = "all", 0
    elif mode == "stereo":
        stereo_target = cast(list[int], target)
        if any(channel < 0 or channel >= mixer.channels for channel in stereo_target):
            raise ValueError(f"Route '{name}' uses {target}, but {kind} has {mixer.channels} output channels")
    elif mode == "one":
        mono_target = cast(int, target)
        if mono_target < 0 or mono_target >= mixer.channels:
            raise ValueError(f"Route '{name}' uses channel {target}, but {kind} has {mixer.channels} output channels")

    voice = _Voice(
        _source(path, mixer.samplerate, looping, force_cached),
        mode,
        target,
        float(gain),
        session,
        honor_shutdown,
        honor_breakcheck,
    )
    # A shutdown can happen while a file is being decoded/buffered.
    with _epoch_lock:
        if honor_shutdown and session.epoch <= _cutoff_epoch:
            voice.source.close()
            session.done.set()
            return
        with _active_lock:
            _active_sessions.append(session)
        mixer.add(voice)
    if not threaded:
        session.done.wait()

def play_to_named_channel(
    wav_file: str,
    target_name: str,
    *,
    gain_override: float | None = None,
    base_folder: Path | str | None = None,
    looping: bool = False,
    honor_shutdown: bool = True,
    honor_breakcheck: bool = True,
    threaded: bool = True,
) -> None:
    """Play a WAV on one configured mono or stereo named route."""
    path = _resolve_sound_path(wav_file, base_folder or DEFAULT_SOUND_DIR)
    if not path.exists():
        raise FileNotFoundError(path)
    gain = _resolve_named_target(target_name)[3] if gain_override is None else gain_override
    log_event(
        f"[Audio] Playing '{path.name}' -> {target_name}, gain={gain}, "
        f"looping={looping}, threaded={threaded}"
    )
    _submit(path, target_name, "one", 0, gain, looping, honor_shutdown, honor_breakcheck, threaded)


def _speak(text: str, name: str | None, gain: float, rate: int) -> None:
    """Prepare the mixer now, synthesize and submit speech in a worker."""
    kind: DeviceKind = "primary" if name is None else _resolve_named_target(name)[0]
    _mixer(kind)

    def run() -> None:
        path: Path | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(suffix=".wav")
            os.close(descriptor)
            path = Path(temporary_path)
            text_to_wav(text, path, rate)
            _submit(path, name, "all" if name is None else "one", 0, gain,
                    False, False, False, True, True)
        except Exception as error:
            log_event(f"[Audio] TTS failed: {error}")
        finally:
            if path is not None:
                # The voice owns decoded PCM; do not retain temporary speech
                # assets in the reusable short-clip cache.
                global _cache_bytes
                with _cache_lock:
                    for key in [key for key in _cache if key[0] == str(path.resolve())]:
                        _cache_bytes -= _cache.pop(key).nbytes
                path.unlink(missing_ok=True)

    threading.Thread(target=run, name="AudioTTS", daemon=True).start()


def play_to_all_channels(
    wav_or_text: str,
    *,
    tts_rate: int = 0,
    gain_override: float | None = None,
    base_folder: Path | str | None = None,
    looping: bool = False,
    honor_shutdown: bool = True,
    honor_breakcheck: bool = True,
    threaded: bool = True,
) -> None:
    """Play a WAV, or speak text, on every channel of the primary output."""
    base = Path(base_folder) if base_folder else DEFAULT_SOUND_DIR
    path = _resolve_sound_path(wav_or_text, base)
    gain = 1 if gain_override is None else gain_override
    if Path(wav_or_text).suffix.lower() == ".wav" or path.exists():
        if not path.exists():
            raise FileNotFoundError(path)
        _submit(path, None, "all", 0, gain, looping, honor_shutdown, honor_breakcheck, threaded)
        return

    _speak(wav_or_text, None, gain, tts_rate)


def play_audio(
    target_or_text: str,
    maybe_file: str | None = None,
    *,
    gain: float | None = None,
    base_folder: Path | str | None = None,
    tts_rate: int = 0,
    looping: bool = False,
    threaded: bool = True,
) -> None:
    """Convenience API for room audio and text-to-speech.

    ``play_audio("Room_1", "hit.wav")`` routes a WAV to the named room.
    ``play_audio("all", "hit.wav")`` broadcasts a WAV on the primary output.
    ``play_audio("Room_1: Welcome")`` speaks on a named route, while bare
    text is spoken on every primary channel.  TTS is always non-blocking and
    intentionally ignores break/shutdown requests.
    """
    if maybe_file:
        if target_or_text.lower() == "all":
            play_to_all_channels(
                maybe_file,
                gain_override=gain,
                base_folder=base_folder,
                looping=looping,
                threaded=threaded,
            )
            return
        play_to_named_channel(
            maybe_file,
            target_or_text,
            gain_override=gain,
            base_folder=base_folder,
            looping=looping,
            threaded=threaded,
        )
        return

    if ":" in target_or_text:
        name, text = (value.strip() for value in target_or_text.split(":", 1))
        try:
            _resolve_named_target(name)
        except ValueError:
            pass
        else:
            default_gain = _resolve_named_target(name)[3]
            _speak(text, name, default_gain if gain is None else gain, tts_rate)
            return

    play_to_all_channels(
        target_or_text,
        tts_rate=tts_rate,
        gain_override=gain,
        base_folder=base_folder,
        honor_shutdown=False,
        honor_breakcheck=False,
        threaded=True,
    )


def _break_monitor() -> None:
    while True:
        try:
            # BreakCheck() logs every failed check. This daemon has the same
            # condition but avoids flooding the log while the house is offline.
            if not house.HouseActive or house.systemState != "ONLINE":
                for mixer in tuple(_mixers.values()):
                    mixer.stop_matching(lambda voice: voice.honor_breakcheck)
        except Exception as error:
            log_event(f"[Audio] BreakCheck monitor error: {error}")
        time.sleep(0.05)


threading.Thread(target=_break_monitor, name="AudioBreakCheck", daemon=True).start()


def stop_all_audio(timeout: float = 2.0) -> None:
    """Stop active file audio while allowing TTS to finish naturally."""
    global _cutoff_epoch
    with _epoch_lock:
        _cutoff_epoch = _play_epoch
        cutoff = _cutoff_epoch
        waiting = [
            voice.session
            for mixer in tuple(_mixers.values())
            for voice in tuple(mixer.voices)
            if voice.honor_shutdown and voice.session.epoch <= cutoff
        ]
        for mixer in tuple(_mixers.values()):
            mixer.stop_matching(lambda voice: voice.honor_shutdown and voice.session.epoch <= cutoff)
    log_event(f"[Audio] stop_all_audio(): cutoff={_cutoff_epoch}")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _active_lock:
            _active_sessions[:] = [session for session in _active_sessions if not session.done.is_set()]
            pending = any(not session.done.is_set() for session in waiting)
        if not pending:
            break
        time.sleep(0.01)
    _stop_event.clear()
    log_event("[Audio] stop_all_audio(): complete")


def list_output_devices() -> list[str]:
    """Return the selectable PortAudio output devices for configuration."""
    devices = cast(list[Mapping[str, Any]], sd.query_devices())
    return [
        f"[{index}] {device['name']} ({device['max_output_channels']}ch)"
        for index, device in enumerate(devices)
        if device.get("max_output_channels", 0) > 0
    ]


def list_named_channels() -> dict[str, NamedChannelInfo]:
    """Return configured channel names, output indexes, gains, and device kind."""
    result: dict[str, NamedChannelInfo] = {}
    for key, value in primary_channels.items():
        result[key] = {"index": value["index"], "gain": value["gain"], "device": "primary"}
    for key, value in secondary_channels.items():
        result[key] = {"index": value["index"], "gain": value["gain"], "device": "secondary"}
    return result


def register_primary_channel(name: str, index: ChannelIndex, gain: float = 1.0) -> None:
    """Add or replace a primary-device route at runtime."""
    if name in secondary_channels:
        raise ValueError(f"'{name}' exists in secondary_channels")
    primary_channels[name] = {"index": index, "gain": gain}


def register_secondary_channel(name: str, index: ChannelIndex, gain: float = 1.0) -> None:
    """Add or replace a secondary-device route at runtime."""
    if name in primary_channels:
        raise ValueError(f"'{name}' exists in primary_channels")
    secondary_channels[name] = {"index": index, "gain": gain}


def set_channel_gain(name: str, gain: float) -> None:
    """Change a configured route's gain at runtime."""
    if name in primary_channels:
        primary_channels[name]["gain"] = gain
        return
    if name in secondary_channels:
        secondary_channels[name]["gain"] = gain
        return
    raise ValueError(f"Unknown channel '{name}'.")


def audio_diagnostics() -> dict[DeviceKind, dict[str, object]]:
    """Return health and voice-count data for each opened persistent mixer."""
    return {kind: mixer.diagnostics() for kind, mixer in _mixers.items()}
