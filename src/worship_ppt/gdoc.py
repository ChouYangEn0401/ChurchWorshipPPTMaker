"""讀敬拜團的 Google 文件（每週歌單）。

做法跟 LINE 提醒機器人讀 Google Sheet 一樣：文件設成「知道連結的人可以檢視」，
直接下載 Google 提供的 HTML 匯出檔，不需要任何金鑰。

文件長相（實際樣本見 tests/fixtures/gdoc_sample.html）：

    10/11
    主領：利亞 / KB：宥辰 / 鼓：莉雯 / Vocal：國旭、暘恩、裕文
    ┌───┬──────┬──────┬───────────┬────────────────┐
    │   │ 歌名 │ 調性 │ 歌序      │ 歌詞           │
    │ 1 │神同在│      │1. 主 2. 主│ 主：…  副前1：… │
    └───┴──────┴──────┴───────────┴────────────────┘

表格可以有好幾個，每個的第一列是欄名；欄的順序不重要，看欄名認（歌名／調性／歌序／歌詞）。
歌詞欄裡「主：」「副前1：」「橋」這種單獨一行的段落名，會轉成程式用的 [主] [副前1] [橋]。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import httpx
import lxml.html

from .errors import AppError, SourceError
from .lyrics import canonical_label, is_known_label, nfkc, normalize_label, parse_sequence, format_sequence

DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]{20,})")
PUB_ID_RE = re.compile(r"/document/d/e/([a-zA-Z0-9_-]{20,})")

NOT_SHARED_HINT = ("請打開那份 Google 文件 → 右上角「共用」→「一般存取權」改成「知道連結的任何人」（檢視者）；"
                   "或是「檔案 → 共用 → 發布到網路」，把發布後的網址貼過來。")

HEADER_WORDS = {
    "title": ("歌名", "曲名", "詩歌", "歌曲", "title", "song"),
    "key": ("調性", "調", "key"),
    "sequence": ("歌序", "順序", "流程", "order", "sequence"),
    "lyrics": ("歌詞", "lyrics"),
}

LABEL_WITH_COLON_RE = re.compile(r"^[\[【]?\s*([^\[\]【】：:]{1,12}?)\s*[\]】]?\s*[：:]\s*(.*)$")
DATE_FULL_RE = re.compile(r"(20\d\d)\s*[/.\-年]\s*(\d{1,2})\s*[/.\-月]\s*(\d{1,2})")
DATE_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-月]\s*(\d{1,2})(?!\d)")
CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


@dataclass
class DocSong:
    title: str
    key: str = ""
    sequence: str = ""
    lyrics: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class DocSheet:
    source_url: str
    date: str = ""          # YYYY-MM-DD，文件裡找不到就是空字串
    date_text: str = ""     # 文件原本寫的（例如 10/11）
    team: str = ""
    songs: list[DocSong] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 下載
# ---------------------------------------------------------------------------

def export_url(url: str) -> str:
    url = (url or "").strip()
    if m := PUB_ID_RE.search(url):
        return f"https://docs.google.com/document/d/e/{m.group(1)}/pub"
    if m := DOC_ID_RE.search(url):
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=html"
    raise AppError("看不懂這個 Google 文件網址",
                   "請貼整串網址，長得像 https://docs.google.com/document/d/……/edit")


def fetch_html(url: str, timeout: float = 20, transport: httpx.BaseTransport | None = None) -> str:
    target = export_url(url)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport,
                          headers={"User-Agent": "worship-ppt/0.1"}) as client:
            resp = client.get(target)
    except httpx.TimeoutException:
        raise SourceError("連 Google 文件逾時", "網路可能比較慢，等一下再按一次。")
    except httpx.HTTPError as exc:
        raise SourceError(f"連不上 Google 文件：{exc.__class__.__name__}", "請確認這台電腦有連上網路。")
    landed_on_login = "accounts.google.com" in str(resp.url) or "ServiceLogin" in str(resp.url)
    if landed_on_login or resp.status_code in (401, 403):
        raise SourceError("這份 Google 文件沒有開放「知道連結的人可以檢視」", NOT_SHARED_HINT)
    if resp.status_code == 404:
        raise SourceError("找不到這份 Google 文件", "網址可能貼錯了，或文件已經被刪除。")
    if resp.status_code >= 400:
        raise SourceError(f"Google 文件回應錯誤（HTTP {resp.status_code}）", "等一下再試一次。")
    return resp.content.decode("utf-8", errors="replace")


def fetch_sheet(url: str, today: date | None = None, **kwargs) -> DocSheet:
    return parse_html(fetch_html(url, **kwargs), url, today=today)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def _text(el) -> str:
    """一個段落的文字；<br> 變換行、&nbsp; 變空白。"""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        if child.tag == "br":
            parts.append("\n")
        else:
            parts.append(_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).replace("\xa0", " ")


def _cell_lines(cell) -> list[str]:
    """表格一格裡的每一行（段落 / 清單項目）。空段落回傳空字串，保留「空一行」的意思。"""
    blocks = [el for el in cell.iter() if el.tag in ("p", "li", "h1", "h2", "h3", "h4")]
    if not blocks:
        return [line for line in _text(cell).split("\n")]
    lines: list[str] = []
    for el in blocks:
        # 巢狀清單時外層 li 的文字會包含內層，只取沒有子區塊的那層
        if any(child.tag in ("p", "li", "ul", "ol") for child in el):
            continue
        lines.extend(_text(el).split("\n"))
    return lines


def _join_title(lines: list[str]) -> str:
    """歌名在格子裡被折成兩行（「常常」「喜樂」）→ 接回「常常喜樂」；英文中間補空白。"""
    title = ""
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        if title and not (CJK_RE.search(title[-1]) and CJK_RE.search(line[0])):
            title += " "
        title += line
    return title


def _header_map(texts: list[str]) -> dict[str, int] | None:
    found: dict[str, int] = {}
    for idx, text in enumerate(texts):
        norm = re.sub(r"\s+", "", nfkc(text)).lower()
        if not norm or len(norm) > 8:
            continue
        for field_name, words in HEADER_WORDS.items():
            if field_name not in found and any(norm == w or norm.startswith(w) for w in words):
                found[field_name] = idx
                break
    if "title" in found and ("lyrics" in found or "sequence" in found):
        return found
    return None


def lyrics_from_lines(lines: list[str], known_labels: set[str] | None = None) -> str:
    """把文件裡的歌詞行轉成 [段落] 格式。

    認得的段落名：
      - 「主：」「副前1：」「Verse 1:」這種後面接冒號的短字（冒號後面還有字就當作第一行歌詞）
      - 單獨一行、剛好是常見段落名（主、副、橋、Chorus…）或歌序裡出現過的名字
      - 本來就寫成 [Verse] 的也照收
    """
    known = known_labels or set()
    out: list[str] = []
    for raw in lines:
        s = raw.strip() if raw else ""
        if not s:
            if out and out[-1] != "" and not out[-1].startswith("["):
                out.append("")
            continue
        bracket = re.match(r"^[\[【]\s*(.+?)\s*[\]】]$", s)
        if bracket:
            _push_label(out, bracket.group(1))
            continue
        m = LABEL_WITH_COLON_RE.match(s)
        if m and (is_known_label(m.group(1)) or canonical_label(m.group(1)) in known
                  or (not m.group(2) and len(m.group(1)) <= 6)):
            _push_label(out, m.group(1).strip())
            if m.group(2).strip():
                out.append(m.group(2).strip())
            continue
        if len(s) <= 12 and (is_known_label(s) or canonical_label(s) in known):
            _push_label(out, s)
            continue
        out.append(s)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _push_label(out: list[str], label: str) -> None:
    while out and out[-1] == "":
        out.pop()
    out.append(f"[{label}]")


def _sequence_from_lines(lines: list[str]) -> str:
    tokens = parse_sequence("\n".join(lines))
    return format_sequence(tokens)


def guess_date(texts: list[str], today: date) -> tuple[str, str]:
    """文件開頭的「10/11」→ 最接近今天的那個日期（快過年時 1/4 會算成明年）。"""
    for text in texts:
        t = nfkc(text)
        if m := DATE_FULL_RE.search(t):
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), m.group(0)
            except ValueError:
                continue
        if m := DATE_MD_RE.search(t):
            month, day = int(m.group(1)), int(m.group(2))
            candidates = []
            for year in (today.year - 1, today.year, today.year + 1):
                try:
                    candidates.append(date(year, month, day))
                except ValueError:
                    pass
            if candidates:
                # 歌單通常是做「接下來」的聚會：以兩個月後為中心，挑最接近的那一年
                best = min(candidates, key=lambda d: abs((d - (today + timedelta(days=60))).days))
                return best.isoformat(), m.group(0)
    return "", ""


def parse_html(html: str, source_url: str = "", today: date | None = None) -> DocSheet:
    today = today or date.today()
    root = lxml.html.fromstring(html)
    for bad in root.xpath("//style|//script|//head"):
        bad.drop_tree()
    body = root.find("body") if root.find("body") is not None else root
    sheet = DocSheet(source_url=source_url)

    # 第一個表格之前的文字：日期、服事同工
    intro: list[str] = []
    for el in body.iter():
        if el.tag == "table":
            break
        if el.tag in ("p", "h1", "h2", "h3", "h4", "li"):
            t = re.sub(r"\s+", " ", _text(el)).strip()
            if t:
                intro.append(t)
    sheet.date, sheet.date_text = guess_date(intro, today)
    team_parts: list[str] = []
    for t in intro:
        if sheet.date_text and sheet.date_text in nfkc(t):
            t = nfkc(t).replace(sheet.date_text, "", 1).strip(" -:：")
        if t:
            team_parts.append(re.sub(r"\s*/\s*", " / ", t))
    sheet.team = " ".join(team_parts).strip()

    for table in body.iter("table"):
        header: dict[str, int] | None = None
        for tr in table.iter("tr"):
            cells = [c for c in tr if c.tag in ("td", "th")]
            texts = [_text(c).strip() for c in cells]
            hm = _header_map(texts)
            if hm:
                header = hm
                continue
            if header is None:
                continue

            def lines_at(name: str) -> list[str]:
                idx = header.get(name)
                return _cell_lines(cells[idx]) if idx is not None and idx < len(cells) else []

            title = _join_title(lines_at("title"))
            seq_lines = lines_at("sequence")
            sequence = _sequence_from_lines(seq_lines)
            known = {canonical_label(t.label) for t in parse_sequence(sequence)}
            lyrics = lyrics_from_lines(lines_at("lyrics"), known)
            key = " ".join(ln.strip() for ln in lines_at("key") if ln.strip())
            if not title and not lyrics:
                continue
            song = DocSong(title=title or "（沒有歌名）", key=key, sequence=sequence, lyrics=lyrics)
            if not title:
                song.warnings.append("文件裡這一列沒有歌名")
            if not lyrics:
                song.warnings.append("文件裡這首歌沒有歌詞")
            sheet.songs.append(song)

    if not sheet.songs:
        sheet.warnings.append("文件裡找不到歌單表格（要有「歌名」和「歌詞」或「歌序」這些欄名）")
    if not sheet.date:
        sheet.warnings.append("文件開頭找不到日期，請自己填聚會日期")
    return sheet


def label_mismatches(song: DocSong) -> list[str]:
    """歌序裡提到、歌詞裡卻沒有的段落（給匯入預覽畫面提醒用）。"""
    from .lyrics import parse_sections, INSTRUMENTAL

    have = {canonical_label(s.label) for s in parse_sections(song.lyrics)}
    missing = []
    for tok in parse_sequence(song.sequence):
        if canonical_label(tok.label) not in have and normalize_label(tok.label) not in INSTRUMENTAL:
            if tok.label not in missing:
                missing.append(tok.label)
    return missing
