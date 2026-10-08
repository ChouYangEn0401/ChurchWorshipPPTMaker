"""歌詞 → 投影片的規則。網頁預覽（static/js/lyrics.js）用一模一樣的規則，測試會逐項比對兩邊結果。

歌詞格式（跟桌面版一樣）：

    [主]
    從日出到日落 我要歌頌你的大能
    並在列邦中述說你的同在

    我要跳舞讚美祂 擊鼓彈琴向祂歡呼      ← 段落裡空一行 = 換下一頁
    [副]
    哦！神同在 哦！神同在

- `[段落名]` 開始一個段落；段落名可以是中文（主、副、副前1、橋）或英文（Verse、Chorus）。
- 同一段落裡空一行就換頁；「每頁最多幾行」有設定時，太長的頁會自動平均拆開。
- 歌序（例如「主 主 副前1 副 副」）決定投影片順序，重複的段落會重複出現；
  主／主歌／Verse／V 視為同一種段落，副／副歌／Chorus／C 也是，後面的數字要一樣（副前1 ≠ 副前2）。
- 歌序裡寫了但歌詞裡找不到的段落（前奏、間奏、自由…）放一張只有背景的空白頁。
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

LABEL_LINE_RE = re.compile(r"^\s*[\[【]\s*(.+?)\s*[\]】]\s*$")

# 同一種段落的各種寫法（全部小寫、去空白後比對）；左邊是統一後的名字
ALIASES: dict[str, tuple[str, ...]] = {
    "主": ("主", "主歌", "verse", "v"),
    "副": ("副", "副歌", "chorus", "c", "cho"),
    "副前": ("副前", "導歌", "預副", "prechorus", "pre-chorus", "pre", "pc"),
    "橋": ("橋", "橋段", "bridge", "b"),
    "前奏": ("前奏", "intro"),
    "間奏": ("間奏", "interlude", "inst", "instrumental"),
    "尾": ("尾", "尾奏", "結尾", "ending", "outro", "end"),
}
_ALIAS_LOOKUP = {name: canon for canon, names in ALIASES.items() for name in names}

# 這些段落本來就沒有歌詞：歌序寫到它們時放空白頁，不需要提醒
INSTRUMENTAL = {"前奏", "間奏", "自由", "禱告", "自由敬拜", "rap"}

SEQ_SPLIT_RE = re.compile(r"[\n,，、;；/→>|]+|\s+")
SEQ_NUMBERING_RE = re.compile(r"^\(?\d+[.)、]")
SEQ_REPEAT_RE = re.compile(r"^(.*?)\(?[*xX×](\d+)\)?$")
SEQ_STANDALONE_REPEAT_RE = re.compile(r"^\(?[*xX×](\d+)\)?$")


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def normalize_label(label: str) -> str:
    """比對用：全形轉半形、去掉冒號與空白、英文轉小寫。"""
    s = nfkc(label).strip()
    s = re.sub(r"[：:]+$", "", s)
    s = re.sub(r"\s+", "", s)
    return s.lower()


def canonical_label(label: str) -> str:
    """把「Verse 1」「主歌1」「V1」都變成「主1」，比對歌序和段落時用。"""
    s = normalize_label(label)
    m = re.match(r"^(.*?)(\d*)$", s)
    base, num = (m.group(1), m.group(2)) if m else (s, "")
    base = base.rstrip("-_.")
    canon = _ALIAS_LOOKUP.get(base)
    if canon is None:
        return s
    return canon + num


def is_known_label(label: str) -> bool:
    """看起來像段落名嗎（主、副2、Verse 1、前奏…）。Google 文件匯入時用來認出段落。"""
    s = normalize_label(label)
    m = re.match(r"^(.*?)(\d*)$", s)
    base = (m.group(1) if m else s).rstrip("-_.")
    return base in _ALIAS_LOOKUP or s in INSTRUMENTAL


# ---------------------------------------------------------------------------
# 歌詞 → 段落
# ---------------------------------------------------------------------------

@dataclass
class Section:
    label: str
    pages: list[str] = field(default_factory=list)


def _split_pages(lines: list[str]) -> list[str]:
    pages: list[str] = []
    current: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            if current:
                pages.append("\n".join(current))
                current = []
            continue
        current.append(text)
    if current:
        pages.append("\n".join(current))
    return pages


def parse_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    label: str | None = None
    lines: list[str] = []

    def flush() -> None:
        pages = _split_pages(lines)
        if label is not None or pages:
            sections.append(Section(label or "", pages))

    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = LABEL_LINE_RE.match(raw)
        if m:
            flush()
            label = m.group(1).strip()
            lines = []
            continue
        lines.append(raw)
    flush()
    return sections


def split_long_page(page: str, max_lines: int) -> list[str]:
    """一頁超過 max_lines 行就平均拆成幾頁（5 行、每頁最多 4 行 → 3 + 2）。"""
    lines = page.split("\n")
    if max_lines <= 0 or len(lines) <= max_lines:
        return [page]
    chunks = math.ceil(len(lines) / max_lines)
    size = math.ceil(len(lines) / chunks)
    return ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]


# ---------------------------------------------------------------------------
# 歌序
# ---------------------------------------------------------------------------

@dataclass
class SeqToken:
    label: str
    repeat: int = 1


def parse_sequence(text: str) -> list[SeqToken]:
    tokens: list[SeqToken] = []
    for part in SEQ_SPLIT_RE.split(nfkc(text)):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d+", part):
            # 「Verse 1」被空白切開了 → 接回前一個英文段落名；其他單獨的數字（編號）略過
            if tokens and re.search(r"[a-zA-Z]$", tokens[-1].label):
                tokens[-1].label += " " + part
            continue
        standalone = SEQ_STANDALONE_REPEAT_RE.match(part)
        if standalone:
            # 「副 x2」「副 (×2)」：次數寫在後面、被空白切開了 → 算在前一個段落
            if tokens:
                tokens[-1].repeat = max(1, int(standalone.group(1)))
            continue
        part = SEQ_NUMBERING_RE.sub("", part).strip()
        if not part:
            continue
        repeat = 1
        m = SEQ_REPEAT_RE.match(part)
        if m and m.group(1).strip():
            part, repeat = m.group(1).strip(), max(1, int(m.group(2)))
        part = re.sub(r"[：:]+$", "", part).strip()
        if part:
            tokens.append(SeqToken(part, repeat))
    return tokens


def format_sequence(tokens: list[SeqToken]) -> str:
    return " ".join(t.label + (f"*{t.repeat}" if t.repeat > 1 else "") for t in tokens)


# ---------------------------------------------------------------------------
# 一首歌 → 投影片清單
# ---------------------------------------------------------------------------

def plan_song(lyrics: str, sequence: str = "", *, follow_sequence: bool = True,
              max_lines: int = 0, title_slide: bool = False) -> dict:
    """回傳 {"slides": [...], "warnings": [...], "labels": [...]}。

    每張投影片是 {"kind": "title"|"lyrics"|"blank", "label": 段落名, "text": 歌詞, "repeat": 次數}。
    labels 是歌詞裡出現的段落名（編輯畫面拿來做「點一下加進歌序」的按鈕）。
    """
    sections = parse_sections(lyrics)
    slides: list[dict] = []
    warnings: list[str] = []
    labels = [s.label for s in sections if s.label]

    if title_slide:
        slides.append({"kind": "title", "label": "", "text": "", "repeat": 1})

    def emit(section: Section, repeat: int) -> None:
        pages: list[str] = []
        for page in section.pages:
            pages.extend(split_long_page(page, max_lines))
        if not pages:
            slides.append({"kind": "blank", "label": section.label, "text": "", "repeat": repeat})
            return
        for page in pages:
            slides.append({"kind": "lyrics", "label": section.label, "text": page, "repeat": repeat})

    tokens = parse_sequence(sequence) if follow_sequence else []
    if tokens:
        index: dict[str, Section] = {}
        for s in sections:
            index.setdefault(canonical_label(s.label), s)
        used: set[str] = set()
        missing: list[str] = []
        for tok in tokens:
            key = canonical_label(tok.label)
            section = index.get(key)
            if section is None:
                slides.append({"kind": "blank", "label": tok.label, "text": "", "repeat": tok.repeat})
                if normalize_label(tok.label) not in INSTRUMENTAL and tok.label not in missing:
                    missing.append(tok.label)
                continue
            used.add(key)
            emit(section, tok.repeat)
        for label in missing:
            warnings.append(f"歌序裡的「{label}」在歌詞找不到，先放一張空白頁")
        for s in sections:
            if s.pages and canonical_label(s.label) not in used:
                name = s.label or "（最前面沒有標段落的歌詞）"
                warnings.append(f"「{name}」沒有出現在歌序裡，不會放進 PPT")
    else:
        for s in sections:
            emit(s, 1)

    if not any(s["kind"] == "lyrics" for s in slides) and (lyrics or "").strip() == "":
        warnings.append("還沒有歌詞")
    return {"slides": slides, "warnings": warnings, "labels": labels}


# ---------------------------------------------------------------------------
# 字太多時自動縮小（PowerPoint 和網頁預覽用同一套估算，兩邊字級一定一樣）
# ---------------------------------------------------------------------------

LINE_HEIGHT = 1.2      # 微軟正黑體在 PowerPoint「單行間距」時，一行大約是字級的 1.2 倍高
WIDTH_SAFETY = 0.97    # 估算寬度留 3% 餘裕
NO_ORPHAN_RATIO = 0.85  # 只差一點點就會折行（最後一兩個字掉到下一行）時，最多縮到 85% 讓它排成一行
MIN_FIT_RATIO = 0.5


def char_em(ch: str) -> float:
    """一個字大約佔多寬（以字級為 1）。中文、全形字 = 1；英文數字大約一半。"""
    o = ord(ch)
    if ch == " ":
        return 0.28
    if o >= 0x0250:
        return 1.0
    if "A" <= ch <= "Z":
        return 0.65
    if ch in "il.,:;'|!()[]{}`\"":
        return 0.3
    return 0.52


def text_em(text: str) -> float:
    return sum(char_em(ch) for ch in text)


def wrap_at_spaces(line: str, size: float, box_w: float) -> list[str]:
    """一行放不下時，從空白處（歌詞的句讀）折成兩行，挑讓兩半最平均的那個空白；還是太長就再折。
    沒有空白的長句就交給 PowerPoint 自己折。"""
    if text_em(line) * size <= box_w or " " not in line.strip():
        return [line]
    parts = line.split(" ")
    best: tuple[float, str, str] | None = None
    for i in range(1, len(parts)):
        left = " ".join(parts[:i]).strip()
        right = " ".join(parts[i:]).strip()
        if not left or not right:
            continue
        score = max(text_em(left), text_em(right))
        if best is None or score < best[0]:
            best = (score, left, right)
    if best is None:
        return [line]
    return wrap_at_spaces(best[1], size, box_w) + wrap_at_spaces(best[2], size, box_w)


def fit_lines(lines: list[str], base: float, box_w: float, box_h: float, line_spacing: float,
              auto_fit: bool = True) -> tuple[float, list[str]]:
    """在寬 box_w、高 box_h（單位：點）的框裡排歌詞，回傳 (字級, 排好的每一行)。

    1. 最長的一行只差一點點（縮到 85% 以內就放得下）→ 整頁縮小一點，保持原本的分行。
    2. 還是放不下的行從空白處折行。
    3. 整頁太高就一點一點縮小，直到放得下（最多縮到一半）。auto_fit 關掉時只做第 2 步。
    """
    box_w = max(box_w, 72.0)
    size = base
    widths = [text_em(line) for line in lines]
    if auto_fit and widths and max(widths) > 0:
        no_wrap = box_w / max(widths)
        if size * NO_ORPHAN_RATIO <= no_wrap < size:
            size = math.floor(no_wrap * 2) / 2

    def arrange(sz: float) -> list[str]:
        out: list[str] = []
        for line in lines:
            out.extend(wrap_at_spaces(line, sz, box_w))
        return out

    def fits(sz: float, arranged: list[str]) -> bool:
        rows = sum(max(1, math.ceil(text_em(x) * sz / box_w - 1e-9)) for x in arranged)
        return rows * sz * LINE_HEIGHT * line_spacing <= box_h + 1e-6

    arranged = arrange(size)
    if auto_fit:
        min_size = max(8.0, base * MIN_FIT_RATIO)
        while size > min_size and not fits(size, arranged):
            size = max(min_size, size - 1)
            arranged = arrange(size)
    return size, arranged


def lyrics_layout(text: str, style: dict, slide_w: float, slide_h: float) -> tuple[float, list[str]]:
    """一頁歌詞實際的字級和分行（PPT 和網頁預覽都用這個結果）。"""
    base = style["lyrics"]["size"]
    if not text:
        return base, []
    box_w = (slide_w - 2 * style["lyricsLeft"]) * 72 * WIDTH_SAFETY
    box_h = (slide_h - style["lyricsTop"] - 0.25) * 72
    return fit_lines(text.split("\n"), base, box_w, box_h, style["lineSpacing"], style.get("autoFit", True))


def header_scale(title: str, label: str, style: dict, slide_w: float) -> float:
    """歌名列太長就整排等比例縮小（最多縮到 60%），保持一行。"""
    if not style.get("autoFit", True):
        return 1.0
    width = text_em(title) * style["title"]["size"]
    if label and style["showSegment"]:
        width += text_em("  [" + label + "]") * style["segment"]["size"]
    box_w = (slide_w - 1.0) * 72 * WIDTH_SAFETY
    if width <= box_w:
        return 1.0
    return max(0.6, math.floor(box_w / width * 100) / 100)


def title_page_size(title: str, style: dict, slide_w: float, slide_h: float) -> float:
    base = max(style["title"]["size"] * 1.5, style["lyrics"]["size"])
    if not style.get("autoFit", True) or not title:
        return base
    size, _ = fit_lines([title], base, (slide_w - 1.0) * 72 * WIDTH_SAFETY, slide_h * 72 * 0.8, 1.0)
    return size
