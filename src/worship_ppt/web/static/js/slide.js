// 在網頁上畫一張投影片（預覽、背景庫、排版的縮圖都用這個）。
// 尺寸全部用「吋」換算成投影片寬度的百分比（cqw），跟 pptx_builder.py 用同一組數字，
// 字級、折行也是 lyrics.js 算出來的（跟 PPT 一樣），所以預覽 ≈ 成品。

import { headerScale, lyricsLayout, lyricsOverflow, titlePageSize, LINE_HEIGHT } from "./lyrics.js";

export const SIZES = { "4:3": [10, 7.5], "16:9": [13.333, 7.5] };

export function mediaUrl(image, width = 960) {
  if (!image) return "";
  return `/media/${image.id}` + (width ? `?w=${width}` : "");
}

function cqw(pt, slideW) {
  return ((pt / 72) / slideW * 100).toFixed(3) + "cqw";
}

function fontStack(name) {
  const safe = String(name || "").replace(/["\\]/g, "");
  return `"${safe}", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif`;
}

function styleText(node, part, size, slideW) {
  node.style.fontFamily = fontStack(part.font);
  node.style.fontSize = cqw(size, slideW);
  node.style.fontWeight = part.bold ? "700" : "400";
  node.style.color = part.color;
  if (part.shadow) {
    node.style.textShadow = `${cqw(2, slideW)} ${cqw(2, slideW)} ${cqw(4, slideW)} rgba(0,0,0,.7)`;
  }
}

export function paintBackground(node, theme, width = 960) {
  node.style.backgroundColor = (theme && theme.bgColor) || "#000";
  node.style.backgroundImage = theme && theme.image ? `url("${mediaUrl(theme.image, width)}")` : "none";
  node.querySelectorAll(":scope > .ov").forEach((o) => o.remove());
  if (theme && theme.overlay > 0) {
    const ov = document.createElement("div");
    ov.className = "ov";
    ov.style.opacity = String(theme.overlay);
    node.prepend(ov);
  }
}

/**
 * info:  { kind: "lyrics"|"blank"|"title", label, text, repeat }
 * ctx:   { title, theme, style, size: "4:3"|"16:9", thumb: 320|960 }
 * 回傳 { el, over }：over = 字太多、會超出投影片下緣
 */
export function renderSlide(info, ctx) {
  const [W, H] = SIZES[ctx.size] || SIZES["4:3"];
  const style = ctx.style;
  const el = document.createElement("div");
  el.className = "slide";
  el.style.setProperty("--aspect", `${W} / ${H}`);
  paintBackground(el, ctx.theme, ctx.thumb || 960);
  let over = false;

  if (info.kind === "title") {
    const tt = document.createElement("div");
    tt.className = "tt";
    tt.textContent = ctx.title || "";
    styleText(tt, style.title, titlePageSize(ctx.title || "", style, W, H), W);
    el.appendChild(tt);
  } else if (info.kind === "lyrics") {
    if (style.showHeader) {
      const hd = document.createElement("div");
      hd.className = "hd";
      hd.style.top = (style.headerTop / H * 100) + "%";
      const label = info.label || "";
      const scale = headerScale(ctx.title || "", label, style, W);
      const t = document.createElement("span");
      t.textContent = ctx.title || "";
      styleText(t, style.title, style.title.size * scale, W);
      hd.appendChild(t);
      if (style.showSegment && label) {
        const s = document.createElement("span");
        s.textContent = "  [" + label + "]";
        s.style.whiteSpace = "pre";
        styleText(s, style.segment, style.segment.size * scale, W);
        hd.appendChild(s);
      }
      el.appendChild(hd);
    }
    const [size, lines] = lyricsLayout(info.text || "", style, W, H);
    const ly = document.createElement("div");
    ly.className = "ly";
    ly.style.left = (style.lyricsLeft / W * 100) + "%";
    ly.style.top = (style.lyricsTop / H * 100) + "%";
    ly.style.width = ((W - 2 * style.lyricsLeft) / W * 100) + "%";
    ly.style.textAlign = style.lyricsAlign || "center";
    ly.style.lineHeight = String(LINE_HEIGHT * (style.lineSpacing || 1));
    styleText(ly, style.lyrics, size, W);
    for (const line of lines) {
      const ln = document.createElement("span");
      ln.className = "ln";
      ln.textContent = line || "\u00a0";
      ly.appendChild(ln);
    }
    el.appendChild(ly);
    over = lyricsOverflow(lines, size, style, W, H);
    if (over) el.classList.add("over");
  } else if (info.label) {
    // 空白頁（前奏、自由…）：PPT 裡只有背景；預覽角落標一下是哪一段
    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = info.label;
    el.appendChild(tag);
  }
  return { el, over };
}
