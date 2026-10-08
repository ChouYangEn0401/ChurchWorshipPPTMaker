import sys
from pathlib import Path

from worship_ppt.tunnel import TunnelManager

FAKE = str(Path(__file__).resolve().parent / "fake_cloudflared.py")


def test_quick_tunnel_lifecycle(tmp_path):
    stopped = []
    tm = TunnelManager(8788, tmp_path / "cf.log", command=[sys.executable, FAKE], on_stop=lambda: stopped.append(1))
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
    tm = TunnelManager(8788, tmp_path / "cf.log", command=[sys.executable, FAKE])
    tm.start()
    status = tm.wait_until_ready(15)
    assert status["state"] == "error"
    assert "中斷" in status["error"]
    assert tm.current_host() is None
