# FANUC CRX Order Fulfillment System

An LLM-powered order tending interface for FANUC CRX robots. Natural language chat control with real-time register writes via OPC UA.

## Quick Start

### Prerequisites
- Python 3.8+
- Ollama (install from https://ollama.com)
- FANUC robot with OPC UA support (optional; simulator mode available)

### Setup

1. **Clone and navigate:**
   ```bash
   git clone https://github.com/JIHANRJ/FANUC_LLM_Control2.git
   cd FANUC_Control2
   ```

2. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install ollama opcua
   ```

4. **Pull the LLM model:**
   ```bash
   ollama pull llama3
   ```

5. **Start Ollama server (in another terminal):**
   ```bash
   ollama serve
   ```

## Running

### Master Terminal Chat (unified interface)

```bash
python3 master_terminal_chat.py
```

This starts both the robot handler and chat interface together.

To launch the voice interface from the master script, use:

```bash
python3 master_terminal_chat.py --voice --voice-model tiny
```

You can also tune speech filtering from the same command line:

```bash
python3 master_terminal_chat.py --voice --silence-threshold 0.08 --confidence-logprob-threshold -0.7
```

**Options:**
- Robot is pre-configured to `172.168.10.2:4880`
- Edit `master_terminal_chat.py` to change robot IP/port
- Runs in simulator mode if robot is unreachable

### Voice Chat (faster-whisper optimized)

```bash
python3 voice_engine/voice_chat.py
```

Choose mode `1` for voice input. Features:
- **Fast transcription** — faster-whisper with int8 quantization (~1 sec/transcription on M1/M2)
- **Continuous listening** — Microphone active in background
- **Silence detection** — Automatically sends audio when silence detected
- **Multi-language** — English by default (configurable)

Example:
```
[VOICE] Listening for voice...
You: "I want three coffees and two croissants"
[VOICE] Transcribed: I want three coffees and two croissants
CRX: Order confirmed! [JSON response with register writes]
```

### Advanced: Separate Terminals

**Terminal 1 - Robot Handler (watches for register writes):**
```bash
python3 Robot_handler/robot_handler.py --watch --robot-ip 172.168.10.2
```

**Terminal 2 - Chat Interface:**
```bash
cd LLM_engine
python3 chat.py
```

## Usage

1. Type orders in natural language:
   ```
   You: I want 2 chocolates and 5 pringles
   CRX: Order confirmed! [JSON response with register writes]
   ```

2. All register writes appear in red debug output in the handler terminal
3. Type `exit` to quit

## Architecture

- **LLM Engine** (`LLM_engine/`) - Llama3 chat with strict JSON output
- **Robot Handler** (`Robot_handler/`) - Computes deltas, writes FANUC registers via OPC UA
- **Master Terminal** (`master_terminal_chat.py`) - Orchestrates both components

## Configuration

Edit `LLM_engine/precontext.txt` to customize:
- Robot personality
- Item descriptions
- System behavior

## Files

- `master_terminal_chat.py` — Main entry point
- `LLM_engine/LLM_engine.py` — LLM backend with strict JSON schema
- `LLM_engine/chat.py` — Terminal interface
- `Robot_handler/robot_handler.py` — Register handler and OPC UA client
- `Robot_handler/fanuc_register_opcua.py` — FANUC OPC UA library
- `Robot_handler/current_cart.json` — Current order state
- `voice_engine/voice_input.py` — faster-whisper speech-to-text with silence detection
- `voice_engine/voice_chat.py` — Voice-enabled chat interface
- `test_voice_integration.py` — Integration test for voice engine

## Voice Engine

The voice engine uses **faster-whisper** (OpenAI Whisper optimized for speed) with int8 quantization for M1/M2 Macs.

### Performance

- **Tiny model** — ~1 sec transcription time (39MB)
- **Base model** — ~2 sec transcription time, better accuracy (140MB)
- **5-10x faster** than openai-whisper on ARM64

### Features

- Continuous microphone listening with silence-based triggers
- Float32 audio input at 16kHz sample rate
- Automatic amplitude threshold detection
- Low-latency transcription (< 2 seconds typical)
- No internet required (fully offline)

### Testing

```bash
# Integration test
python3 test_voice_integration.py

# Run voice chat
python3 voice_engine/voice_chat.py
```

See [voice_engine/README.md](voice_engine/README.md) for detailed documentation.
