
import numpy as np
import sounddevice as sd

print(sd.query_devices())
device = int(input("Denon HDMI device index: "))

sample_rate = 48000
duration = 3
t = np.arange(sample_rate * duration) / sample_rate

audio = np.zeros((len(t), 8), dtype=np.float32)
audio[:, 3] = 0.15 * np.sin(2 * np.pi * 50 * t)

sd.play(audio, samplerate=sample_rate, device=device)
sd.wait()
