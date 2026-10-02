import sys
import time as t
from pathlib import Path

# Allow this utility to be launched directly from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control.audio_manager import list_named_channels, play_audio
from control.audio_manager import initialize_audio
from context import house


def testAudio(test_sound="waterWave01.wav", gain=1, announce_delay=2, sound_delay=3):
    # Standalone file playback must satisfy the same BreakCheck state as rooms.
    house.HouseActive = True
    house.systemState = "ONLINE"
    initialize_audio()
    channels = list_named_channels()

    for channel in channels:
        play_audio(f"{channel}: speaker {channel}")
        t.sleep(announce_delay)

        play_audio(channel, test_sound, gain=gain)
        t.sleep(sound_delay)


if __name__ == "__main__":
    testAudio()
