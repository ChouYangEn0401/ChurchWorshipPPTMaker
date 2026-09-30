"""對外連結：用 cloudflared 開一條 Cloudflare 臨時網址（https://xxxx.trycloudflare.com）。

- 不需要 Cloudflare 帳號、不需要網域；每次開都是新的網址（舊網址自動失效）。
- cloudflared 跟著這個程式一起開、一起關；關掉對外連結時，所有遠端登入一起登出。
- 找 cloudflared 的順序：設定頁填的路徑 → PATH → Program Files → winget 安裝的位置。
  沒裝的話：winget install --id Cloudflare.cloudflared
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .errors import AppError

URL_RE = re.compile(r"https://([a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com)\b")
READY_RE = re.compile(r"Registered tunnel connection|Connection [0-9a-f-]+ registered")
LOG_LIMIT = 2 * 1024 * 1024
INSTALL_HINT = "請先安裝 cloudflared：打開「命令提示字元」輸入 winget install --id Cloudflare.cloudflared ，裝好後再按一次。"


def find_cloudflared(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("cloudflared")
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base and (Path(base) / "cloudflared" / "cloudflared.exe").is_file():
                return str(Path(base) / "cloudflared" / "cloudflared.exe")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            link = Path(local) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe"
            if link.is_file():
                return str(link)
            for pkg in (Path(local) / "Microsoft" / "WinGet" / "Packages").glob("Cloudflare.cloudflared*"):
                for exe in pkg.rglob("cloudflared*.exe"):
                    return str(exe)
    return None


def conflicting_config() -> Path | None:
    """~/.cloudflared/config.yml 存在時，臨時網址會失敗（它會去讀那個設定）。"""
    home = Path.home() / ".cloudflared"
    for name in ("config.yml", "config.yaml"):
        if (home / name).is_file():
            return home / name
    return None


class TunnelManager:
    def __init__(self, port: int, log_file: Path, configured_path=lambda: "", on_stop=None, command=None):
        self.port = port
        self.log_file = log_file
        self._configured_path = configured_path
        self._on_stop = on_stop
        self._command = command  # 測試時換成假的 cloudflared
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self.state = "stopped"      # stopped / starting / running / error
        self.hostname: str | None = None
        self.error = ""
        self.started_at: float | None = None

    # ---------- 狀態 ----------
    @property
    def url(self) -> str | None:
        return f"https://{self.hostname}" if self.hostname else None

    def status(self) -> dict:
        with self._lock:
            return {"state": self.state, "url": self.url if self.state == "running" else None,
                    "error": self.error, "startedAt": self.started_at,
                    "installed": bool(self._command or find_cloudflared(self._configured_path()))}

    def current_host(self) -> str | None:
        """Host 檢查用：只有開著（或正在開）的那一條網址算數。"""
        with self._lock:
            return self.hostname if self.state in ("starting", "running") else None

    # ---------- 開 / 關 ----------
    def start(self) -> dict:
        with self._lock:
            if self.state in ("starting", "running"):
                return self.status()
            command = self._command
            if command is None:
                exe = find_cloudflared(self._configured_path())
                if not exe:
                    raise AppError("這台電腦還沒有安裝 cloudflared", INSTALL_HINT)
                conflict = conflicting_config()
                if conflict:
                    raise AppError(f"找到 {conflict}，臨時網址會開不起來",
                                   "那是別的 Cloudflare 設定。先把它改名（例如 config.yml.bak）再按一次。")
                command = [exe]
            args = [*command, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self.port}"]
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("TUNNEL_")}
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                self._proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.PIPE, env=env, creationflags=flags)
            except OSError as exc:
                raise AppError(f"cloudflared 開不起來：{exc}", INSTALL_HINT)
            self.state, self.hostname, self.error, self.started_at = "starting", None, "", time.time()
            proc = self._proc
        threading.Thread(target=self._read_output, args=(proc,), daemon=True, name="cloudflared-log").start()
        threading.Thread(target=self._watch_start, args=(proc,), daemon=True, name="cloudflared-wait").start()
        return self.status()

    def stop(self, reason: str = "") -> dict:
        with self._lock:
            proc, self._proc = self._proc, None
            self.state, self.hostname, self.started_at = "stopped", None, None
            self.error = reason
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._on_stop:
            self._on_stop()
        return self.status()

    def wait_until_ready(self, timeout: float = 60) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.state in ("running", "error", "stopped"):
                break
            time.sleep(0.3)
        return self.status()

    # ---------- 背景執行緒 ----------
    def _read_output(self, proc: subprocess.Popen) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(self.log_file, "w", encoding="utf-8", errors="replace") as log:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace")
                if written < LOG_LIMIT:
                    log.write(line)
                    log.flush()
                    written += len(line)
                with self._lock:
                    if proc is not self._proc:
                        continue
                    if self.hostname is None and (m := URL_RE.search(line)) and m.group(1) != "api.trycloudflare.com":
                        self.hostname = m.group(1)
                    if self.hostname and READY_RE.search(line) and self.state == "starting":
                        self.state = "running"
        proc.wait()
        with self._lock:
            if proc is self._proc and self.state in ("starting", "running"):
                self.state, self.hostname = "error", None
                self.error = "對外連結中斷了（cloudflared 停止執行），請再按一次「開啟」。"
                self._proc = None
        if self._on_stop and proc.returncode is not None:
            self._on_stop()

    def _watch_start(self, proc: subprocess.Popen, timeout: float = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if proc is not self._proc or self.state != "starting":
                    return
            time.sleep(0.5)
        with self._lock:
            if proc is not self._proc or self.state != "starting":
                return
        self.stop("等了一分鐘還是開不起來。可能是網路擋住了 Cloudflare，請換個網路或稍後再試。")
        with self._lock:
            self.state = "error"
