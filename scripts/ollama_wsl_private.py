#!/usr/bin/python3
"""Bind Ollama to WSL's current private eth0 address; never all interfaces."""

import argparse
import fcntl
import ipaddress
import os
import socket
import struct
from pathlib import Path


def private_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        data = fcntl.ioctl(connection.fileno(), 0x8915, struct.pack("256s", b"eth0"))
    address = socket.inet_ntoa(data[20:24])
    allowed = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(
        ipaddress.ip_address(address) in ipaddress.ip_network(n) for n in allowed
    ):
        raise RuntimeError("Refusing to expose Ollama on a non-private eth0 address")
    return address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", action="store_true")
    parser.add_argument("--update-env", type=Path)
    args = parser.parse_args()
    address = private_address()
    if args.update_env:
        path = args.update_env
        text = path.read_text() if path.exists() else ""
        lines = [
            line
            for line in text.splitlines()
            if not line.startswith(("OLLAMA_HOST_ADDRESS=", "OLLAMA_BASE_URL="))
        ]
        lines.append("OLLAMA_HOST_ADDRESS=" + address)
        lines.append("OLLAMA_BASE_URL=http://" + address + ":11434")
        path.write_text("\n".join(lines) + "\n")
    if args.address:
        print(address)
    else:
        os.environ["OLLAMA_HOST"] = address + ":11434"
        os.execv("/usr/local/bin/ollama", ["ollama", "serve"])


if __name__ == "__main__":
    main()
