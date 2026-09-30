// 詩歌庫裡的一首歌：編輯 + 預覽（自動存檔）。

import { $, $$, api, debounce, el, pageData, showError, toast } from "./common.js";
import { planSong } from "./lyrics.js";
import { renderSlide } from "./slide.js";

const data = pageData();
const song = data.song;
const themes = data.themes;
const styles = data.styles;
const settings = data.settings || {};

const fields = {
  title: $("#fTitle"), key: $("#fKey"), aliases: $("#fAliases"), sequence: $("#fSequence"),
  lyrics: $("#fLyrics"), themeId: $("#fTheme"), styleId: $("#fStyle"), notes: $("#fNotes"),
};

function fillSelect(select, list, value, emptyText) {
  select.replaceChildren(el("option", { value: "", text: emptyText }),
    ...list.filter((x) => !x.archived || x.id === value).map((x) => el("option", { value: String(x.id), text: x.name, selected: x.id === value })));
}
fillSelect(fields.themeId, themes, song.themeId, "（用歌單的預設）");
fillSelect(fields.styleId, styles, song.styleId, "（用歌單的預設）");
for (const name of ["title", "key", "aliases", "sequence", "lyrics", "notes"]) fields[name].value = song[name] || "";

const theme = () => themes.find((t) => t.id === Number(fields.themeId.value))
  || themes.find((t) => t.id === settings.default_theme_id) || themes[0] || { bgColor: "#000", overlay: 0, image: null };
const style = () => styles.find((s) => s.id === Number(fields.styleId.value))
  || styles.find((s) => s.id === settings.default_style_id) || styles[0];

function renderPreview() {
  const st = style();
  const plan = planSong(fields.lyrics.value, fields.sequence.value, { maxLines: st.maxLines, titleSlide: st.titleSlide });
  const box = $("#preview");
  box.replaceChildren();
  plan.slides.forEach((info, i) => {
    const { el: slide, over } = renderSlide(info, { title: fields.title.value, theme: theme(), style: st, size: settings.slide_size || "4:3", thumb: 960 });
    box.appendChild(el("div", { class: "slide-cell" }, slide,
      el("div", { class: "slide-cap" }, el("span", { class: "n", text: String(i + 1) }),
        el("span", { class: "l", text: info.kind === "title" ? "歌名頁" : (info.label || "歌詞") }),
        over ? el("span", { class: "w", text: "字太多" }) : null)));
  });
  $("#count").textContent = `${plan.slides.length} 張`;
  $("#warn").replaceChildren(...plan.warnings.map((w) => el("span", { class: "w", text: w })));
}

const state = $("#saveState");
const save = debounce(async () => {
  state.className = "save-state saving";
  state.textContent = "儲存中…";
  try {
    const body = {};
    for (const [name, input] of Object.entries(fields)) body[name] = input.value;
    body.themeId = fields.themeId.value || null;
    body.styleId = fields.styleId.value || null;
    await api(`/api/songs/${song.id}`, { method: "PATCH", body });
    state.className = "save-state ok";
    state.textContent = "已儲存 ✓";
  } catch (e) {
    showError(e);
    state.className = "save-state bad";
    state.textContent = "沒存到";
  }
}, 700);

for (const input of Object.values(fields)) {
  input.addEventListener(input.tagName === "SELECT" ? "change" : "input", () => { save(); renderPreviewSoon(); });
}
const renderPreviewSoon = debounce(renderPreview, 150);

$("#btnDelete").addEventListener("click", async () => {
  if (!confirm(`從詩歌庫刪除「${song.title}」？\n以前的歌單和匯出紀錄不受影響。`)) return;
  try {
    await api(`/api/songs/${song.id}`, { method: "DELETE" });
    location.href = "/songs?msg=" + encodeURIComponent(`已刪除「${song.title}」`);
  } catch (e) { showError(e); }
});

$$("[data-restore]").forEach((btn) => btn.addEventListener("click", async () => {
  if (!confirm("把歌詞和歌序換回這個舊版本？（現在的版本也會存成一個舊版本）")) return;
  try {
    await api(`/api/songs/${song.id}/restore/${btn.dataset.restore}`, { method: "POST" });
    toast("已還原");
    setTimeout(() => location.reload(), 500);
  } catch (e) { showError(e); }
}));

renderPreview();
