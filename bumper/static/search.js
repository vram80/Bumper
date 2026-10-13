"use strict";
const $ = id => document.getElementById(id);
const FACET_LABELS = { kb: "Collection", doc_code: "Document type", art_unit: "Art unit", examiner: "Examiner",
  customer_number: "Customer number", next_out: "Next outgoing action", prev_out: "Previous outgoing action",
  next_in: "Next incoming filing", prev_in: "Previous incoming filing" };
// Search-API parameter name for each facet column.
const FACET_PARAM = { kb: "kb", doc_code: "code", art_unit: "artunit", examiner: "examiner", customer_number: "customer",
  next_out: "next_out", prev_out: "prev_out", next_in: "next_in", prev_in: "prev_in" };
let codeLabels = {}, groups = {}, selected = {}, page = 1;

function label(col, v) { return ["doc_code", "next_out", "prev_out", "next_in", "prev_in"].includes(col) ? `${codeLabels[v] ?? v} (${v})` : v; }

function params() {
  const p = new URLSearchParams();
  p.set("q", $("q").value); p.set("sort", $("sort").value); p.set("page", page);
  if ($("all").checked) p.set("mode", "all");
  if ($("kb").value) p.append("kb", $("kb").value);
  if ($("group").value) p.append("code", groups[$("group").value].join("|"));
  for (const [col, vals] of Object.entries(selected)) vals.forEach(v => p.append(FACET_PARAM[col], v));
  return p;
}

async function run(resetPage = true) {
  if (resetPage) page = 1;
  const p = params();
  history.replaceState(null, "", `/search?${p}`);
  const res = await fetch(`/api/search?${p}`);
  const data = await res.json();
  if (!res.ok) { $("summary").textContent = data.error; $("results").innerHTML = ""; return; }
  $("summary").textContent = `${data.total.toLocaleString()} document${data.total === 1 ? "" : "s"}`;
  $("results").innerHTML = data.results.map(r => `
    <div class="result"><h3><a data-id="${esc(r.doc_id)}">${esc(r.doc_desc || r.doc_code)}</a></h3>
      <div class="meta">${esc(r.app_no ?? "")} · ${esc(r.mail_date ?? "")} · ${esc(r.examiner ?? "")} · AU ${esc(r.art_unit ?? "–")}
        ${r.filer ? ` · signed by ${esc(r.filer)}` : ""}${r.next_out ? ` · next action: ${esc(codeLabels[r.next_out] ?? r.next_out)}` : ""}</div>
      <div class="snippet">${r.snippet}</div></div>`).join("") || `<div class="empty">No documents match.</div>`;
  $("results").querySelectorAll("a[data-id]").forEach(a => a.addEventListener("click", () => openViewer(a.dataset.id)));
  const pages = Math.ceil(data.total / data.per_page);
  $("pager").innerHTML = pages > 1 ? `${page > 1 ? `<button class="btn" data-p="${page - 1}">Previous</button>` : ""}
    <span class="meta">Page ${page} of ${pages}</span>${page < pages ? `<button class="btn" data-p="${page + 1}">Next</button>` : ""}` : "";
  $("pager").querySelectorAll("[data-p]").forEach(b => b.addEventListener("click", () => { page = +b.dataset.p; run(false); scrollTo(0, 0); }));
  $("facets").innerHTML = Object.entries(data.facets).filter(([, v]) => v.length).map(([col, vals]) => `
    <div><h4>${FACET_LABELS[col]}</h4>${vals.map(([v, n]) => `<label><span><input type="checkbox" data-col="${col}" value="${esc(v)}"
      ${(selected[col] ?? []).includes(v) ? "checked" : ""}> ${esc(label(col, v))}</span><span class="meta">${n}</span></label>`).join("")}</div>`).join("")
    || `<div class="meta">No filters for this result set.</div>`;
  $("facets").querySelectorAll("input[type=checkbox]").forEach(cb => cb.addEventListener("change", () => {
    const list = selected[cb.dataset.col] ??= [];
    cb.checked ? list.push(cb.value) : list.splice(list.indexOf(cb.value), 1);
    run();
  }));
}

(async () => {
  const codes = await (await fetch("/api/codes")).json();
  codeLabels = codes.codes; groups = codes.groups;
  $("group").innerHTML += Object.keys(groups).map(g => `<option>${esc(g)}</option>`).join("");
  const init = new URLSearchParams(location.search);
  $("q").value = init.get("q") ?? "";
  if (init.get("sort")) $("sort").value = init.get("sort");
  $("all").checked = init.get("mode") === "all";
  for (const [col, key] of Object.entries(FACET_PARAM)) { const v = init.getAll(key); if (v.length && col !== "kb") selected[col] = v; }
  if (init.get("kb")) $("kb").value = init.get("kb");
  run();
})();
$("form").addEventListener("submit", e => { e.preventDefault(); run(); });
["kb", "group", "sort", "all"].forEach(id => $(id).addEventListener("change", () => run()));
$("helpBtn").addEventListener("click", e => { e.preventDefault(); $("help").open = !$("help").open; $("help").scrollIntoView(); });
