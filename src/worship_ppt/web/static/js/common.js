// 各頁共用的小工具。不依賴外部套件；使用者的資料一律用 textContent 放進畫面（不會被當成 HTML 執行）。

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** el("button", { class: "btn", text: "存檔", onclick: fn, title: "…" }, child1, child2) */
export function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected" || key === "hidden") node[key] = !!value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.appendChild(typeof kid === "string" || typeof kid === "number" ? document.createTextNode(String(kid)) : kid);
  }
  return node;
}

export function pageData() {
  const node = document.getElementById("page-data");
  return node ? JSON.parse(node.textContent) : {};
}

export const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

export class ApiError extends Error {
  constructor(status, body) {
    super((body && body.message) || `HTTP ${status}`);
    this.status = status;
    this.hint = (body && body.hint) || "";
    this.body = body || {};
  }
}

/** 呼叫後端 JSON API。body 是物件就送 JSON；form 是 FormData 就直接送。 */
export async function api(path, { method = "GET", body, form } = {}) {
  const headers = { Accept: "application/json" };
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  } catch (_) {
    throw new ApiError(0, { message: "連不到伺服器", hint: "網路斷了，或主機電腦的程式被關掉了。" });
  }
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    if (res.status === 401) {
      toast("登入已經過期，請重新登入", "bad");
      setTimeout(() => location.reload(), 1500);
    }
    throw new ApiError(res.status, data);
  }
  return data;
}

export function showError(err, prefix = "") {
  const msg = (prefix ? prefix + "：" : "") + (err && err.message ? err.message : String(err));
  toast(msg, "bad", err && err.hint);
}

let toastBox = null;
export function toast(message, level = "ok", sub = "", ms = 4200) {
  if (!toastBox) {
    toastBox = el("div", { class: "toast-box", role: "status", "aria-live": "polite" });
    document.body.appendChild(toastBox);
  }
  const node = el("div", { class: "toast " + level }, message, sub ? el("span", { class: "sub", text: sub }) : null);
  toastBox.appendChild(node);
  setTimeout(() => node.remove(), level === "bad" ? Math.max(ms, 7000) : ms);
  return node;
}

export function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

/** 對話框。回傳 { root, body, close }。buttons: [{ text, class, onclick(close) }] */
export function modal({ title, body, buttons = [], wide = false, onClose } = {}) {
  const bodyBox = el("div", { class: "modal-body" });
  if (body) bodyBox.appendChild(body);
  const closeBtn = el("button", { type: "button", class: "icon-btn", "aria-label": "關閉", text: "✕" });
  const foot = buttons.length ? el("div", { class: "modal-foot" }) : null;
  const box = el("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" },
    el("div", { class: "modal-head" }, el("h3", { text: title || "" }), closeBtn), bodyBox, foot);
  const back = el("div", { class: "modal-back" }, box);
  const close = () => {
    back.remove();
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => { if (e.key === "Escape" && !e.isComposing) close(); };
  for (const b of buttons) {
    foot.appendChild(el("button", { type: "button", class: "btn " + (b.class || ""), text: b.text,
      onclick: () => b.onclick ? b.onclick(close) : close() }));
  }
  closeBtn.addEventListener("click", close);
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
  return { root: back, body: bodyBox, close };
}

export function pickFile(accept = "image/*", multiple = false) {
  return new Promise((resolve) => {
    const input = el("input", { type: "file", accept, multiple });
    input.addEventListener("change", () => resolve(multiple ? Array.from(input.files) : (input.files[0] || null)));
    input.click();
  });
}

const WEEKDAYS = "日一二三四五六";
export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  if (isNaN(d)) return iso;
  return `${d.getMonth() + 1}/${d.getDate()}（${WEEKDAYS[d.getDay()]}）`;
}

export function fmtBytes(n) {
  if (!n) return "0";
  if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

/** 上傳圖片（可以一次多張），回傳建立好的背景清單。createTheme=false 時只存圖、回傳 {image}。 */
export async function uploadImages(files, onProgress, createTheme = true) {
  const out = [];
  for (const [i, file] of files.entries()) {
    if (onProgress) onProgress(i, files.length, file);
    const form = new FormData();
    form.append("file", file);
    out.push(await api("/api/images" + (createTheme ? "" : "?theme=0"), { method: "POST", form }));
  }
  return out;
}

/** 把拖進來的檔案接住：dropzone 元素 + 收到檔案後要做的事 */
export function wireDropzone(zone, onFiles) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("hover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("hover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("hover");
    const files = Array.from(e.dataTransfer.files || []).filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|bmp|gif)$/i.test(f.name));
    if (files.length) onFiles(files);
  });
}

export function download(url) {
  const a = el("a", { href: url, download: "" });
  document.body.appendChild(a);
  a.click();
  a.remove();
}
