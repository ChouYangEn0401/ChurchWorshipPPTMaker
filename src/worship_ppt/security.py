"""誰在用、能不能用。做法參考 CloudServicesPlatform，但簡化成教會用得到的程度。

- 伺服器只綁 127.0.0.1：區網裡別台電腦連不到，外面的人只能透過 Cloudflare 臨時網址進來。
- 「本機」＝這台電腦自己開瀏覽器（沒有 Cloudflare 的標頭、Host 是 127.0.0.1/localhost）：
  不用登入，而且只有本機能開關對外連結、改密碼、備份。
- 「遠端」＝透過 Cloudflare 網址進來的：一定要輸入團隊密碼。還沒設定密碼就一律擋掉（不會不小心公開）。
- Host 只接受 127.0.0.1 / localhost 和「目前這條」Cloudflare 網址（擋 DNS rebinding、舊網址）。
- 會改資料的請求（POST/PATCH/DELETE）都要同源（Origin/Referer），遠端還要帶 X-CSRF-Token。
- 密碼猜錯太多次：同一個 IP 暫停 15 分鐘；本機永遠不會被鎖。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .db import Database

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
CF_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-ipcountry", "cf-visitor", "cdn-loop")

SESSION_IDLE_SECONDS = 14 * 24 * 3600      # 兩週沒用就要重新登入
SESSION_MAX_SECONDS = 60 * 24 * 3600       # 最長 60 天
LOCAL_COOKIE = "wppt_session"
TUNNEL_COOKIE = "__Host-wppt_session"      # 透過 https 時用 __Host- 前綴：只能是這個網址、只走 https


# ---------------------------------------------------------------------------
# 密碼（scrypt）
# ---------------------------------------------------------------------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str, n: int = SCRYPT_N) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${n}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # 沒設定密碼時也跑一次 scrypt，回應時間不會洩漏「有沒有設密碼」
        hashlib.scrypt(b"x", salt=b"0" * 16, n=2 ** 10, r=8, p=1, dklen=32)
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                                p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------------------
# 這個請求是本機還是遠端
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClientInfo:
    local: bool
    ip: str
    host: str          # 請求的 Host（不含 port）
    scheme: str        # 使用者瀏覽器看到的 http / https


def _split_host(host_header: str) -> tuple[str, int | None]:
    host_header = (host_header or "").strip().lower()
    if host_header.startswith("["):
        end = host_header.find("]")
        name, rest = host_header[: end + 1], host_header[end + 1:]
    else:
        name, _, rest = host_header.partition(":")
        rest = ":" + rest if rest else ""
    port = None
    if rest.startswith(":") and rest[1:].isdigit():
        port = int(rest[1:])
    return name, port


def classify(headers, peer_host: str | None) -> ClientInfo:
    """headers 是 Starlette 的 Headers（小寫鍵）。有任何 Cloudflare 標頭或 Host 不是本機，就算遠端。"""
    host, _ = _split_host(headers.get("host", ""))
    via_cf = any(h in headers for h in CF_HEADERS)
    peer_local = True
    if peer_host:
        try:
            peer_local = ipaddress.ip_address(peer_host).is_loopback
        except ValueError:
            peer_local = peer_host in ("testclient", "localhost")
    if not via_cf and peer_local and host in LOCAL_HOSTS:
        return ClientInfo(True, "local", host, "http")
    ip = (headers.get("cf-connecting-ip") or "").strip() or "unknown"
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        ip = "unknown"
    return ClientInfo(False, ip, host, "https" if via_cf else "http")


def host_allowed(client: ClientInfo, headers, port: int, tunnel_host: str | None, extra_hosts: set[str]) -> bool:
    host, req_port = _split_host(headers.get("host", ""))
    if client.local:
        return req_port in (port, None) and host in LOCAL_HOSTS
    if tunnel_host and host == tunnel_host and req_port in (None, 443):
        return True
    return host in extra_hosts and req_port in (None, 443)


def same_origin(headers, client: ClientInfo) -> bool:
    """會改資料的請求一定要來自同一個網址（防 CSRF：別的網站不能偷偷叫你的瀏覽器送請求）。"""
    source = headers.get("origin") or headers.get("referer") or ""
    if not source or source == "null":
        return False
    parts = urlsplit(source)
    return (parts.netloc or "").lower() == (headers.get("host") or "").lower()


# ---------------------------------------------------------------------------
# 登入狀態（存在資料庫，cookie 只放隨機字串）
# ---------------------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def create_session(db: Database, name: str, client: ClientInfo, user_agent: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO sessions(token_hash, name, csrf, host, created_at, last_seen, ip, user_agent) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (_token_hash(token), name[:30], csrf, client.host, now, now, client.ip, user_agent[:200]))
        conn.execute("DELETE FROM sessions WHERE last_seen < ? OR created_at < ?",
                     (now - SESSION_IDLE_SECONDS, now - SESSION_MAX_SECONDS))
    return token, csrf


def resolve_session(db: Database, token: str | None, client: ClientInfo) -> dict | None:
    if not token or len(token) > 100:
        return None
    row = db.one("SELECT * FROM sessions WHERE token_hash=?", (_token_hash(token),))
    if not row:
        return None
    now = time.time()
    if row["last_seen"] < now - SESSION_IDLE_SECONDS or row["created_at"] < now - SESSION_MAX_SECONDS:
        delete_session(db, token)
        return None
    if row["host"] != client.host:
        return None
    if now - row["last_seen"] > 60:  # 一分鐘最多寫一次，不要每個請求都寫資料庫
        with db.tx() as conn:
            conn.execute("UPDATE sessions SET last_seen=?, ip=? WHERE token_hash=?", (now, client.ip, row["token_hash"]))
    return row


def delete_session(db: Database, token: str | None) -> None:
    if token:
        with db.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def delete_all_sessions(db: Database) -> int:
    with db.tx() as conn:
        return conn.execute("DELETE FROM sessions").rowcount


def active_sessions(db: Database) -> list[dict]:
    cutoff = time.time() - SESSION_IDLE_SECONDS
    return db.all("SELECT name, host, ip, user_agent, created_at, last_seen FROM sessions WHERE last_seen >= ? "
                  "ORDER BY last_seen DESC", (cutoff,))


def cookie_name(client: ClientInfo) -> str:
    return TUNNEL_COOKIE if client.scheme == "https" else LOCAL_COOKIE


# ---------------------------------------------------------------------------
# 猜密碼太多次就暫停
# ---------------------------------------------------------------------------

class LoginThrottle:
    """同一個 IP 15 分鐘內錯 8 次 → 暫停 15 分鐘；全部遠端加起來 10 分鐘錯 60 次 → 遠端登入全部暫停 10 分鐘。
    本機不算（主人永遠不會被自己鎖在外面）。"""

    PER_IP = (8, 15 * 60, 15 * 60)
    GLOBAL = (60, 10 * 60, 10 * 60)

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def _prune(self, key: str, window: float, now: float) -> list[float]:
        hits = [t for t in self._fails.get(key, []) if t > now - window]
        self._fails[key] = hits
        return hits

    def blocked_for(self, client: ClientInfo) -> int:
        """還要等幾秒才能再試（0 = 可以試）。"""
        if client.local:
            return 0
        now = self._clock()
        with self._lock:
            waits = [until - now for key, until in self._blocked.items()
                     if key in (client.ip, "*") and until > now]
        return int(max(waits)) + 1 if waits else 0

    def failed(self, client: ClientInfo) -> None:
        if client.local:
            return
        now = self._clock()
        with self._lock:
            for key, (limit, window, block) in ((client.ip, self.PER_IP), ("*", self.GLOBAL)):
                hits = self._prune(key, window, now)
                hits.append(now)
                if len(hits) >= limit:
                    self._blocked[key] = now + block
                    self._fails[key] = []

    def succeeded(self, client: ClientInfo) -> None:
        with self._lock:
            self._fails.pop(client.ip, None)


# ---------------------------------------------------------------------------
# 回應標頭
# ---------------------------------------------------------------------------

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; "
       "object-src 'none'")


def security_headers(client: ClientInfo) -> dict[str, str]:
    headers = {
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "X-Robots-Tag": "noindex, nofollow",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if client.scheme == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return headers
