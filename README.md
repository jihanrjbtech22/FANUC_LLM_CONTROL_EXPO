# FANUC LLM Control

LLM-powered ordering and robot control for a FANUC CRX workflow. Natural language orders are turned into JSON cart updates, forwarded through a FIFO pipe, and written to FANUC registers through OPC UA.

## Quick Start

### 1. Install prerequisites

- Python 3.10 or newer
- Ollama installed locally
- A pulled Ollama model, such as `llama3:latest`
- Optional: FANUC robot with OPC UA enabled

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want a single bootstrap command, run `bash setup.sh` from the repository root.

For a guided install walkthrough, see [INSTALL.md](INSTALL.md).

### 3. Start Ollama

```bash
ollama serve
ollama pull llama3:latest
```

### 4. Run the system

The simplest entrypoint is the master script. It starts the robot handler and the selected chat mode.

The browser frontend is already included in `Fanuc-frontend/dist`, so a fresh checkout does not need an npm build step to run the UI.

```bash
python3 master_terminal_chat.py
```

For the browser UI with backend voice support:

```bash
python3 master_terminal_chat.py --frontend
```

For voice mode:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny
```

For voice plus browser UI:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny --frontend
```

## What’s In This Repo

- `master_terminal_chat.py` - main orchestrator for text, voice, and frontend runs
- `fanuc_frontend_backend.py` - WebSocket backend for the browser frontend
- `LLM_engine/LLM_engine.py` - Ollama-backed JSON response generator
- `LLM_engine/chat.py` - standalone text chat wrapper for the LLM engine
- `Robot_handler/robot_handler.py` - FIFO consumer and FANUC register writer
- `voice_engine/voice_chat.py` - voice/text chat wrapper around the LLM engine
- `voice_engine/voice_tuner.py` - microphone threshold tuning helper
- `test_voice_integration.py` - voice dependency and model smoke test

## How It Runs

1. `master_terminal_chat.py` starts the robot handler.
2. If `--frontend` is used, it also starts the WebSocket backend on port `9876` and serves the static frontend.
3. The LLM engine produces JSON cart updates.
4. The robot handler writes the cart state to `Robot_handler/current_cart.json` and forwards updates through the FIFO pipe.

## Voice Notes

- Voice input uses the Python Whisper backend through `faster-whisper` and `sounddevice`.
- The browser mic is disabled so the voice button does not depend on Firefox/browser SpeechRecognition.
- Wake-word mode is optional and may require additional setup depending on the current voice backend configuration.

See [voice_engine/README.md](voice_engine/README.md) for the voice subsystem details.

## Common Commands

Text chat only:

```bash
python3 LLM_engine/chat.py
```

Voice/text chat only:

```bash
python3 voice_engine/voice_chat.py
```

Robot handler only:

```bash
python3 Robot_handler/robot_handler.py --watch --robot-ip 172.168.10.2 --robot-port 4880
```

Frontend backend only:

```bash
python3 fanuc_frontend_backend.py --host 127.0.0.1 --port 9876 --auto-start
```

## Key Command-Line Flags

### `master_terminal_chat.py`

- `--voice` - launch the voice chat flow instead of text chat
- `--voice-model` - faster-whisper model size, default: `tiny`
- `--silence-threshold` - amplitude threshold used for silence detection
- `--silence-duration` - seconds of silence before sending audio
- `--min-duration` - minimum audio duration before transcription
- `--min-transcript-chars` - minimum transcript length accepted
- `--amplitude-accept-threshold` - minimum RMS amplitude accepted
- `--confidence-logprob-threshold` - minimum average log probability accepted
- `--use-wake-word` - enable wake-word mode if supported by the current backend
- `--frontend` - launch the browser frontend stack
- `--frontend-host` - bind host for the frontend/backend, default: `127.0.0.1`
- `--frontend-port` - HTTP port for the static frontend, default: `5173`
- `--backend-port` - WebSocket port for the frontend backend, default: `9876`

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

## First-Run Checklist

If you are pulling the code on a fresh machine, the minimum working path is:

1. Install Python 3.10+.
2. Create and activate `.venv`.
3. Install `requirements.txt`.
4. Start `ollama serve`.
5. Pull `llama3:latest`.
6. Run `python3 master_terminal_chat.py --frontend`.
7. Open the browser UI and verify the status shows `ONLINE` and `RUNNING`.

## Troubleshooting

- If Ollama is not running, the LLM engine will fail to start.
- If the frontend says `OFFLINE`, reload the page and confirm the backend process is still running.
- If the handler says the robot is disconnected, verify the robot IP, OPC UA port, and network reachability.
- If voice is not responding, confirm the voice button shows `VOICE ACTIVE` and that `faster-whisper` and `sounddevice` are installed.
