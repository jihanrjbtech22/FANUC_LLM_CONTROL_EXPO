# Voice Engine

Speech-to-text transcription using **faster-whisper** on the local machine. The voice stack listens on the microphone, transcribes speech locally, and forwards the resulting text to the chat pipeline.

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

- **Fast transcription** — Uses faster-whisper with the ctranslate2 backend
- **CPU-friendly defaults** — Uses the `int8` compute path by default
- **Real-time listening** — Listens continuously on the microphone
- **Auto-detection** — Detects speech automatically via amplitude threshold
- **Silence-based trigger** — Sends audio for transcription after silence is detected
- **Low latency** — The `tiny` model is the fastest option
- **Better accuracy** — Larger models improve accuracy at the cost of speed

## How It Works

1. Microphone listens continuously in a background thread
2. Audio chunks are buffered as they arrive (float32 format)
3. When silence is detected after speech, audio is sent to faster-whisper
4. Faster-whisper transcribes using the local ctranslate2 backend
5. Transcribed text is returned to chat
6. Chat sends the order to the handler and the robot registers are updated

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
- `sounddevice` - Microphone input
- `numpy` - Audio processing

## Wake Word Detection

Wake-word support depends on the current voice backend configuration. The default project setup runs without wake word, and the browser UI uses the Python voice engine rather than a browser microphone API.

If wake-word mode is enabled in code, it should be treated as an optional advanced setup, not part of the basic first-run path.

## Recommended First Test

Run the smoke test after installing dependencies:

```bash
python3 ../test_voice_integration.py
```

If that passes, start voice chat with:

```bash
python3 ../master_terminal_chat.py --voice --voice-model tiny
```
