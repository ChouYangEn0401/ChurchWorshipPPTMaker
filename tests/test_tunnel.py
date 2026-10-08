"""對外連結：現在是 CloudServicesPlatform 的 SDK（isdcsp.tunnel.PublicTunnel）在開，這裡測它接在這個程式裡的樣子。"""

import sys
import time
from pathlib import Path

import pytest
from isdcsp.tunnel import PublicTunnel, TunnelDriverError

FAKE = str(Path(__file__).resolve().parent / "fake_cloudflared.py")


def make(tmp_path, **kw):
    return PublicTunnel(8788, command=[sys.executable, FAKE], log_file=tmp_path / "cf.log", watch_seconds=0.2, **kw)


def test_quick_tunnel_lifecycle(tmp_path):
    stopped = []
    tm = make(tmp_path, on_stop=lambda: stopped.append(1))
    assert tm.status()["state"] == "stopped" and tm.current_host() is None
    tm.start()
    status = tm.wait_until_ready(15)
    assert status["state"] == "running"
    assert status["url"] == "https://tidy-bird-sings-loud.trycloudflare.com"
    assert tm.current_host() == "tidy-bird-sings-loud.trycloudflare.com"
    assert "Registered tunnel connection" in (tmp_path / "cf.log").read_text(encoding="utf-8")
    tm.stop()
    assert tm.status()["state"] == "stopped" and tm.current_host() is None
    assert stopped  # 關掉時把遠端登入的人全部登出


def test_tunnel_that_dies_reports_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CF_MODE", "die")
    stopped = []
    tm = make(tmp_path, on_stop=lambda: stopped.append(1))
    tm.start()
    assert tm.wait_until_ready(15)["state"] == "running"
    deadline = time.monotonic() + 15
    while tm.status()["state"] != "error" and time.monotonic() < deadline:
        time.sleep(0.1)
    status = tm.status()
    assert status["state"] == "error" and "中斷" in status["error"]
    assert tm.current_host() is None and stopped    # 斷了也一樣：遠端登入的人全部登出


def test_without_cloudflared_the_button_hears_it_at_once(tmp_path):
    tm = PublicTunnel(8788, cloudflared_path=str(tmp_path / "nowhere" / "cloudflared.exe"))
    assert tm.status()["installed"] is False
    with pytest.raises(TunnelDriverError):
        tm.start()
