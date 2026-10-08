"""測試共用：每個測試都用一個全新的資料夾（WORSHIP_PPT_HOME），絕對不碰真正的 data/。"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from worship_ppt import store
from worship_ppt.gdoc import parse_html
from worship_ppt.paths import Paths

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 9, 30)
DOC_URL = "https://docs.google.com/document/d/16LDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/edit"
TUNNEL_HOST = "tidy-bird-sings-loud.trycloudflare.com"
# 伺服器只綁 127.0.0.1，所以連進來的永遠是這台電腦（瀏覽器或 cloudflared）。測試用的連線也要是這樣：
# 門口（isdcsp.web.Site）會擋掉「不是這台電腦」的連線，Starlette 預設的 "testclient" 不是 IP。
PEER = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORSHIP_PPT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORSHIP_PPT_ALLOWED_HOSTS", raising=False)


@pytest.fixture
def paths(tmp_path) -> Paths:
    p = Paths(tmp_path / "home")
    p.root.mkdir(parents=True, exist_ok=True)
    p.ensure()
    return p


@pytest.fixture
def db(paths):
    return store.open_db(paths)


@pytest.fixture
def sample_html() -> str:
    return (FIXTURES / "gdoc_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def sheet(sample_html):
    return parse_html(sample_html, DOC_URL, today=TODAY)


@pytest.fixture
def legacy_files(paths):
    """把 repo 裡桌面版的存檔和背景圖（legacy/desktop/）複製到測試資料夾的同一個位置。"""
    paths.legacy_file.parent.mkdir(parents=True, exist_ok=True)
    for name in ("ppt_settings.json", "pic1.png", "pic2.png", "pic3.png", "pic4.png", "background.jpg"):
        src = REPO / "legacy" / "desktop" / name
        if src.exists():
            shutil.copy(src, paths.legacy_file.parent / name)
    return paths.legacy_file


@pytest.fixture
def app(paths):
    from worship_ppt.web.app import create_app

    application = create_app(paths, port=8788)
    # 假裝對外連結開著，網址是 TUNNEL_HOST（不真的啟動 cloudflared）
    application.state.tunnel.hosts = lambda: {TUNNEL_HOST}
    return application


LOCAL_BASE = "http://127.0.0.1:8788"
LOCAL_HEADERS = {"Origin": LOCAL_BASE}


@pytest.fixture
def local(app):
    """在主機電腦上用瀏覽器（不用登入）。"""
    return TestClient(app, base_url=LOCAL_BASE, headers=LOCAL_HEADERS, client=PEER)


def remote_client(app, ip: str = "203.0.113.7") -> TestClient:
    """透過 Cloudflare 臨時網址進來的人。"""
    base = f"https://{TUNNEL_HOST}"
    return TestClient(app, base_url=base, follow_redirects=False, client=PEER,
                      headers={"cf-connecting-ip": ip, "cf-ray": "abc", "Origin": base})
