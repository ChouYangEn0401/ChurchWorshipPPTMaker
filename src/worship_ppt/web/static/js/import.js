// 從 Google 文件匯入：先讀取、給人看一遍，再建立歌單。

import { $, api, el, fmtDate, pageData, showError, toast } from "./common.js";

const { target } = pageData();
let lastSheet = null;
let targetId = target ? target.id : null;

function songBlock(song) {
  const status = [];
  if (song.library) {
    status.push(el("span", { class: "badge ok", text: "詩歌庫有" }));
    status.push(el("span", { class: "sub", text: song.library.lyricsChanged
      ? "歌詞跟詩歌庫的不一樣：這次用文件上的，匯出時詩歌庫會更新（舊版本會保留）。"
      : "會套用上次的背景和排版。" }));
  } else {
    status.push(el("span", { class: "badge warn", text: "新歌" }));
    status.push(el("span", { class: "sub", text: "詩歌庫還沒有：先用前一首的背景和排版，匯出時自動加進詩歌庫。" }));
  }
  const warns = [...(song.warnings || []), ...(song.missing || []).map((m) => `歌序裡的「${m}」在歌詞找不到，會放一張空白頁`)];
  return el("div", { class: "import-song" },
    el("div", { class: "stack" },
      el("b", { text: song.title }),
      song.key ? el("span", { class: "chip", text: "調性 " + song.key }) : null,
      el("div", { class: "stack small" }, ...status),
      el("span", { class: "small muted", text: "歌序：" + (song.sequence || "（沒寫，照歌詞順序）") }),
      warns.length ? el("div", { class: "warnlist" }, ...warns.map((w) => el("span", { class: "w", text: w }))) : null),
    el("pre", { class: "lyr", text: song.lyrics || "（沒有歌詞）" }));
}

function renderTargets(sameDate) {
  const box = $("#targetChoice");
  box.replaceChildren();
  const options = [];
  if (target) options.push({ id: target.id, text: `更新「${fmtDate(target.date)} ${target.name}」這份歌單（保留已經挑好的背景和排版）` });
  for (const s of sameDate || []) {
    if (!target || s.id !== target.id) options.push({ id: s.id, text: `更新已經有的「${fmtDate(s.date)} ${s.name}」（保留背景和排版）` });
  }
  if (!options.length) { targetId = null; return; }
  options.push({ id: null, text: "另外建立一份新的歌單" });
  targetId = options[0].id;
  for (const [i, opt] of options.entries()) {
    const radio = el("input", { type: "radio", name: "target", checked: i === 0 });
    radio.addEventListener("change", () => { targetId = opt.id; updateButton(); });
    box.appendChild(el("label", { class: "row small" }, radio, " " + opt.text));
  }
}

function updateButton() {
  $("#btnImport").textContent = targetId ? "更新歌單 →" : "建立歌單 →";
}

$("#btnPreview").addEventListener("click", async () => {
  const btn = $("#btnPreview");
  btn.disabled = true;
  btn.textContent = "讀取中…";
  try {
    const r = await api("/api/gdoc/preview", { method: "POST", body: { url: $("#gdocUrl").value.trim() } });
    lastSheet = r.sheet;
    $("#previewPanel").hidden = false;
    $("#sheetMeta").textContent = [r.sheet.date_text ? `文件日期 ${r.sheet.date_text}` : "", r.sheet.team, `${r.sheet.songs.length} 首歌`]
      .filter(Boolean).join(" · ");
    $("#songs").replaceChildren(...r.sheet.songs.map(songBlock));
    const warn = $("#sheetWarn");
    warn.hidden = !r.sheet.warnings.length;
    warn.replaceChildren(...r.sheet.warnings.map((w) => el("span", { class: "w", text: w })));
    $("#svcDate").value = r.sheet.date || new Date().toISOString().slice(0, 10);
    renderTargets(r.sameDate);
    updateButton();
    $("#previewPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    showError(e, "讀不到文件");
  }
  btn.disabled = false;
  btn.textContent = "讀取文件";
});

$("#btnImport").addEventListener("click", async () => {
  if (!lastSheet) return;
  const btn = $("#btnImport");
  btn.disabled = true;
  try {
    const svc = await api("/api/gdoc/import", { method: "POST", body: {
      url: $("#gdocUrl").value.trim(), date: $("#svcDate").value, serviceId: targetId,
    } });
    toast(`歌單好了：${svc.items.length} 首歌`);
    location.href = `/services/${svc.id}`;
  } catch (e) {
    showError(e, "匯入失敗");
    btn.disabled = false;
  }
});

if (target) toast(`會更新「${target.name}」這份歌單`, "ok");
