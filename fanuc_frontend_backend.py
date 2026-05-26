#!/usr/bin/env python3
"""
WebSocket bridge for Fanuc-frontend.

This gives the browser UI the same core behavior as master_terminal_chat.py:
start the robot handler, keep an LLM chat process alive, send cart updates to
the handler FIFO, and publish connection/cart state back to the UI.
"""

import argparse
import base64
import hashlib
import json
import os
import queue
import re
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

PROJECT_ROOT = Path(__file__).parent
ROBOT_HANDLER_DIR = PROJECT_ROOT / "Robot_handler"
LLM_ENGINE_DIR = PROJECT_ROOT / "LLM_engine"
VOICE_ENGINE_DIR = PROJECT_ROOT / "voice_engine"
HANDLER_SCRIPT = ROBOT_HANDLER_DIR / "robot_handler.py"
ENGINE_SCRIPT = LLM_ENGINE_DIR / "LLM_engine.py"
PIPE_PATH = ROBOT_HANDLER_DIR / "robot_handler.pipe"
CURRENT_CART = ROBOT_HANDLER_DIR / "current_cart.json"

sys.path.insert(0, str(VOICE_ENGINE_DIR))
try:
    from voice_input import VoiceInput
    VOICE_AVAILABLE = True
except Exception:
    VoiceInput = None
    VOICE_AVAILABLE = False

ROBOT_IP = "192.168.1.100"
ROBOT_PORT = 4880

ITEM_NAMES = [
    "Coke Zero",
    "Diet Coke",
    "Cough Medicine",
    "Crepe Bandage",
    "Ball_Red",
    "Ball_Yellow",
    "Ball_Blue",
    "Capsule Bottle",
    "Tea",
    "Bearing",
]

EMPTY_CART = {name: 0 for name in ITEM_NAMES}
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def normalize_cart(cart: Optional[Dict]) -> Dict[str, int]:
    normalized = {}
    cart = cart if isinstance(cart, dict) else {}
    for name in ITEM_NAMES:
        try:
            normalized[name] = max(0, int(cart.get(name, 0)))
        except (TypeError, ValueError):
            normalized[name] = 0
    return normalized


def load_cart() -> Dict[str, int]:
    try:
        with open(CURRENT_CART, "r") as file_handle:
            return normalize_cart(json.load(file_handle))
    except Exception:
        return dict(EMPTY_CART)


def save_cart(cart: Dict[str, int]) -> None:
    with open(CURRENT_CART, "w") as file_handle:
        json.dump(normalize_cart(cart), file_handle, indent=2)


def extract_json_candidates(text: str) -> Iterable[object]:
    """Yield JSON objects found in a string, including fenced or embedded JSON."""
    if not isinstance(text, str):
        return

    stripped = text.strip()
    if not stripped:
        return

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        yield from extract_json_candidates(fence_match.group(1))

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        yield value


def parse_llm_payload(raw: object) -> Dict:
    """
    Parse model/process output defensively.

    The terminal engine usually returns {"role": "assistant", "content": "...json..."},
    but local models sometimes wrap JSON in prose, code fences, or double-encoded
    strings. This function digs down to the first valid response/cart payload.
    """
    pending = [raw]
    seen = set()
    while pending:
        value = pending.pop(0)
        marker = repr(value)[:1000]
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(value, dict):
            if "error" in value:
                raise ValueError(str(value["error"]))
            if "response" in value or "cart" in value:
                return {
                    "response": str(value.get("response", "")).strip(),
                    "cart": normalize_cart(value.get("cart")),
                }
            for key in ("content", "message", "data", "output"):
                if key in value:
                    pending.append(value[key])
            continue

        if isinstance(value, list):
            pending.extend(value)
            continue

        if isinstance(value, str):
            for candidate in extract_json_candidates(value):
                pending.append(candidate)

    raise ValueError("Could not find a valid response/cart payload in LLM output")


class FanucBridge:
    def __init__(self, robot_ip: str, robot_port: int):
        self.robot_ip = robot_ip
        self.robot_port = robot_port
        self.handler_proc: Optional[subprocess.Popen] = None
        self.engine_proc: Optional[subprocess.Popen] = None
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.engine_lock = threading.Lock()
        self.outgoing = queue.Queue()
        self.running = False
        self.opcua_connected = False
        self.handler_connected = False
        self.last_cart = load_cart()
        self.stop_event = threading.Event()
        self.voice_input = None
        self.voice_thread = None
        self.voice_running = False

    def start(self) -> None:
        if self.running:
            self.broadcast_status()
            return

        self.last_cart = load_cart()
        self.start_handler()
        self.start_engine()
        self.running = True
        self.broadcast({"type": "engine_output", "data": "System online. Type or speak your order."})
        self.broadcast_cart()
        self.broadcast_status()

    def stop(self) -> None:
        self.running = False
        self.stop_voice()
        self._terminate(self.engine_proc)
        self._terminate(self.handler_proc)
        self.engine_proc = None
        self.handler_proc = None
        self.opcua_connected = False
        self.handler_connected = False
        self.broadcast_status()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.stop()
        if PIPE_PATH.exists():
            try:
                os.remove(PIPE_PATH)
            except OSError:
                pass

    def start_voice(self, model: str = "tiny") -> None:
        if self.voice_running:
            self.broadcast_voice_state(True, model)
            return
        if not VOICE_AVAILABLE or VoiceInput is None:
            self.broadcast({"type": "engine_error", "data": "Python voice engine is unavailable. Check faster-whisper and sounddevice dependencies."})
            self.broadcast_voice_state(False, model)
            return

        try:
            self.voice_input = VoiceInput(model=model, use_wake_word=False)
            self.voice_input.start()
        except Exception as error:
            self.voice_input = None
            self.broadcast({"type": "engine_error", "data": f"Failed to start voice engine: {error}"})
            self.broadcast_voice_state(False, model)
            return

        self.voice_running = True
        self.broadcast_voice_state(True, model)
        self.voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
        self.voice_thread.start()

    def stop_voice(self) -> None:
        if not self.voice_running and not self.voice_input:
            self.broadcast_voice_state(False)
            return
        self.voice_running = False
        if self.voice_input:
            try:
                self.voice_input.stop()
            except Exception:
                pass
        self.voice_input = None
        self.broadcast_voice_state(False)

    def broadcast_voice_state(self, recording: bool, model: str = "tiny") -> None:
        self.broadcast({"type": "voice_state", "data": {"recording": recording, "model": model}})

    def start_handler(self) -> None:
        if self.handler_proc and self.handler_proc.poll() is None:
            return

        self.handler_proc = subprocess.Popen(
            [
                sys.executable,
                str(HANDLER_SCRIPT),
                "--watch",
                "--robot-ip",
                self.robot_ip,
                "--robot-port",
                str(self.robot_port),
            ],
            cwd=str(ROBOT_HANDLER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_handler_output, daemon=True).start()

    def start_engine(self) -> None:
        if self.engine_proc and self.engine_proc.poll() is None:
            return

        self.engine_proc = subprocess.Popen(
            [sys.executable, str(ENGINE_SCRIPT)],
            cwd=str(LLM_ENGINE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_engine_stderr, daemon=True).start()

    def handle_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.running:
            self.start()
        self.broadcast({"type": "user_transcript", "data": text})

        with self.engine_lock:
            try:
                self.start_engine()
                assert self.engine_proc and self.engine_proc.stdin and self.engine_proc.stdout
                self.engine_proc.stdin.write(text + "\n")
                self.engine_proc.stdin.flush()
                output = self.engine_proc.stdout.readline().strip()
                if not output:
                    raise ValueError("LLM engine returned no output")
                print(f"[LLM RAW] {output}", flush=True)
                payload = parse_llm_payload(output)
            except Exception as error:
                self.broadcast({"type": "engine_error", "data": str(error)})
                return

        response = payload.get("response", "")
        self.broadcast({"type": "engine_output", "data": response})
        self.send_to_handler(payload)
        self.last_cart = normalize_cart(payload.get("cart"))
        self.broadcast_cart()

    def send_to_handler(self, payload: Dict) -> None:
        if not PIPE_PATH.exists():
            self.broadcast({"type": "engine_error", "data": "Robot handler pipe is not available."})
            return
        try:
            fd = os.open(PIPE_PATH, os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "w") as pipe:
                pipe.write(json.dumps(payload) + "\n")
                pipe.flush()
        except OSError as error:
            self.broadcast({"type": "engine_error", "data": f"Robot handler is not connected: {error}"})
        except BrokenPipeError:
            self.broadcast({"type": "engine_error", "data": "Robot handler disconnected."})

    def broadcast(self, message: Dict) -> None:
        encoded = json.dumps(message)
        with self.clients_lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.send_text(encoded)
            except OSError:
                self.unregister(client)

    def broadcast_cart(self) -> None:
        self.broadcast({"type": "cart_update", "data": self.last_cart})

    def broadcast_status(self) -> None:
        self.broadcast(
            {
                "type": "handler_status",
                "data": {
                    "running": self.running,
                    "handler_connected": self.handler_connected,
                    "opcua_connected": self.opcua_connected,
                    "robot_ip": self.robot_ip,
                    "robot_port": self.robot_port,
                },
            }
        )

    def register(self, client) -> None:
        with self.clients_lock:
            self.clients.add(client)
        client.send_text(json.dumps({"type": "cart_update", "data": self.last_cart}))
        client.send_text(
            json.dumps(
                {
                    "type": "handler_status",
                    "data": {
                        "running": self.running,
                        "handler_connected": self.handler_connected,
                        "opcua_connected": self.opcua_connected,
                        "robot_ip": self.robot_ip,
                        "robot_port": self.robot_port,
                    },
                }
            )
        )

    def unregister(self, client) -> None:
        with self.clients_lock:
            self.clients.discard(client)

    def poll_cart(self) -> None:
        while not self.stop_event.is_set():
            current = load_cart()
            if current != self.last_cart:
                self.last_cart = current
                self.broadcast_cart()
            time.sleep(0.5)

    def _voice_loop(self) -> None:
        while self.voice_running and self.voice_input:
            transcript = self.voice_input.get_text(timeout=0.5)
            if transcript:
                self.handle_text(transcript)

    def _read_handler_output(self) -> None:
        if not self.handler_proc or not self.handler_proc.stdout:
            return
        for raw_line in self.handler_proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            self.broadcast({"type": "handler_output", "data": line})
            lower = line.lower()
            if "connected to robot successfully" in lower:
                self.opcua_connected = True
                self.handler_connected = True
                self.broadcast_status()
            elif "failed to connect" in lower or "robot not connected" in lower or "falling back to simulator" in lower:
                self.opcua_connected = False
                self.handler_connected = True
                self.broadcast_status()
            elif "waiting for json" in lower:
                self.handler_connected = True
                self.broadcast_status()

    def _read_engine_stderr(self) -> None:
        if not self.engine_proc or not self.engine_proc.stderr:
            return
        for raw_line in self.engine_proc.stderr:
            line = raw_line.strip()
            if line:
                self.broadcast({"type": "engine_error", "data": line})

    @staticmethod
    def _terminate(proc: Optional[subprocess.Popen]) -> None:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


class WebSocketHandler(socketserver.BaseRequestHandler):
    bridge: FanucBridge = None

    def setup(self) -> None:
        self.alive = True

    def handle(self) -> None:
        if not self._handshake():
            return
        self.bridge.register(self)
        try:
            while self.alive:
                message = self._recv_text()
                if message is None:
                    break
                self._handle_message(message)
        finally:
            self.bridge.unregister(self)

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        if payload.get("type") == "user_input":
            self.bridge.handle_text(str(payload.get("text", "")))
            return

        if payload.get("type") == "control":
            action = payload.get("action")
            if action == "start":
                self.bridge.start()
            elif action == "stop":
                self.bridge.stop()
            elif action == "voice_on":
                self.bridge.start_voice(str(payload.get("model", "tiny")))
            elif action == "voice_off":
                self.bridge.stop_voice()

    def _handshake(self) -> bool:
        data = self.request.recv(4096).decode("utf-8", errors="ignore")
        headers = {}
        for line in data.split("\r\n")[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        ws_key = headers.get("sec-websocket-key")
        if not ws_key:
            return False
        accept = base64.b64encode(hashlib.sha1((ws_key + WS_GUID).encode()).digest()).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.request.sendall(response.encode("ascii"))
        return True

    def _recv_exact(self, count: int) -> Optional[bytes]:
        chunks = []
        remaining = count
        while remaining > 0:
            try:
                chunk = self.request.recv(remaining)
            except (ConnectionResetError, OSError):
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_text(self) -> Optional[str]:
        header = self._recv_exact(2)
        if not header:
            return None
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            ext = self._recv_exact(2)
            if not ext:
                return None
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = self._recv_exact(8)
            if not ext:
                return None
            length = struct.unpack("!Q", ext)[0]

        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if payload is None:
            return None
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 8:
            self.alive = False
            return None
        if opcode == 9:
            self._send_frame(payload, opcode=10)
            return ""
        if opcode != 1:
            return ""
        return payload.decode("utf-8", errors="replace")

    def send_text(self, text: str) -> None:
        self._send_frame(text.encode("utf-8"), opcode=1)

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        self.request.sendall(bytes(header) + payload)


class ThreadedWebSocketServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fanuc frontend WebSocket backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--robot-ip", default=ROBOT_IP)
    parser.add_argument("--robot-port", type=int, default=ROBOT_PORT)
    parser.add_argument("--auto-start", action="store_true", help="Start handler and LLM immediately")
    args = parser.parse_args()

    bridge = FanucBridge(args.robot_ip, args.robot_port)
    WebSocketHandler.bridge = bridge
    threading.Thread(target=bridge.poll_cart, daemon=True).start()

    def stop_server(_signum=None, _frame=None):
        bridge.shutdown()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)

    if args.auto_start:
        bridge.start()

    with ThreadedWebSocketServer((args.host, args.port), WebSocketHandler) as server:
        print(f"[frontend-backend] WebSocket listening on ws://{args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.shutdown()


if __name__ == "__main__":
    main()
