#!/usr/bin/env python3
"""
Voice tuning tool for faster-whisper-based input.

This utility records a short ambient-noise sample and a short speech sample,
then prints audio metrics, transcription confidence, and suggested threshold
values so you can tune voice filtering before anything reaches the LLM.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from voice_input import (
    SAMPLE_RATE,
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_SILENCE_DURATION,
    DEFAULT_MIN_DURATION,
    DEFAULT_MIN_TRANSCRIPT_CHARS,
    DEFAULT_AMPLITUDE_ACCEPT_THRESHOLD,
    DEFAULT_CONFIDENCE_LOGPROB_THRESHOLD,
)


BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


@dataclass
class AudioStats:
    mean_abs: float
    rms: float
    peak: float
    duration: float


@dataclass
class TranscriptStats:
    text: str
    avg_logprob: Optional[float]
    no_speech_prob: Optional[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune microphone thresholds for the FANUC voice engine")
    parser.add_argument("--model", default="tiny", help="faster-whisper model size to test")
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE, help="Recording sample rate")
    parser.add_argument("--noise-seconds", type=float, default=3.0, help="Ambient-noise capture length")
    parser.add_argument("--speech-seconds", type=float, default=4.0, help="Speech capture length")
    parser.add_argument("--device", default=None, help="Optional microphone device index/name")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type")
    parser.add_argument("--language", default="en", help="Transcription language")
    parser.add_argument("--save-wav", action="store_true", help="Save captured samples as .npy files for offline review")
    return parser.parse_args()


def record_audio(seconds: float, sample_rate: int, device: Optional[str] = None) -> np.ndarray:
    print(f"{YELLOW}[TUNER] Recording {seconds:.1f}s... keep quiet / speak when prompted{RESET}")
    frames = int(seconds * sample_rate)
    audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype=np.float32, device=device)
    sd.wait()
    return audio.flatten()


def compute_stats(audio: np.ndarray, sample_rate: int) -> AudioStats:
    if audio.size == 0:
        return AudioStats(mean_abs=0.0, rms=0.0, peak=0.0, duration=0.0)
    return AudioStats(
        mean_abs=float(np.mean(np.abs(audio))),
        rms=float(np.sqrt(np.mean(np.square(audio)))),
        peak=float(np.max(np.abs(audio))),
        duration=float(audio.size / sample_rate),
    )


def transcribe(model: WhisperModel, audio: np.ndarray, language: str) -> TranscriptStats:
    normalized = audio.astype(np.float32)
    max_val = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    if max_val > 0:
        normalized = normalized / max_val

    segments, info = model.transcribe(normalized, language=language, beam_size=1)
    text = " ".join(segment.text for segment in segments).strip()

    logprobs = []
    for segment in segments:
        if hasattr(segment, "avg_logprob"):
            try:
                logprobs.append(float(getattr(segment, "avg_logprob")))
            except Exception:
                pass

    avg_logprob = sum(logprobs) / len(logprobs) if logprobs else None
    no_speech_prob = None
    try:
        if hasattr(info, "no_speech_prob"):
            no_speech_prob = float(getattr(info, "no_speech_prob"))
    except Exception:
        no_speech_prob = None

    return TranscriptStats(text=text, avg_logprob=avg_logprob, no_speech_prob=no_speech_prob)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def recommend_thresholds(noise: AudioStats, speech: AudioStats, speech_tx: TranscriptStats) -> dict:
    silence_threshold = clamp(noise.mean_abs * 1.6, 0.01, 0.15)
    amplitude_accept = clamp(max(noise.rms * 2.5, noise.mean_abs * 3.0), 0.01, 0.2)

    if speech_tx.avg_logprob is not None:
        confidence_threshold = clamp(speech_tx.avg_logprob - 0.35, -2.5, -0.1)
    else:
        confidence_threshold = DEFAULT_CONFIDENCE_LOGPROB_THRESHOLD

    min_chars = DEFAULT_MIN_TRANSCRIPT_CHARS
    if len(speech_tx.text.split()) <= 1 and len(speech_tx.text) > 0:
        min_chars = max(DEFAULT_MIN_TRANSCRIPT_CHARS, 4)

    min_duration = clamp(max(DEFAULT_MIN_DURATION, speech.duration * 0.15), 0.2, 1.0)

    return {
        "silence_threshold": silence_threshold,
        "amplitude_accept_threshold": amplitude_accept,
        "confidence_logprob_threshold": confidence_threshold,
        "min_transcript_chars": min_chars,
        "min_duration": min_duration,
    }


def print_stats(label: str, stats: AudioStats) -> None:
    print(f"{BLUE}[TUNER] {label} stats{RESET}")
    print(f"  mean_abs: {stats.mean_abs:.6f}")
    print(f"  rms:      {stats.rms:.6f}")
    print(f"  peak:     {stats.peak:.6f}")
    print(f"  duration: {stats.duration:.2f}s")


def print_transcript_stats(label: str, stats: TranscriptStats) -> None:
    print(f"{BLUE}[TUNER] {label} transcription{RESET}")
    print(f"  text: {stats.text or '[empty]'}")
    print(f"  avg_logprob: {stats.avg_logprob if stats.avg_logprob is not None else '[n/a]'}")
    print(f"  no_speech_prob: {stats.no_speech_prob if stats.no_speech_prob is not None else '[n/a]'}")


def save_sample(name: str, audio: np.ndarray) -> None:
    out_path = Path(__file__).with_name(f"{name}.npy")
    np.save(out_path, audio)
    print(f"{YELLOW}[TUNER] Saved sample to {out_path}{RESET}")


def main() -> int:
    args = parse_args()

    print(f"\n{GREEN}{'='*60}")
    print("FANUC Voice Tuning Tool")
    print(f"{'='*60}{RESET}")
    print(f"Model: {args.model} | Sample rate: {args.sample_rate} Hz | Compute: {args.compute_type}")
    print("This tool only records locally and never sends audio to the LLM.\n")

    try:
        model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    except Exception as e:
        print(f"{RED}[TUNER] Failed to load Whisper model: {e}{RESET}")
        return 1

    input(f"{YELLOW}[TUNER] Press Enter to record ambient noise...{RESET}")
    noise_audio = record_audio(args.noise_seconds, args.sample_rate, args.device)
    noise_stats = compute_stats(noise_audio, args.sample_rate)

    input(f"{YELLOW}[TUNER] Press Enter and speak a normal command...{RESET}")
    speech_audio = record_audio(args.speech_seconds, args.sample_rate, args.device)
    speech_stats = compute_stats(speech_audio, args.sample_rate)
    speech_tx = transcribe(model, speech_audio, args.language)

    if args.save_wav:
        save_sample("voice_tuner_noise", noise_audio)
        save_sample("voice_tuner_speech", speech_audio)

    print()
    print_stats("Ambient noise", noise_stats)
    print_stats("Speech", speech_stats)
    print_transcript_stats("Speech", speech_tx)

    recommendations = recommend_thresholds(noise_stats, speech_stats, speech_tx)

    print(f"\n{GREEN}[TUNER] Suggested settings{RESET}")
    print(f"  silence_threshold: {recommendations['silence_threshold']:.3f}")
    print(f"  amplitude_accept_threshold: {recommendations['amplitude_accept_threshold']:.3f}")
    print(f"  confidence_logprob_threshold: {recommendations['confidence_logprob_threshold']:.3f}")
    print(f"  min_transcript_chars: {recommendations['min_transcript_chars']}")
    print(f"  min_duration: {recommendations['min_duration']:.2f}")

    if noise_stats.rms > 0 and speech_stats.rms / max(noise_stats.rms, 1e-9) < 2.5:
        print(f"\n{RED}[TUNER] Warning: speech is not much louder than noise. Consider a better mic or a quieter room.{RESET}")

    print(f"\n{BLUE}[TUNER] Try the suggested values in master_terminal_chat.py:{RESET}")
    print(
        f"python3 master_terminal_chat.py --voice --silence-threshold {recommendations['silence_threshold']:.3f} "
        f"--amplitude-accept-threshold {recommendations['amplitude_accept_threshold']:.3f} "
        f"--confidence-logprob-threshold {recommendations['confidence_logprob_threshold']:.3f} "
        f"--min-transcript-chars {recommendations['min_transcript_chars']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())