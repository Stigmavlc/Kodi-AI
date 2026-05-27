"""Unit tests for lib.setup_ip — LAN IP discovery + RFC1918 validation."""
from __future__ import annotations
import socket
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# _is_usable_lan_ip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ip", [
    "192.168.1.1",
    "192.168.0.42",
    "192.168.255.254",
    "10.0.0.1",
    "10.255.255.254",
    "172.16.0.1",
    "172.20.50.100",
    "172.31.255.254",
])
def test_is_usable_lan_ip_accepts_rfc1918(ip):
    from lib import setup_ip
    assert setup_ip._is_usable_lan_ip(ip) is True


@pytest.mark.parametrize("ip", [
    None,
    "",
    "127.0.0.1",        # loopback /8
    "127.5.5.5",
    "169.254.1.1",      # link-local
    "169.254.250.250",
    "100.64.0.1",       # CGNAT lower bound
    "100.100.100.100",  # CGNAT mid
    "100.127.255.254",  # CGNAT upper bound
    "0.0.0.0",
    "::1",              # IPv6 loopback
    "fe80::1",          # IPv6 link-local
    "2001:db8::1",      # IPv6 documentation
    "1.2.3",            # malformed — 3 octets
    "1.2.3.4.5",        # malformed — 5 octets
    "300.1.1.1",        # octet out of range
    "-1.1.1.1",         # negative octet
    "abc.def.ghi.jkl",  # non-numeric
    "8.8.8.8",          # public — Google DNS
    "1.1.1.1",          # public — Cloudflare
    "172.15.0.1",       # OUTSIDE 172.16/12 (172.15 = public)
    "172.32.0.1",       # OUTSIDE 172.16/12 (172.32 = public)
])
def test_is_usable_lan_ip_rejects(ip):
    from lib import setup_ip
    assert setup_ip._is_usable_lan_ip(ip) is False


# ---------------------------------------------------------------------------
# _get_lan_ip — primary path: xbmc.getIPAddress()
# ---------------------------------------------------------------------------
def test_get_lan_ip_uses_xbmc_when_usable(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = "192.168.1.50"
    # Patch the module-bound attribute directly (the module already cached
    # `import xbmc` at import-time; we override that bound name).
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)
    assert setup_ip._get_lan_ip() == "192.168.1.50"


def test_get_lan_ip_falls_through_when_xbmc_returns_loopback(monkeypatch):
    """xbmc.getIPAddress() may return 127.0.0.1 if the device is offline."""
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = "127.0.0.1"
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    # Fallback also unusable: simulate no network.
    def _no_route(*args, **kwargs):
        raise OSError("Network unreachable")
    monkeypatch.setattr(socket.socket, "connect", _no_route)
    assert setup_ip._get_lan_ip() is None


def test_get_lan_ip_falls_through_when_xbmc_returns_link_local(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = "169.254.10.5"
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    def _no_route(*args, **kwargs):
        raise OSError("Network unreachable")
    monkeypatch.setattr(socket.socket, "connect", _no_route)
    assert setup_ip._get_lan_ip() is None


def test_get_lan_ip_falls_through_when_xbmc_returns_cgnat(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = "100.96.0.1"
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    def _no_route(*args, **kwargs):
        raise OSError("Network unreachable")
    monkeypatch.setattr(socket.socket, "connect", _no_route)
    assert setup_ip._get_lan_ip() is None


def test_get_lan_ip_falls_through_when_xbmc_returns_empty(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = ""
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    def _no_route(*args, **kwargs):
        raise OSError("Network unreachable")
    monkeypatch.setattr(socket.socket, "connect", _no_route)
    assert setup_ip._get_lan_ip() is None


# ---------------------------------------------------------------------------
# _get_lan_ip — fallback path: UDP-connect trick
# ---------------------------------------------------------------------------
def test_get_lan_ip_uses_udp_fallback(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = ""  # xbmc unhelpful
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    # Patch socket.socket() to return a controllable mock.
    fake_sock = mock.MagicMock()
    fake_sock.getsockname.return_value = ("192.168.42.7", 12345)
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: fake_sock)

    assert setup_ip._get_lan_ip() == "192.168.42.7"


def test_get_lan_ip_returns_none_when_udp_fallback_yields_unusable(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.return_value = ""
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    fake_sock = mock.MagicMock()
    # OS picks a link-local on offline boot.
    fake_sock.getsockname.return_value = ("169.254.99.99", 12345)
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: fake_sock)

    assert setup_ip._get_lan_ip() is None


def test_get_lan_ip_returns_none_when_both_methods_fail(monkeypatch):
    from lib import setup_ip
    fake_xbmc = mock.MagicMock()
    fake_xbmc.getIPAddress.side_effect = Exception("xbmc broken")
    monkeypatch.setattr(setup_ip, "xbmc", fake_xbmc)

    def _raise(*a, **kw):
        raise OSError("Network unreachable")
    monkeypatch.setattr(socket, "socket", _raise)

    assert setup_ip._get_lan_ip() is None
