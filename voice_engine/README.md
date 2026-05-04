# Voice Engine

Speech-to-text transcription using **faster-whisper** (optimized Whisper). Continuously listens for voice commands and transcribes them in real-time with high speed.

## Files

- **voice_input.py** — Core voice input handler with faster-whisper integration
- **voice_chat.py** — Voice-enabled chat interface
- **voice_tuner.py** — Interactive microphone tuning tool for noise/confidence filtering
- **__init__.py** — Package initialization

## Usage

### Voice Chat Only

```bash
cd voice_engine
python3 voice_chat.py
```

Choose mode `1` for voice input. The system will listen for speech, transcribe it with faster-whisper, and send it to the LLM.

### Tune Voice Filtering

```bash
cd voice_engine
python3 voice_tuner.py
```

The tuner records two samples locally:
- ambient noise
- a normal spoken command

It prints measured RMS/peak values, local transcription confidence, and a suggested command you can paste into `master_terminal_chat.py`.

## Features

- **🚀 Fast transcription** — Uses faster-whisper with ctranslate2 backend (5-10x faster than openai-whisper!)
- **Int8 quantization** — Optimized model quantization for M1/M2 Macs
- **Real-time listening** — Listens continuously on the microphone
- **Auto-detection** — Detects speech automatically via amplitude threshold
- **Silence-based trigger** — Sends audio for transcription after silence is detected (0.5s by default)
- **Low latency** — "tiny" model: ~1 sec per transcription on M1/M2
- **Better accuracy** — "base" model: ~2 sec per transcription, significantly more accurate

## How It Works

1. Microphone listens continuously in background thread
2. Audio chunks are buffered as they arrive (float32 format)
3. When 0.5+ second of silence is detected after speech, audio is sent to faster-whisper
4. Faster-whisper transcribes using ctranslate2 backend (optimized for ARM64)
5. Transcribed text is returned to chat
6. Chat sends order to handler → robot registers written

## Confidence Filtering

The engine applies several checks before sending text to the LLM to avoid random-noise transcripts:

- **Minimum text length:** short fragments are rejected (default 3 chars)
- **Amplitude check:** raw audio RMS must exceed a minimum threshold
- **Model confidence:** if the model exposes `avg_logprob`/`no_speech_prob`, the engine uses those scores to reject low-confidence transcriptions
- **Fallbacks:** when model scores are unavailable, amplitude + length checks are used

You can adjust thresholds from the command line via `master_terminal_chat.py --voice ...` or tune them interactively with `voice_tuner.py`.

## Performance

| Model | Speed (M1/M2) | Accuracy | Size |
|-------|---------------|----------|------|
| tiny  | ~1 sec        | Good     | 39M  |
| base  | ~2 sec        | Better   | 140M |

Faster-whisper with int8 quantization is **5-10x faster** than openai-whisper on ARM64!

## Customization

Edit **voice_input.py**:

```python
# Change Whisper model (bigger = more accurate, slower)
voice_input = VoiceInput(model="base", use_wake_word=False)

# Adjust silence detection
DEFAULT_SILENCE_THRESHOLD = 0.08  # amplitude threshold (higher = more sensitive)
DEFAULT_SILENCE_DURATION = 0.5    # seconds of silence before transcribe
DEFAULT_MIN_DURATION = 0.3        # minimum audio duration to transcribe
```

## Dependencies

- `faster-whisper` - Fast Whisper inference
- `ctranslate2` - ONNX backend for inference
- `onnxruntime` - ONNX runtime (ARM64 optimized)
- `sounddevice` - Microphone input
- `numpy` - Audio processing

## Wake Word Detection (Optional)

Wake word detection using Porcupine requires a free API key from [console.picovoice.ai](https://console.picovoice.ai). Currently disabled by default. To enable:

```python
# Get free access key from console.picovoice.ai
voice_input = VoiceInput(model="tiny", use_wake_word=True)
```

### Requirements

- `openai-whisper` — Speech-to-text model
- `sounddevice` — Microphone input
- `numpy` — Audio processing
- `torch` — Whisper dependency
