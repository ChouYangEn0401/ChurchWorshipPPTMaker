// 清單頁的按鈕：<button data-action="…">。首頁、歌單、詩歌庫、匯出紀錄共用。

import { $$, api, el, fmtDate, modal, showError, toast } from "./common.js";

function nextSunday() {
  const d = new Date();
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7));
  // 不能用 toISOString()：那是 UTC，台灣早上 8 點前會變成前一天
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const actions = {
  "new-service": () => {
    const date = el("input", { type: "date", value: nextSunday(), required: true });
    const name = el("input", { type: "text", placeholder: "主日敬拜（不填就用預設名稱）", maxlength: 60 });
    const body = el("div", { class: "stack" },
      el("label", { class: "field" }, el("span", { class: "lbl", text: "聚會日期" }), date),
      el("label", { class: "field" }, el("span", { class: "lbl", text: "名稱" }), name),
      el("p", { class: "hint-line", text: "建好之後再一首一首加歌；也可以回上一頁用「從 Google 文件匯入」一次建好。" }));
    modal({
      title: "新增空白歌單", body,
      buttons: [{ text: "取消" }, {
        text: "建立", class: "btn-primary", onclick: async (close) => {
          try {
            const svc = await api("/api/services", { method: "POST", body: { date: date.value, name: name.value } });
            close();
            location.href = `/services/${svc.id}`;
          } catch (e) { showError(e); }
        },
      }],
    });
    date.focus();
  },

  "duplicate-service": async (btn) => {
    const date = el("input", { type: "date", value: btn.dataset.date || nextSunday() });
    modal({
      title: "複製成新的一週",
      body: el("div", { class: "stack" },
        el("p", { text: "同樣的歌、歌序、背景和排版，換一個日期。原本那份不會動。" }),
        el("label", { class: "field" }, el("span", { class: "lbl", text: "新的聚會日期" }), date)),
      buttons: [{ text: "取消" }, {
        text: "複製", class: "btn-primary", onclick: async (close) => {
          try {
            const svc = await api(`/api/services/${btn.dataset.id}/duplicate`, { method: "POST", body: { date: date.value } });
            close();
            location.href = `/services/${svc.id}`;
          } catch (e) { showError(e); }
        },
      }],
    });
  },

  "delete-service": async (btn) => {
    if (!confirm(`確定刪除歌單「${btn.dataset.name}」？\n（詩歌庫的歌和匯出過的 PPT 檔都會留著）`)) return;
    try {
      await api(`/api/services/${btn.dataset.id}`, { method: "DELETE" });
      btn.closest("tr, .item")?.remove();
      toast("已刪除");
    } catch (e) { showError(e); }
  },

  "reimport": async (btn) => {
    btn.disabled = true;
    try {
      const svc = await api(`/api/services/${btn.dataset.id}/gdoc`, { method: "POST", body: {} });
      toast(`已從 Google 文件更新：${svc.items.length} 首歌`);
      setTimeout(() => location.reload(), 700);
    } catch (e) { showError(e, "讀文件失敗"); btn.disabled = false; }
  },

  "legacy-import": async (btn) => {
    btn.disabled = true;
    btn.textContent = "匯入中…";
    try {
      const r = await api("/api/legacy/import", { method: "POST", body: {} });
      toast(`匯入 ${r.songs.length} 首歌`, "ok", r.missingImages.length ? "找不到的背景圖：" + r.missingImages.join("、") : "");
      setTimeout(() => { location.href = `/services/${r.serviceId}`; }, 900);
    } catch (e) { showError(e, "匯入失敗"); btn.disabled = false; btn.textContent = "匯入桌面版存檔"; }
  },

  "export-detail": async (btn) => {
    try {
      const rec = await api(`/api/exports/${btn.dataset.id}`);
      const songs = rec.snapshot.songs || [];
      const body = el("div", { class: "stack" },
        el("p", { class: "muted", text: `${fmtDate(rec.serviceDate)} ${rec.serviceName} · ${rec.slides} 張 · ${rec.createdAt}` }),
        ...songs.map((s, i) => el("details", { class: "faq" },
          el("summary", {}, `${i + 1}. ${s.title || "（沒有歌名）"}`,
            el("span", { class: "muted small", text: `　背景：${s.theme.name} · 排版：${s.style.name} · ${s.slides.length} 張` })),
          el("div", { class: "stack" },
            el("span", { class: "small muted", text: "歌序：" + (s.sequence || "照歌詞順序") }),
            el("pre", { class: "lyr", text: s.lyrics || "" })))),
        rec.warnings.length ? el("div", { class: "warnlist" }, ...rec.warnings.map((w) => el("span", { class: "w", text: w }))) : null);
      modal({ title: "這份 PPT 的內容", body, wide: true,
        buttons: [{ text: "關閉" }, { text: "下載 PPT", class: "btn-primary", onclick: () => { location.href = `/exports/${rec.id}/download`; } }] });
    } catch (e) { showError(e); }
  },

  "new-song": () => {
    const title = el("input", { type: "text", placeholder: "歌名", maxlength: 80, required: true });
    modal({
      title: "新增一首歌到詩歌庫",
      body: el("label", { class: "field" }, el("span", { class: "lbl", text: "歌名" }), title),
      buttons: [{ text: "取消" }, {
        text: "建立", class: "btn-primary", onclick: async (close) => {
          try {
            const song = await api("/api/songs", { method: "POST", body: { title: title.value } });
            close();
            location.href = `/songs/${song.id}`;
          } catch (e) { showError(e); }
        },
      }],
    });
    title.focus();
  },
};

$$("[data-action]").forEach((btn) => {
  const fn = actions[btn.dataset.action];
  if (fn) btn.addEventListener("click", () => fn(btn));
});

// 日期顯示成「10/11（日）」
$$("[data-date-label]").forEach((node) => { node.textContent = fmtDate(node.dataset.dateLabel); });
