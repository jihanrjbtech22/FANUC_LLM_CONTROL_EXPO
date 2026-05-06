# FANUC LLM Control

LLM-powered ordering and robot control for a FANUC CRX workflow. The system turns natural language orders into JSON cart updates, forwards them through a FIFO pipe, and writes FANUC registers through OPC UA.

## What is in this repo

- `master_terminal_chat.py` - main orchestrator for text, voice, and frontend runs
- `fanuc_frontend_backend.py` - WebSocket backend for the browser frontend
- `LLM_engine/LLM_engine.py` - Ollama-backed JSON response generator
- `LLM_engine/chat.py` - standalone text chat wrapper for the LLM engine
- `Robot_handler/robot_handler.py` - FIFO consumer and FANUC register writer
- `voice_engine/voice_chat.py` - voice/text chat wrapper around the LLM engine
- `voice_engine/voice_tuner.py` - microphone threshold tuning helper
- `test_voice_integration.py` - voice dependency and model smoke test

## Requirements

- Python 3.10 or newer
- Ollama installed and running
- A pulled Ollama model, such as `llama3`
- Optional: FANUC robot with OPC UA enabled

Install the Python dependencies from [requirements.txt](requirements.txt):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start Ollama in another terminal before running the chat flows:

```bash
ollama serve
ollama pull llama3
```

## Setup Notes

- The default robot target is `172.168.10.2:4880`
- The cart state is stored in `Robot_handler/current_cart.json`
- The robot handler listens on `Robot_handler/robot_handler.pipe`
- If the robot is unreachable, the code falls back to simulator behavior in some entry points

## Recommended Run Modes

### 1. Unified master terminal

This is the easiest way to run the system. It starts the handler and the chosen chat mode.

Text mode:

```bash
python3 master_terminal_chat.py
```

Voice mode:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny
```

Frontend mode:

```bash
python3 master_terminal_chat.py --frontend
```

Voice plus frontend:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny --frontend
```

### 2. Standalone chat wrapper

Text chat only:

```bash
python3 LLM_engine/chat.py
```

Voice/text chat:

```bash
python3 voice_engine/voice_chat.py
```

### 3. Robot handler only

Use this when another process is already generating JSON payloads and you only want to consume FIFO updates.

```bash
python3 Robot_handler/robot_handler.py --watch --robot-ip 172.168.10.2 --robot-port 4880
```

### 4. Frontend backend only

Use this to run the browser backend separately from the master script.

```bash
python3 fanuc_frontend_backend.py --host 127.0.0.1 --port 9876 --auto-start
```

## Command Line Parameters

### `master_terminal_chat.py`

- `--voice` - launch the voice chat flow instead of text chat
- `--voice-model` - faster-whisper model size, default: `tiny`
- `--silence-threshold` - amplitude threshold used for silence detection
- `--silence-duration` - seconds of silence before sending audio
- `--min-duration` - minimum audio duration before transcription
- `--min-transcript-chars` - minimum transcript length accepted
- `--amplitude-accept-threshold` - minimum RMS amplitude accepted
- `--confidence-logprob-threshold` - minimum average log probability accepted
- `--use-wake-word` - enable wake-word mode if configured
- `--frontend` - launch the browser frontend stack
- `--frontend-host` - bind host for the frontend/backend, default: `127.0.0.1`
- `--frontend-port` - HTTP port for the static frontend, default: `5173`
- `--backend-port` - WebSocket port for the frontend backend, default: `9876`

Examples:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny
python3 master_terminal_chat.py --voice --silence-threshold 0.010 --amplitude-accept-threshold 0.015 --min-transcript-chars 4
python3 master_terminal_chat.py --frontend --frontend-port 5173 --backend-port 9876
```

### `fanuc_frontend_backend.py`

- `--host` - bind host, default: `127.0.0.1`
- `--port` - WebSocket port, default: `9876`
- `--robot-ip` - FANUC robot IP, default: `172.168.10.2`
- `--robot-port` - FANUC OPC UA port, default: `4880`
- `--auto-start` - start the handler and LLM immediately

### `Robot_handler/robot_handler.py`

- `--watch` - read JSON lines from `robot_handler.pipe`
- `--robot-ip` - connect to a FANUC robot by IP
- `--robot-port` - OPC UA port, default: `4880`
- `--pipe` - FIFO path, default: `Robot_handler/robot_handler.pipe`
- `--cart` - cart file path, default: `Robot_handler/current_cart.json`

### `voice_engine/voice_chat.py`

- `--voice-model` - faster-whisper model size, default: `tiny`
- `--silence-threshold` - silence detector threshold
- `--silence-duration` - silence window before transcription
- `--min-duration` - minimum audio length before transcription
- `--min-transcript-chars` - minimum transcript length accepted
- `--amplitude-accept-threshold` - minimum RMS amplitude accepted
- `--confidence-logprob-threshold` - minimum average log probability accepted
- `--use-wake-word` - enable wake-word mode if configured

### `voice_engine/voice_tuner.py`

- `--model` - faster-whisper model to test, default: `tiny`
- `--sample-rate` - audio sample rate, default: `16000`
- `--noise-seconds` - ambient noise recording length, default: `3.0`
- `--speech-seconds` - speech recording length, default: `4.0`
- `--device` - microphone device index or name
- `--compute-type` - Whisper compute type, default: `int8`
- `--language` - transcription language, default: `en`
- `--save-wav` - save captured samples as `.npy` files

## Typical Workflow

1. Start Ollama:

   ```bash
   ollama serve
   ```

2. Start the master script:

   ```bash
   python3 master_terminal_chat.py --frontend
   ```

3. Enter a natural language order in the terminal or browser UI.

4. The LLM emits a JSON payload, the handler receives it through the FIFO pipe, and the robot registers are written.

## Voice Setup and Testing

If you want to use voice input, install the extra audio packages from `requirements.txt`, then run:

```bash
python3 test_voice_integration.py
python3 voice_engine/voice_tuner.py
python3 master_terminal_chat.py --voice --voice-model tiny
```

The voice engine uses `faster-whisper` with a CPU-friendly `int8` configuration by default.

## Configuration Files

- `LLM_engine/precontext.txt` - system prompt and item behavior
- `Robot_handler/current_cart.json` - persisted cart state
- `Robot_handler/robot_handler.pipe` - FIFO transport between the UI/LLM and handler

## Troubleshooting

- If Ollama is not running, the LLM engine will fail to start.
- If the handler says the robot is disconnected, verify the robot IP, OPC UA port, and network reachability.
- If the frontend does not connect, check the `--host`, `--port`, and `--backend-port` values.
- If the voice engine is too sensitive or too strict, use `voice_tuner.py` and apply the suggested thresholds.

## More Details

See [voice_engine/README.md](voice_engine/README.md) for the voice subsystem documentation.
