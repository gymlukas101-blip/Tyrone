"""List-Unsubscribe (RFC 2369) and List-Unsubscribe-Post (RFC 8058) parsing, and the checks on every address Monkey
would use to unsubscribe.

Only the `List-Unsubscribe` header is ever used: never a link from an email's body, whatever the body says. Header
values come from the sender, so they are untrusted too:
  * one-click: https only, port 443, no user:password@, no IP literal or name that resolves to a private, loopback,
    link-local, reserved or multicast address (checked again right before the POST, which then connects to the
    checked address, so a DNS answer can't change in between);
  * mailto: exactly one recipient, no cc/bcc or other header fields, short subject and body;
  * a web page: https only, the same host checks; it is opened only in Monkey's browser under the unsubscribe_page
    template (permissions/templates).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

Resolver = Callable[[str], list[str]]

ONE_CLICK_BODY = "List-Unsubscribe=One-Click"
MAX_URL = 2048
_ANGLE = re.compile(r"<([^>]*)>")
_ADDR = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_BAD_HOST_SUFFIX = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".arpa")


def parse_list_unsubscribe(value: str) -> list[str]:
    """The URIs in a List-Unsubscribe header, in the sender's order. Whitespace inside <> is folding: removed."""
    out = []
    for m in _ANGLE.finditer(value or ""):
        uri = re.sub(r"\s+", "", m.group(1))
        if uri and len(uri) <= MAX_URL:
            out.append(uri)
    return out[:4]


def is_one_click(post_value: str) -> bool:
    """RFC 8058: the List-Unsubscribe-Post header must be exactly `List-Unsubscribe=One-Click`."""
    return re.sub(r"\s+", "", post_value or "").lower() == ONE_CLICK_BODY.lower()


def parse_list_id(value: str) -> str:
    """RFC 2919 List-Id: 'Name <id.example.com>' -> 'id.example.com' (lowercased)."""
    m = _ANGLE.search(value or "")
    raw = (m.group(1) if m else (value or "")).strip().lower()
    return raw[:200] if re.fullmatch(r"[a-z0-9._+-]+", raw or "-") else ""


def default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return sorted({i[4][0] for i in infos})


def public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local
                                 or ip.is_reserved or ip.is_unspecified)


@dataclass
class UrlCheck:
    ok: bool
    reason: str = ""
    host: str = ""
    port: int = 443
    ips: tuple[str, ...] = ()


def check_https_url(url: str, resolve: Resolver | None = default_resolve) -> UrlCheck:
    """Is this a URL Monkey may contact for an unsubscribe? `resolve=None` skips DNS (shape-only, for display)."""
    if not url or len(url) > MAX_URL or re.search(r"[\s\x00-\x1f\x7f\\]", url):
        return UrlCheck(False, "the address is empty, too long or has hidden characters")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return UrlCheck(False, "the address can't be read")
    if u.scheme.lower() != "https":
        return UrlCheck(False, "only https addresses are used for unsubscribing")
    if u.username is not None or u.password is not None or "@" in (u.netloc or ""):
        return UrlCheck(False, "the address has a user name or password in it")
    host = (u.hostname or "").lower().rstrip(".")
    if not host:
        return UrlCheck(False, "the address has no site name")
    if port not in (None, 443):
        return UrlCheck(False, "the address uses an unusual port")
    try:
        ipaddress.ip_address(host)
        return UrlCheck(False, "the address is a bare IP address, not a site name", host)
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith(_BAD_HOST_SUFFIX) or \
            not re.fullmatch(r"[a-z0-9.-]+", host):
        return UrlCheck(False, "the address points at a local or unusual name", host)
    if resolve is None:
        return UrlCheck(True, "", host)
    try:
        ips = tuple(resolve(host))
    except (OSError, UnicodeError):
        return UrlCheck(False, "the site name doesn't resolve", host)
    if not ips:
        return UrlCheck(False, "the site name doesn't resolve", host)
    if not all(public_ip(a) for a in ips):
        return UrlCheck(False, "the site name points at a private or local network address", host)
    return UrlCheck(True, "", host, 443, ips)


@dataclass
class Mailto:
    to: str
    subject: str
    body: str


def check_mailto(uri: str) -> tuple[Mailto | None, str]:
    """A mailto: unsubscribe address -> (Mailto, '') or (None, why it isn't used)."""
    if not uri or not uri.lower().startswith("mailto:") or len(uri) > MAX_URL or re.search(r"[\s\x00-\x1f\x7f]", uri):
        return None, "not a usable mailto address"
    rest = uri[7:]
    addr_part, _, query = rest.partition("?")
    addrs = [unquote(a).strip() for a in addr_part.split(",") if a.strip()]
    q = {k.lower(): v for k, v in parse_qs(query, keep_blank_values=True).items()}
    if len(addrs) != 1 or not _ADDR.match(addrs[0]):
        return None, "the unsubscribe email must go to exactly one valid address"
    extra = set(q) - {"subject", "body"}
    if extra:
        return None, "the unsubscribe email asks to add other headers (" + ", ".join(sorted(extra))[:40] + ")"
    subject = " ".join((q.get("subject") or ["unsubscribe"])[0].split())[:200] or "unsubscribe"
    body = (q.get("body") or ["unsubscribe"])[0][:1000] or "unsubscribe"
    return Mailto(addrs[0], subject, body), ""


def sender_parts(from_header: str) -> tuple[str, str]:
    name, addr = parseaddr(from_header or "")
    return " ".join(name.split())[:80], addr.strip().lower()[:200]


def methods_from(unsub: str, unsub_post: str) -> dict:
    """{'one_click': url, 'mailto': uri, 'web': url} from one message's headers (shape checks only; DNS later)."""
    out: dict[str, str] = {}
    for uri in parse_list_unsubscribe(unsub):
        low = uri.lower()
        if low.startswith("https:") and check_https_url(uri, resolve=None).ok:
            if is_one_click(unsub_post) and "one_click" not in out:
                out["one_click"] = uri
            elif "web" not in out:
                out["web"] = uri
        elif low.startswith("mailto:") and "mailto" not in out and check_mailto(uri)[0] is not None:
            out["mailto"] = uri
    if "one_click" in out and "web" not in out:
        out["web"] = out["one_click"]          # the same page usually works in a browser if one-click fails
    return out
