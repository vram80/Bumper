"use strict";
const $ = id => document.getElementById(id);
const out = $("out");
const kind = () => document.querySelector("input[name=type]:checked").value;
const PLACEHOLDER = { pat: "Patent number, e.g. 10,000,000", pub: "Publication number, e.g. US 2020/0123456 A1", app: "Application number, e.g. 16/123,456" };
document.querySelectorAll("input[name=type]").forEach(r => r.addEventListener("change", () => { $("q").placeholder = PLACEHOLDER[kind()]; }));

function kv(rows) { return `<dl class="kv">${rows.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`; }
function famId(d) { return d ? `${esc(d.country ?? "")}${esc(d["doc-number"] ?? "")} ${esc(d.kind ?? "")}` : "–"; }

async function load(type, number) {
  document.querySelector(`input[name=type][value=${type}]`).checked = true;
  $("q").value = number;
  history.replaceState(null, "", `/lookup?type=${type}&q=${encodeURIComponent(number)}`);
  out.innerHTML = `<div class="empty">Loading…</div>`;
  const res = await fetch(`/api/lookup?type=${type}&q=${encodeURIComponent(number)}`);
  const d = await res.json();
  if (!res.ok) { out.innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
  const b = d.biblio, L = d.links;
  const fmtBool = v => v == null ? null : (v ? "Yes" : "No");
  out.innerHTML = `
    ${d.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("")}
    <h1>${esc(b.title ?? "Untitled")}</h1>
    <div class="sub">Application ${esc(b.application_number)}${b.patent_number ? ` · Patent ${esc(b.patent_number)}` : ""}
      ${b.earliest_publication_number ? ` · Publication ${esc(b.earliest_publication_number)}` : ""}</div>
    <div class="toolbar">
      ${L.patent_pdf ? `<a class="btn primary" href="${L.patent_pdf}" target="_blank" rel="noopener">Patent PDF</a>
        <a class="btn" href="#" data-text="pat:${esc(b.patent_number)}">Patent text</a>` : ""}
      ${L.publication_pdf ? `<a class="btn ${L.patent_pdf ? "" : "primary"}" href="${L.publication_pdf}" target="_blank" rel="noopener">Publication PDF</a>` : ""}
      ${b.examiner ? `<a class="btn" href="/examiner?id=${encodeURIComponent(b.examiner)}">Examiner statistics</a>` : ""}
      <a class="btn" href="/search?q=${encodeURIComponent("app:" + b.application_number)}">Search this file</a>
    </div>
    <div class="grid">
      <div class="card"><h3>Bibliographic data</h3>${kv([
        ["Filing date", esc(b.filing_date)], ["Effective filing date", esc(b.effective_filing_date)],
        ["Application type", esc(b.application_type)], ["Status", esc(b.status)], ["Status date", esc(b.status_date)],
        ["Examiner", esc(b.examiner)], ["Art unit", esc(b.art_unit)], ["Customer number", esc(b.customer_number)],
        ["Attorney docket", esc(b.attorney_docket)], ["Correspondent", esc(b.correspondent)],
        ["US class", esc(b.class_subclass)], ["Entity status", esc(b.entity_status)], ["AIA (first inventor to file)", fmtBool(b.aia)],
        ["Publication", b.earliest_publication_number ? `${esc(b.earliest_publication_number)} (${esc(b.earliest_publication_date)})` : null],
        ["Patent", b.patent_number ? `${esc(b.patent_number)} (${esc(b.issue_date)})` : null],
        ["Applicants", (b.applicants ?? []).map(esc).join("<br>")],
        ["Inventors", (b.inventors ?? []).map(i => `${esc(i.name)}${i.location ? ` <span class="meta">${esc(i.location)}</span>` : ""}`).join("<br>")],
        ["Data as of", esc(b.last_updated)]])}</div>
      <div class="card"><h3>Assignments <small>${d.assignments.length}</small></h3>
        ${d.assignments.length ? `<table><tr><th>Recorded</th><th>Conveyance</th><th>Assignee</th><th>Reel/frame</th></tr>
          ${d.assignments.map(a => `<tr><td>${esc(a.recorded)}</td><td>${esc(a.conveyance)}</td><td>${a.assignees.map(esc).join("<br>")}</td>
            <td>${esc(a.reel_frame)}</td></tr>`).join("")}</table>` : `<div class="meta">None on record.</div>`}</div>
      <div class="card"><h3>Patent family <small>${d.family.length} members</small></h3>
        ${d.family.length ? `<table><tr><th>Publication</th><th>Date</th><th>Application</th></tr>
          ${d.family.map(f => `<tr><td>${famId(f.publication)}</td><td>${esc(f.publication?.date ?? "")}</td><td>${famId(f.application)}</td></tr>`).join("")}</table>`
          : `<div class="meta">No family data.</div>`}</div>
    </div>
    <div class="card apps"><h3>File history documents <small>${d.documents.length}</small></h3>
      <table><tr><th>Date</th><th>Code</th><th>Description</th><th></th><th class="num">Pages</th></tr>
      ${d.documents.map(doc => `<tr><td>${esc(doc.date)}</td><td>${esc(doc.code)}</td><td>${esc(doc.description)}</td>
        <td>${doc.direction === "INCOMING" ? "in" : doc.direction === "OUTGOING" ? "out" : ""}</td><td class="num">${esc(doc.pages ?? "")}</td>
        <td><a href="#" data-doc="${esc(doc.doc_id)}" data-indexed="${doc.indexed ? 1 : ""}" data-title="${esc(`${doc.description} (${doc.date})`)}">View</a></td></tr>`).join("")}
      </table></div>
    <div class="card apps"><h3>Transaction history <small>${b.transactions.length}</small></h3>
      <table><tr><th>Date</th><th>Code</th><th>Event</th></tr>
      ${b.transactions.map(t => `<tr><td>${esc(t.date)}</td><td>${esc(t.code)}</td><td>${esc(t.description)}</td></tr>`).join("")}</table></div>`;
  out.querySelectorAll("a[data-doc]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    openViewer(a.dataset.indexed ? a.dataset.doc : { app: b.application_number, doc_id: a.dataset.doc, title: a.dataset.title });
  }));
  out.querySelectorAll("a[data-text]").forEach(a => a.addEventListener("click", async e => {
    e.preventDefault();
    const [t, n] = a.dataset.text.split(":");
    const r = await (await fetch(`/api/patent/text?type=${t}&n=${encodeURIComponent(n)}`)).json();
    const text = r.error ?? r.note ?? [r.title, r.abstract && `ABSTRACT\n${r.abstract}`, r.claims && `CLAIMS\n${r.claims}`,
      r.description && `DESCRIPTION\n${r.description}`].filter(Boolean).join("\n\n");
    document.getElementById("viewer").innerHTML = `<div class="viewer"><div class="box"><div class="head"><span class="grow">Text of ${esc(n)}</span>
      <button class="btn" onclick="document.getElementById('viewer').innerHTML=''">Close</button></div>
      <div class="body"><pre>${esc(text)}</pre></div></div></div>`;
  }));
}

$("form").addEventListener("submit", e => { e.preventDefault(); if ($("q").value.trim()) load(kind(), $("q").value.trim()); });
const init = new URLSearchParams(location.search);
if (init.get("q")) load(init.get("type") || "pat", init.get("q"));
