// 歌詞 → 投影片的規則。這是 src/worship_ppt/lyrics.py 的逐行翻譯：
// 預覽和匯出的 PPT 一定要做出一樣的決定（分頁、歌序、字級、折行），tests/test_js_parity.py 會兩邊比對。
// 改這裡的時候，lyrics.py 也要一起改。

const LABEL_LINE_RE = /^\s*[\[【]\s*(.+?)\s*[\]】]\s*$/;

const ALIASES = {
  "主": ["主", "主歌", "verse", "v"],
  "副": ["副", "副歌", "chorus", "c", "cho"],
  "副前": ["副前", "導歌", "預副", "prechorus", "pre-chorus", "pre", "pc"],
  "橋": ["橋", "橋段", "bridge", "b"],
  "前奏": ["前奏", "intro"],
  "間奏": ["間奏", "interlude", "inst", "instrumental"],
  "尾": ["尾", "尾奏", "結尾", "ending", "outro", "end"],
};
const ALIAS_LOOKUP = new Map();
for (const [canon, names] of Object.entries(ALIASES)) for (const n of names) ALIAS_LOOKUP.set(n, canon);

export const INSTRUMENTAL = new Set(["前奏", "間奏", "自由", "禱告", "自由敬拜", "rap"]);

const SEQ_SPLIT_RE = /[\n,，、;；/→>|]+|\s+/;
const SEQ_NUMBERING_RE = /^\(?\d+[.)、]/;
const SEQ_REPEAT_RE = /^(.*?)\(?[*xX×](\d+)\)?$/;
const SEQ_STANDALONE_REPEAT_RE = /^\(?[*xX×](\d+)\)?$/;

export const nfkc = (text) => (text || "").normalize("NFKC");

export function normalizeLabel(label) {
  return nfkc(label).trim().replace(/[：:]+$/, "").replace(/\s+/g, "").toLowerCase();
}

export function canonicalLabel(label) {
  const s = normalizeLabel(label);
  const m = s.match(/^(.*?)(\d*)$/);
  let base = m ? m[1] : s;
  const num = m ? m[2] : "";
  base = base.replace(/[-_.]+$/, "");
  const canon = ALIAS_LOOKUP.get(base);
  return canon === undefined ? s : canon + num;
}

// ---------------------------------------------------------------------------
// 歌詞 → 段落
// ---------------------------------------------------------------------------

function splitPages(lines) {
  const pages = [];
  let current = [];
  for (const line of lines) {
    const text = line.trim();
    if (!text) {
      if (current.length) { pages.push(current.join("\n")); current = []; }
      continue;
    }
    current.push(text);
  }
  if (current.length) pages.push(current.join("\n"));
  return pages;
}

export function parseSections(text) {
  const sections = [];
  let label = null;
  let lines = [];
  const flush = () => {
    const pages = splitPages(lines);
    if (label !== null || pages.length) sections.push({ label: label || "", pages });
  };
  for (const raw of (text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n")) {
    const m = raw.match(LABEL_LINE_RE);
    if (m) {
      flush();
      label = m[1].trim();
      lines = [];
      continue;
    }
    lines.push(raw);
  }
  flush();
  return sections;
}

export function splitLongPage(page, maxLines) {
  const lines = page.split("\n");
  if (maxLines <= 0 || lines.length <= maxLines) return [page];
  const chunks = Math.ceil(lines.length / maxLines);
  const size = Math.ceil(lines.length / chunks);
  const out = [];
  for (let i = 0; i < lines.length; i += size) out.push(lines.slice(i, i + size).join("\n"));
  return out;
}

// ---------------------------------------------------------------------------
// 歌序
// ---------------------------------------------------------------------------

export function parseSequence(text) {
  const tokens = [];
  for (let part of nfkc(text).split(SEQ_SPLIT_RE)) {
    part = (part || "").trim();
    if (!part) continue;
    if (/^\d+$/.test(part)) {
      if (tokens.length && /[a-zA-Z]$/.test(tokens[tokens.length - 1].label)) {
        tokens[tokens.length - 1].label += " " + part;
      }
      continue;
    }
    const standalone = part.match(SEQ_STANDALONE_REPEAT_RE);
    if (standalone) {
      if (tokens.length) tokens[tokens.length - 1].repeat = Math.max(1, parseInt(standalone[1], 10));
      continue;
    }
    part = part.replace(SEQ_NUMBERING_RE, "").trim();
    if (!part) continue;
    let repeat = 1;
    const m = part.match(SEQ_REPEAT_RE);
    if (m && m[1].trim()) {
      part = m[1].trim();
      repeat = Math.max(1, parseInt(m[2], 10));
    }
    part = part.replace(/[：:]+$/, "").trim();
    if (part) tokens.push({ label: part, repeat });
  }
  return tokens;
}

// ---------------------------------------------------------------------------
// 一首歌 → 投影片清單
// ---------------------------------------------------------------------------

export function planSong(lyrics, sequence = "", { followSequence = true, maxLines = 0, titleSlide = false } = {}) {
  const sections = parseSections(lyrics);
  const slides = [];
  const warnings = [];
  const labels = sections.filter((s) => s.label).map((s) => s.label);

  if (titleSlide) slides.push({ kind: "title", label: "", text: "", repeat: 1 });

  const emit = (section, repeat) => {
    const pages = [];
    for (const page of section.pages) pages.push(...splitLongPage(page, maxLines));
    if (!pages.length) {
      slides.push({ kind: "blank", label: section.label, text: "", repeat });
      return;
    }
    for (const page of pages) slides.push({ kind: "lyrics", label: section.label, text: page, repeat });
  };

  const tokens = followSequence ? parseSequence(sequence) : [];
  if (tokens.length) {
    const index = new Map();
    for (const s of sections) {
      const key = canonicalLabel(s.label);
      if (!index.has(key)) index.set(key, s);
    }
    const used = new Set();
    const missing = [];
    for (const tok of tokens) {
      const key = canonicalLabel(tok.label);
      const section = index.get(key);
      if (section === undefined) {
        slides.push({ kind: "blank", label: tok.label, text: "", repeat: tok.repeat });
        if (!INSTRUMENTAL.has(normalizeLabel(tok.label)) && !missing.includes(tok.label)) missing.push(tok.label);
        continue;
      }
      used.add(key);
      emit(section, tok.repeat);
    }
    for (const label of missing) warnings.push(`歌序裡的「${label}」在歌詞找不到，先放一張空白頁`);
    for (const s of sections) {
      if (s.pages.length && !used.has(canonicalLabel(s.label))) {
        const name = s.label || "（最前面沒有標段落的歌詞）";
        warnings.push(`「${name}」沒有出現在歌序裡，不會放進 PPT`);
      }
    }
  } else {
    for (const s of sections) emit(s, 1);
  }

  if (!slides.some((s) => s.kind === "lyrics") && (lyrics || "").trim() === "") warnings.push("還沒有歌詞");
  return { slides, warnings, labels };
}

// ---------------------------------------------------------------------------
// 字太多時自動縮小
// ---------------------------------------------------------------------------

export const LINE_HEIGHT = 1.2;
const WIDTH_SAFETY = 0.97;
const NO_ORPHAN_RATIO = 0.85;
const MIN_FIT_RATIO = 0.5;
const NARROW = new Set("il.,:;'|!()[]{}`\"");

export function charEm(ch) {
  const o = ch.codePointAt(0);
  if (ch === " ") return 0.28;
  if (o >= 0x0250) return 1.0;
  if (ch >= "A" && ch <= "Z") return 0.65;
  if (NARROW.has(ch)) return 0.3;
  return 0.52;
}

export function textEm(text) {
  let total = 0;
  for (const ch of text) total += charEm(ch);
  return total;
}

export function wrapAtSpaces(line, size, boxW) {
  if (textEm(line) * size <= boxW || !line.trim().includes(" ")) return [line];
  const parts = line.split(" ");
  let best = null;
  for (let i = 1; i < parts.length; i++) {
    const left = parts.slice(0, i).join(" ").trim();
    const right = parts.slice(i).join(" ").trim();
    if (!left || !right) continue;
    const score = Math.max(textEm(left), textEm(right));
    if (best === null || score < best[0]) best = [score, left, right];
  }
  if (best === null) return [line];
  return [...wrapAtSpaces(best[1], size, boxW), ...wrapAtSpaces(best[2], size, boxW)];
}

function rowsFor(arranged, size, boxW) {
  let rows = 0;
  for (const x of arranged) rows += Math.max(1, Math.ceil(textEm(x) * size / boxW - 1e-9));
  return rows;
}

export function fitLines(lines, base, boxW, boxH, lineSpacing, autoFit = true) {
  boxW = Math.max(boxW, 72.0);
  let size = base;
  const widths = lines.map(textEm);
  const longest = widths.length ? Math.max(...widths) : 0;
  if (autoFit && widths.length && longest > 0) {
    const noWrap = boxW / longest;
    if (size * NO_ORPHAN_RATIO <= noWrap && noWrap < size) size = Math.floor(noWrap * 2) / 2;
  }
  const arrange = (sz) => {
    const out = [];
    for (const line of lines) out.push(...wrapAtSpaces(line, sz, boxW));
    return out;
  };
  const fits = (sz, arranged) => rowsFor(arranged, sz, boxW) * sz * LINE_HEIGHT * lineSpacing <= boxH + 1e-6;
  let arranged = arrange(size);
  if (autoFit) {
    const minSize = Math.max(8.0, base * MIN_FIT_RATIO);
    while (size > minSize && !fits(size, arranged)) {
      size = Math.max(minSize, size - 1);
      arranged = arrange(size);
    }
  }
  return [size, arranged];
}

export function lyricsBox(style, slideW, slideH) {
  return {
    w: (slideW - 2 * style.lyricsLeft) * 72 * WIDTH_SAFETY,
    h: (slideH - style.lyricsTop - 0.25) * 72,
  };
}

export function lyricsLayout(text, style, slideW, slideH) {
  const base = style.lyrics.size;
  if (!text) return [base, []];
  const box = lyricsBox(style, slideW, slideH);
  return fitLines(text.split("\n"), base, box.w, box.h, style.lineSpacing, style.autoFit !== false);
}

// 放不下（字會超出投影片下緣）嗎？跟 PPT 用同一個估算
export function lyricsOverflow(lines, size, style, slideW, slideH) {
  const box = lyricsBox(style, slideW, slideH);
  const boxW = Math.max(box.w, 72.0);
  return rowsFor(lines, size, boxW) * size * LINE_HEIGHT * style.lineSpacing > box.h + 1e-6;
}

export function headerScale(title, label, style, slideW) {
  if (style.autoFit === false) return 1.0;
  let width = textEm(title) * style.title.size;
  if (label && style.showSegment) width += textEm("  [" + label + "]") * style.segment.size;
  const boxW = (slideW - 1.0) * 72 * WIDTH_SAFETY;
  if (width <= boxW) return 1.0;
  return Math.max(0.6, Math.floor(boxW / width * 100) / 100);
}

export function titlePageSize(title, style, slideW, slideH) {
  const base = Math.max(style.title.size * 1.5, style.lyrics.size);
  if (style.autoFit === false || !title) return base;
  return fitLines([title], base, (slideW - 1.0) * 72 * WIDTH_SAFETY, slideH * 72 * 0.8, 1.0)[0];
}
