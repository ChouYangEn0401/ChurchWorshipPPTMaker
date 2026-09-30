"""測試共用：每個測試都用一個全新的資料夾（WORSHIP_PPT_HOME），絕對不碰真正的 data/。"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from worship_ppt import store
from worship_ppt.gdoc import parse_html
from worship_ppt.paths import Paths

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 9, 30)
DOC_URL = "https://docs.google.com/document/d/16LDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/edit"


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
    """把 repo 裡桌面版的存檔和背景圖複製到測試資料夾。"""
    for name in ("ppt_settings.json", "pic1.png", "pic2.png", "pic3.png", "pic4.png", "background.jpg"):
        src = REPO / name
        if src.exists():
            shutil.copy(src, paths.root / name)
    return paths.root / "ppt_settings.json"
