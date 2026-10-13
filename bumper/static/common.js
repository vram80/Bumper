"use strict";
const fmt = {
  pct: v => v == null ? "–" : Math.round(v * 100) + "%",
  num: (v, d = 1) => v == null ? "–" : Number(v).toFixed(d),
  int: v => v == null ? "–" : String(v),
};
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// Colour a percentile: 'hard' metrics shade red at the top, green at the bottom.
function rankColor(p, hardWhenHigh) {
  if (p == null) return "#9aa3b2";
  const t = hardWhenHigh ? p : 1 - p;
  const r = Math.round(31 + (214 - 31) * t), g = Math.round(157 + (69 - 157) * t), b = Math.round(85 + (69 - 85) * t);
  return `rgb(${r},${g},${b})`;
}
function autocomplete(input, endpoint, onPick) {
  const list = document.createElement("ul");
  list.className = "suggest"; list.hidden = true;
  input.parentNode.appendChild(list);
  let items = [], active = -1, timer;
  const render = () => {
    list.innerHTML = items.map((s, i) => `<li class="${i === active ? "active" : ""}" data-i="${i}">${esc(s)}</li>`).join("");
    list.hidden = !items.length;
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const term = input.value.trim();
      if (!term) { items = []; return render(); }
      const res = await fetch(`${endpoint}?term=${encodeURIComponent(term)}`);
      items = res.ok ? await res.json() : []; active = -1; render();
    }, 150);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter") { const v = items[active] ?? input.value.trim(); if (v) onPick(v); }
    else if (e.key === "Escape") { items = []; render(); }
  });
  list.addEventListener("mousedown", e => { const li = e.target.closest("li"); if (li) onPick(items[+li.dataset.i]); });
  input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 100));
}
const charts = {};
function drawChart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

// Document viewer overlay with text, details, PDF and Word tabs.
// `doc` is either an indexed document id (string) or {app, doc_id, title} for an unindexed file.
async function openViewer(doc) {
  const root = document.getElementById("viewer");
  const indexed = typeof doc === "string";
  let meta = null;
  if (indexed) {
    const res = await fetch(`/api/doc?id=${encodeURIComponent(doc)}`);
    if (!res.ok) return alert("Document not found");
    meta = await res.json();
  }
  const id = indexed ? meta.doc_id : doc.doc_id;
  const pdfUrl = indexed ? `/api/doc/pdf?id=${encodeURIComponent(id)}`
                         : `/api/file/pdf?app=${encodeURIComponent(doc.app)}&doc=${encodeURIComponent(id)}`;
  const title = indexed ? `${meta.doc_desc || meta.doc_code} · ${meta.app_no ?? ""} · ${meta.mail_date ?? ""}` : doc.title;
  const tabs = indexed ? ["Text", "Details", "PDF"] : ["PDF"];
  root.innerHTML = `<div class="viewer"><div class="box">
    <div class="head"><span class="grow">${esc(title)}</span>
      <span class="tabs" style="margin:0">${tabs.map((t, i) => `<button data-tab="${t}" class="${i ? "" : "on"}">${t}</button>`).join("")}</span>
      ${indexed ? `<a class="btn" href="/api/doc/docx?id=${encodeURIComponent(id)}">Word</a>` : ""}
      <a class="btn" href="${pdfUrl}" target="_blank" rel="noopener">Open PDF</a>
      <button class="btn" data-close>Close</button></div>
    <div class="body" id="viewerBody"></div></div></div>`;
  const body = root.querySelector("#viewerBody");
  const show = tab => {
    root.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
    if (tab === "Text") body.innerHTML = `<pre>${esc(meta.text || "No text was extracted for this document.")}</pre>`;
    else if (tab === "Details") {
      const rows = [["Application", meta.app_no], ["Document code", meta.doc_code], ["Description", meta.doc_desc],
        ["Direction", meta.direction], ["Date", meta.mail_date], ["Examiner", meta.examiner], ["Art unit", meta.art_unit],
        ["Customer number", meta.customer_number], ["Correspondent", meta.correspondent], ["Signed by", meta.filer],
        ["Registration no.", meta.filer_reg], ["Previous outgoing action", meta.prev_out], ["Next outgoing action", meta.next_out],
        ["Previous incoming filing", meta.prev_in], ["Next incoming filing", meta.next_in], ["Pages", meta.pages], ["Collection", meta.kb]];
      body.innerHTML = `<dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v ?? "–")}</dd>`).join("")}</dl>`;
    } else body.innerHTML = `<iframe src="${pdfUrl}" title="PDF"></iframe>`;
  };
  root.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => show(b.dataset.tab)));
  root.querySelector("[data-close]").addEventListener("click", () => { root.innerHTML = ""; });
  root.querySelector(".viewer").addEventListener("click", e => { if (e.target.classList.contains("viewer")) root.innerHTML = ""; });
  show(tabs[0]);
}
document.addEventListener("keydown", e => { if (e.key === "Escape") { const v = document.getElementById("viewer"); if (v) v.innerHTML = ""; } });
