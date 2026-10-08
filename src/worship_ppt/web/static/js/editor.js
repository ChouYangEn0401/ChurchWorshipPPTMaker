// 歌單編輯畫面：左邊歌曲清單、中間編輯一首歌、右邊即時預覽。
//
// - 每一個改動都會自動存（停手 0.6 秒後送出），不用按存檔。
// - 每筆資料有版本號：兩個人同時改同一首歌時，後存的人會被擋下來並看到最新內容（不會默默蓋掉別人的）。
// - 每 10 秒問一次伺服器有沒有別人的修改，有的話直接更新畫面（正在打字的那一欄不會被打斷）。

import { $, api, debounce, download, el, fmtDate, modal, pageData, showError, toast, uploadImages, wireDropzone } from "./common.js";
import { planSong } from "./lyrics.js";
import { mediaUrl, paintBackground, renderSlide } from "./slide.js";

const data = pageData();
let svc = data.service;
let themes = data.themes;
let styles = data.styles;
const settings = data.settings || {};
let selectedId = null;
let previewMode = "song";
let lastTyping = 0;

// ---------------------------------------------------------------------------
// 查資料
// ---------------------------------------------------------------------------

const itemById = (id) => svc.items.find((i) => i.id === id);
const current = () => itemById(selectedId);
const FALLBACK_THEME = { id: null, name: "純黑底", image: null, bgColor: "#000000", overlay: 0 };

function themeFor(item) {
  return themes.find((t) => t.id === item.themeId)
    || themes.find((t) => t.id === settings.default_theme_id) || themes[0] || FALLBACK_THEME;
}
function styleFor(item) {
  return styles.find((s) => s.id === item.styleId)
    || styles.find((s) => s.id === settings.default_style_id) || styles[0];
}
function planFor(item) {
  const style = styleFor(item);
  return planSong(item.lyrics, item.sequence, {
    followSequence: svc.followSequence, maxLines: style.maxLines, titleSlide: style.titleSlide,
  });
}
const stampOf = (s) => [String(s.version), ...s.items.map((i) => `${i.id}.${i.version}`)].join("-");

// ---------------------------------------------------------------------------
// 自動存檔
// ---------------------------------------------------------------------------

const saver = {
  dirty: new Map(),
  timers: new Map(),
  inflight: new Set(),
  retry: null,

  mark(itemId, fields) {
    this.dirty.set(itemId, { ...(this.dirty.get(itemId) || {}), ...fields });
    setItemState("saving", "儲存中…");
    clearTimeout(this.timers.get(itemId));
    this.timers.set(itemId, setTimeout(() => this.flush(itemId), 600));
  },

  busy() { return this.dirty.size > 0 || this.inflight.size > 0; },

  async flush(itemId) {
    clearTimeout(this.timers.get(itemId));
    if (this.inflight.has(itemId)) return;
    const fields = this.dirty.get(itemId);
    if (!fields) return;
    const item = itemById(itemId);
    if (!item) { this.dirty.delete(itemId); return; }
    this.dirty.delete(itemId);
    this.inflight.add(itemId);
    try {
      const updated = await api(`/api/items/${itemId}`, { method: "PATCH", body: { ...fields, version: item.version } });
      item.version = updated.version;
      item.updatedBy = updated.updatedBy;
      item.updatedAt = updated.updatedAt;
      item.songId = updated.songId;
      if (!this.dirty.size) setItemState("ok", "已儲存 ✓");
    } catch (err) {
      if (err.status === 409) {
        await handleConflict(itemId, fields, err);
      } else if (err.status === 404) {
        toast("這首歌已經被別人移出歌單了", "warn");
        await reloadService();
      } else {
        this.dirty.set(itemId, { ...fields, ...(this.dirty.get(itemId) || {}) });
        setItemState("bad", "沒存到，稍後自動再試");
        clearTimeout(this.retry);
        this.retry = setTimeout(() => this.flush(itemId), 5000);
      }
    } finally {
      this.inflight.delete(itemId);
      if (this.dirty.has(itemId)) this.timers.set(itemId, setTimeout(() => this.flush(itemId), 300));
    }
  },

  async flushAll() {
    for (const id of Array.from(this.dirty.keys())) await this.flush(id);
    while (this.inflight.size) await new Promise((r) => setTimeout(r, 80));
  },
};

function setItemState(level, text) {
  const node = $("#itemState");
  node.className = "save-state " + level;
  node.textContent = text;
}

async function handleConflict(itemId, mine, err) {
  const fresh = await api(`/api/services/${svc.id}`);
  svc = fresh;
  renderAll();
  const note = el("div", { class: "remote-note" },
    el("span", { text: `⚠ ${err.message}。你剛剛的修改沒有存進去。` }));
  if (mine.lyrics !== undefined) {
    note.appendChild(el("button", {
      type: "button", class: "btn btn-sm", text: "複製我剛打的歌詞",
      onclick: async () => {
        try { await navigator.clipboard.writeText(mine.lyrics); toast("已複製，可以貼回歌詞欄"); } catch (_) { /* 不允許就算了 */ }
      },
    }));
  }
  $("#itemEditor").prepend(note);
  setItemState("bad", "有衝突");
}

async function reloadService() {
  svc = await api(`/api/services/${svc.id}`);
  if (!itemById(selectedId)) selectedId = svc.items[0] ? svc.items[0].id : null;
  renderAll();
}

// 歌單本身（名稱、日期、比例、照歌序）
async function saveService(fields) {
  const state = $("#svcState");
  state.className = "save-state saving";
  state.textContent = "儲存中…";
  try {
    const fresh = await api(`/api/services/${svc.id}`, { method: "PATCH", body: { ...fields, version: svc.version } });
    mergeService(fresh);
    state.className = "save-state ok";
    state.textContent = "已儲存 ✓";
  } catch (err) {
    showError(err);
    state.className = "save-state bad";
    state.textContent = "沒存到";
    if (err.status === 409) await reloadService();
  }
}
const saveName = debounce((v) => saveService({ name: v }), 600);

/** 用伺服器回來的歌單更新畫面；正在等著存的那幾首保留本地的內容。 */
function mergeService(fresh) {
  const pending = new Map();
  for (const [id, fields] of saver.dirty) pending.set(id, fields);
  svc = fresh;
  for (const [id, fields] of pending) {
    const item = itemById(id);
    if (item) Object.assign(item, fields);
  }
}

// ---------------------------------------------------------------------------
// 左邊：歌單資訊與歌曲清單
// ---------------------------------------------------------------------------

function renderMeta() {
  const name = $("#svcName");
  if (document.activeElement !== name) name.value = svc.name;
  $("#svcDate").value = svc.date;
  $("#svcSize").value = svc.slideSize;
  $("#svcFollow").checked = svc.followSequence;
  $("#svcTeam").textContent = svc.team || "";
  document.title = `${fmtDate(svc.date)} ${svc.name}・敬拜 PPT 產生器`;
}

let dragId = null;

function renderSongList() {
  const box = $("#songList");
  box.replaceChildren();
  svc.items.forEach((item, i) => {
    const sub = [item.key, item.sequence ? item.sequence : "照歌詞順序"].filter(Boolean).join(" · ");
    const row = el("div", {
      class: "srow" + (item.id === selectedId ? " active" : ""), draggable: "true", dataset: { id: item.id },
      onclick: () => select(item.id),
    },
    el("span", { class: "i", text: String(i + 1), title: "拖曳可以調整順序" }),
    el("span", { class: "t" },
      el("b", { class: item.title ? "" : "empty", text: item.title || "（沒有歌名）" },
        item.songId ? null : el("span", { class: "dot", title: "新歌：匯出後會自動加進詩歌庫" })),
      el("span", { text: sub })),
    el("span", { class: "ops" },
      el("button", { type: "button", class: "icon-btn", title: "上移", text: "▲", disabled: i === 0,
        onclick: (e) => { e.stopPropagation(); move(item.id, -1); } }),
      el("button", { type: "button", class: "icon-btn", title: "下移", text: "▼", disabled: i === svc.items.length - 1,
        onclick: (e) => { e.stopPropagation(); move(item.id, 1); } }),
      el("button", { type: "button", class: "icon-btn", title: "從這份歌單移除", text: "✕",
        onclick: (e) => { e.stopPropagation(); removeItem(item.id); } })));
    row.addEventListener("dragstart", (e) => { dragId = item.id; e.dataTransfer.effectAllowed = "move"; });
    row.addEventListener("dragover", (e) => { e.preventDefault(); row.classList.add("drag-over"); });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      row.classList.remove("drag-over");
      if (dragId && dragId !== item.id) dropBefore(dragId, item.id);
      dragId = null;
    });
    box.appendChild(row);
  });
  if (!svc.items.length) {
    box.appendChild(el("div", { class: "empty" }, el("b", { text: "還沒有歌" }),
      el("span", { text: "在下面打歌名，從詩歌庫加進來；或按「從文件更新」。" })));
  }
}

async function reorder(ids) {
  await saver.flushAll();
  try {
    mergeService(await api(`/api/services/${svc.id}/reorder`, { method: "POST", body: { itemIds: ids } }));
    renderSongList();
    renderPreview();
  } catch (e) { showError(e); }
}
function move(id, dir) {
  const ids = svc.items.map((i) => i.id);
  const at = ids.indexOf(id);
  const to = at + dir;
  if (to < 0 || to >= ids.length) return;
  [ids[at], ids[to]] = [ids[to], ids[at]];
  reorder(ids);
}
function dropBefore(movingId, targetId) {
  const ids = svc.items.map((i) => i.id).filter((x) => x !== movingId);
  ids.splice(ids.indexOf(targetId), 0, movingId);
  reorder(ids);
}

async function removeItem(id) {
  const item = itemById(id);
  if (!confirm(`把「${item.title || "這首歌"}」從這份歌單移除？\n（詩歌庫裡的歌不會被刪掉）`)) return;
  saver.dirty.delete(id);
  try {
    await api(`/api/items/${id}`, { method: "DELETE" });
    await reloadService();
  } catch (e) { showError(e); }
}

async function addItem(body) {
  await saver.flushAll();
  try {
    const item = await api(`/api/services/${svc.id}/items`, { method: "POST", body });
    svc = await api(`/api/services/${svc.id}`);
    select(item.id);
    if (!body.songId) setTimeout(() => $("#f-title")?.focus(), 50);
  } catch (e) { showError(e); }
}

// ---------- 從詩歌庫找歌 ----------
const search = $("#songSearch");
const results = $("#searchResults");
let resultButtons = [];
let resultIndex = -1;

const runSearch = debounce(async () => {
  const q = search.value.trim();
  if (!q) { results.hidden = true; return; }
  let songs = [];
  try { songs = await api(`/api/songs?q=${encodeURIComponent(q)}&limit=8`); } catch (_) { songs = []; }
  results.replaceChildren();
  resultButtons = [];
  for (const s of songs) {
    const meta = [s.key, s.lastUsed ? `上次 ${fmtDate(s.lastUsed)}` : "還沒用過", s.useCount ? `用過 ${s.useCount} 次` : ""]
      .filter(Boolean).join(" · ");
    resultButtons.push(el("button", { type: "button", onclick: () => pickResult({ songId: s.id }) },
      el("b", { text: s.title }), el("span", { text: meta })));
  }
  resultButtons.push(el("button", { type: "button", onclick: () => pickResult({ title: q }) },
    el("b", { text: `＋ 新歌「${q}」` }), el("span", { text: "詩歌庫還沒有這首：先建一首空白的，歌詞自己貼" })));
  results.append(...resultButtons);
  resultIndex = songs.length ? 0 : resultButtons.length - 1;
  highlight();
  results.hidden = false;
}, 180);

function highlight() { resultButtons.forEach((b, i) => b.classList.toggle("on", i === resultIndex)); }
function pickResult(body) {
  results.hidden = true;
  search.value = "";
  addItem(body);
}
search.addEventListener("input", runSearch);
search.addEventListener("keydown", (e) => {
  if (results.hidden || e.isComposing) return;
  if (e.key === "ArrowDown") { resultIndex = Math.min(resultIndex + 1, resultButtons.length - 1); highlight(); e.preventDefault(); }
  if (e.key === "ArrowUp") { resultIndex = Math.max(resultIndex - 1, 0); highlight(); e.preventDefault(); }
  if (e.key === "Enter" && resultButtons[resultIndex]) { resultButtons[resultIndex].click(); e.preventDefault(); }
  if (e.key === "Escape") results.hidden = true;
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search-pop")) results.hidden = true; });
$("#btnBlankSong").addEventListener("click", () => addItem({ title: "" }));

// ---------------------------------------------------------------------------
// 中間：編輯一首歌
// ---------------------------------------------------------------------------

function select(id) {
  selectedId = id;
  history.replaceState(null, "", id ? `#item-${id}` : location.pathname);
  renderSongList();
  renderEditor();
  renderPreview();
}

function lookCard(kind, item) {
  const card = el("button", { type: "button", class: "look-card", title: kind === "theme" ? "換背景" : "換排版" });
  const sw = el("span", { class: "sw" });
  const tx = el("span", { class: "tx" });
  if (kind === "theme") {
    const t = themeFor(item);
    paintBackground(sw, t, 320);
    tx.append(el("span", { text: "背景" }), el("b", { text: t.name }),
      el("span", { text: t.overlay > 0 ? `暗色遮罩 ${Math.round(t.overlay * 100)}%` : (t.image ? "圖片" : "純色") }));
    card.addEventListener("click", () => openThemePicker(item));
  } else {
    const s = styleFor(item);
    sw.style.background = "#333842";
    sw.style.display = "grid";
    sw.style.placeItems = "center";
    sw.style.color = s.lyrics.color;
    sw.style.fontWeight = s.lyrics.bold ? "700" : "400";
    sw.textContent = "Aa 字";
    tx.append(el("span", { text: "排版" }), el("b", { text: s.name }),
      el("span", { text: `歌詞 ${s.lyrics.size}pt${s.showHeader ? " · 有歌名列" : ""}${s.maxLines ? ` · 每頁最多 ${s.maxLines} 行` : ""}` }));
    card.addEventListener("click", () => openStylePicker(item));
  }
  card.append(sw, tx);
  return card;
}

function renderEditor() {
  const box = $("#itemEditor");
  const item = current();
  box.replaceChildren();
  $("#itemHeading").textContent = item ? (item.title || "（沒有歌名）") : "還沒有選歌";
  setItemState("", item && item.updatedBy ? `最後修改：${item.updatedBy}` : "");
  if (!item) {
    box.appendChild(el("div", { class: "empty" }, el("b", { text: "左邊選一首歌來編輯" }),
      el("span", { text: "或在左下角打歌名，從詩歌庫加歌進來。" })));
    return;
  }

  // 歌名、調性
  const title = el("input", { id: "f-title", type: "text", value: item.title, maxlength: 80, placeholder: "歌名" });
  title.addEventListener("input", () => {
    item.title = title.value;
    $("#itemHeading").textContent = item.title || "（沒有歌名）";
    saver.mark(item.id, { title: item.title });
    renderSongListSoon();
    renderPreviewSoon();
  });
  const key = el("input", { type: "text", value: item.key, maxlength: 20, placeholder: "例：G" });
  key.addEventListener("input", () => { item.key = key.value; saver.mark(item.id, { key: item.key }); renderSongListSoon(); });
  box.appendChild(el("div", { class: "row" },
    el("label", { class: "field", style: { flex: "1 1 220px" } }, el("span", { class: "lbl", text: "歌名" }), title),
    el("label", { class: "field", style: { width: "96px" } }, el("span", { class: "lbl", text: "調性" }), key)));

  // 詩歌庫狀態
  const libLine = el("div", { class: "row small" });
  if (item.songId) {
    libLine.append(el("span", { class: "badge ok", text: "詩歌庫" }),
      el("span", { class: "muted", text: "這首歌在詩歌庫裡；匯出時會把這次的歌詞、歌序、背景存回去。" }),
      el("a", { href: `/songs/${item.songId}`, target: "_blank", rel: "noopener", text: "看紀錄 ↗" }));
  } else {
    const btn = el("button", { type: "button", class: "btn btn-sm", text: "現在存到詩歌庫" });
    btn.addEventListener("click", async () => {
      await saver.flushAll();
      try {
        const r = await api(`/api/items/${item.id}/to-library`, { method: "POST" });
        Object.assign(item, { songId: r.item.songId, version: r.item.version });
        toast("已存進詩歌庫");
        renderSongList();
        renderEditor();
      } catch (e) { showError(e); }
    });
    libLine.append(el("span", { class: "badge warn", text: "新歌" }),
      el("span", { class: "muted", text: "詩歌庫還沒有這首；匯出時會自動加進去。" }), btn);
  }
  box.appendChild(libLine);

  // 歌序
  const plan = planFor(item);
  const seq = el("input", { type: "text", value: item.sequence, placeholder: "例：主 主 副前1 副 橋 副（空白、逗號都可以）" });
  seq.addEventListener("input", () => {
    item.sequence = seq.value;
    saver.mark(item.id, { sequence: item.sequence });
    renderSongListSoon();
    renderPreviewSoon();
  });
  const chips = el("div", { class: "seq-chips" });
  for (const label of Array.from(new Set(plan.labels))) {
    chips.appendChild(el("button", { type: "button", class: "chip", text: "+ " + label, title: `把「${label}」加到歌序最後`,
      onclick: () => {
        seq.value = (seq.value.trim() ? seq.value.trim() + " " : "") + label;
        seq.dispatchEvent(new Event("input"));
      } }));
  }
  if (item.sequence) {
    chips.appendChild(el("button", { type: "button", class: "chip off", text: "清空歌序",
      onclick: () => { seq.value = ""; seq.dispatchEvent(new Event("input")); } }));
  }
  box.appendChild(el("div", { class: "field" },
    el("span", { class: "lbl", text: "歌序" }), seq, chips,
    el("span", { class: "hint-line", text: svc.followSequence
      ? "投影片照這個順序排，重複唱的段落會重複放；寫「前奏」「間奏」「自由」會放一張只有背景的空白頁。空著就照歌詞順序。"
      : "（左邊「照歌序排投影片」關掉了：現在每個段落只放一次，照歌詞順序。）" })));

  // 歌詞
  const lyrics = el("textarea", { class: "lyrics", spellcheck: "false",
    placeholder: "[主]\n從日出到日落 我要歌頌你的大能\n並在列邦中述說你的同在\n\n[副]\n哦！神同在 哦！神同在" });
  lyrics.value = item.lyrics;
  lyrics.addEventListener("input", () => {
    item.lyrics = lyrics.value;
    lastTyping = Date.now();
    saver.mark(item.id, { lyrics: item.lyrics });
    renderPreviewSoon();
    refreshChipsSoon();
  });
  box.appendChild(el("div", { class: "field" },
    el("span", { class: "lbl", text: "歌詞" }), lyrics,
    el("span", { class: "hint-line", text: "用 [段落名] 分段（例如 [主] [副前1] [副] [橋]）。同一段裡空一行 = 換下一頁。" })));

  // 背景、排版
  const look = el("div", { class: "look-row" }, lookCard("theme", item), lookCard("style", item));
  box.appendChild(el("div", { class: "field" }, el("span", { class: "lbl", text: "這首歌的樣子" }), look));

  // 注意事項
  const warn = el("div", { class: "warnlist", id: "itemWarn" });
  box.appendChild(warn);
  paintWarnings(plan);
}

function paintWarnings(plan) {
  const warn = $("#itemWarn");
  if (!warn) return;
  warn.replaceChildren(...plan.warnings.filter((w) => w !== "還沒有歌詞").map((w) => el("span", { class: "w", text: w })));
}

const refreshChipsSoon = debounce(() => {
  const item = current();
  if (!item) return;
  const plan = planFor(item);
  paintWarnings(plan);
  const chips = $(".seq-chips");
  if (!chips) return;
  const have = Array.from(chips.querySelectorAll(".chip:not(.off)")).map((c) => c.textContent.slice(2));
  const want = Array.from(new Set(plan.labels));
  if (have.join("|") !== want.join("|")) {
    const seq = chips.previousElementSibling;
    chips.querySelectorAll(".chip:not(.off)").forEach((c) => c.remove());
    for (const label of want.reverse()) {
      chips.prepend(el("button", { type: "button", class: "chip", text: "+ " + label, title: `把「${label}」加到歌序最後`,
        onclick: () => {
          seq.value = (seq.value.trim() ? seq.value.trim() + " " : "") + label;
          seq.dispatchEvent(new Event("input"));
        } }));
    }
  }
}, 400);

const renderSongListSoon = debounce(renderSongList, 250);

// ---------- 背景挑選 ----------
function openThemePicker(item) {
  const grid = el("div", { class: "card-grid small" });
  const zone = el("div", { class: "dropzone", tabindex: "0" },
    el("b", { text: "＋ 上傳新的背景圖" }), el("span", { class: "small", text: "把圖片拖進來，或點這裡選檔案（可以一次選好幾張）" }));
  const overlayRange = el("input", { type: "range", min: "0", max: "0.8", step: "0.05" });
  const overlayVal = el("span", { class: "small muted" });
  const overlayRow = el("div", { class: "row" }, el("span", { class: "lbl", text: "暗色遮罩" }), overlayRange, overlayVal,
    el("span", { class: "hint-line", text: "越暗字越清楚。這是背景本身的設定，用到它的歌都會一起變。" }));
  const applyAll = el("label", { class: "row small" }, el("input", { type: "checkbox" }), " 整份歌單都換成這個背景");

  const paint = () => {
    grid.replaceChildren();
    const chosen = themeFor(item);
    for (const t of themes.filter((x) => !x.archived)) {
      const pic = el("div", { class: "pic" });
      paintBackground(pic, t, 320);
      const used = [t.lastUsed ? `上次 ${fmtDate(t.lastUsed)}` : "還沒用過", t.serviceCount ? `${t.serviceCount} 次` : ""].filter(Boolean).join(" · ");
      grid.appendChild(el("button", { type: "button", class: "bcard" + (t.id === chosen.id ? " on" : ""), onclick: () => choose(t) },
        pic, el("div", { class: "meta2" }, el("b", { text: t.name }), el("span", { text: used }))));
    }
    overlayRange.value = String(chosen.overlay || 0);
    overlayVal.textContent = Math.round((chosen.overlay || 0) * 100) + "%";
    overlayRange.disabled = !chosen.id;
  };

  const choose = async (t) => {
    if (applyAll.querySelector("input").checked) {
      await saver.flushAll();
      try {
        mergeService(await api(`/api/services/${svc.id}/apply`, { method: "POST", body: { themeId: t.id } }));
        toast(`整份歌單都換成「${t.name}」`);
      } catch (e) { showError(e); return; }
    } else {
      item.themeId = t.id;
      saver.mark(item.id, { themeId: t.id });
    }
    paint();
    renderEditor();
    renderPreview();
  };

  const saveOverlay = debounce(async (theme, value) => {
    try {
      const fresh = await api(`/api/themes/${theme.id}`, { method: "PATCH", body: { overlay: value } });
      Object.assign(theme, fresh);
    } catch (e) { showError(e); }
  }, 400);
  overlayRange.addEventListener("input", () => {
    const t = themeFor(item);
    if (!t.id) return;
    t.overlay = Number(overlayRange.value);
    overlayVal.textContent = Math.round(t.overlay * 100) + "%";
    saveOverlay(t, t.overlay);
    paint();
    renderPreview();
  });

  const onFiles = async (files) => {
    zone.querySelector("b").textContent = "上傳中…";
    try {
      const created = await uploadImages(files, (i, n) => { zone.querySelector("b").textContent = `上傳中… ${i + 1}/${n}`; });
      for (const t of created) {
        const at = themes.findIndex((x) => x.id === t.id);
        if (at >= 0) themes[at] = t; else themes.unshift(t);
      }
      toast(`上傳了 ${created.length} 張`);
      if (created[0]) await choose(created[0]);
    } catch (e) { showError(e, "上傳失敗"); }
    zone.querySelector("b").textContent = "＋ 上傳新的背景圖";
    paint();
  };
  zone.addEventListener("click", async () => {
    const input = el("input", { type: "file", accept: "image/*", multiple: true });
    input.addEventListener("change", () => { if (input.files.length) onFiles(Array.from(input.files)); });
    input.click();
  });
  wireDropzone(zone, onFiles);

  paint();
  modal({
    title: `「${item.title || "這首歌"}」的背景`, wide: true,
    body: el("div", { class: "stack" }, zone, grid, overlayRow, applyAll,
      el("a", { href: "/backgrounds", target: "_blank", rel: "noopener", class: "small", text: "到背景庫改名字、刪掉不用的背景 ↗" })),
    buttons: [{ text: "完成", class: "btn-primary" }],
  });
}

// ---------- 排版挑選 ----------
function openStylePicker(item) {
  const grid = el("div", { class: "card-grid" });
  const applyAll = el("label", { class: "row small" }, el("input", { type: "checkbox" }), " 整份歌單都換成這個排版");
  const plan = planFor(item);
  const sample = plan.slides.find((s) => s.kind === "lyrics") || { kind: "lyrics", label: "副", text: "主耶穌 我敬拜祢\n祢配得一切頌讚" };
  const paint = () => {
    grid.replaceChildren();
    const chosen = styleFor(item);
    for (const s of styles.filter((x) => !x.archived)) {
      const { el: slide } = renderSlide(sample, { title: item.title || "詩歌", theme: themeFor(item), style: s, size: svc.slideSize, thumb: 320 });
      grid.appendChild(el("button", { type: "button", class: "bcard" + (s.id === chosen.id ? " on" : ""), onclick: () => choose(s) },
        el("div", { class: "pic" }, slide), el("div", { class: "meta2" }, el("b", { text: s.name }),
          el("span", { text: `歌詞 ${s.lyrics.size}pt · ${s.showHeader ? "有歌名列" : "只有歌詞"}` }))));
    }
  };
  const choose = async (s) => {
    if (applyAll.querySelector("input").checked) {
      await saver.flushAll();
      try {
        mergeService(await api(`/api/services/${svc.id}/apply`, { method: "POST", body: { styleId: s.id } }));
        toast(`整份歌單都換成「${s.name}」`);
      } catch (e) { showError(e); return; }
    } else {
      item.styleId = s.id;
      saver.mark(item.id, { styleId: s.id });
    }
    paint();
    renderEditor();
    renderPreview();
  };
  paint();
  modal({
    title: `「${item.title || "這首歌"}」的排版`, wide: true,
    body: el("div", { class: "stack" }, grid, applyAll,
      el("a", { href: "/styles", target: "_blank", rel: "noopener", class: "small", text: "到排版頁調整字型、大小、位置（改完回來重新整理）↗" })),
    buttons: [{ text: "完成", class: "btn-primary" }],
  });
}

// ---------------------------------------------------------------------------
// 右邊：預覽
// ---------------------------------------------------------------------------

function slideCell(info, n, item) {
  const { el: slide, over } = renderSlide(info, {
    title: item.title, theme: themeFor(item), style: styleFor(item), size: svc.slideSize, thumb: 960,
  });
  const label = info.kind === "title" ? "歌名頁" : (info.label || "歌詞") + (info.repeat > 1 ? ` ×${info.repeat}` : "")
    + (info.kind === "blank" ? "（空白頁）" : "");
  return el("div", { class: "slide-cell" }, slide,
    el("div", { class: "slide-cap" }, el("span", { class: "n", text: String(n) }), el("span", { class: "l", text: label }),
      over ? el("span", { class: "w", text: "字太多，會超出畫面" }) : null));
}

function renderPreview() {
  const box = $("#preview");
  const warnBox = $("#previewWarn");
  box.replaceChildren();
  warnBox.replaceChildren();
  let total = 0;
  if (previewMode === "song") {
    const item = current();
    box.className = "slides-grid big";
    if (!item) { $("#slideCount").textContent = ""; return; }
    const plan = planFor(item);
    plan.slides.forEach((info, i) => box.appendChild(slideCell(info, i + 1, item)));
    total = plan.slides.length;
    if (!total) box.appendChild(el("div", { class: "empty" }, el("b", { text: "貼上歌詞就會看到每一頁" })));
    paintWarnings(plan);
    $("#slideCount").textContent = `${total} 張`;
  } else {
    box.className = "slides-grid";
    for (const item of svc.items) {
      const plan = planFor(item);
      box.appendChild(el("div", { class: "row", style: { gridColumn: "1 / -1" } },
        el("b", { text: item.title || "（沒有歌名）" }), el("span", { class: "muted small", text: `${plan.slides.length} 張` })));
      plan.slides.forEach((info) => { total += 1; box.appendChild(slideCell(info, total, item)); });
      for (const w of plan.warnings) warnBox.appendChild(el("span", { class: "w", text: `${item.title || "（沒有歌名）"}：${w}` }));
    }
    $("#slideCount").textContent = `整份共 ${total} 張`;
  }
}
const renderPreviewSoon = debounce(renderPreview, 120);

$("#previewMode").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-mode]");
  if (!btn) return;
  previewMode = btn.dataset.mode;
  $("#previewMode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
  renderPreview();
});

function renderExportInfo() {
  const info = $("#exportInfo");
  const last = svc.lastExport;
  info.replaceChildren();
  if (last) {
    info.append(`上次匯出：${last.created_at}（${last.slides} 張${last.created_by ? " · " + last.created_by : ""}） `,
      el("a", { href: `/exports/${last.id}/download`, text: "再下載一次" }));
  } else {
    info.textContent = "還沒匯出過。匯出後會留一份在「匯出紀錄」。";
  }
}

// ---------------------------------------------------------------------------
// 匯出
// ---------------------------------------------------------------------------

$("#btnExport").addEventListener("click", async () => {
  const btn = $("#btnExport");
  btn.disabled = true;
  btn.textContent = "製作中…";
  try {
    await saver.flushAll();
    const r = await api(`/api/services/${svc.id}/export`, { method: "POST" });
    mergeService(r.service);
    download(r.downloadUrl);
    const added = r.library.filter((x) => x.action === "added").length;
    const updated = r.library.filter((x) => x.action === "updated").length;
    const lib = [added ? `詩歌庫新增 ${added} 首` : "", updated ? `更新 ${updated} 首的歌詞` : ""].filter(Boolean).join("、");
    toast(`PPT 做好了（${r.export.slides} 張），開始下載`, "ok", lib);
    if (r.warnings.length) toast("注意：" + r.warnings.join("；"), "warn", "", 9000);
    renderAll();
  } catch (e) {
    showError(e, "匯出失敗");
  }
  btn.disabled = false;
  btn.textContent = "⬇ 匯出 PPT";
});

// ---------------------------------------------------------------------------
// 左上：歌單資訊
// ---------------------------------------------------------------------------

$("#svcName").addEventListener("input", (e) => { svc.name = e.target.value; saveName(e.target.value); });
$("#svcDate").addEventListener("change", (e) => { if (e.target.value) saveService({ date: e.target.value }); });
$("#svcSize").addEventListener("change", (e) => { svc.slideSize = e.target.value; renderPreview(); saveService({ slideSize: e.target.value }); });
$("#svcFollow").addEventListener("change", (e) => {
  svc.followSequence = e.target.checked;
  renderEditor();
  renderPreview();
  saveService({ followSequence: e.target.checked });
});
$("#btnReimport").addEventListener("click", async () => {
  if (!confirm("重新讀一次 Google 文件？\n歌詞和歌序會換成文件上的；已經挑好的背景和排版會保留。")) return;
  await saver.flushAll();
  const btn = $("#btnReimport");
  btn.disabled = true;
  try {
    svc = await api(`/api/services/${svc.id}/gdoc`, { method: "POST", body: {} });
    if (!itemById(selectedId)) selectedId = svc.items[0] ? svc.items[0].id : null;
    renderAll();
    toast(`已從文件更新：${svc.items.length} 首歌`);
  } catch (e) { showError(e, "讀文件失敗"); }
  btn.disabled = false;
});
$("#btnDuplicate").addEventListener("click", async () => {
  const d = new Date(svc.date + "T00:00:00");
  d.setDate(d.getDate() + 7);
  const next = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const date = prompt("新的聚會日期（同樣的歌、背景、排版）", next);
  if (!date) return;
  await saver.flushAll();
  try {
    const fresh = await api(`/api/services/${svc.id}/duplicate`, { method: "POST", body: { date } });
    location.href = `/services/${fresh.id}`;
  } catch (e) { showError(e); }
});

// ---------------------------------------------------------------------------
// 別人的修改：每 10 秒問一次
// ---------------------------------------------------------------------------

async function poll() {
  if (document.hidden || saver.busy()) return;
  let fresh;
  try { fresh = await api(`/api/services/${svc.id}`); } catch (_) { return; }
  if (saver.busy() || fresh.stamp === stampOf(svc)) return;
  const before = current();
  const beforeVersion = before ? before.version : null;
  const typingHere = document.activeElement && document.activeElement.closest("#itemEditor") && Date.now() - lastTyping < 15000;
  svc = fresh;
  if (!itemById(selectedId)) selectedId = svc.items[0] ? svc.items[0].id : null;
  renderMeta();
  renderSongList();
  renderExportInfo();
  const now = current();
  if (now && beforeVersion !== null && now.version !== beforeVersion) {
    if (typingHere) {
      toast(`${now.updatedBy || "別人"} 剛剛也改了這首歌`, "warn", "你下一次存檔會被擋下來，畫面會換成最新內容。");
    } else {
      renderEditor();
      toast(`${now.updatedBy || "別人"} 更新了「${now.title}」`, "ok");
    }
  }
  renderPreview();
}
setInterval(poll, 10000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

// Ctrl+S：馬上存
document.addEventListener("keydown", async (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    await saver.flushAll();
    toast("都存好了");
  }
});
window.addEventListener("beforeunload", (e) => {
  if (saver.busy()) { e.preventDefault(); e.returnValue = ""; }
});

// ---------------------------------------------------------------------------
// 開始
// ---------------------------------------------------------------------------

function renderAll() {
  renderMeta();
  renderSongList();
  renderEditor();
  renderPreview();
  renderExportInfo();
}

const fromHash = Number((location.hash.match(/^#item-(\d+)$/) || [])[1]);
selectedId = itemById(fromHash) ? fromHash : (svc.items[0] ? svc.items[0].id : null);
renderAll();
