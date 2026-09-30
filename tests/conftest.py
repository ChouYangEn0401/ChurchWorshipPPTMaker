"""測試共用的資料：真實 Google 文件的樣本（名字已經換掉）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from worship_ppt.gdoc import parse_html

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 9, 30)
DOC_URL = "https://docs.google.com/document/d/16LDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/edit"


@pytest.fixture
def sample_html() -> str:
    return (FIXTURES / "gdoc_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def sheet(sample_html):
    return parse_html(sample_html, DOC_URL, today=TODAY)
