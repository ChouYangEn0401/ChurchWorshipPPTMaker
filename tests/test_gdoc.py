from datetime import date

import httpx
import pytest

from worship_ppt.errors import AppError, SourceError
from worship_ppt.gdoc import export_url, fetch_html, guess_date, label_mismatches, lyrics_from_lines, parse_html
from worship_ppt.lyrics import plan_song

from .conftest import DOC_URL, TODAY


def test_real_document_sample(sheet):
    assert sheet.date == "2026-10-11"
    assert sheet.date_text == "10/11"
    assert sheet.team.startswith("主領：小明 / KB：小華")
    assert [s.title for s in sheet.songs] == ["神同在", "常常喜樂", "盼望聖靈", "聖靈請祢來充滿我心"]
    first = sheet.songs[0]
    assert first.sequence == "主 主 副前1 副 主 副前1 副 副前2 副 副"
    assert first.lyrics.startswith("[主]\n從日出到日落 我要歌頌你的大能")
    assert "[副前2]" in first.lyrics
    # 「盼望聖靈」的段落名沒有冒號（主、副、橋），也要認得
    assert "[橋]" in sheet.songs[2].lyrics
    # 段落裡的空行保留下來（換頁）
    assert "我喜樂滿懷\n\n冰冷的心" in sheet.songs[1].lyrics
    assert label_mismatches(sheet.songs[3]) == ["尾"]
    assert sheet.warnings == []


def test_real_doc_songs_plan_cleanly(sheet):
    first = sheet.songs[0]
    plan = plan_song(first.lyrics, first.sequence)
    assert len(plan["slides"]) == 10 and plan["warnings"] == []
    last = sheet.songs[3]
    plan = plan_song(last.lyrics, last.sequence)
    assert [s["label"] for s in plan["slides"] if s["kind"] == "blank"] == ["自由", "尾"]
    assert plan["slides"][-1]["repeat"] == 2


def test_title_split_across_lines_is_joined(sheet):
    assert sheet.songs[1].title == "常常喜樂"


def test_label_detection_variants():
    lines = ["Verse 1:", "Hello", "副：哦 神同在", "", "", "橋", "從我心深處", "[Chorus]", "Sing"]
    assert lyrics_from_lines(lines).split("\n") == [
        "[Verse 1]", "Hello", "[副]", "哦 神同在", "[橋]", "從我心深處", "[Chorus]", "Sing"]


def test_label_from_sequence_is_recognised_even_if_unusual():
    assert lyrics_from_lines(["呼召", "來跟隨我"], {"呼召"}) == "[呼召]\n來跟隨我"
    # 不在歌序、也不是常見段落名的短句，就當歌詞
    assert lyrics_from_lines(["呼召", "來跟隨我"]) == "呼召\n來跟隨我"


def test_guess_date_picks_nearest_upcoming_year():
    assert guess_date(["10/11"], TODAY)[0] == "2026-10-11"
    assert guess_date(["1/4 新年敬拜"], date(2026, 12, 20))[0] == "2027-01-04"
    assert guess_date(["2025/12/25"], TODAY)[0] == "2025-12-25"
    assert guess_date(["沒有日期"], TODAY) == ("", "")


def test_missing_table_is_reported():
    sheet = parse_html("<html><body><p>10/11</p><p>還沒排</p></body></html>", DOC_URL, today=TODAY)
    assert sheet.songs == []
    assert any("找不到歌單表格" in w for w in sheet.warnings)


def test_columns_found_by_header_name_not_position():
    html = """<html><body><table>
      <tr><td>歌詞</td><td>歌名</td><td>歌序</td></tr>
      <tr><td><p>[副]</p><p>哈利路亞</p></td><td><p>讚美之泉</p></td><td><ol><li>副</li><li>副</li></ol></td></tr>
    </table></body></html>"""
    sheet = parse_html(html, DOC_URL, today=TODAY)
    assert sheet.songs[0].title == "讚美之泉"
    assert sheet.songs[0].sequence == "副 副"
    assert sheet.songs[0].lyrics == "[副]\n哈利路亞"


def test_export_url_variants():
    assert export_url(DOC_URL).endswith("/export?format=html")
    assert export_url("https://docs.google.com/document/d/e/2PACX-1vabcdefghijklmnopqrstuvwxyz/pub").endswith("/pub")
    with pytest.raises(AppError):
        export_url("https://example.com/whatever")


def _transport(handler):
    return httpx.MockTransport(handler)


def test_fetch_reports_private_document():
    def handler(request):
        if "accounts.google.com" in str(request.url):
            return httpx.Response(200, text="login")
        return httpx.Response(302, headers={"Location": "https://accounts.google.com/ServiceLogin"})

    with pytest.raises(SourceError) as exc:
        fetch_html(DOC_URL, transport=_transport(handler))
    assert "知道連結" in exc.value.message


def test_fetch_reports_missing_document():
    with pytest.raises(SourceError) as exc:
        fetch_html(DOC_URL, transport=_transport(lambda r: httpx.Response(404)))
    assert "找不到" in exc.value.message


def test_fetch_returns_html(sample_html):
    got = fetch_html(DOC_URL, transport=_transport(lambda r: httpx.Response(200, content=sample_html.encode("utf-8"))))
    assert "<table" in got
