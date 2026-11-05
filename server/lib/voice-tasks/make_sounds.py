#!/usr/bin/env python3
"""Synthesise the "Claude is working" sound pool (own work, CC0). Writes 20 s loopable clips:
   make_sounds.py OUTDIR   -> OUTDIR/<category>-<name>.ogg, loudness-normalised with ffmpeg.
Categories (used by the agent to match the task): typing, paper, ui, scifi, chime, lofi, pad.
"""
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

SR, DUR = 48000, 20.0
N = int(SR * DUR)
T = np.arange(N) / SR
rng = np.random.default_rng(7)


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # one-pole; fine for 20 s clips
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def highpass(x, cutoff):
    return x - lowpass(x, cutoff)


def env(n, attack, decay):
    a = max(1, int(attack * SR))
    e = np.exp(-np.arange(n) / (decay * SR))
    e[:a] *= np.linspace(0, 1, a)
    return e


def place(buf, sig, at):
    i = int(at * SR) % N
    end = min(N, i + len(sig))
    buf[i:end] += sig[: end - i]
    if i + len(sig) > N:  # wrap around so the loop is seamless
        buf[: i + len(sig) - N] += sig[end - i:]


def bell(freq, dur=1.6, bright=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t * 6)
    return s * env(n, 0.004, dur / 4)


def blip(freq, dur=0.09):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * freq * t) * env(n, 0.003, dur / 3)


def key_click():
    n = int(rng.uniform(0.012, 0.03) * SR)
    burst = rng.standard_normal(n) * env(n, 0.0005, 0.006)
    thock = np.sin(2 * np.pi * rng.uniform(180, 320) * np.arange(n) / SR) * env(n, 0.001, 0.01) * 0.6
    return highpass(burst, 1500) * 0.8 + thock


# ---------- clips ----------
def typing(seed):
    r = np.random.default_rng(seed)
    out, t = np.zeros(N), 0.0
    while t < DUR - 0.05:
        place(out, key_click() * r.uniform(0.5, 1.0), t)
        t += r.uniform(0.07, 0.2) if r.random() > 0.08 else r.uniform(0.35, 0.8)
    return out


def scribble():
    noise = lowpass(highpass(rng.standard_normal(N), 900), 4000)
    amp, t = np.zeros(N), 0.0
    while t < DUR:
        d = rng.uniform(0.15, 0.6)
        i, j = int(t * SR), min(N, int((t + d) * SR))
        amp[i:j] = np.sin(np.linspace(0, np.pi, j - i)) * (0.6 + 0.4 * np.sin(np.linspace(0, 18 * np.pi, j - i)) ** 2)
        t += d + rng.uniform(0.05, 0.5)
    return noise * amp


def paper():
    out = np.zeros(N)
    for t in np.arange(0.3, DUR, 2.2):
        n = int(rng.uniform(0.25, 0.5) * SR)
        place(out, lowpass(rng.standard_normal(n), 2500) * np.sin(np.linspace(0, np.pi, n)) ** 0.5, t + rng.uniform(0, 0.8))
    return out


def ui_hum():
    return (np.sin(2 * np.pi * 110 * T) + 0.5 * np.sin(2 * np.pi * 220 * T) + 0.2 * np.sin(2 * np.pi * 330.5 * T)) \
        * (0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * T))


def ui_pulse():
    out = np.zeros(N)
    for k, t in enumerate(np.arange(0, DUR, 1.25)):
        place(out, blip([880, 1046.5, 987.8, 1174.7][k % 4], 0.25), t)
    return out + 0.15 * ui_hum()


def scifi_processing(seed, scale):
    r = np.random.default_rng(seed)
    out = np.zeros(N)
    for t in np.arange(0, DUR, 0.125):
        if r.random() < 0.7:
            place(out, blip(r.choice(scale)) * r.uniform(0.4, 1), t)
    delayed = np.roll(out, int(0.19 * SR)) * 0.4 + np.roll(out, int(0.38 * SR)) * 0.2
    return out + delayed + 0.1 * np.sin(2 * np.pi * 55 * T)


def scifi_scan():
    out = np.zeros(N)
    for t in np.arange(0, DUR, 2.5):
        n = int(1.2 * SR)
        tt = np.arange(n) / SR
        f = 300 + 900 * tt / 1.2
        place(out, np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.linspace(0, np.pi, n)) ** 2, t)
    return out + 0.3 * np.sin(2 * np.pi * 73.4 * T) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.2 * T))


def chimes(scale, step, seed):
    r = np.random.default_rng(seed)
    out = np.zeros(N)
    for k, t in enumerate(np.arange(0, DUR, step)):
        place(out, bell(scale[(k * 2 + r.integers(0, 2)) % len(scale)]) * r.uniform(0.6, 1), t)
    return out


def chimes_sparse():
    out, t = np.zeros(N), 0.2
    while t < DUR:
        place(out, bell(rng.choice([523.3, 659.3, 784.0, 880.0, 1046.5]), 2.5, 0.2), t)
        t += rng.uniform(1.4, 3.0)
    return out


def lofi(bpm, seed, chord):
    r = np.random.default_rng(seed)
    beat = 60 / bpm
    out = np.zeros(N)
    kick_n = int(0.25 * SR)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-kt * 25)) / SR) * env(kick_n, 0.002, 0.08)
    snare = lowpass(r.standard_normal(int(0.18 * SR)), 3500) * env(int(0.18 * SR), 0.001, 0.04)
    hat = highpass(r.standard_normal(int(0.05 * SR)), 6000) * env(int(0.05 * SR), 0.0005, 0.01)
    bars = int(DUR / (beat * 4))
    for b in range(bars):
        t0 = b * beat * 4
        for s in range(8):
            swing = 0.03 if s % 2 else 0
            place(out, hat * 0.25, t0 + s * beat / 2 + swing)
        place(out, kick, t0)
        place(out, kick * 0.8, t0 + beat * 2.5)
        place(out, snare * 0.5, t0 + beat)
        place(out, snare * 0.5, t0 + beat * 3)
    pad = sum(np.sin(2 * np.pi * f * T) for f in chord) / len(chord) * (0.5 + 0.5 * np.sin(2 * np.pi * T / (beat * 8)) ** 2)
    crackle = (r.random(N) > 0.9993) * r.uniform(-1, 1, N) * 0.5
    return out + 0.25 * lowpass(pad, 1200) + crackle


def pad(chord, lfo):
    s = sum(np.sin(2 * np.pi * f * T) + np.sin(2 * np.pi * f * 1.003 * T) for f in chord) / (2 * len(chord))
    return lowpass(s, 1500) * (0.6 + 0.4 * np.sin(2 * np.pi * lfo * T))


def drone():
    return lowpass(np.sin(2 * np.pi * 65.4 * T) + 0.5 * np.sin(2 * np.pi * 98.0 * T) + 0.15 * rng.standard_normal(N), 500) \
        * (0.7 + 0.3 * np.sin(2 * np.pi * 0.1 * T)) + 0.05 * np.sin(2 * np.pi * 1568 * T) * np.sin(2 * np.pi * 0.3 * T) ** 2


def clock():
    out = np.zeros(N)
    for k, t in enumerate(np.arange(0, DUR, 0.5)):
        place(out, blip(2200 if k % 2 else 1800, 0.02) * 0.6, t)
    return out


CLIPS = {
    "typing-quick": lambda: typing(1), "typing-slow": lambda: typing(2) * 0.9,
    "paper-pen-scribble": scribble, "paper-shuffle": paper, "paper-clock-tick": clock,
    "ui-hum": ui_hum, "ui-pulse": ui_pulse,
    "scifi-processing": lambda: scifi_processing(3, [1046.5, 1174.7, 1318.5, 1568.0, 1760.0]),
    "scifi-data": lambda: scifi_processing(4, [783.99, 880.0, 987.77, 1174.7, 1318.5, 1975.5]),
    "scifi-scan": scifi_scan,
    "chime-arpeggio-major": lambda: chimes([523.3, 587.3, 659.3, 784.0, 880.0, 1046.5], 0.5, 5),
    "chime-arpeggio-minor": lambda: chimes([440.0, 523.3, 587.3, 659.3, 784.0, 880.0], 0.75, 6),
    "chime-sparse": chimes_sparse,
    "lofi-beat-80": lambda: lofi(80, 8, [261.6, 329.6, 392.0, 493.9]),
    "lofi-beat-72": lambda: lofi(72, 9, [220.0, 261.6, 329.6, 392.0]),
    "pad-warm": lambda: pad([130.8, 164.8, 196.0, 246.9], 0.07),
    "pad-minor": lambda: pad([110.0, 130.8, 164.8, 220.0], 0.05),
    "pad-drone": drone,
}


def main() -> None:
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)
    only = set(sys.argv[2:])
    for name, fn in CLIPS.items():
        if only and name not in only:
            continue
        x = fn()
        x = x / (np.abs(x).max() + 1e-9) * 0.8
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            w = wave.open(f.name, "wb")
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
            w.writeframes((x * 32767).astype(np.int16).tobytes())
            w.close()
            dst = os.path.join(out_dir, name + ".ogg")
            # same loudness for every clip (-28 LUFS); the agent then plays them quietly
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", f.name, "-af", "loudnorm=I=-28:TP=-3:LRA=11",
                            "-ar", "48000", "-ac", "1", "-c:a", "libvorbis", "-q:a", "4", dst], check=True)
            os.unlink(f.name)
        print(name, flush=True)


if __name__ == "__main__":
    main()
