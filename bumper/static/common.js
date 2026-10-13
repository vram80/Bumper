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

// Search terms worth highlighting: words and phrases that are not excluded,
// not operators and not field filters.
function queryTerms(q) {
  const terms = [];
  (q || "").replace(/"([^"]+)"(~\d+)?|(\S+)/g, (_, phrase, near, word) => {
    if (phrase) { if (near) terms.push(...phrase.split(/\s+/)); else terms.push(phrase); return; }
    if (/^[-!]/.test(word) || /^(AND|OR|NOT|&&|\|\|)$/.test(word) || /^\w+:/.test(word)) return;
    word = word.replace(/^[+(]+|[)]+$/g, "").replace(/~\d*$/, "");
    if (word.length > 1) terms.push(word);
  });
  return terms;
}

function highlight(text, terms) {
  let html = esc(text);
  if (!terms.length) return html;
  const parts = terms.map(t => esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\*$/, "\\w*").replace(/\s+/g, "\\s+"));
  return html.replace(new RegExp(`\\b(${parts.join("|")})`, "gi"), "<mark>$1</mark>");
}

const DOC_VIEW_KEY = "bumper.docview";
function savedView() { try { return localStorage.getItem(DOC_VIEW_KEY) || "split"; } catch { return "split"; } }
function saveView(v) { try { localStorage.setItem(DOC_VIEW_KEY, v); } catch { /* storage unavailable */ } }

// Render a document into `container`: text and PDF side by side, with
// text-only, PDF-only and details views. `doc` is an indexed document id
// (string) or {app, doc_id, title, code} for a file-history document.
async function showDocument(container, doc, opts = {}) {
  const indexed = typeof doc === "string";
  let meta = {};
  if (indexed) {
    const res = await fetch(`/api/doc?id=${encodeURIComponent(doc)}`);
    if (!res.ok) { container.innerHTML = `<div class="dnote">Document not found.</div>`; return; }
    meta = await res.json();
  } else {
    meta = { doc_id: doc.doc_id, app_no: doc.app, doc_desc: doc.title, doc_code: doc.code, mail_date: doc.date };
  }
  const id = encodeURIComponent(meta.doc_id), app = encodeURIComponent(meta.app_no || "");
  const pdfUrl = indexed ? `/api/doc/pdf?id=${id}` : `/api/file/pdf?app=${app}&doc=${id}`;
  const docxUrl = indexed ? `/api/doc/docx?id=${id}` : `/api/file/docx?app=${app}&doc=${id}&title=${encodeURIComponent(meta.doc_desc || "")}`;
  const hasDrawings = ["SPEC", "CLM", "ABST"].includes(meta.doc_code);
  const terms = queryTerms(opts.query);
  let view = savedView();
  container.innerHTML = `<div class="docpanel">
    <div class="dhead">${opts.closable ? `<button class="btn dclose" data-close>Close</button>` : ""}
      <h3>${esc(meta.doc_desc || meta.doc_code || "Document")}</h3>
      <div class="meta">${esc(meta.app_no ?? "")}${meta.mail_date ? ` · ${esc(meta.mail_date)}` : ""}${meta.doc_code ? ` · ${esc(meta.doc_code)}` : ""}${meta.examiner ? ` · ${esc(meta.examiner)}` : ""}${meta.art_unit ? ` · AU ${esc(meta.art_unit)}` : ""}</div>
      <div class="dtools">
        <span class="seg">${[["split", "Side by side"], ["text", "Text"], ["pdf", "PDF"], ["details", "Details"]].map(([v, l]) => `<button data-view="${v}">${l}</button>`).join("")}</span>
        ${hasDrawings ? `<button class="btn" data-drawings>Drawings</button>` : ""}
        <a class="btn" href="${docxUrl}">Word</a>
        <a class="btn" href="${pdfUrl}" target="_blank" rel="noopener">Open PDF</a>
        ${meta.app_no ? `<a class="btn" href="/lookup?type=app&q=${app}">File history</a>` : ""}
      </div></div>
    <div class="dbody"><div class="dtext"><div class="dnote">Loading text…</div></div><div class="dpdf"><div class="dnote">Loading PDF…</div></div>
      <div class="dmeta"></div></div></div>`;
  const body = container.querySelector(".dbody");
  const setView = v => {
    view = v; saveView(v); body.className = `dbody ${v === "split" ? "" : v}`;
    container.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  };
  container.querySelectorAll("[data-view]").forEach(b => b.addEventListener("click", () => setView(b.dataset.view)));
  setView(view);
  const close = container.querySelector("[data-close]");
  if (close) close.addEventListener("click", () => opts.onClose && opts.onClose());

  const rows = [["Application", meta.app_no], ["Document code", meta.doc_code], ["Description", meta.doc_desc],
    ["Direction", meta.direction], ["Date", meta.mail_date], ["Examiner", meta.examiner], ["Art unit", meta.art_unit],
    ["Customer number", meta.customer_number], ["Correspondent", meta.correspondent], ["Signed by", meta.filer],
    ["Registration no.", meta.filer_reg], ["Previous outgoing action", meta.prev_out], ["Next outgoing action", meta.next_out],
    ["Previous incoming filing", meta.prev_in], ["Next incoming filing", meta.next_in], ["Pages", meta.pages], ["Collection", meta.kb]];
  body.querySelector(".dmeta").innerHTML = `<dl class="kv">${rows.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;

  // PDF: fetch first so a missing file shows a message instead of an error page.
  const loadPdf = async (url, label) => {
    const pane = body.querySelector(".dpdf");
    pane.innerHTML = `<div class="dnote">Loading ${label}…</div>`;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
      const blob = URL.createObjectURL(await res.blob());
      pane.innerHTML = `<iframe title="${esc(label)}" src="${blob}"></iframe>`;
    } catch (e) {
      pane.innerHTML = `<div class="dnote">No ${esc(label)} available: ${esc(e.message)}</div>`;
    }
  };
  loadPdf(pdfUrl, "PDF");
  const drawingsBtn = container.querySelector("[data-drawings]");
  if (drawingsBtn) drawingsBtn.addEventListener("click", () => {
    if (view === "text" || view === "details") setView("split");
    loadPdf(`/api/file/drawings?app=${app}`, "drawings");
  });

  let text = meta.text;
  if (text == null || text === "") {
    const res = await fetch(`/api/file/text?app=${app}&doc=${id}`);
    text = res.ok ? (await res.json()).text : "";
  }
  body.querySelector(".dtext").innerHTML = text
    ? `<pre>${highlight(text, terms)}</pre>`
    : `<div class="dnote">The USPTO has no text version of this document (it is a scan). Read it in the PDF.</div>`;
  const first = body.querySelector(".dtext mark");
  if (first) first.scrollIntoView({ block: "center" });
}

// Slide-in document drawer used outside the search workspace.
function openViewer(doc, opts = {}) {
  const root = document.getElementById("viewer");
  root.innerHTML = `<div class="drawer"></div>`;
  const close = () => { root.innerHTML = ""; };
  showDocument(root.firstElementChild, doc, { ...opts, closable: true, onClose: close });
}
document.addEventListener("keydown", e => { if (e.key === "Escape") { const v = document.getElementById("viewer"); if (v) v.innerHTML = ""; } });
