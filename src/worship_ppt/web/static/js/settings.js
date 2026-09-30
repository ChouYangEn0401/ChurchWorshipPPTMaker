// 設定頁：儲存預設值；本機另外有對外連結、密碼、備份、匯入桌面版。

import { $, api, pageData, showError, toast } from "./common.js";

const { isLocal } = pageData();

// ---------- 一般設定 ----------
$("#btnSave").addEventListener("click", async () => {
  const state = $("#saveState");
  const body = {
    gdoc_url: $("#sGdoc").value.trim(),
    slide_size: $("#sSize").value,
    service_name: $("#sName").value,
    default_theme_id: $("#sTheme").value || null,
    default_style_id: $("#sStyle").value || null,
  };
  if (isLocal && $("#sCloudflared")) body.cloudflared_path = $("#sCloudflared").value.trim();
  state.className = "save-state saving";
  state.textContent = "儲存中…";
  try {
    await api("/api/settings", { method: "PATCH", body });
    state.className = "save-state ok";
    state.textContent = "已儲存 ✓";
  } catch (e) {
    showError(e);
    state.className = "save-state bad";
    state.textContent = "沒存到";
  }
});

if (isLocal) {
  // ---------- 對外連結 ----------
  let timer = null;
  const LABEL = { stopped: "關著", starting: "開啟中…", running: "開著", error: "出問題了" };
  const TONE = { stopped: "", starting: "accent", running: "ok", error: "bad" };

  const paint = (st) => {
    const badge = $("#tunnelState");
    badge.textContent = LABEL[st.state] || st.state;
    badge.className = "badge " + (TONE[st.state] || "");
    const running = st.state === "running";
    $("#tunnelUrlBox").hidden = !running;
    $("#qr").hidden = !running;
    $("#btnCopyUrl").hidden = !running;
    $("#btnTunnelStop").hidden = !(running || st.state === "starting");
    $("#btnTunnelStart").hidden = running || st.state === "starting";
    $("#tunnelInstall").hidden = st.installed;
    $("#btnTunnelStart").disabled = !st.installed;
    const err = $("#tunnelError");
    err.hidden = !st.error;
    err.textContent = st.error ? "⚠ " + st.error : "";
    if (running) {
      if ($("#tunnelUrl").textContent !== st.url) {
        $("#tunnelUrl").textContent = st.url;
        $("#qrImg").src = "/api/tunnel/qr.svg?t=" + Date.now();
      }
    }
    clearTimeout(timer);
    if (st.state === "starting") timer = setTimeout(refresh, 1200);
  };
  const refresh = async () => {
    try { paint(await api("/api/tunnel")); } catch (_) { /* 伺服器關了 */ }
  };

  $("#btnTunnelStart").addEventListener("click", async () => {
    try { paint(await api("/api/tunnel/start", { method: "POST" })); } catch (e) { showError(e, "開不起來"); }
  });
  $("#btnTunnelStop").addEventListener("click", async () => {
    if (!confirm("關閉對外連結？外面的人會馬上被登出，網址也會失效。")) return;
    try { paint(await api("/api/tunnel/stop", { method: "POST" })); } catch (e) { showError(e); }
  });
  $("#btnCopyUrl").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("#tunnelUrl").textContent);
      toast("網址已複製，可以貼到 LINE 群組");
    } catch (_) { toast("請手動選取網址複製", "warn"); }
  });
  refresh();
  setInterval(refresh, 15000);

  // ---------- 密碼 ----------
  $("#btnPassword").addEventListener("click", async () => {
    const password = $("#newPassword").value;
    try {
      await api("/api/settings/password", { method: "POST", body: { password } });
      toast("團隊密碼已設定，之前登入的人要重新登入");
      setTimeout(() => location.reload(), 900);
    } catch (e) { showError(e); }
  });
  $("#btnKick")?.addEventListener("click", async () => {
    if (!confirm("把所有從外面登入的人登出？")) return;
    try {
      const r = await api("/api/sessions/clear", { method: "POST" });
      toast(`登出了 ${r.removed} 個人`);
      setTimeout(() => location.reload(), 700);
    } catch (e) { showError(e); }
  });

  // ---------- 備份、匯入 ----------
  $("#btnBackup").addEventListener("click", async () => {
    const btn = $("#btnBackup");
    btn.disabled = true;
    try {
      const r = await api("/api/backup", { method: "POST" });
      toast("備份好了", "ok", r.file, 9000);
    } catch (e) { showError(e, "備份失敗"); }
    btn.disabled = false;
  });
  $("#btnLegacy").addEventListener("click", async () => {
    try {
      const r = await api("/api/legacy/import", { method: "POST", body: { path: $("#legacyPath").value.trim() } });
      toast(`匯入 ${r.songs.length} 首歌`, "ok", r.missingImages.length ? "找不到的背景圖：" + r.missingImages.join("、") : "");
      setTimeout(() => { location.href = `/services/${r.serviceId}`; }, 900);
    } catch (e) { showError(e, "匯入失敗"); }
  });
}
