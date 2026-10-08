// 背景庫：上傳、改名、暗色遮罩、純色背景、收起／刪除。

import { $, api, debounce, el, fmtDate, modal, pageData, showError, toast, uploadImages, wireDropzone } from "./common.js";
import { paintBackground, renderSlide } from "./slide.js";

const data = pageData();
let themes = data.themes;
const styles = data.styles;
const settings = data.settings || {};
const sampleStyle = styles.find((s) => s.id === settings.default_style_id) || styles[0];

function usage(t) {
  if (!t.serviceCount && !t.songCount) return "還沒用過";
  const parts = [];
  if (t.serviceCount) parts.push(`用過 ${t.serviceCount} 次`);
  if (t.lastUsed) parts.push(`上次 ${fmtDate(t.lastUsed)}`);
  if (t.songCount) parts.push(`${t.songCount} 首歌的預設`);
  return parts.join(" · ");
}

function render() {
  const grid = $("#grid");
  const showArchived = $("#showArchived").checked;
  const q = $("#q").value.trim().toLowerCase();
  grid.replaceChildren();
  for (const t of themes) {
    if (t.archived && !showArchived) continue;
    if (q && !t.name.toLowerCase().includes(q)) continue;
    const pic = el("div", { class: "pic" });
    paintBackground(pic, t, 320);
    const card = el("div", { class: "bcard" + (t.archived ? " off" : "") }, pic,
      el("div", { class: "meta2" }, el("b", { text: t.name }), el("span", { text: usage(t) }),
        el("span", { text: [t.image ? `${t.image.width}×${t.image.height}` : `純色 ${t.bgColor}`,
          t.overlay > 0 ? `遮罩 ${Math.round(t.overlay * 100)}%` : ""].filter(Boolean).join(" · ") })),
      el("div", { class: "acts" },
        el("button", { type: "button", class: "btn btn-sm", text: "調整", onclick: () => edit(t) }),
        t.archived
          ? el("button", { type: "button", class: "btn btn-sm", text: "拿出來", onclick: () => patch(t, { archived: false }) })
          : el("button", { type: "button", class: "btn btn-sm btn-danger", text: "刪除", onclick: () => remove(t) })));
    grid.appendChild(card);
  }
  if (!grid.children.length) grid.appendChild(el("div", { class: "empty" }, el("b", { text: "沒有符合的背景" })));
}

async function patch(t, body) {
  try {
    Object.assign(t, await api(`/api/themes/${t.id}`, { method: "PATCH", body }));
    render();
  } catch (e) { showError(e); }
}

async function remove(t) {
  if (!confirm(`刪除背景「${t.name}」？\n用過的背景只會收起來（以前的歌單還看得到），沒用過的會真的刪掉。`)) return;
  try {
    const r = await api(`/api/themes/${t.id}`, { method: "DELETE" });
    if (r.result === "deleted") themes = themes.filter((x) => x.id !== t.id);
    else t.archived = true;
    toast(r.result === "deleted" ? "已刪除" : "用過了，先收起來（勾「顯示收起來的背景」可以拿回來）");
    render();
  } catch (e) { showError(e); }
}

function edit(t) {
  const draft = { ...t };
  const name = el("input", { type: "text", value: t.name, maxlength: 60 });
  const color = el("input", { type: "color", value: t.bgColor });
  const overlay = el("input", { type: "range", min: "0", max: "0.8", step: "0.05", value: String(t.overlay || 0) });
  const overlayVal = el("span", { class: "small muted", text: Math.round((t.overlay || 0) * 100) + "%" });
  const preview = el("div");
  const refresh = () => {
    const { el: slide } = renderSlide({ kind: "lyrics", label: "副", text: "主耶穌 我敬拜祢\n祢配得一切頌讚" },
      { title: "詩歌", theme: draft, style: sampleStyle, size: settings.slide_size || "4:3", thumb: 960 });
    preview.replaceChildren(slide);
  };
  name.addEventListener("input", () => { draft.name = name.value; });
  color.addEventListener("input", () => { draft.bgColor = color.value; refresh(); });
  overlay.addEventListener("input", () => {
    draft.overlay = Number(overlay.value);
    overlayVal.textContent = Math.round(draft.overlay * 100) + "%";
    refresh();
  });
  const replace = el("button", { type: "button", class: "btn btn-sm", text: t.image ? "換一張圖" : "加上圖片" });
  replace.addEventListener("click", () => {
    const input = el("input", { type: "file", accept: "image/*" });
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      try {
        const [created] = await uploadImages([input.files[0]], null, false);
        draft.image = created.image;
        draft.imageId = created.image.id;
        refresh();
        toast("換好了，按「儲存」才會生效");
      } catch (e) { showError(e, "上傳失敗"); }
    });
    input.click();
  });
  const removeImg = el("button", { type: "button", class: "btn btn-sm btn-ghost", text: "拿掉圖片，只用底色", hidden: !t.image });
  removeImg.addEventListener("click", () => { draft.image = null; draft.imageId = null; refresh(); });
  refresh();
  modal({
    title: "調整背景", wide: true,
    body: el("div", { class: "style-editor" },
      el("div", { class: "stack" },
        el("label", { class: "field" }, el("span", { class: "lbl", text: "名稱" }), name),
        el("div", { class: "row" }, el("span", { class: "lbl", text: "圖片" }), replace, removeImg),
        el("div", { class: "row" }, el("span", { class: "lbl", text: "底色" }), color,
          el("span", { class: "hint-line", text: "沒有圖片時用這個顏色；有圖片時通常看不到。" })),
        el("div", { class: "row" }, el("span", { class: "lbl", text: "暗色遮罩" }), overlay, overlayVal),
        el("p", { class: "hint-line", text: "改這裡，所有用這個背景的歌都會一起變（包括以前的歌單重新匯出時）。" })),
      preview),
    buttons: [{ text: "取消" }, {
      text: "儲存", class: "btn-primary", onclick: async (close) => {
        const body = { name: draft.name, bgColor: draft.bgColor, overlay: draft.overlay };
        if ("imageId" in draft) body.imageId = draft.imageId;
        await patch(t, body);
        close();
        toast("已儲存");
      },
    }],
  });
}

async function onFiles(files) {
  const zone = $("#drop");
  const label = zone.querySelector("b");
  try {
    const created = await uploadImages(files, (i, n) => { label.textContent = `上傳中… ${i + 1}/${n}`; });
    for (const t of created) {
      const at = themes.findIndex((x) => x.id === t.id);
      if (at >= 0) themes[at] = t; else themes.unshift(t);
    }
    toast(`上傳了 ${created.length} 張背景`);
    render();
  } catch (e) { showError(e, "上傳失敗"); }
  label.textContent = "＋ 上傳背景圖";
}

const drop = $("#drop");
wireDropzone(drop, onFiles);
drop.addEventListener("click", () => {
  const input = el("input", { type: "file", accept: "image/*", multiple: true });
  input.addEventListener("change", () => { if (input.files.length) onFiles(Array.from(input.files)); });
  input.click();
});

$("#btnColor").addEventListener("click", () => {
  const name = el("input", { type: "text", placeholder: "例：深藍底", maxlength: 60 });
  const color = el("input", { type: "color", value: "#0B1D3A" });
  modal({
    title: "新增純色背景",
    body: el("div", { class: "stack" },
      el("label", { class: "field" }, el("span", { class: "lbl", text: "名稱" }), name),
      el("div", { class: "row" }, el("span", { class: "lbl", text: "顏色" }), color)),
    buttons: [{ text: "取消" }, {
      text: "新增", class: "btn-primary", onclick: async (close) => {
        try {
          const t = await api("/api/themes", { method: "POST", body: { name: name.value || "純色背景", bgColor: color.value } });
          themes.unshift(t);
          render();
          close();
        } catch (e) { showError(e); }
      },
    }],
  });
});

$("#showArchived").addEventListener("change", render);
$("#q").addEventListener("input", debounce(render, 150));
render();
