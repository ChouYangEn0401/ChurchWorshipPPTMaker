"""排版樣式：字型、大小、顏色、位置。存進資料庫前一律整理過（擋掉奇怪的值），預覽和匯出都吃同一份。

位置單位是「吋」，跟 PowerPoint 一樣（4:3 投影片是 10 × 7.5 吋，16:9 是 13.333 × 7.5 吋）。
"""

from __future__ import annotations

import copy
import re

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ALIGNS = ("center", "left", "right")
PARTS = ("title", "segment", "lyrics")

DEFAULT_FONT = "Microsoft JhengHei"

DEFAULT_STYLE: dict = {
    "title": {"font": DEFAULT_FONT, "size": 32, "color": "#FFD966", "bold": True, "shadow": True},
    "segment": {"font": DEFAULT_FONT, "size": 22, "color": "#F4B183", "bold": False, "shadow": True},
    "lyrics": {"font": DEFAULT_FONT, "size": 44, "color": "#FFFFFF", "bold": True, "shadow": True},
    "showHeader": True,      # 上方顯示「歌名 [段落]」
    "showSegment": True,     # 歌名旁邊要不要加 [段落]
    "headerTop": 0.35,       # 歌名列距離上緣（吋）
    "lyricsLeft": 0.5,       # 歌詞框左右各留多少（吋）
    "lyricsTop": 1.8,        # 歌詞框距離上緣（吋）
    "lyricsAlign": "center",
    "lineSpacing": 1.0,      # 行距倍數（PowerPoint 的「單行間距」= 1.0）
    "maxLines": 0,           # 每頁最多幾行（0 = 不自動拆）
    "titleSlide": False,     # 每首歌前面先放一張歌名頁
    "autoFit": True,         # 字太多、快要折行時自動縮小一點
}

PRESETS: list[tuple[str, dict]] = [
    ("標準：白字＋歌名列", {}),
    ("大字：只有歌詞", {
        "showHeader": False,
        "lyrics": {"font": DEFAULT_FONT, "size": 54, "color": "#FFFFFF", "bold": True, "shadow": True},
        "lyricsTop": 1.4, "maxLines": 4,
    }),
    ("桌面版的樣子", {
        "title": {"font": DEFAULT_FONT, "size": 60, "color": "#FFD700", "bold": True, "shadow": False},
        "segment": {"font": DEFAULT_FONT, "size": 30, "color": "#FF4500", "bold": False, "shadow": False},
        "lyrics": {"font": DEFAULT_FONT, "size": 52, "color": "#FFFFFF", "bold": False, "shadow": False},
        "headerTop": 0.4, "lyricsLeft": 0.05, "lyricsTop": 1.8,
    }),
]


def _num(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _part(src, default: dict) -> dict:
    src = src if isinstance(src, dict) else {}
    font = str(src.get("font") or default["font"]).strip()[:60] or default["font"]
    color = str(src.get("color") or "")
    return {
        "font": font,
        "size": round(_num(src.get("size"), default["size"], 8, 200), 1),
        "color": color.upper() if HEX_RE.match(color) else default["color"],
        "bold": bool(src.get("bold", default["bold"])),
        "shadow": bool(src.get("shadow", default["shadow"])),
    }


def clean_style(data: dict | None, base: dict | None = None) -> dict:
    """把使用者送來的樣式整理成完整、安全的樣子；缺的欄位用 base（或預設值）補上。"""
    data = data if isinstance(data, dict) else {}
    base = clean_style(base) if base else copy.deepcopy(DEFAULT_STYLE)
    out = {part: _part(data.get(part), base[part]) for part in PARTS}
    out["showHeader"] = bool(data.get("showHeader", base["showHeader"]))
    out["showSegment"] = bool(data.get("showSegment", base["showSegment"]))
    out["headerTop"] = round(_num(data.get("headerTop"), base["headerTop"], 0, 7), 2)
    out["lyricsLeft"] = round(_num(data.get("lyricsLeft"), base["lyricsLeft"], 0, 5), 2)
    out["lyricsTop"] = round(_num(data.get("lyricsTop"), base["lyricsTop"], 0, 7), 2)
    align = data.get("lyricsAlign", base["lyricsAlign"])
    out["lyricsAlign"] = align if align in ALIGNS else "center"
    out["lineSpacing"] = round(_num(data.get("lineSpacing"), base["lineSpacing"], 0.7, 2.5), 2)
    out["maxLines"] = int(_num(data.get("maxLines"), base["maxLines"], 0, 20))
    out["titleSlide"] = bool(data.get("titleSlide", base["titleSlide"]))
    out["autoFit"] = bool(data.get("autoFit", base["autoFit"]))
    return out


def preset(overrides: dict) -> dict:
    merged = copy.deepcopy(DEFAULT_STYLE)
    merged.update(copy.deepcopy(overrides))
    return clean_style(merged)


def clean_color(value, default: str = "#000000") -> str:
    value = str(value or "")
    return value.upper() if HEX_RE.match(value) else default
