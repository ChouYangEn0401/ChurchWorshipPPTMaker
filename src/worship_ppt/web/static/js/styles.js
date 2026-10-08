// 排版：清單 + 編輯（字型、大小、顏色、位置），右邊即時預覽。

import { $, api, el, modal, pageData, showError, toast } from "./common.js";
import { SIZES, renderSlide } from "./slide.js";

const data = pageData();
let styles = data.styles;
const themes = data.themes.filter((t) => !t.archived);
const settings = data.settings || {};
const size = settings.slide_size || "4:3";

const FONTS = [
  ["Microsoft JhengHei", "微軟正黑體"], ["Microsoft JhengHei UI", "微軟正黑體 UI"], ["PMingLiU", "新細明體"],
  ["DFKai-SB", "標楷體"], ["Noto Sans TC", "Noto Sans TC（思源黑體）"], ["Arial", "Arial"],
  ["Segoe UI", "Segoe UI"], ["Times New Roman", "Times New Roman"], ["Georgia", "Georgia"],
];
const PARTS = [["title", "歌名"], ["segment", "段落"], ["lyrics", "歌詞"]];
const SAMPLES = [
  { kind: "lyrics", label: "副", text: "哦！神同在 哦！神同在\n讓主的愛敞開你的胸懷\n歌唱神同在 歡呼神同在\n願全地上齊宣告神同在" },
  { kind: "lyrics", label: "主", text: "聖靈請祢來充滿我心 我需要祢恩膏 充滿我靈\n聖靈啊我好愛祢 我的靈讓祢牽引" },
];

const themeSelect = $("#previewTheme");
themeSelect.replaceChildren(...themes.map((t) => el("option", { value: String(t.id), text: t.name,
  selected: t.id === settings.default_theme_id })));
const previewTheme = () => themes.find((t) => t.id === Number(themeSelect.value)) || themes[0] || { bgColor: "#333842", overlay: 0 };

function render() {
  const grid = $("#grid");
  const showArchived = $("#showArchived").checked;
  grid.replaceChildren();
  for (const s of styles) {
    if (s.archived && !showArchived) continue;
    const { el: slide } = renderSlide(SAMPLES[0], { title: "神同在", theme: previewTheme(), style: s, size, thumb: 320 });
    const used = [s.serviceCount ? `用過 ${s.serviceCount} 次` : "還沒用過", s.id === settings.default_style_id ? "預設" : ""]
      .filter(Boolean).join(" · ");
    grid.appendChild(el("div", { class: "bcard" + (s.archived ? " off" : "") },
      el("div", { class: "pic" }, slide),
      el("div", { class: "meta2" }, el("b", { text: s.name }),
        el("span", { text: `歌詞 ${s.lyrics.size}pt · ${s.showHeader ? "有歌名列" : "只有歌詞"}${s.maxLines ? ` · 每頁最多 ${s.maxLines} 行` : ""}` }),
        el("span", { text: used })),
      el("div", { class: "acts" },
        el("button", { type: "button", class: "btn btn-sm", text: "編輯", onclick: () => edit(s) }),
        el("button", { type: "button", class: "btn btn-sm", text: "複製", onclick: () => duplicate(s) }),
        s.archived
          ? el("button", { type: "button", class: "btn btn-sm", text: "拿出來", onclick: () => save(s, { ...s, archived: false }) })
          : el("button", { type: "button", class: "btn btn-sm btn-danger", text: "刪除", onclick: () => remove(s) }))));
  }
}

async function save(s, body) {
  try {
    const fresh = await api(`/api/styles/${s.id}`, { method: "PATCH", body });
    styles = styles.map((x) => (x.id === s.id ? fresh : x));
    render();
    return fresh;
  } catch (e) { showError(e); return null; }
}

async function duplicate(s) {
  try {
    const fresh = await api(`/api/styles/${s.id}/duplicate`, { method: "POST" });
    styles.push(fresh);
    render();
    edit(fresh);
  } catch (e) { showError(e); }
}

async function remove(s) {
  if (!confirm(`刪除排版「${s.name}」？\n用過的排版只會收起來，沒用過的會真的刪掉。`)) return;
  try {
    const r = await api(`/api/styles/${s.id}`, { method: "DELETE" });
    if (r.result === "deleted") styles = styles.filter((x) => x.id !== s.id);
    else s.archived = true;
    toast(r.result === "deleted" ? "已刪除" : "用過了，先收起來");
    render();
  } catch (e) { showError(e); }
}

function fontPicker(part, onChange) {
  const select = el("select");
  const known = FONTS.some(([v]) => v === part.font);
  for (const [value, label] of FONTS) select.appendChild(el("option", { value, text: label, selected: value === part.font }));
  if (!known) select.appendChild(el("option", { value: part.font, text: part.font + "（自訂）", selected: true }));
  select.appendChild(el("option", { value: "__custom__", text: "自己輸入字型名稱…" }));
  select.addEventListener("change", () => {
    if (select.value === "__custom__") {
      const name = prompt("字型名稱（要跟 PowerPoint 裡看到的一樣，例如：微軟正黑體 = Microsoft JhengHei）", part.font);
      if (name && name.trim()) {
        select.insertBefore(el("option", { value: name.trim(), text: name.trim() + "（自訂）" }), select.lastChild);
        select.value = name.trim();
      } else {
        select.value = part.font;
      }
    }
    onChange(select.value);
  });
  return select;
}

function edit(s) {
  const d = JSON.parse(JSON.stringify(s));
  const preview = el("div", { class: "stack" });
  const refresh = () => {
    preview.replaceChildren();
    const samples = d.titleSlide ? [{ kind: "title" }, ...SAMPLES] : SAMPLES;
    for (const info of samples) {
      const { el: slide, over } = renderSlide(info, { title: "神同在", theme: previewTheme(), style: d, size, thumb: 960 });
      preview.appendChild(el("div", { class: "slide-cell" }, slide, over ? el("span", { class: "slide-cap" }, el("span", { class: "w", text: "字太多，會超出畫面" })) : null));
    }
  };

  const parts = el("div", { class: "parts" });
  for (const [key, label] of PARTS) {
    const part = d[key];
    const sizeInput = el("input", { type: "number", min: "8", max: "200", step: "1", value: String(part.size), class: "num" });
    sizeInput.addEventListener("input", () => { if (Number(sizeInput.value) >= 8) { part.size = Number(sizeInput.value); refresh(); } });
    const color = el("input", { type: "color", value: part.color });
    color.addEventListener("input", () => { part.color = color.value.toUpperCase(); refresh(); });
    const bold = el("input", { type: "checkbox", checked: part.bold });
    bold.addEventListener("change", () => { part.bold = bold.checked; refresh(); });
    const shadow = el("input", { type: "checkbox", checked: part.shadow });
    shadow.addEventListener("change", () => { part.shadow = shadow.checked; refresh(); });
    parts.appendChild(el("div", { class: "part-row" },
      el("span", { class: "nm", text: label }), fontPicker(part, (v) => { part.font = v; refresh(); }), sizeInput, color,
      el("label", {}, bold, "粗體"), el("label", {}, shadow, "陰影")));
  }

  const check = (key, text, help) => {
    const box = el("input", { type: "checkbox", checked: d[key] });
    box.addEventListener("change", () => { d[key] = box.checked; refresh(); });
    return el("label", {}, box, el("span", {}, el("b", { text }), help ? el("span", { class: "muted small", text: "　" + help }) : null));
  };
  const num = (key, label, step, min, max, help) => {
    const input = el("input", { type: "number", step: String(step), min: String(min), max: String(max), value: String(d[key]), class: "num" });
    input.addEventListener("input", () => {
      const v = Number(input.value);
      if (!Number.isNaN(v) && v >= min && v <= max) { d[key] = v; refresh(); }
    });
    return el("label", { class: "field", title: help || "" }, el("span", { class: "lbl", text: label }), input);
  };
  const align = el("select", {}, ...[["center", "置中"], ["left", "靠左"], ["right", "靠右"]].map(([v, t]) =>
    el("option", { value: v, text: t, selected: d.lyricsAlign === v })));
  align.addEventListener("change", () => { d.lyricsAlign = align.value; refresh(); });

  const [W, H] = SIZES[size];
  const name = el("input", { type: "text", value: d.name, maxlength: 60 });
  name.addEventListener("input", () => { d.name = name.value; });

  const form = el("div", { class: "stack" },
    el("label", { class: "field" }, el("span", { class: "lbl", text: "名稱" }), name),
    el("span", { class: "lbl", text: "字型" }), parts,
    el("div", { class: "checks" },
      check("showHeader", "上面顯示歌名", ""), check("showSegment", "歌名旁邊加 [段落]", ""),
      check("autoFit", "字太多時自動縮小", "快要折行或超出畫面時"), check("titleSlide", "每首歌先放一張歌名頁", "")),
    el("span", { class: "lbl", text: `位置（單位：吋；投影片是 ${W} × ${H} 吋）` }),
    el("div", { class: "pos-row" },
      num("headerTop", "歌名距離上緣", 0.05, 0, 7), num("lyricsTop", "歌詞距離上緣", 0.1, 0, 7),
      num("lyricsLeft", "歌詞左右留白", 0.05, 0, 5),
      el("label", { class: "field" }, el("span", { class: "lbl", text: "對齊" }), align)),
    el("div", { class: "pos-row" },
      num("lineSpacing", "行距（倍）", 0.05, 0.7, 2.5), num("maxLines", "每頁最多幾行（0 = 不限）", 1, 0, 20,
        "超過就平均拆成兩頁")),
    el("p", { class: "hint-line", text: "預覽和 PPT 用同一套尺寸換算。字型要播放 PPT 的那台電腦也有裝，不然 PowerPoint 會換成別的字。" }));
  refresh();
  const isDefault = s.id === settings.default_style_id;
  modal({
    title: `編輯排版：${s.name}`, wide: true,
    body: el("div", { class: "style-editor" }, form, preview),
    buttons: [
      { text: "取消" },
      { text: "另存成新排版", onclick: async (close) => {
        try {
          const fresh = await api("/api/styles", { method: "POST", body: { ...d, name: d.name + "（新）" } });
          styles.push(fresh);
          render();
          close();
          toast("已另存新排版");
        } catch (e) { showError(e); }
      } },
      { text: "儲存", class: "btn-primary", onclick: async (close) => {
        if (await save(s, d)) { close(); toast(isDefault ? "已儲存（這是預設排版）" : "已儲存"); }
      } },
    ],
  });
}

$("#btnNew").addEventListener("click", async () => {
  try {
    const fresh = await api("/api/styles", { method: "POST", body: { name: "新排版" } });
    styles.push(fresh);
    render();
    edit(fresh);
  } catch (e) { showError(e); }
});
$("#showArchived").addEventListener("change", render);
themeSelect.addEventListener("change", render);
render();
const editId = Number((location.hash.match(/^#(\d+)$/) || [])[1]);
if (editId && styles.find((s) => s.id === editId)) edit(styles.find((s) => s.id === editId));
