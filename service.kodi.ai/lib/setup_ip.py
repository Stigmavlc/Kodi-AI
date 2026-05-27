"""LAN IP discovery for the phone-driven setup flow.

Primary method:  xbmc.getIPAddress().
Fallback method: UDP-connect trick to 8.8.8.8:80 (no packet sent — just
                 resolves the OS's default-route source IP).

Both results are validated by `_is_usable_lan_ip`. If neither produces a
usable RFC1918 address, `_get_lan_ip()` returns None and the caller is
expected to show a clear error dialog and abort.

Reject list (NOT a usable LAN IP):
- empty / None
- IPv6 (contains ':')
- non-4-octet IPv4
- 127.0.0.0/8  (loopback)
- 169.254.0.0/16  (link-local — Android assigns when DHCP fails)
- 100.64.0.0/10  (CGNAT — Starlink, T-Mobile Home Internet, etc.)
- 0.0.0.0

Accept list:
- 10.0.0.0/8
- 172.16.0.0/12
- 192.168.0.0/16
"""
from __future__ import annotations
import socket
from typing import Optional

try:
    import xbmc  # type: ignore
except ImportError:  # pragma: no cover — only on non-Kodi test hosts
    xbmc = None  # type: ignore


def _is_usable_lan_ip(ip: Optional[str]) -> bool:
    """True iff `ip` is a parseable IPv4 address in 10/8, 172.16/12, or
    192.168/16. False for any malformed / non-routable / CGNAT / link-local
    / loopback / IPv6 address."""
    if not ip:
        return False
    if ":" in ip:  # IPv6
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False
    if any(o < 0 or o > 255 for o in octets):
        return False
    o1, o2, _o3, _o4 = octets
    # Reject 0.0.0.0
    if o1 == 0 and o2 == 0 and octets[2] == 0 and octets[3] == 0:
        return False
    # Reject loopback (127.0.0.0/8)
    if o1 == 127:
        return False
    # Reject link-local (169.254.0.0/16)
    if o1 == 169 and o2 == 254:
        return False
    # Reject CGNAT (100.64.0.0/10 — 100.64.0.0 through 100.127.255.255)
    if o1 == 100 and 64 <= o2 <= 127:
        return False
    # Accept 10.0.0.0/8
    if o1 == 10:
        return True
    # Accept 172.16.0.0/12 (172.16 through 172.31)
    if o1 == 172 and 16 <= o2 <= 31:
        return True
    # Accept 192.168.0.0/16
    if o1 == 192 and o2 == 168:
        return True
    return False


def _get_lan_ip() -> Optional[str]:
    """Return a usable RFC1918 LAN IP, or None if none can be detected.

    Tries `xbmc.getIPAddress()` first (fast, no network), then a UDP-connect
    fallback that resolves the OS's default-route source IP without sending
    any packets.
    """
    # Method 1: Kodi's own IP. Fast, no socket needed.
    if xbmc is not None:
        try:
            ip = xbmc.getIPAddress()
        except Exception:
            ip = None
        if ip and not ip.startswith("127."):
            if _is_usable_lan_ip(ip):
                return ip

    # Method 2: UDP-connect to a public IP. Does NOT send a packet —
    # just asks the OS which interface would be used.
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 8.8.8.8 is Google DNS. We don't actually need to reach it.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if _is_usable_lan_ip(ip):
            return ip
    except OSError:
        pass
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    return None
