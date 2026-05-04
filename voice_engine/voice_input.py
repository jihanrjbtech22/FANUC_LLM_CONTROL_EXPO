"""
Voice input module using faster-whisper for fast speech-to-text transcription.
Includes wake word detection using Porcupine.
"""

from faster_whisper import WhisperModel
import sounddevice as sd
import numpy as np
import threading
import queue
from typing import Optional
import sys

try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except Exception:
    PORCUPINE_AVAILABLE = False

# ANSI colors
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"

# Audio parameters
SAMPLE_RATE = 16000  # 16kHz for Whisper
CHUNK_DURATION = 1  # seconds per chunk
DEFAULT_SILENCE_THRESHOLD = 0.010  # amplitude threshold for silence
DEFAULT_SILENCE_DURATION = 0.5  # seconds of silence to trigger transcription (faster)
DEFAULT_MIN_DURATION = 0.3  # minimum audio duration before transcribing
# Confidence filtering
DEFAULT_MIN_TRANSCRIPT_CHARS = 4  # minimum characters required to accept a transcript
DEFAULT_AMPLITUDE_ACCEPT_THRESHOLD = 0.015  # require some minimum signal amplitude to accept
DEFAULT_CONFIDENCE_LOGPROB_THRESHOLD = -0.9  # if model provides avg_logprob, require > this (higher is better)


class VoiceInput:
    def __init__(
        self,
        model: str = "tiny",
        use_wake_word: bool = True,
        silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
        silence_duration: float = DEFAULT_SILENCE_DURATION,
        min_duration: float = DEFAULT_MIN_DURATION,
        min_transcript_chars: int = DEFAULT_MIN_TRANSCRIPT_CHARS,
        amplitude_accept_threshold: float = DEFAULT_AMPLITUDE_ACCEPT_THRESHOLD,
        confidence_logprob_threshold: float = DEFAULT_CONFIDENCE_LOGPROB_THRESHOLD,
    ):
        """
        Initialize voice input with faster-whisper and optional wake word.

        Args:
            model: Whisper model size (tiny, base, small, medium, large)
            use_wake_word: Enable wake word detection (requires pvporcupine)
        """
        self.model = model
        self.whisper_model = None
        self.porcupine = None
        self.use_wake_word = use_wake_word and PORCUPINE_AVAILABLE
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.min_duration = min_duration
        self.min_transcript_chars = min_transcript_chars
        self.amplitude_accept_threshold = amplitude_accept_threshold
        self.confidence_logprob_threshold = confidence_logprob_threshold
        self.is_listening = False
        self.audio_queue = queue.Queue()
        self.transcript_queue = queue.Queue()
        self.recording_thread = None
        self.transcription_thread = None
        self.wake_word_detected = False

        print(f"{BLUE}[VOICE] Loading faster-whisper model: {model}...{RESET}", flush=True)
        try:
            self.whisper_model = WhisperModel(model, device="cpu", compute_type="int8")
            print(f"{GREEN}[VOICE] Whisper model loaded (int8 quantized - fast!){RESET}", flush=True)
        except Exception as e:
            print(f"{RED}[VOICE] Failed to load Whisper model: {e}{RESET}", flush=True)
            raise

        # Initialize wake word detection
        if self.use_wake_word:
            print(f"{BLUE}[VOICE] Initializing wake word detection...{RESET}", flush=True)
            try:
                # Porcupine free tier requires obtaining an access key from console.picovoice.ai
                # For now, fall back to silence-based detection
                print(f"{YELLOW}[VOICE] Wake word detection disabled (requires free Picovoice key){RESET}", flush=True)
                self.use_wake_word = False
            except Exception as e:
                print(f"{RED}[VOICE] Wake word init failed: {e}{RESET}", flush=True)
                self.porcupine = None
                self.use_wake_word = False

    def _detect_wake_word(self, audio_chunk: np.ndarray) -> bool:
        """Check if wake word is detected in audio chunk."""
        if not self.porcupine:
            return True

        try:
            # Convert to int16 for porcupine
            audio_int16 = (audio_chunk * 32767).astype(np.int16)
            keywords_detected = self.porcupine.process(audio_int16)
            return len(keywords_detected) > 0
        except Exception:
            return False

    def _record_audio(self):
        """Record audio from microphone in chunks."""
        if self.use_wake_word:
            print(f"{YELLOW}[VOICE] Listening for wake word 'jarvis'...{RESET}", flush=True)
        else:
            print(f"{YELLOW}[VOICE] Listening...{RESET}", flush=True)

        silence_count = 0
        audio_buffer = np.array([])
        wake_word_found = False

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                blocksize=int(SAMPLE_RATE * CHUNK_DURATION),
                dtype=np.float32,
            ) as stream:
                while self.is_listening:
                    data, _ = stream.read(int(SAMPLE_RATE * CHUNK_DURATION))
                    data = data.flatten()

                    # If using wake word, check for it first
                    if self.use_wake_word and not wake_word_found:
                        if self._detect_wake_word(data):
                            print(f"{GREEN}[VOICE] Wake word detected! Recording...{RESET}", flush=True)
                            wake_word_found = True
                            audio_buffer = np.array([])
                            silence_count = 0
                        continue

                    # Check for silence
                    amplitude = np.abs(data).mean()
                    if amplitude < self.silence_threshold:
                        silence_count += 1
                    else:
                        silence_count = 0

                    # Accumulate audio
                    audio_buffer = np.concatenate([audio_buffer, data])

                    # If we have silence after recording, send to queue
                    if (
                        silence_count > (self.silence_duration / CHUNK_DURATION)
                        and len(audio_buffer) > int(SAMPLE_RATE * self.min_duration)
                    ):
                        self.audio_queue.put(audio_buffer.copy())
                        audio_buffer = np.array([])
                        silence_count = 0
                        wake_word_found = False

        except Exception as e:
            print(f"{RED}[VOICE] Recording error: {e}{RESET}", flush=True)

    def _transcribe_audio(self):
        """Transcribe audio using faster-whisper."""
        while self.is_listening:
            try:
                audio_data = self.audio_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                # Keep the raw RMS for tuning, then normalize for transcription.
                audio_data = audio_data.astype(np.float32)
                raw_rms = float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size > 0 else 0.0
                max_val = np.max(np.abs(audio_data))
                if max_val > 0:
                    audio_data = audio_data / max_val

                # Use faster-whisper's transcribe
                segments, info = self.whisper_model.transcribe(
                    audio_data, language="en", beam_size=1
                )
                
                text = " ".join([segment.text for segment in segments]).strip()

                # Try to compute confidence from model if available
                confs = []
                for segment in segments:
                    # faster-whisper may provide avg_logprob on segment objects
                    seg_conf = None
                    if hasattr(segment, "avg_logprob"):
                        try:
                            seg_conf = float(getattr(segment, "avg_logprob"))
                        except Exception:
                            seg_conf = None
                    # Some implementations put scores in segment.no_speech_prob
                    if seg_conf is None and hasattr(segment, "no_speech_prob"):
                        try:
                            # no_speech_prob: lower means more speech; invert to be comparable
                            seg_conf = -float(getattr(segment, "no_speech_prob"))
                        except Exception:
                            seg_conf = None
                    if seg_conf is not None:
                        confs.append(seg_conf)

                mean_conf = None
                if len(confs) > 0:
                    mean_conf = sum(confs) / len(confs)

                # Additional info-level check (some transcribers return no_speech_prob)
                info_no_speech = None
                try:
                    if isinstance(info, dict) and "no_speech_prob" in info:
                        info_no_speech = float(info.get("no_speech_prob"))
                except Exception:
                    info_no_speech = None

                # Amplitude check uses the raw, pre-normalized signal so tuning is meaningful.
                rms = raw_rms

                accept = True
                reason = []

                # Reject very short / empty transcriptions
                if not text or len(text) < self.min_transcript_chars:
                    accept = False
                    reason.append("too short")

                # Require some signal amplitude
                if rms < self.amplitude_accept_threshold:
                    accept = False
                    reason.append("low amplitude")

                # If model provided mean_logprob, require it be above threshold
                if mean_conf is not None:
                    if mean_conf < self.confidence_logprob_threshold:
                        accept = False
                        reason.append(f"low model confidence ({mean_conf:.2f})")

                # If info-level no_speech_prob exists, reject when it's high
                if info_no_speech is not None:
                    if info_no_speech > 0.6:
                        accept = False
                        reason.append(f"no_speech_prob {info_no_speech:.2f}")

                if accept:
                    print(f"{GREEN}[VOICE] Transcribed: {text}{RESET}", flush=True)
                    self.transcript_queue.put(text)
                        
            except Exception as e:
                print(f"{RED}[VOICE] Transcription error: {e}{RESET}", flush=True)

    def start(self):
        """Start listening for voice input."""
        if self.is_listening:
            return

        self.is_listening = True

        # Start recording thread
        self.recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.recording_thread.start()

        # Start transcription thread
        self.transcription_thread = threading.Thread(
            target=self._transcribe_audio, daemon=True
        )
        self.transcription_thread.start()

        print(f"{GREEN}[VOICE] Voice engine started{RESET}", flush=True)

    def stop(self):
        """Stop listening for voice input."""
        self.is_listening = False
        if self.recording_thread:
            self.recording_thread.join(timeout=2)
        if self.transcription_thread:
            self.transcription_thread.join(timeout=2)
        if self.porcupine:
            self.porcupine.delete()
        print(f"{BLUE}[VOICE] Voice engine stopped{RESET}", flush=True)

    def get_text(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Get transcribed text from queue.

        Args:
            timeout: Timeout in seconds (None = wait forever)

        Returns:
            Transcribed text or None if timeout
        """
        try:
            return self.transcript_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def __del__(self):
        """Cleanup on deletion."""
        self.stop()
