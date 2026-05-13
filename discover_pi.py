#!/usr/bin/env python3
"""Find a specific Buildroot-based Raspberry Pi on the local network."""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    psutil = None


DEFAULT_HOSTNAME = "lohi-bassline-junkie"
SSH_PORT = 22
RASPBERRY_PI_MAC_PREFIXES = {
    "b8:27:eb",
    "dc:a6:32",
    "e4:5f:01",
    "d8:3a:dd",
    "2c:cf:67",
    "28:cd:c1",
}


@dataclass(frozen=True)
class HostResult:
    ip: str
    hostname: str | None
    mac: str | None
    open_ports: list[int]
    resolved_from: str | None


@dataclass(frozen=True)
class ScoredHost:
    host: HostResult
    score: int
    confidence: str
    evidence: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find a Buildroot Raspberry Pi on the local network."
    )
    parser.add_argument(
        "--hostname",
        default=DEFAULT_HOSTNAME,
        help=f"target hostname to find; also tries .local (default: {DEFAULT_HOSTNAME})",
    )
    parser.add_argument(
        "--network",
        action="append",
        help="CIDR network to scan, e.g. 192.168.8.0/24; may be repeated",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.4,
        help="per-probe timeout in seconds (default: 0.4)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=128,
        help="maximum concurrent scan workers (default: 128)",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="show all responsive hosts, not only likely matches",
    )
    return parser.parse_args()


def candidate_hostnames(hostname: str) -> list[str]:
    names = [hostname.strip()]
    if names[0].endswith(".local"):
        base = names[0][:-6]
        if base:
            names.append(base)
    else:
        names.append(f"{names[0]}.local")
    return list(dict.fromkeys(name for name in names if name))


def resolve_hostname(name: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []

    ips = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


def get_local_networks() -> list[ipaddress.IPv4Network]:
    if psutil is None:
        print(
            "Missing dependency: psutil\nInstall with: pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(2)

    stats = psutil.net_if_stats()
    networks: list[ipaddress.IPv4Network] = []

    for interface, addresses in psutil.net_if_addrs().items():
        if interface in stats and not stats[interface].isup:
            continue

        for address in addresses:
            if address.family != socket.AF_INET or not address.netmask:
                continue

            ip = ipaddress.IPv4Address(address.address)
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                continue

            iface = ipaddress.IPv4Interface(f"{address.address}/{address.netmask}")
            network = iface.network
            if network.prefixlen < 24:
                network = ipaddress.IPv4Network(f"{address.address}/24", strict=False)

            if network not in networks:
                networks.append(network)

    return networks


def normalize_networks(cli_networks: list[str] | None) -> list[ipaddress.IPv4Network]:
    if not cli_networks:
        return get_local_networks()

    networks: list[ipaddress.IPv4Network] = []
    for raw in cli_networks:
        try:
            network = ipaddress.IPv4Network(raw, strict=False)
        except ValueError as exc:
            print(f"Invalid CIDR network: {raw}", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
        if network not in networks:
            networks.append(network)
    return networks


def probe_ssh(ip: str, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((ip, SSH_PORT)) == 0


def lookup_reverse_dns(ip: str) -> str | None:
    try:
        hostname = socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return None
    return hostname.rstrip(".")


def load_neighbor_cache() -> dict[str, str]:
    system = platform.system().lower()
    if system == "linux":
        return _parse_linux_ip_neigh(_run_command(["ip", "neigh"]))
    if system == "darwin":
        return _parse_arp_a(_run_command(["arp", "-a"]))
    if system == "windows":
        return _parse_windows_arp(_run_command(["arp", "-a"]))
    return {}


def _run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def _parse_linux_ip_neigh(output: str) -> dict[str, str]:
    neighbors: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or "lladdr" not in parts:
            continue
        ip = parts[0]
        mac = parts[parts.index("lladdr") + 1].lower()
        if _is_ipv4(ip) and _is_mac(mac):
            neighbors[ip] = mac
    return neighbors


def _parse_arp_a(output: str) -> dict[str, str]:
    neighbors: dict[str, str] = {}
    pattern = re.compile(
        r"\((?P<ip>\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+(?P<mac>[0-9a-fA-F:.-]+)"
    )
    for match in pattern.finditer(output):
        ip = match.group("ip")
        mac = _normalize_mac(match.group("mac"))
        if _is_ipv4(ip) and mac:
            neighbors[ip] = mac
    return neighbors


def _parse_windows_arp(output: str) -> dict[str, str]:
    neighbors: dict[str, str] = {}
    pattern = re.compile(
        r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+(?P<mac>[0-9a-fA-F-]{17})\s+\w+"
    )
    for match in pattern.finditer(output):
        ip = match.group("ip")
        mac = _normalize_mac(match.group("mac"))
        if _is_ipv4(ip) and mac:
            neighbors[ip] = mac
    return neighbors


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def _normalize_mac(value: str) -> str | None:
    value = value.strip().lower().replace("-", ":")
    if value == "(incomplete)":
        return None
    if "." in value:
        compact = value.replace(".", "")
        if len(compact) == 12:
            value = ":".join(compact[index : index + 2] for index in range(0, 12, 2))
    return value if _is_mac(value) else None


def _is_mac(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", value.lower()))


def scan_network(
    networks: Iterable[ipaddress.IPv4Network],
    timeout: float,
    workers: int,
) -> list[HostResult]:
    neighbor_cache = load_neighbor_cache()
    own_ips = _local_ipv4_addresses()
    targets = [
        str(ip)
        for network in networks
        for ip in network.hosts()
        if str(ip) not in own_ips
    ]

    if not targets:
        return []

    max_workers = max(1, min(workers, len(targets)))
    results: list[HostResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_probe_scan_target, ip, timeout, neighbor_cache): ip
            for ip in targets
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    return sorted(results, key=lambda item: tuple(int(part) for part in item.ip.split(".")))


def _local_ipv4_addresses() -> set[str]:
    if psutil is None:
        return set()

    addresses: set[str] = set()
    for iface_addresses in psutil.net_if_addrs().values():
        for address in iface_addresses:
            if address.family == socket.AF_INET:
                addresses.add(address.address)
    return addresses


def _probe_scan_target(
    ip: str,
    timeout: float,
    neighbor_cache: dict[str, str],
) -> HostResult | None:
    ssh_open = probe_ssh(ip, timeout)
    hostname = lookup_reverse_dns(ip) if ssh_open or ip in neighbor_cache else None
    mac = neighbor_cache.get(ip)

    if not ssh_open and hostname is None and mac is None:
        return None

    return HostResult(
        ip=ip,
        hostname=hostname,
        mac=mac,
        open_ports=[SSH_PORT] if ssh_open else [],
        resolved_from=None,
    )


def score_host(result: HostResult, target_hostname: str) -> ScoredHost:
    target_names = {target_hostname.lower(), f"{target_hostname.lower()}.local"}
    hostnames = {
        name.lower()
        for name in (result.hostname, result.resolved_from)
        if name
    }

    evidence: list[str] = []
    score = 0

    if hostnames & target_names:
        score += 100
        evidence.append("hostname")
    elif any(_generic_pi_hostname(name) for name in hostnames):
        score += 25
        evidence.append("generic_pi_hostname")

    if SSH_PORT in result.open_ports:
        score += 35
        evidence.append("ssh")

    if result.mac and _is_raspberry_pi_mac(result.mac):
        score += 60
        evidence.append("mac_vendor")

    if score >= 100:
        confidence = "high"
    elif score >= 50:
        confidence = "medium"
    else:
        confidence = "low"

    return ScoredHost(host=result, score=score, confidence=confidence, evidence=evidence)


def _generic_pi_hostname(hostname: str) -> bool:
    simple = hostname.split(".")[0]
    return simple in {"raspberrypi", "raspi", "rpi", "pi"} or simple.startswith("raspi-")


def _is_raspberry_pi_mac(mac: str) -> bool:
    normalized = _normalize_mac(mac)
    if not normalized:
        return False
    return ":".join(normalized.split(":")[:3]) in RASPBERRY_PI_MAC_PREFIXES


def format_results(
    results: list[ScoredHost],
    target_hostname: str,
    tried_hostnames: list[str],
    scanned_networks: list[ipaddress.IPv4Network],
    show_all: bool = False,
) -> str:
    if not results:
        return _format_not_found(tried_hostnames, scanned_networks)

    visible = results if show_all else [result for result in results if result.score > 0]
    if not visible:
        return _format_not_found(tried_hostnames, scanned_networks)

    best = visible[0]
    if best.confidence == "high" and "hostname" in best.evidence:
        host = best.host
        return "\n".join(
            [
                f"Found {target_hostname}",
                "",
                f"IP:          {host.ip}",
                f"Hostname:    {_display(host.hostname or host.resolved_from)}",
                f"MAC:         {_display(host.mac)}",
                f"SSH:         {'reachable' if SSH_PORT in host.open_ports else 'not reachable'}",
                f"Confidence:  {best.confidence}",
                f"Evidence:    {', '.join(best.evidence) or '-'}",
            ]
        )

    if show_all:
        title = "Responsive hosts"
    else:
        title = "Raspberry Pi candidate" if len(visible) == 1 else "Raspberry Pi candidates"
    rows = [
        [
            item.host.ip,
            _display(item.host.hostname or item.host.resolved_from),
            _display(item.host.mac),
            ",".join(str(port) for port in item.host.open_ports) or "-",
            item.confidence,
            ", ".join(item.evidence) or "-",
        ]
        for item in visible
    ]
    headers = ["IP", "Hostname", "MAC", "Open Ports", "Confidence", "Evidence"]
    return f"{title}\n\n{_format_table(headers, rows)}"


def _format_not_found(
    tried_hostnames: list[str],
    scanned_networks: list[ipaddress.IPv4Network],
) -> str:
    lines = ["No matching Raspberry Pi found.", "", "Tried hostnames:"]
    lines.extend(f"- {name}" for name in tried_hostnames)
    if scanned_networks:
        lines.extend(["", "Scanned networks:"])
        lines.extend(f"- {network}" for network in scanned_networks)
    return "\n".join(lines)


def _display(value: str | None) -> str:
    return value if value else "-"


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    header_line = "  ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    )
    row_lines = [
        "  ".join(row[index].ljust(widths[index]) for index in range(len(headers)))
        for row in rows
    ]
    return "\n".join([header_line, *row_lines])


def _direct_hostname_results(
    hostnames: list[str],
    timeout: float,
    neighbor_cache: dict[str, str],
) -> list[HostResult]:
    results: list[HostResult] = []
    seen: set[tuple[str, str]] = set()

    for hostname in hostnames:
        for ip in resolve_hostname(hostname):
            key = (hostname, ip)
            if key in seen:
                continue
            seen.add(key)
            ssh_open = probe_ssh(ip, timeout)
            reverse_name = lookup_reverse_dns(ip)
            results.append(
                HostResult(
                    ip=ip,
                    hostname=reverse_name or hostname,
                    mac=neighbor_cache.get(ip),
                    open_ports=[SSH_PORT] if ssh_open else [],
                    resolved_from=hostname,
                )
            )

    return results


def _deduplicate_results(results: list[HostResult]) -> list[HostResult]:
    by_ip: dict[str, HostResult] = {}
    for result in results:
        existing = by_ip.get(result.ip)
        if existing is None:
            by_ip[result.ip] = result
            continue

        by_ip[result.ip] = HostResult(
            ip=result.ip,
            hostname=existing.hostname or result.hostname,
            mac=existing.mac or result.mac,
            open_ports=sorted(set(existing.open_ports + result.open_ports)),
            resolved_from=existing.resolved_from or result.resolved_from,
        )

    return list(by_ip.values())


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("--timeout must be greater than zero", file=sys.stderr)
        return 2
    if args.workers <= 0:
        print("--workers must be greater than zero", file=sys.stderr)
        return 2

    hostnames = candidate_hostnames(args.hostname)
    neighbor_cache = load_neighbor_cache()
    direct_results = _direct_hostname_results(hostnames, args.timeout, neighbor_cache)
    direct_scored = sorted(
        (score_host(result, args.hostname) for result in direct_results),
        key=lambda item: item.score,
        reverse=True,
    )

    if direct_scored and direct_scored[0].confidence == "high" and not args.show_all:
        print(format_results(direct_scored, args.hostname, hostnames, [], args.show_all))
        return 0

    networks = normalize_networks(args.network)
    if not networks:
        print(
            "Could not detect local networks. Try:\n"
            "python discover_pi.py --network 192.168.1.0/24",
            file=sys.stderr,
        )
        return 2

    scan_results = scan_network(networks, args.timeout, args.workers)
    all_results = _deduplicate_results([*direct_results, *scan_results])
    scored = sorted(
        (score_host(result, args.hostname) for result in all_results),
        key=lambda item: (item.score, bool(item.host.open_ports), item.host.ip),
        reverse=True,
    )

    print(format_results(scored, args.hostname, hostnames, networks, args.show_all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
