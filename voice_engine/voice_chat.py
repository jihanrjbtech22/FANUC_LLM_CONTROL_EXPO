"""
Voice-enabled chat interface with Whisper transcription.
Combines text and voice input modes.
"""

import subprocess
import sys
import json
import os
import argparse
from pathlib import Path
from typing import Optional

try:
    from voice_input import VoiceInput
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

# ANSI colors
WHITE = "\033[97m"
CRX_GREEN = "\033[38;2;0;255;102m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

# Paths
ENGINE_DIR = Path(__file__).parent.parent / "LLM_engine"


def parse_llm_payload(raw_content: str) -> dict:
    return json.loads(raw_content)


def send_to_handler(payload: dict) -> None:
    handler_pipe = Path(__file__).parent.parent / "Robot_handler" / "robot_handler.pipe"

    if not handler_pipe.exists():
        print(
            f"{RED}[Handler] Live terminal not running. Start: python3 Robot_handler/robot_handler.py --watch{RESET}"
        )
        return

    try:
        fd = os.open(handler_pipe, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        print(
            f"{RED}[Handler] Live terminal not connected. Start: python3 Robot_handler/robot_handler.py --watch{RESET}"
        )
        return

    try:
        with os.fdopen(fd, "w") as pipe:
            pipe.write(json.dumps(payload) + "\n")
            pipe.flush()
    except BrokenPipeError:
        print(f"{RED}[Handler] The live handler disconnected. Restart it in another terminal.{RESET}")


def parse_args():
    parser = argparse.ArgumentParser(description="Voice-enabled FANUC chat interface")
    parser.add_argument("--voice-model", default="tiny", help="faster-whisper model size")
    parser.add_argument("--silence-threshold", type=float, default=0.010, help="Amplitude threshold for silence detection")
    parser.add_argument("--silence-duration", type=float, default=0.5, help="Seconds of silence before transcription")
    parser.add_argument("--min-duration", type=float, default=0.3, help="Minimum audio duration before transcription")
    parser.add_argument("--min-transcript-chars", type=int, default=4, help="Minimum transcript length accepted")
    parser.add_argument("--amplitude-accept-threshold", type=float, default=0.015, help="Minimum RMS amplitude accepted")
    parser.add_argument("--confidence-logprob-threshold", type=float, default=-0.9, help="Minimum avg_logprob accepted")
    parser.add_argument("--use-wake-word", action="store_true", help="Enable wake word mode if Picovoice key is configured")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"\n{CRX_GREEN}{'='*60}")
    print("FANUC CRX Order Fulfillment - Voice Chat Interface")
    print(f"{'='*60}{RESET}\n")

    # Check voice availability
    if not VOICE_AVAILABLE:
        print(f"{RED}[ERROR] voice_input module not found{RESET}")
        sys.exit(1)

    # Ask for input mode
    print(f"{YELLOW}Choose input mode:{RESET}")
    print("1. Voice (Whisper) - speak your orders")
    print("2. Text - type your orders")
    mode = input("Enter choice (1 or 2): ").strip()

    if mode == "1":
        use_voice = True
        print(f"\n{BLUE}[VOICE] Initializing Whisper...{RESET}")
        try:
            voice_input = VoiceInput(
                model=args.voice_model,
                use_wake_word=args.use_wake_word,
                silence_threshold=args.silence_threshold,
                silence_duration=args.silence_duration,
                min_duration=args.min_duration,
                min_transcript_chars=args.min_transcript_chars,
                amplitude_accept_threshold=args.amplitude_accept_threshold,
                confidence_logprob_threshold=args.confidence_logprob_threshold,
            )
            voice_input.start()
        except Exception as e:
            print(f"{RED}[ERROR] Failed to start voice engine: {e}{RESET}")
            sys.exit(1)
    else:
        use_voice = False
        voice_input = None
        print(f"\n{YELLOW}[TEXT] Text mode selected{RESET}")

    # Start LLM engine
    print(f"\n{YELLOW}[CHAT] Starting LLM engine...{RESET}")
    engine_proc = subprocess.Popen(
        [sys.executable, "LLM_engine.py"],
        cwd=str(ENGINE_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    print(f"\n{CRX_GREEN}[READY] System ready. {YELLOW}Type 'exit' or Ctrl+C to quit{CRX_GREEN}.{RESET}\n")

    try:
        while True:
            # Get user input (voice or text)
            if use_voice:
                print(f"{YELLOW}[VOICE] Listening for your order...{RESET}")
                user_input = voice_input.get_text(timeout=None)
                if not user_input:
                    continue
                print(f"{WHITE}You (voice): {user_input}{RESET}")
            else:
                user_input = input(f"{WHITE}You: {RESET}").strip()
                if not user_input:
                    continue

            if user_input.lower() in {"exit", "quit"}:
                print("Goodbye!")
                break

            # Send to engine
            engine_proc.stdin.write(user_input + "\n")
            engine_proc.stdin.flush()

            # Get response
            output = engine_proc.stdout.readline().strip()
            if not output:
                stderr_output = engine_proc.stderr.readline().strip()
                if stderr_output:
                    print(f"{RED}[Engine] {stderr_output}{RESET}")
                continue

            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                print(f"{RED}[Malformed output] {output}{RESET}")
                continue

            if "error" in data:
                print(f"{RED}[Engine Error] {data['error']}{RESET}")
                continue

            content = data.get("content", "")
            try:
                payload = parse_llm_payload(content)
            except json.JSONDecodeError:
                print(f"{CRX_GREEN}CRX: {content}{RESET}\n")
                continue

            response = payload.get("response", "")
            cart = payload.get("cart", {})
            print(f"{CRX_GREEN}CRX: {response}{RESET}")
            print(f"{CRX_GREEN}Cart: {json.dumps(cart, indent=2)}{RESET}\n")
            send_to_handler(payload)

    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        if use_voice:
            voice_input.stop()
        try:
            engine_proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
