import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

try:
    from fanuc_register_opcua import connect, disconnect, write_register, write_registers
    OPCUA_AVAILABLE = True
except ImportError:
    OPCUA_AVAILABLE = False

# ANSI colors
RED = "\033[91m"
RESET = "\033[0m"

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

CURRENT_CART_PATH = os.path.join(os.path.dirname(__file__), "current_cart.json")
FIFO_PATH = os.path.join(os.path.dirname(__file__), "robot_handler.pipe")


class RegisterSimulator:
    def __init__(self):
        self.registers = {}

    def write_register(self, index: int, value: int):
        self.registers[index] = int(value)
        print(f"{RED}[DEBUG] Write R[{index}] = {value}{RESET}", flush=True)

    def write_registers(self, start: int, values: List[int]):
        for i, v in enumerate(values):
            self.write_register(start + i, v)

    def dump(self):
        print(f"{RED}[DEBUG] Registers snapshot:{RESET}", flush=True)
        for key in sorted(self.registers.keys()):
            print(f"{RED}  R[{key}] = {self.registers[key]}{RESET}", flush=True)


class RegisterOPCUA:
    def __init__(self, ip: str, port: int = 4880):
        self.ip = ip
        self.port = port
        self.client = None
        self.connected = False
        try:
            print(f"{RED}[DEBUG] Connecting to FANUC robot at {ip}:{port}{RESET}", flush=True)
            self.client = connect(ip, port)
            self.connected = True
            print(f"{RED}[DEBUG] Connected to robot successfully{RESET}", flush=True)
        except Exception as e:
            print(f"{RED}[ERROR] Failed to connect to robot: {e}{RESET}", flush=True)
            self.connected = False

    def write_register(self, index: int, value: int):
        if not self.connected:
            print(f"{RED}[ERROR] Robot not connected{RESET}", flush=True)
            return
        try:
            write_register(self.client, index, int(value))
            print(f"{RED}[DEBUG] Write R[{index}] = {value}{RESET}", flush=True)
        except Exception as e:
            error_str = str(e)
            if "BadSessionIdInvalid" in error_str or "session" in error_str.lower():
                print(f"{RED}[DEBUG] Session lost, reconnecting...{RESET}", flush=True)
                self.__init__(self.ip, self.port)  # Reconnect
                if self.connected:
                    try:
                        write_register(self.client, index, int(value))
                        print(f"{RED}[DEBUG] Write R[{index}] = {value} (after reconnect){RESET}", flush=True)
                        return
                    except Exception as retry_e:
                        print(f"{RED}[ERROR] Retry failed for R[{index}]: {retry_e}{RESET}", flush=True)
            print(f"{RED}[ERROR] Failed to write R[{index}]: {e}{RESET}", flush=True)

    def write_registers(self, start: int, values: List[int]):
        if not self.connected:
            print(f"{RED}[ERROR] Robot not connected{RESET}", flush=True)
            return
        try:
            write_registers(self.client, start, [int(v) for v in values])
            for i, v in enumerate(values):
                print(f"{RED}[DEBUG] Write R[{start + i}] = {v}{RESET}", flush=True)
        except Exception as e:
            error_str = str(e)
            if "BadSessionIdInvalid" in error_str or "session" in error_str.lower():
                print(f"{RED}[DEBUG] Session lost, reconnecting...{RESET}", flush=True)
                self.__init__(self.ip, self.port)  # Reconnect
                if self.connected:
                    try:
                        write_registers(self.client, start, [int(v) for v in values])
                        for i, v in enumerate(values):
                            print(f"{RED}[DEBUG] Write R[{start + i}] = {v} (after reconnect){RESET}", flush=True)
                        return
                    except Exception as retry_e:
                        print(f"{RED}[ERROR] Retry failed for registers: {retry_e}{RESET}", flush=True)
            print(f"{RED}[ERROR] Failed to write registers: {e}{RESET}", flush=True)

    def dump(self):
        if self.connected:
            print(f"{RED}[DEBUG] Registers written to robot successfully{RESET}", flush=True)
        else:
            print(f"{RED}[DEBUG] Robot connection unavailable (no robot register write){RESET}", flush=True)

    def __del__(self):
        if self.client and self.connected:
            try:
                disconnect(self.client)
                print(f"{RED}[DEBUG] Disconnected from robot{RESET}", flush=True)
            except Exception:
                pass


def load_current_cart(path: str = CURRENT_CART_PATH) -> Dict[str, int]:
    if not os.path.exists(path):
        return {name: 0 for name in ITEM_NAMES}
    with open(path, "r") as file_handle:
        loaded = json.load(file_handle)
    return {name: int(loaded.get(name, 0)) for name in ITEM_NAMES}


def save_current_cart(cart: Dict[str, int], path: str = CURRENT_CART_PATH):
    normalized = {name: int(cart.get(name, 0)) for name in ITEM_NAMES}
    with open(path, "w") as file_handle:
        json.dump(normalized, file_handle, indent=2)


def compute_deltas(old: Dict[str, int], new: Dict[str, int]) -> List[int]:
    return [int(new.get(name, 0)) - int(old.get(name, 0)) for name in ITEM_NAMES]


def format_cart(cart: Dict[str, int]) -> str:
    return json.dumps({name: int(cart.get(name, 0)) for name in ITEM_NAMES}, indent=2)


def handle_llm_output(llm_json: Dict, register_handler: Optional = None, current_cart_path: str = CURRENT_CART_PATH):
    if register_handler is None:
        register_handler = RegisterSimulator()

    if "cart" not in llm_json:
        print(f"{RED}[DEBUG] LLM output missing 'cart' field{RESET}", flush=True)
        return

    new_cart = {name: int(llm_json["cart"].get(name, 0)) for name in ITEM_NAMES}
    current_cart = load_current_cart(current_cart_path)
    deltas = compute_deltas(current_cart, new_cart)
    adds = [delta if delta > 0 else 0 for delta in deltas]

    print(f"{RED}[DEBUG] Current cart:{RESET}\n{RED}{format_cart(current_cart)}{RESET}", flush=True)
    print(f"{RED}[DEBUG] Incoming cart:{RESET}\n{RED}{format_cart(new_cart)}{RESET}", flush=True)
    print(f"{RED}[DEBUG] Deltas:{RESET} {dict(zip(ITEM_NAMES, deltas))}", flush=True)

    # Bring/add operations are mapped in register order R[51]..R[60].
    # Negative deltas (removes) are ignored.
    if any(value > 0 for value in adds):
        print(f"{RED}[DEBUG] Writing bring registers R[51..] with adds{RESET}", flush=True)
        register_handler.write_registers(51, adds)

    register_handler.dump()
    save_current_cart(new_cart, current_cart_path)
    print(f"{RED}[DEBUG] Updated current_cart.json{RESET}", flush=True)


def process_json_line(raw_line: str, register_handler: Optional = None, current_cart_path: str = CURRENT_CART_PATH):
    line = raw_line.strip()
    if not line:
        return
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        print(f"{RED}[DEBUG] Failed to parse JSON: {error}{RESET}", flush=True)
        return
    if register_handler is None:
        register_handler = RegisterSimulator()
    handle_llm_output(payload, register_handler, current_cart_path=current_cart_path)


def watch_pipe(pipe_path: str = FIFO_PATH, current_cart_path: str = CURRENT_CART_PATH, robot_ip: Optional[str] = None):
    if not os.path.exists(pipe_path):
        os.mkfifo(pipe_path)

    register_handler = None
    if robot_ip:
        if not OPCUA_AVAILABLE:
            print(f"{RED}[ERROR] opcua library not installed. Run: pip install opcua{RESET}", flush=True)
            print(f"{RED}[DEBUG] Falling back to simulator mode{RESET}", flush=True)
            register_handler = RegisterSimulator()
        else:
            register_handler = RegisterOPCUA(robot_ip)
            if not register_handler.connected:
                print(f"{RED}[DEBUG] Falling back to simulator mode (robot unreachable){RESET}", flush=True)
                register_handler = RegisterSimulator()
    else:
        register_handler = RegisterSimulator()

    print(f"{RED}[DEBUG] Waiting for JSON on {pipe_path}{RESET}", flush=True)
    while True:
        try:
            with open(pipe_path, "r") as pipe_handle:
                for raw_line in pipe_handle:
                    process_json_line(raw_line, register_handler, current_cart_path=current_cart_path)
        except Exception as e:
            print(f"{RED}[ERROR] Pipe error: {e}{RESET}", flush=True)
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Read JSON lines from robot_handler.pipe")
    parser.add_argument("--robot-ip", type=str, help="FANUC robot IP address (e.g. 172.168.10.2)")
    parser.add_argument("--robot-port", type=int, default=4880, help="FANUC OPC UA port (default 4880)")
    parser.add_argument("--pipe", default=FIFO_PATH, help="Path to the FIFO when using --watch")
    parser.add_argument("--cart", default=CURRENT_CART_PATH, help="Path to current_cart.json")
    args = parser.parse_args()

    if args.watch:
        watch_pipe(args.pipe, current_cart_path=args.cart, robot_ip=args.robot_ip)
        return

    raw_input = sys.stdin.read()
    if not raw_input:
        print(f"{RED}[DEBUG] No input received on stdin{RESET}", flush=True)
        return

    register_handler = None
    if args.robot_ip:
        if not OPCUA_AVAILABLE:
            print(f"{RED}[ERROR] opcua library not installed. Run: pip install opcua{RESET}", flush=True)
            register_handler = RegisterSimulator()
        else:
            register_handler = RegisterOPCUA(args.robot_ip, args.robot_port)
            if not register_handler.connected:
                print(f"{RED}[DEBUG] Falling back to simulator mode (robot unreachable){RESET}", flush=True)
                register_handler = RegisterSimulator()
    else:
        register_handler = RegisterSimulator()

    process_json_line(raw_input, register_handler, current_cart_path=args.cart)


if __name__ == "__main__":
    main()
