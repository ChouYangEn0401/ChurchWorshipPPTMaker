/* 教會敬拜 PPT 產生器 — 網頁版前端 (純 vanilla JS，無外部相依) */

// ---------- 常數 ----------
const SIZES = { "4:3": [10, 7.5], "16:9": [13.333, 7.5] };

const FONTS = [
  { label: "微軟正黑體", value: "Microsoft JhengHei" },
  { label: "微軟正黑體 UI", value: "Microsoft JhengHei UI" },
  { label: "新細明體", value: "PMingLiU" },
  { label: "細明體", value: "MingLiU" },
  { label: "標楷體", value: "DFKai-SB" },
  { label: "Arial", value: "Arial" },
  { label: "Times New Roman", value: "Times New Roman" },
  { label: "Segoe UI", value: "Segoe UI" },
  { label: "Georgia", value: "Georgia" },
  { label: "Verdana", value: "Verdana" },
];

const PALETTE = ["#FFFFFF", "#000000", "#FFD700", "#FFFACD", "#1E90FF",
  "#87CEFA", "#FF4500", "#32CD32", "#A9A9A9"];

// 舊專案的預設絕對路徑（匯入舊資料時當預設值）；ppt_settings.json 是 README 在用的存檔
const LEGACY_DEFAULT = "c:/Users/user/Documents/_myProjects_/Python Projects/ChurchWorshipPPTMaker/ppt_settings.json";

// ---------- 小工具 ----------
let _seq = 0;
const uid = (p) => `${p}${Date.now().toString(36)}${(_seq++).toString(36)}`;
const byId = (id) => document.getElementById(id);
const escapeHtml = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function h(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const k of kids) {
    if (k == null) continue;
    e.appendChild(typeof k === "string" ? document.createTextNode(k) : k);
  }
  return e;
}

let _toastT = null;
function toast(msg) {
  const t = byId("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(_toastT);
  _toastT = setTimeout(() => t.classList.remove("show"), 3200);
}

// ---------- 狀態 ----------
let state = freshState();

function defaultStyleObj(id, name) {
  return {
    id, name,
    title: { font: "Microsoft JhengHei", size: 60, color: "#FFD700", bold: true },
    segment: { font: "Microsoft JhengHei", size: 30, color: "#FF4500", bold: false },
    lyrics: { font: "Microsoft JhengHei", size: 52, color: "#FFFFFF", bold: false },
    lyricsLeft: 0.05, lyricsTop: 1.8, lyricsAlign: "center", showHeader: true,
  };
}
function newSong(themeId, styleId) {
  return { id: uid("song"), title: "", lyrics: "", themeId, textStyleId: styleId };
}
function freshState() {
  const t = { id: uid("t"), name: "純黑底", image: null, bgColor: "#000000", overlay: 0 };
  const s = defaultStyleObj(uid("s"), "預設樣式");
  return {
    library: { themes: [t], textStyles: [s] },
    project: { name: "", slideSize: "4:3", songs: [newSong(t.id, s.id)] },
    ui: { selectedSongId: null },
  };
}
function normalize(s) {
  s.ui = s.ui || {};
  if (!s.library.themes.length) s.library.themes.push(freshState().library.themes[0]);
  if (!s.library.textStyles.length) s.library.textStyles.push(defaultStyleObj(uid("s"), "預設樣式"));
  return s;
}
function ensureSelection() {
  const songs = state.project.songs;
  if (!songs.find((x) => x.id === state.ui.selectedSongId)) {
    state.ui.selectedSongId = songs.length ? songs[0].id : null;
  }
}

const themeById = (id) => state.library.themes.find((t) => t.id === id) || state.library.themes[0];
const styleById = (id) => state.library.textStyles.find((t) => t.id === id) || state.library.textStyles[0];
const currentSong = () => state.project.songs.find((s) => s.id === state.ui.selectedSongId);

// ---------- 自動存檔 ----------
let _saveT = null;
function scheduleSave() {
  clearTimeout(_saveT);
  _saveT = setTimeout(() => {
    fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library: state.library, project: state.project }),
    }).catch(() => {});
  }, 700);
}
function touched() { scheduleSave(); }

// ---------- 歌詞解析（對齊後端 pptx_builder.parse_lyrics）----------
function parseLyrics(text) {
  const blocks = [];
  let seg = "Intro", lines = [];
  for (const raw of (text || "").split(/\r?\n/)) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { if (lines.length) lines.push(""); continue; }
    const m = line.trim().match(/^\[(.+?)\]$/);
    if (m) {
      if (lines.length) blocks.push([seg, lines.join("\n").replace(/^\n+|\n+$/g, "")]);
      seg = m[1]; lines = [];
    } else lines.push(line);
  }
  if (lines.length) blocks.push([seg, lines.join("\n").replace(/^\n+|\n+$/g, "")]);
  return blocks;
}

// ---------- 預覽投影片元件（預覽與積木縮圖共用）----------
function styleRun(node, part, ff) {
  node.style.fontFamily = `"${part.font}", "Microsoft JhengHei", sans-serif`;
  node.style.color = part.color;
  node.style.fontWeight = part.bold ? "700" : "400";
  node.style.fontSize = (part.size * ff).toFixed(3) + "cqw";
}
function buildSlideEl(slide, theme, ts, sizeKey) {
  const [W, H] = SIZES[sizeKey] || SIZES["4:3"];
  const ff = 100 / 72 / W; // 每一點(pt) 對應多少 cqw
  const el = h("div", "slide");
  el.style.setProperty("--aspect", `${W} / ${H}`);
  el.style.backgroundColor = theme.bgColor || "#000";
  if (theme.image) el.style.backgroundImage = `url(/media/${theme.image})`;
  if (theme.overlay > 0) {
    const ov = h("div", "overlay");
    ov.style.opacity = theme.overlay;
    el.appendChild(ov);
  }
  if (ts.showHeader && (slide.title || slide.seg)) {
    const hd = h("div", "header");
    hd.style.top = (0.4 / H * 100) + "%";
    if (slide.title) {
      const t = h("span"); t.textContent = slide.title + "  ";
      styleRun(t, ts.title, ff); hd.appendChild(t);
    }
    if (slide.seg) {
      const s = h("span"); s.textContent = "[" + slide.seg + "]";
      styleRun(s, ts.segment, ff); hd.appendChild(s);
    }
    el.appendChild(hd);
  }
  const ly = h("div", "lyrics");
  const left = Number(ts.lyricsLeft) || 0, top = Number(ts.lyricsTop) || 0;
  ly.style.left = (left / W * 100) + "%";
  ly.style.top = (top / H * 100) + "%";
  ly.style.width = ((W - 2 * left) / W * 100) + "%";
  ly.style.textAlign = ts.lyricsAlign || "center";
  styleRun(ly, ts.lyrics, ff);
  ly.textContent = slide.lyrics || "";
  el.appendChild(ly);
  return el;
}

// ---------- 渲染：歌曲清單 ----------
function renderSongList() {
  const box = byId("songList");
  box.innerHTML = "";
  const n = state.project.songs.length;
  state.project.songs.forEach((song, i) => {
    const row = h("div", "song-row" + (song.id === state.ui.selectedSongId ? " active" : ""));
    row.appendChild(h("span", "idx", String(i + 1)));
    const nm = h("span", "name" + (song.title ? "" : " empty"), song.title || "未命名");
    row.appendChild(nm);
    const up = h("button", "ghost small", "▲");
    up.title = "上移"; up.disabled = i === 0;
    up.onclick = (e) => { e.stopPropagation(); moveSong(i, -1); };
    const down = h("button", "ghost small", "▼");
    down.title = "下移"; down.disabled = i === n - 1;
    down.onclick = (e) => { e.stopPropagation(); moveSong(i, 1); };
    const del = h("button", "ghost small", "✕");
    del.title = "刪除這首歌";
    del.onclick = (e) => { e.stopPropagation(); removeSong(song.id); };
    row.appendChild(up); row.appendChild(down); row.appendChild(del);
    row.onclick = () => selectSong(song.id);
    box.appendChild(row);
  });
}

// ---------- 渲染：歌曲編輯區 ----------
function fontSelect(value, onChange) {
  const sel = h("select");
  let found = false;
  for (const f of FONTS) {
    const o = h("option"); o.value = f.value; o.textContent = f.label;
    if (f.value === value) { o.selected = true; found = true; }
    sel.appendChild(o);
  }
  if (!found) {
    const o = h("option"); o.value = value; o.textContent = value + "（自訂）";
    o.selected = true; sel.appendChild(o);
  }
  const oc = h("option"); oc.value = "__custom__"; oc.textContent = "自訂字型…";
  sel.appendChild(oc);
  sel.onchange = () => {
    if (sel.value === "__custom__") {
      const v = prompt("輸入字型名稱（要跟系統/PowerPoint 內的名稱一致）", value || "");
      if (v) onChange(v.trim());
      renderSongEditor(); // 重繪以更新選項
    } else onChange(sel.value);
  };
  return sel;
}

function renderSongEditor() {
  const box = byId("songEditor");
  box.innerHTML = "";
  const song = currentSong();
  if (!song) {
    box.appendChild(h("div", "empty-note", "左側「新增歌曲」開始製作"));
    return;
  }

  // 歌名
  const f1 = h("div", "field");
  f1.appendChild(h("label", null, "歌曲名稱"));
  const title = h("input"); title.type = "text"; title.value = song.title;
  title.placeholder = "例：新酒";
  title.oninput = () => {
    song.title = title.value;
    renderSongList(); renderPreview(); touched();
  };
  f1.appendChild(title);
  box.appendChild(f1);

  // 歌詞
  const f2 = h("div", "field");
  f2.appendChild(h("label", null, "歌詞（用 [段落] 分頁，例 [Verse] [Chorus]）"));
  const ta = h("textarea");
  ta.value = song.lyrics;
  ta.placeholder = "[Verse]\n我感覺主恩膏充滿我們中間\n神的聖靈正在運行\n[Chorus]\n新酒澆灌帶下新鮮恩膏";
  ta.oninput = () => { song.lyrics = ta.value; renderPreview(); touched(); };
  f2.appendChild(ta);
  box.appendChild(f2);

  // 布景積木
  box.appendChild(blockPicker("🖼 布景積木", state.library.themes, song.themeId,
    (id) => { song.themeId = id; renderPreview(); touched(); },
    () => openThemeEditor(themeById(song.themeId)),
    () => openThemeEditor(null, (t) => { song.themeId = t.id; })));

  // 字體積木
  box.appendChild(blockPicker("🔤 字體積木", state.library.textStyles, song.textStyleId,
    (id) => { song.textStyleId = id; renderPreview(); touched(); },
    () => openStyleEditor(styleById(song.textStyleId)),
    () => openStyleEditor(null, (s) => { song.textStyleId = s.id; })));

  box.appendChild(h("div", "hint",
    "小提醒：積木是共用的，改一塊布景／字體，所有用到它的歌都會一起變。要單獨換就按「新增」開一塊新的。"));
}

function blockPicker(label, list, currentId, onPick, onEdit, onNew) {
  const f = h("div", "field");
  f.appendChild(h("label", null, label));
  const row = h("div", "blockpick");
  const sel = h("select");
  for (const b of list) {
    const o = h("option"); o.value = b.id; o.textContent = b.name;
    if (b.id === currentId) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => onPick(sel.value);
  const edit = h("button", "small", "編輯"); edit.onclick = onEdit;
  const add = h("button", "small", "＋ 新增"); add.onclick = onNew;
  row.appendChild(sel); row.appendChild(edit); row.appendChild(add);
  f.appendChild(row);
  return f;
}

// ---------- 渲染：預覽 ----------
function renderPreview() {
  const pane = byId("previewPane");
  pane.innerHTML = "";
  const song = currentSong();
  if (!song) { pane.appendChild(h("div", "empty-note", "尚無歌曲")); return; }
  const theme = themeById(song.themeId), ts = styleById(song.textStyleId);
  const blocks = parseLyrics(song.lyrics);

  const head = h("div", "preview-head");
  head.innerHTML = `<b>${escapeHtml(song.title || "未命名")}</b>` +
    `<span class="count">共 ${blocks.length} 頁 · ${state.project.slideSize}</span>`;
  pane.appendChild(head);

  if (!blocks.length) {
    pane.appendChild(h("div", "empty-note", "貼上歌詞就會即時看到每一頁的樣子"));
    return;
  }
  blocks.forEach(([seg, lyr], i) => {
    const wrap = h("div", "slide-wrap");
    const lab = h("div", "slide-label");
    lab.innerHTML = `<span>第 ${i + 1} 頁 · [${escapeHtml(seg)}]</span>`;
    wrap.appendChild(lab);
    wrap.appendChild(buildSlideEl({ title: song.title, seg, lyrics: lyr }, theme, ts, state.project.slideSize));
    pane.appendChild(wrap);
  });
}

function renderTopbar() {
  byId("projName").value = state.project.name || "";
  document.querySelectorAll("#sizeToggle button").forEach((b) => {
    b.classList.toggle("active", b.dataset.size === state.project.slideSize);
  });
}

function renderAll() {
  renderTopbar();
  renderSongList();
  renderSongEditor();
  renderPreview();
}

// ---------- 歌曲操作 ----------
function selectSong(id) { state.ui.selectedSongId = id; renderSongList(); renderSongEditor(); renderPreview(); }
function addSong() {
  const cur = currentSong();
  const themeId = cur ? cur.themeId : state.library.themes[0].id;
  const styleId = cur ? cur.textStyleId : state.library.textStyles[0].id;
  const s = newSong(themeId, styleId);
  state.project.songs.push(s);
  selectSong(s.id); touched();
}
function moveSong(i, dir) {
  const songs = state.project.songs;
  const j = i + dir;
  if (j < 0 || j >= songs.length) return;
  [songs[i], songs[j]] = [songs[j], songs[i]];
  renderSongList(); touched();
}
function removeSong(id) {
  const songs = state.project.songs;
  if (songs.length <= 1) { toast("至少要留一首歌"); return; }
  const i = songs.findIndex((x) => x.id === id);
  songs.splice(i, 1);
  ensureSelection();
  renderAll(); touched();
}

// ---------- Modal 基礎 ----------
function openModal(title, bodyEl, footEl, wide) {
  const back = h("div", "modal-back");
  const modal = h("div", "modal");
  if (wide) modal.style.width = "min(980px, 96vw)";
  const head = h("div", "modal-head");
  head.appendChild(h("h3", null, title));
  const close = h("button", "ghost", "✕");
  close.onclick = () => back.remove();
  head.appendChild(close);
  const body = h("div", "modal-body"); body.appendChild(bodyEl);
  modal.appendChild(head); modal.appendChild(body);
  if (footEl) modal.appendChild(footEl);
  back.appendChild(modal);
  back.onclick = (e) => { if (e.target === back) back.remove(); };
  byId("modalRoot").appendChild(back);
  return back;
}

// ---------- 積木庫 ----------
function openLibrary() {
  const body = h("div");
  const tabs = h("div", "tabs");
  const grid = h("div", "block-grid");
  let tab = "themes";

  function draw() {
    tabs.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.t === tab));
    grid.innerHTML = "";
    if (tab === "themes") drawThemes(); else drawStyles();
  }
  function drawThemes() {
    for (const t of state.library.themes) {
      const card = h("div", "block-card");
      const thumb = h("div", "thumb");
      thumb.style.backgroundColor = t.bgColor || "#000";
      if (t.image) thumb.style.backgroundImage = `url(/media/${t.image})`;
      if (t.overlay > 0) { const o = h("div", "mini-ov"); o.style.opacity = t.overlay; thumb.appendChild(o); }
      card.appendChild(thumb);
      card.appendChild(blockCardBody(t.name,
        () => { openThemeEditor(t); },
        () => { duplicateTheme(t); draw(); },
        () => { if (deleteTheme(t)) draw(); }));
      grid.appendChild(card);
    }
    const add = h("div", "block-card add", "＋ 新增布景積木");
    add.onclick = () => openThemeEditor(null);
    grid.appendChild(add);
  }
  function drawStyles() {
    const sample = { title: "詩歌", seg: "Chorus", lyrics: "主耶穌 我敬拜祢\n祢配得一切頌讚" };
    const neutral = { image: null, bgColor: "#333842", overlay: 0 };
    for (const s of state.library.textStyles) {
      const card = h("div", "block-card");
      const thumb = h("div", "thumb");
      thumb.style.padding = "0";
      thumb.appendChild(buildSlideEl(sample, neutral, s, "4:3"));
      card.appendChild(thumb);
      card.appendChild(blockCardBody(s.name,
        () => { openStyleEditor(s); },
        () => { duplicateStyle(s); draw(); },
        () => { if (deleteStyle(s)) draw(); }));
      grid.appendChild(card);
    }
    const add = h("div", "block-card add", "＋ 新增字體積木");
    add.onclick = () => openStyleEditor(null);
    grid.appendChild(add);
  }

  const tb1 = h("button", null, "🖼 布景積木"); tb1.dataset.t = "themes";
  const tb2 = h("button", null, "🔤 字體積木"); tb2.dataset.t = "styles";
  tb1.onclick = () => { tab = "themes"; draw(); };
  tb2.onclick = () => { tab = "styles"; draw(); };
  tabs.appendChild(tb1); tabs.appendChild(tb2);
  body.appendChild(tabs); body.appendChild(grid);
  draw();
  const back = openModal("積木庫", body, null, true);
  // 關閉時刷新主畫面（名稱/樣式可能有變）
  const obs = new MutationObserver(() => {
    if (!document.body.contains(back)) { obs.disconnect(); renderAll(); }
  });
  obs.observe(byId("modalRoot"), { childList: true });
}

function blockCardBody(name, onEdit, onDup, onDel) {
  const body = h("div", "body");
  body.appendChild(h("div", "nm", name));
  const acts = h("div", "acts");
  const e = h("button", "small", "編輯"); e.onclick = onEdit;
  const d = h("button", "small", "複製"); d.onclick = onDup;
  const x = h("button", "small danger", "刪除"); x.onclick = onDel;
  acts.appendChild(e); acts.appendChild(d); acts.appendChild(x);
  body.appendChild(acts);
  return body;
}

// ---------- 布景積木編輯器 ----------
function openThemeEditor(theme, afterCreate) {
  const isNew = !theme;
  const t = theme ? JSON.parse(JSON.stringify(theme))
    : { id: uid("t"), name: "新布景", image: null, bgColor: "#000000", overlay: 0 };

  const body = h("div");
  const preview = h("div", "mini-slide-wrap");
  function refresh() {
    preview.innerHTML = "";
    preview.appendChild(buildSlideEl(
      { title: "詩歌", seg: "Verse", lyrics: "在祢面前\n我敬拜" },
      t, defaultStyleObj("_", "_"), "4:3"));
  }

  // 名稱
  const nameRow = h("div", "form-row");
  nameRow.appendChild(h("label", null, "名稱"));
  const name = h("input"); name.type = "text"; name.value = t.name; name.style.flex = "1";
  name.oninput = () => { t.name = name.value; };
  nameRow.appendChild(name);
  body.appendChild(nameRow);

  // 背景圖
  const imgRow = h("div", "form-row");
  imgRow.appendChild(h("label", null, "背景圖"));
  const upBtn = h("button", "small", "上傳圖片…");
  const imgName = h("span", "hint", t.image ? t.image : "（未設定，使用底色）");
  const rmBtn = h("button", "small ghost", "移除");
  upBtn.onclick = async () => {
    const file = await pickFile("image/*");
    if (!file) return;
    upBtn.textContent = "上傳中…"; upBtn.disabled = true;
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const j = await res.json();
      t.image = j.filename; imgName.textContent = j.filename; refresh();
    } catch (e) { toast("上傳失敗：" + e.message); }
    upBtn.textContent = "上傳圖片…"; upBtn.disabled = false;
  };
  rmBtn.onclick = () => { t.image = null; imgName.textContent = "（未設定，使用底色）"; refresh(); };
  imgRow.appendChild(upBtn); imgRow.appendChild(rmBtn); imgRow.appendChild(imgName);
  body.appendChild(imgRow);

  // 底色
  const colRow = h("div", "form-row");
  colRow.appendChild(h("label", null, "底色"));
  const col = h("input", "swatch"); col.type = "color"; col.value = t.bgColor;
  col.oninput = () => { t.bgColor = col.value; refresh(); };
  colRow.appendChild(col);
  colRow.appendChild(paletteRow((c) => { t.bgColor = c; col.value = c; refresh(); }));
  body.appendChild(colRow);

  // 暗色遮罩
  const ovRow = h("div", "form-row");
  ovRow.appendChild(h("label", null, "暗色遮罩"));
  const rr = h("div", "range-row");
  const rng = h("input"); rng.type = "range"; rng.min = 0; rng.max = 0.8; rng.step = 0.05; rng.value = t.overlay;
  const val = h("span", "hint", Math.round(t.overlay * 100) + "%");
  rng.oninput = () => { t.overlay = Number(rng.value); val.textContent = Math.round(t.overlay * 100) + "%"; refresh(); };
  rr.appendChild(rng); rr.appendChild(val);
  ovRow.style.flex = "1"; rr.style.flex = "1";
  ovRow.appendChild(rr);
  body.appendChild(ovRow);
  body.appendChild(h("div", "hint", "遮罩越高，背景越暗、文字越好讀。"));

  body.appendChild(h("div", "editor-preview"));
  body.appendChild(preview);
  refresh();

  const foot = h("div", "modal-foot");
  const cancel = h("button", null, "取消");
  const save = h("button", "primary", isNew ? "新增" : "儲存");
  const back = openModal(isNew ? "新增布景積木" : "編輯布景積木", body, foot);
  cancel.onclick = () => back.remove();
  save.onclick = () => {
    if (isNew) state.library.themes.push(t);
    else Object.assign(themeById(t.id), t);
    back.remove();
    if (afterCreate) afterCreate(t);
    renderAll(); touched();
  };
  foot.appendChild(cancel); foot.appendChild(save);
}

// ---------- 字體積木編輯器 ----------
function openStyleEditor(ts, afterCreate) {
  const isNew = !ts;
  const s = ts ? JSON.parse(JSON.stringify(ts)) : defaultStyleObj(uid("s"), "新字體樣式");

  const body = h("div");
  const preview = h("div", "mini-slide-wrap");
  const neutral = { image: null, bgColor: "#333842", overlay: 0 };
  function refresh() {
    preview.innerHTML = "";
    preview.appendChild(buildSlideEl(
      { title: "詩歌", seg: "Chorus", lyrics: "主耶穌 我敬拜祢\n祢的愛永不改變" },
      neutral, s, "4:3"));
  }

  // 名稱
  const nameRow = h("div", "form-row");
  nameRow.appendChild(h("label", null, "名稱"));
  const name = h("input"); name.type = "text"; name.value = s.name; name.style.flex = "1";
  name.oninput = () => { s.name = name.value; };
  nameRow.appendChild(name);
  body.appendChild(nameRow);

  // 三個部位
  body.appendChild(styleLine("標題", s.title, refresh));
  body.appendChild(styleLine("段落", s.segment, refresh));
  body.appendChild(styleLine("歌詞", s.lyrics, refresh));

  // 顯示標題列
  const shRow = h("div", "form-row");
  const sh = h("input"); sh.type = "checkbox"; sh.checked = s.showHeader;
  sh.onchange = () => { s.showHeader = sh.checked; refresh(); };
  const shl = h("label"); shl.style.width = "auto";
  shl.appendChild(sh); shl.appendChild(document.createTextNode(" 顯示上方標題列（歌名＋段落）"));
  shRow.appendChild(shl);
  body.appendChild(shRow);

  // 位置 + 對齊
  const posRow = h("div", "form-row");
  posRow.appendChild(h("label", null, "歌詞位置"));
  const left = numInput(s.lyricsLeft, 0.05, (v) => { s.lyricsLeft = v; refresh(); });
  const top = numInput(s.lyricsTop, 0.1, (v) => { s.lyricsTop = v; refresh(); });
  posRow.appendChild(labeled("距左(吋)", left));
  posRow.appendChild(labeled("距上(吋)", top));
  const align = h("select");
  [["center", "置中"], ["left", "靠左"], ["right", "靠右"]].forEach(([v, t]) => {
    const o = h("option"); o.value = v; o.textContent = t;
    if (v === s.lyricsAlign) o.selected = true; align.appendChild(o);
  });
  align.onchange = () => { s.lyricsAlign = align.value; refresh(); };
  posRow.appendChild(labeled("對齊", align));
  body.appendChild(posRow);

  body.appendChild(preview);
  refresh();

  const foot = h("div", "modal-foot");
  const cancel = h("button", null, "取消");
  const save = h("button", "primary", isNew ? "新增" : "儲存");
  const back = openModal(isNew ? "新增字體積木" : "編輯字體積木", body, foot);
  cancel.onclick = () => back.remove();
  save.onclick = () => {
    if (isNew) state.library.textStyles.push(s);
    else Object.assign(styleById(s.id), s);
    back.remove();
    if (afterCreate) afterCreate(s);
    renderAll(); touched();
  };
  foot.appendChild(cancel); foot.appendChild(save);
}

function styleLine(label, part, refresh) {
  const line = h("div", "style-line");
  line.appendChild(h("span", "lab", label));
  line.appendChild(fontSelectInline(part, refresh));
  const size = h("input"); size.type = "number"; size.min = 6; size.max = 200; size.value = part.size;
  size.oninput = () => { part.size = Number(size.value) || part.size; refresh(); };
  line.appendChild(size);
  const col = h("input", "swatch"); col.type = "color"; col.value = part.color;
  col.oninput = () => { part.color = col.value; refresh(); };
  line.appendChild(col);
  const bl = h("label"); bl.style.width = "auto";
  const b = h("input"); b.type = "checkbox"; b.checked = part.bold;
  b.onchange = () => { part.bold = b.checked; refresh(); };
  bl.appendChild(b); bl.appendChild(document.createTextNode("粗"));
  line.appendChild(bl);
  return line;
}
function fontSelectInline(part, refresh) {
  return fontSelect(part.font, (v) => { part.font = v; refresh(); });
}

// ---------- 表單小元件 ----------
function numInput(value, step, onChange) {
  const i = h("input"); i.type = "number"; i.step = step; i.min = 0; i.value = value; i.style.width = "64px";
  i.oninput = () => { const v = Number(i.value); if (v >= 0) onChange(v); };
  return i;
}
function labeled(text, node) {
  const w = h("span"); w.style.display = "inline-flex"; w.style.flexDirection = "column"; w.style.gap = "2px";
  w.appendChild(h("label", null, text)); w.appendChild(node);
  return w;
}
function paletteRow(onPick) {
  const row = h("span"); row.style.display = "inline-flex"; row.style.gap = "4px"; row.style.flexWrap = "wrap";
  for (const c of PALETTE) {
    const b = h("button", "swatch"); b.style.background = c; b.style.width = "22px"; b.style.height = "22px";
    b.title = c; b.onclick = () => onPick(c);
    row.appendChild(b);
  }
  return row;
}
function pickFile(accept) {
  return new Promise((resolve) => {
    const inp = h("input"); inp.type = "file"; inp.accept = accept || "*/*";
    inp.onchange = () => resolve(inp.files[0] || null);
    inp.click();
  });
}

// ---------- 存 / 讀 專案 ----------
async function saveProject() {
  const name = (state.project.name || "").trim();
  if (!name) { toast("請先在上方填專案名稱"); byId("projName").focus(); return; }
  const res = await fetch("/api/projects/" + encodeURIComponent(name), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ library: state.library, project: state.project }),
  });
  if (res.ok) toast("已儲存專案：" + name);
  else toast("儲存失敗");
}
async function openProjectDialog() {
  const list = await (await fetch("/api/projects")).json();
  const body = h("div");
  if (!list.length) body.appendChild(h("div", "empty-note", "還沒有存過任何專案"));
  for (const p of list) {
    const row = h("div", "song-row");
    row.style.cursor = "default";
    row.appendChild(h("span", "name", p.name));
    const load = h("button", "small primary", "載入");
    const del = h("button", "small danger", "刪除");
    load.onclick = async () => {
      const st = await (await fetch("/api/projects/" + encodeURIComponent(p.name))).json();
      applyLoadedState(st); back.remove(); toast("已載入：" + p.name);
    };
    del.onclick = async () => {
      if (!confirm(`確定刪除專案「${p.name}」？`)) return;
      await fetch("/api/projects/" + encodeURIComponent(p.name), { method: "DELETE" });
      row.remove();
    };
    row.appendChild(load); row.appendChild(del);
    body.appendChild(row);
  }
  const back = openModal("讀取專案", body, null);
}
function applyLoadedState(st) {
  if (!st || !st.project || !st.library) { toast("檔案格式不正確"); return; }
  state = normalize({ library: st.library, project: st.project, ui: {} });
  ensureSelection();
  renderAll(); touched();
}

// ---------- 匯入舊資料 ----------
async function importLegacy() {
  const path = prompt("輸入舊版 songs.json 的完整路徑：", LEGACY_DEFAULT);
  if (!path) return;
  const res = await fetch("/api/import-legacy", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) { toast("匯入失敗：" + await res.text()); return; }
  const st = await res.json();
  applyLoadedState(st);
  toast("已匯入舊資料，背景圖也一起搬進來了");
}

// ---------- 匯出 PPT ----------
async function exportPPT() {
  const resolved = {
    name: state.project.name || "敬拜歌單",
    slideSize: state.project.slideSize,
    songs: state.project.songs.map((s) => ({
      title: s.title, lyrics: s.lyrics,
      theme: themeById(s.themeId), textStyle: styleById(s.textStyleId),
    })),
  };
  const btn = byId("btnExport");
  btn.disabled = true; btn.textContent = "產生中…";
  try {
    const res = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(resolved),
    });
    if (!res.ok) throw new Error(await res.text());
    const warn = res.headers.get("X-PPT-Warnings");
    const blob = await res.blob();
    const today = new Date().toISOString().slice(0, 10);
    downloadBlob(blob, `${resolved.name}_${today}.pptx`);
    toast("PPT 已產生，開始下載");
    if (warn) toast("注意：背景圖遺失 → " + warn);
  } catch (e) {
    toast("匯出失敗：" + e.message);
  }
  btn.disabled = false; btn.textContent = "⬇ 匯出 PPT";
}
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a"); a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- 事件綁定 ----------
function wireTopbar() {
  byId("projName").oninput = (e) => { state.project.name = e.target.value; touched(); };
  document.querySelectorAll("#sizeToggle button").forEach((b) => {
    b.onclick = () => {
      state.project.slideSize = b.dataset.size;
      renderTopbar(); renderPreview(); touched();
    };
  });
  byId("btnAddSong").onclick = addSong;
  byId("btnLibrary").onclick = openLibrary;
  byId("btnOpen").onclick = openProjectDialog;
  byId("btnSave").onclick = saveProject;
  byId("btnImport").onclick = importLegacy;
  byId("btnExport").onclick = exportPPT;
}

// ---------- 啟動 ----------
async function init() {
  wireTopbar();
  try {
    const s = await (await fetch("/api/session")).json();
    if (s && s.project && s.library) state = normalize({ ...s, ui: {} });
    else state = freshState();
  } catch (e) { state = freshState(); }
  ensureSelection();
  renderAll();
}
init();
