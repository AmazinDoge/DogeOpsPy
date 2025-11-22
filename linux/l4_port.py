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

def is_port_used(port):
    ipv4_used = False
    ipv6_used = False

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind(('0.0.0.0', port))
        except OSError:
            ipv4_used = True

    if ipv4_used:
        return True

    with closing(socket.socket(socket.AF_INET6, socket.SOCK_STREAM)) as s:
        try:
            s.bind(('::', port))
        except OSError:
            ipv6_used = True

    return ipv6_used

def find_available_ports(start, end):
    """Scan ports from `start` to `end` inclusive, and return list of available ports."""
    available = []
    for port in range(start, end + 1):
        if not is_port_used(port):
            available.append(port)
    return available

def aggregate_ports(ports):
    """
    Take a list of port numbers and return a list of strings where consecutive
    runs are collapsed to 'start-end' and singletons stay as 'n'.
    Example: [3001,3004,3009,3010,3011,3995,3997,3998,3999]
             -> ['3001','3004','3009-3011','3995','3997','3998-3999']
    """
    if not ports:
        return []

    ports = sorted(set(int(p) for p in ports))
    result = []

    start = prev = ports[0]
    for p in ports[1:]:
        if p == prev + 1:
            # still in a consecutive run
            prev = p
            continue

        # run ended at prev; emit it
        if start == prev:
            result.append(str(start))
        else:
            result.append(f"{start}-{prev}")

        # start a new run
        start = prev = p

    # emit the final run
    if start == prev:
        result.append(str(start))
    else:
        result.append(f"{start}-{prev}")

    return result


def parse_port_range(arg):
    """Parse 'start-end' into (start, end) with basic validation."""
    s = arg.strip()
    if '-' not in s:
        raise ValueError("Range must be in the form start-end")
    a, b = s.split('-', 1)
    if not (a.strip().isdigit() and b.strip().isdigit()):
        raise ValueError("Ports must be integers")
    start, end = int(a), int(b)
    if start < 1 or end > 65535 or start > end:
        raise ValueError("Range must be within 1-65535 and start <= end")
    return start, end

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        # Mode 1: preserve original behavior — count across all ports
        if len(sys.argv) == 2:
            ports = len(find_available_ports(1, 65535))
            print(f"{ports} available ports")
        # Mode 2: scan a specific range and print count + aggregated list
        elif len(sys.argv) >= 3 and '-' in sys.argv[2]:
            try:
                start, end = parse_port_range(sys.argv[2])
            except ValueError as e:
                print(f"Error: {e}")
                sys.exit(1)
            available = find_available_ports(start, end)
            agg = aggregate_ports(available)
            print(f"{len(available)} available ports")
            if agg:
                print("\n".join(agg))
        else:
            print("Usage:")
            print("  python3 l4_port.py scan")
            print("  python3 l4_port.py scan <start-end>")

if __name__ == '__main__':
    main()
