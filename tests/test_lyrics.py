from worship_ppt.lyrics import (
    canonical_label, fit_lines, lyrics_layout, parse_sections, parse_sequence, plan_song, split_long_page,
    text_em, wrap_at_spaces,
)
from worship_ppt.styles import clean_style


def test_sections_and_blank_line_page_breaks():
    text = "[主]\nA1\nA2\n\nA3\n[副]\nB1\n\n\nB2\n"
    sections = parse_sections(text)
    assert [(s.label, s.pages) for s in sections] == [("主", ["A1\nA2", "A3"]), ("副", ["B1", "B2"])]


def test_lyrics_without_labels_still_make_pages():
    sections = parse_sections("第一行\n第二行\n\n第三行")
    assert [(s.label, s.pages) for s in sections] == [("", ["第一行\n第二行", "第三行"])]


def test_full_width_brackets_and_empty_section():
    sections = parse_sections("【前奏】\n【副】\n哦")
    assert [(s.label, s.pages) for s in sections] == [("前奏", []), ("副", ["哦"])]


def test_sequence_parsing_handles_doc_numbering_repeats_and_separators():
    seq = parse_sequence("1. 主\n2. 主\n3. 副前1\n10. 尾*2")
    assert [(t.label, t.repeat) for t in seq] == [("主", 1), ("主", 1), ("副前1", 1), ("尾", 2)]
    assert [(t.label, t.repeat) for t in parse_sequence("主、副，橋 / 副 x2")] == [("主", 1), ("副", 1), ("橋", 1), ("副", 2)]
    assert [t.label for t in parse_sequence("Verse 1, Chorus, Verse 2")] == ["Verse 1", "Chorus", "Verse 2"]
    assert [(t.label, t.repeat) for t in parse_sequence("副（×3） 橋(x2)")] == [("副", 3), ("橋", 2)]


def test_label_aliases():
    assert canonical_label("Verse 1") == canonical_label("主歌1") == canonical_label("V1") == "主1"
    assert canonical_label("副：") == canonical_label("Chorus") == "副"
    assert canonical_label("副前1") != canonical_label("副前2")
    assert canonical_label("Pre-Chorus") == "副前"


def test_plan_follows_sequence_with_repeats_and_blank_for_missing():
    lyrics = "[主]\nA\n[副]\nB1\n\nB2"
    plan = plan_song(lyrics, "主 副 前奏 尾 主")
    assert [(s["kind"], s["label"], s["text"]) for s in plan["slides"]] == [
        ("lyrics", "主", "A"), ("lyrics", "副", "B1"), ("lyrics", "副", "B2"),
        ("blank", "前奏", ""), ("blank", "尾", ""), ("lyrics", "主", "A")]
    # 前奏本來就沒有歌詞 → 不提醒；尾 → 提醒
    assert plan["warnings"] == ["歌序裡的「尾」在歌詞找不到，先放一張空白頁"]


def test_plan_warns_about_sections_left_out_of_sequence():
    plan = plan_song("[主]\nA\n[橋]\nC", "主")
    assert "「橋」沒有出現在歌序裡，不會放進 PPT" in plan["warnings"]


def test_plan_without_sequence_or_when_disabled_uses_written_order():
    lyrics = "[主]\nA\n[副]\nB"
    assert [s["label"] for s in plan_song(lyrics, "")["slides"]] == ["主", "副"]
    assert [s["label"] for s in plan_song(lyrics, "副 副 主", follow_sequence=False)["slides"]] == ["主", "副"]


def test_title_slide_and_max_lines():
    plan = plan_song("[主]\n1\n2\n3\n4\n5", "", max_lines=4, title_slide=True)
    assert [s["kind"] for s in plan["slides"]] == ["title", "lyrics", "lyrics"]
    assert [s["text"] for s in plan["slides"][1:]] == ["1\n2\n3", "4\n5"]
    assert split_long_page("a\nb", 0) == ["a\nb"]


def test_text_width_estimate():
    assert text_em("神同在") == 3.0
    assert text_em("AB") == 1.3
    assert text_em("ab 1") < 2.0


def test_wrap_at_spaces_picks_balanced_phrase_break():
    line = "我要追求祢主 我將生命獻給祢"
    assert wrap_at_spaces(line, 44, 100000) == [line]
    assert wrap_at_spaces(line, 44, 44 * 10) == ["我要追求祢主", "我將生命獻給祢"]
    assert wrap_at_spaces("沒有空白的很長很長很長的一句", 44, 44 * 5) == ["沒有空白的很長很長很長的一句"]


def test_fit_shrinks_a_little_instead_of_leaving_an_orphan():
    # 15.28 em 的一行在 14.7 em 寬的框：縮小一點就能放一行，不要拆
    lines = ["我要跳舞讚美祂 擊鼓彈琴向祂歡呼"]
    size, arranged = fit_lines(lines, 44, 44 * 14.7, 1000, 1.0)
    assert size < 44 and size >= 44 * 0.85
    assert arranged == lines


def test_fit_breaks_at_phrases_then_shrinks_to_fit_height():
    style = clean_style({"lyrics": {"size": 54}, "lyricsTop": 1.4})
    text = "我要追求祢主 我將生命獻給祢\n牽引我更親近祢 祢大能更新我靈\n無人能與祢相比 主我仰望祢的榮面\n我敬拜祢在靈與真理裡"
    size, lines = lyrics_layout(text, style, 10.0, 7.5)
    assert lines[:2] == ["我要追求祢主", "我將生命獻給祢"]
    assert size < 54
    rows = len(lines)
    assert rows * size * 1.2 <= (7.5 - 1.4 - 0.25) * 72 + 1e-6


def test_autofit_off_keeps_size():
    style = clean_style({"autoFit": False, "lyrics": {"size": 80}})
    size, _ = lyrics_layout("很長很長很長很長很長很長很長很長很長很長很長很長", style, 10.0, 7.5)
    assert size == 80
