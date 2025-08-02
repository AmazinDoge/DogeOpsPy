import socket
import sys
from contextlib import closing

def get_port_from_str(addr_str):
    addr_str = str(addr_str).strip()
    if addr_str.isdigit():
        return int(addr_str)
    if ":" in addr_str:
        port = addr_str.split(":")[-1].strip()
        if port.isdigit():
            return int(port)
    return -1

def is_port_open(port):
    """Check if a port is open by trying to bind a socket to it."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('0.0.0.0', port))
            return False  # Port is not open
        except OSError:
            return True  # Port is in use


def find_available_ports(start, end):
    """Scan ports from `start` to `end` inclusive, and return list of available ports."""
    available = []
    for port in range(start, end + 1):
        if not is_port_open(port):
            available.append(port)
    return available


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        ports = len(find_available_ports(1, 65535))
        print(f"{ports} opened")
