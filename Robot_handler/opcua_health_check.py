#!/usr/bin/env python3
"""Continuous/read-once OPC UA health check for the FANUC robot."""

import argparse
import logging
import sys
import time
from datetime import datetime


GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


DEFAULT_ROBOT_IP = "192.168.1.100"
DEFAULT_ROBOT_PORT = 4880
DEFAULT_REGISTERS = [1, 5, 8, 13]


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def suppress_opcua_crypto_warning() -> None:
    logging.getLogger("opcua").setLevel(logging.ERROR)
    logging.getLogger("opcua.client.client").setLevel(logging.ERROR)
    logging.getLogger("opcua.server.server").setLevel(logging.ERROR)


suppress_opcua_crypto_warning()

from fanuc_register_opcua import connect, disconnect, read_register


def check_once(robot_ip: str, robot_port: int, registers: list[int]) -> bool:
    client = None
    try:
        client = connect(robot_ip, robot_port)
        values = {f"R[{index}]": read_register(client, index) for index in registers}
        print(f"{GREEN}[{timestamp()}] OK connected to {robot_ip}:{robot_port} | {values}{RESET}", flush=True)
        return True
    except Exception as error:
        print(f"[{timestamp()}] {RED}FAIL{RESET} {robot_ip}:{robot_port} | {error}", file=sys.stderr, flush=True)
        return False
    finally:
        if client is not None:
            disconnect(client)


def parse_registers(raw: str) -> list[int]:
    registers = []
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        registers.append(int(value))
    return registers or DEFAULT_REGISTERS


def main() -> int:
    parser = argparse.ArgumentParser(description="Test FANUC OPC UA connectivity.")
    parser.add_argument("--robot-ip", default=DEFAULT_ROBOT_IP, help="Robot controller IP address")
    parser.add_argument("--robot-port", type=int, default=DEFAULT_ROBOT_PORT, help="Robot OPC UA port")
    parser.add_argument(
        "--registers",
        default=",".join(str(index) for index in DEFAULT_REGISTERS),
        help="Comma-separated R registers to read, e.g. 1,5,8,13",
    )
    parser.add_argument("--watch", action="store_true", help="Keep checking until stopped")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between checks in --watch mode")
    args = parser.parse_args()

    registers = parse_registers(args.registers)
    if not args.watch:
        return 0 if check_once(args.robot_ip, args.robot_port, registers) else 1

    exit_code = 0
    try:
        while True:
            if not check_once(args.robot_ip, args.robot_port, registers):
                exit_code = 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped OPC UA health check.", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
