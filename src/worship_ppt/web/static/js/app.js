// 每一頁都有的小功能：深淺色、手機選單、側欄狀況、確認對話框、點一下複製、表格搜尋。

import { $, $$, api } from "./common.js";

const store = {
  get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* 私密視窗就算了 */ } },
};

// ---------- 深色 / 淺色 ----------
$("#btn-theme")?.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("wppt.theme", next);
});

// ---------- 手機：☰ 打開／關閉側欄 ----------
$(".menu-toggle")?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
$("#view")?.addEventListener("click", () => document.body.classList.remove("nav-open"));

// ---------- 上方訊息列的 ✕ ----------
$$("[data-dismiss-banner]").forEach((b) => b.addEventListener("click", () => b.closest(".banner").remove()));

// ---------- 送出表單前確認；送出後鎖住按鈕 ----------
document.addEventListener("submit", (e) => {
  const msg = e.target.dataset && e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
  e.target.querySelectorAll("button[type=submit]").forEach((b) => { b.disabled = true; });
});

// ---------- 點一下複製 ----------
$$(".copy").forEach((node) => {
  node.title = "點一下複製";
  node.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(node.dataset.copy || node.textContent.trim());
      node.classList.add("copied");
      setTimeout(() => node.classList.remove("copied"), 1200);
    } catch (_) { /* 瀏覽器不允許就手動選取 */ }
  });
});

// ---------- 表格搜尋：<input data-filter="#table-id"> ----------
$$("[data-filter]").forEach((input) => {
  const table = $(input.dataset.filter);
  if (!table) return;
  const run = () => {
    const needle = input.value.trim().toLowerCase();
    table.querySelectorAll("tbody tr").forEach((row) => {
      row.hidden = needle !== "" && !(row.dataset.search || row.textContent).toLowerCase().includes(needle);
    });
  };
  input.addEventListener("input", run);
  run();
});

// ---------- 整列可以點 ----------
$$("tr[data-href]").forEach((row) => {
  row.addEventListener("click", (e) => {
    if (e.target.closest("a, button, input, select, form")) return;
    location.href = row.dataset.href;
  });
});

// ---------- 側欄每一項「現在的狀況」 ----------
(() => {
  const items = $$("[data-nav]");
  if (!items.length) return;
  const paint = (status) => {
    for (const item of items) {
      const info = status && status[item.dataset.nav];
      if (!info) continue;
      const sub = item.querySelector("[data-sub]");
      const count = item.querySelector("[data-count]");
      if (sub && info.sub) {
        sub.textContent = info.sub;
        sub.className = "sub " + (info.tone === "bad" || info.tone === "warn" ? info.tone : "");
      }
      if (count && info.count !== undefined) {
        count.textContent = info.count ? String(info.count) : "";
        count.className = "count " + (info.tone || "");
      }
    }
  };
  try { paint(JSON.parse(sessionStorage.getItem("wppt.nav") || "null")); } catch (_) { /* 壞掉就不用 */ }
  api("/api/nav").then((status) => {
    paint(status);
    try { sessionStorage.setItem("wppt.nav", JSON.stringify(status)); } catch (_) { /* 同上 */ }
  }).catch(() => { /* 問不到就留原本的說明 */ });
})();
