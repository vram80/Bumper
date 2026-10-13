"use strict";
// Patent reader. Section references (R1...) point to docs/specs/patent-reader.md.
const $ = id => document.getElementById(id);
const doc = $("doc");
let current = null;            // payload of the patent on screen
let labelIndex = {};           // label (upper case) -> [sheet numbers]
let observer = null;

// ---------------------------------------------------------------- settings (R10)
const DEFAULTS = { size: "regular", font: "serif", mode: "light", bg: "on", bgtone: "normal" };
const store = {
  get(k, d) { try { const v = localStorage.getItem("bumper.reader." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("bumper.reader." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
let settings = { ...DEFAULTS, ...store.get("settings", {}) };
function applySettings() {
  const b = document.body;
  b.className = b.className.replace(/\b(size|font|mode|bg|bgtone)-\S+/g, "").trim();
  for (const [k, v] of Object.entries(settings)) b.classList.add(`${k}-${v}`);
  document.querySelectorAll("#setMenu .seg").forEach(seg =>
    seg.querySelectorAll("button").forEach(btn => btn.classList.toggle("on", settings[seg.dataset.set] === btn.dataset.v)));
}
document.querySelectorAll("#setMenu .seg button").forEach(btn => btn.addEventListener("click", () => {
  settings[btn.parentElement.dataset.set] = btn.dataset.v; store.set("settings", settings); applySettings();
}));
$("resetSettings").addEventListener("click", () => { settings = { ...DEFAULTS }; store.set("settings", settings); applySettings(); });
applySettings();

// ---------------------------------------------------------------- menus and top bar
document.querySelectorAll(".menu > .tb").forEach(btn => btn.addEventListener("click", e => {
  e.stopPropagation();
  const menu = btn.parentElement, open = !menu.classList.contains("open");
  document.querySelectorAll(".menu.open").forEach(m => m.classList.remove("open"));
  menu.classList.toggle("open", open);
}));
document.querySelectorAll(".menu-list").forEach(l => l.addEventListener("click", e => e.stopPropagation()));
document.addEventListener("click", () => document.querySelectorAll(".menu.open").forEach(m => m.classList.remove("open")));

// R5: the top bar hides while reading and returns near the top edge or at the top of the page.
let lastY = 0;
window.addEventListener("scroll", () => {
  const y = window.scrollY, bar = $("topbar");
  if (y < 100 || document.querySelector(".menu.open")) bar.classList.remove("hidden");
  else if (y > lastY) bar.classList.add("hidden");
  lastY = y;
  maybeShowStrip();
}, { passive: true });
document.addEventListener("mousemove", e => { if (e.clientY < 60) $("topbar").classList.remove("hidden"); });

// R5: collapsible sidebar, remembered; overlay on narrow screens.
const narrow = () => window.matchMedia("(max-width: 900px)").matches;
if (store.get("sidebar", "open") === "closed") document.body.classList.add("side-closed");
$("sidebarBtn").addEventListener("click", () => {
  if (narrow()) { document.body.classList.toggle("side-open"); return; }
  const closed = document.body.classList.toggle("side-closed");
  store.set("sidebar", closed ? "closed" : "open");
});
$("scrim").addEventListener("click", () => document.body.classList.remove("side-open"));

// ---------------------------------------------------------------- number display (R2)
function displayNumber(n) {
  if (!n) return "";
  if (n.type === "pat") {
    const m = /^([A-Z]*)(\d+)$/.exec(n.n);
    return m ? `U.S. ${m[1]}${Number(m[2]).toLocaleString("en-US")}` : `U.S. ${n.n}`;
  }
  if (n.type === "pub") return `US ${n.n.slice(0, 4)}/${n.n.slice(4)}`;
  return n.n;
}
function linkFor(type, n, text) {
  return `<a class="plink" data-type="${esc(type)}" data-n="${esc(n)}" href="/patent?type=${esc(type)}&n=${encodeURIComponent(n)}">${esc(text ?? n)}</a>`;
}

// ---------------------------------------------------------------- text rendering (R7)
function renderParts(parts) {
  return parts.map(p => {
    if (p.t === "num") {
      const sheets = labelIndex[p.v.toUpperCase()];
      return sheets ? `<span class="lab num" data-label="${esc(p.v.toUpperCase())}">${esc(p.v)}</span>` : `<b>${esc(p.v)}</b>`;
    }
    if (p.t === "fig") {
      const keys = (p.figs || []).map(f => `FIG. ${f}`).filter(k => labelIndex[k]);
      return keys.length ? `<span class="lab" data-label="${esc(keys.join("|"))}">${esc(p.v)}</span>` : esc(p.v);
    }
    if (p.t === "ref") return `<a class="cref" data-claim="${esc(p.to)}">${esc(p.v)}</a>`;
    return esc(p.v);
  }).join("");
}
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const sentence = s => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

// ---------------------------------------------------------------- page assembly (R2-R4, R9)
function render(d) {
  current = d;
  labelIndex = d.drawings.labels || {};
  const b = d.biblio, num = displayNumber(d.number);
  document.title = `${num} - Patent Reader`;
  $("sideNum").textContent = num;
  const helpIcon = text => `<span class="help" title="${esc(text)}">?</span>`;
  const related = b.related || [];
  const relatedHtml = related.length > 3
    ? `<a class="plink-more" data-list="${esc(JSON.stringify(related))}">${related.length} related publications</a>`
    : related.map(r => r.link ? linkFor(r.link.type, r.link.n, `${r.number}${r.kind && r.kind.length < 4 ? " " + r.kind : ""}`) + (r.kind && r.kind.length >= 4 ? ` <span class="meta">(${esc(r.kind)})</span>` : "") : esc(r.number)).join(", ");
  const person = (name, field) => `<a href="#" class="who" data-q='${esc(`applicationMetaData.${field}:"${name}"`)}'>${esc(name)}</a>`;
  const rows = [
    ["Publication number", esc(b.publication_number)], ["Publication type", esc(b.publication_type)],
    ["Application number", b.application_number ? linkFor("app", b.application_number) : ""],
    ["Publication date", esc(b.publication_date)], ["Filing date", esc(b.filing_date)],
    [`Priority date${helpIcon("The earliest claimed priority date as listed; it is not a legal conclusion about the effective date.")}`, esc(b.priority_date)],
    [`Status${helpIcon("The USPTO status as recorded; fee and term status should be confirmed before relying on it.")}`, esc(b.status)],
    ["Related publications", relatedHtml],
    ["Inventors", (b.inventors || []).map(n => person(n, "inventorBag.inventorNameText")).join(", ")],
    ["Assignee", (b.assignees || []).map(n => person(n, "firstApplicantName")).join(", ")],
    ["Examiner", b.examiner ? `<a href="/examiner?id=${encodeURIComponent(b.examiner)}">${esc(b.examiner)}</a> · AU ${esc(b.art_unit ?? "")}` : ""],
    ["Export citation", ["bibtex", "enw", "ris"].map(f => `<a href="/api/patent/cite?type=${d.number.type}&n=${encodeURIComponent(d.number.n)}&format=${f}">${{ bibtex: "BibTeX", enw: "EndNote", ris: "RIS" }[f]}</a>`).join(", ")],
    ["External links", [`<a href="/lookup?type=app&q=${encodeURIComponent(b.application_number || "")}">USPTO file history</a>`,
      `<a href="https://assignmentcenter.uspto.gov/search/patent?q=${encodeURIComponent(d.number.n)}" target="_blank" rel="noopener">USPTO assignments</a>`,
      `<a href="https://worldwide.espacenet.com/patent/search?q=pn%3DUS${encodeURIComponent(d.number.n)}" target="_blank" rel="noopener">Espacenet</a>`].join(", ")],
  ].filter(([, v]) => v);

  const indep = d.claims.filter(c => c.independent).length;
  const claimsHtml = d.claims.map(c => `<div class="claim ${c.independent ? "ind" : "dep"}" id="${esc(c.id)}">${renderParts(c.parts)}</div>`).join("");
  const abstractHtml = d.abstract.map(p => `<p class="para">${renderParts(p)}</p>`).join("");
  const toc = [];
  let descHtml = "";
  for (const p of d.description) {
    if (p.kind === "heading") {
      const id = "d-" + slug(p.text);
      toc.push({ id, text: sentence(p.text) });
      descHtml += `<h3 class="sub" id="${id}">${esc(p.text)}</h3>`;
    } else descHtml += `<p class="para"><span class="pid">[${esc(p.num || "")}]</span>${renderParts(p.parts)}</p>`;
  }
  const citations = d.citations.length ? `<table class="data"><tr><th>Cited patent</th><th>Date</th><th>Name</th></tr>
    ${d.citations.map(c => `<tr><td>${c.link ? linkFor(c.link.type, c.link.n, `${c.country}${c.number}${c.kind ? " " + c.kind : ""}`) : esc(`${c.country}${c.number} ${c.kind || ""}`)}${c.by_examiner ? " *" : ""}</td>
      <td>${esc(c.date || "")}</td><td>${esc(c.name || "")}</td></tr>`).join("")}</table>
    ${d.npl.length ? `<h3 class="sub">Other references</h3>${d.npl.map(n => `<p class="para">${esc(n.text)}${n.by_examiner ? " *" : ""}</p>`).join("")}` : ""}
    <p class="meta">* Cited by examiner</p>` : "";
  const cls = d.classifications, clsRows = [["CPC", cls.cpc], ["International (IPC)", cls.ipc], ["U.S. classification", cls.uspc]].filter(([, v]) => v.length);
  const legal = d.legal_events.length ? `<table class="data"><tr><th>Date</th><th>Code</th><th>Event</th></tr>
    ${d.legal_events.map(e => `<tr><td>${esc(e.date)}</td><td>${esc(e.code)}</td><td>${esc(e.description)}</td></tr>`).join("")}</table>` : "";

  // R3: sections without data are left out together with their navigation entry.
  const sections = [
    ["claims", "Claims", d.claims.length && `<h2 id="claims">Claims <span class="claim-counts">${indep ? `<a data-claims="Independent" title="Show the independent claims">(${indep})</a> | <a data-claims="All" title="Show all claims">(${d.claims.length})</a>` : ""}</span></h2>${claimsHtml}`],
    ["abstract", "Abstract", abstractHtml && `<h2 id="abstract">Abstract</h2>${abstractHtml}`],
    ["description", "Description", descHtml && `<h2 id="description">Description</h2>${descHtml}`],
    ["citations", "Patent citations", citations && `<h2 id="citations">Patent citations</h2>${citations}`],
    ["classifications", "Classifications", clsRows.length && `<h2 id="classifications">Classifications</h2><table class="data">${clsRows.map(([k, v]) => `<tr><td>${k}</td><td>${v.map(esc).join(", ")}</td></tr>`).join("")}</table>`],
    ["legal", "Legal events", legal && `<h2 id="legal">Legal events</h2>${legal}`],
  ].filter(s => s[2]);

  doc.innerHTML = `<div class="pnum">${esc(num)}</div><h1>${esc(d.title || "")}</h1>
    ${d.full_text ? "" : `<div class="note">The USPTO has not published full text for this document in its per-patent files, so only the bibliographic data, legal events and page images are shown. The PDF has the complete text.</div>`}
    <table class="bib">${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>
    ${sections.map(s => s[2]).join("")}`;

  $("sideList").innerHTML = sections.map(([id, label]) => `<li><a href="#${id}">${label}</a>${id === "description" && toc.length
    ? `<ul>${toc.map(t => `<li><a href="#${t.id}">${esc(t.text)}</a></li>`).join("")}</ul>` : ""}</li>`).join("");

  // R12 links.
  const pdf = `/api/patent/pdf?type=${d.number.type}&n=${encodeURIComponent(d.number.n)}`;
  $("pdfRead").href = pdf; $("pdfDownload").href = pdf; $("pdfDownload").download = `US${d.number.n}.pdf`;
  $("pdfEmail").href = `mailto:?subject=${encodeURIComponent(`${num}: ${d.title}`)}&body=${encodeURIComponent(location.origin + pdf)}`;
  $("extLink").href = `https://patents.google.com/patent/US${d.number.n}${d.number.kind || ""}/en`;
  updateStar();
  buildStrip();
  setupScrollSpy();
  setupBackdrop();
}

// ---------------------------------------------------------------- loading (R1)
async function openPatent(type, n, push = true) {
  hidePop();
  $("busy").hidden = false;
  try {
    const res = await fetch(`/api/patent/read?type=${encodeURIComponent(type)}&n=${encodeURIComponent(n)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    if (push) history.pushState({ type, n }, "", `/patent?type=${encodeURIComponent(type)}&n=${encodeURIComponent(n)}`);
    render(data);
    window.scrollTo(0, 0);
    countView(data.number);
  } catch (e) {
    doc.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  } finally {
    $("busy").hidden = true;
  }
}
window.addEventListener("popstate", () => route(false));

function guessType(text) {
  const t = text.trim().toUpperCase().replace(/^US/, "").replace(/[\s,]/g, "");
  if (/^(D|RE|PP|H|T)?\d{4,8}(B\d|E|S|P\d)?$/.test(t)) return "pat";
  if (/^\d{4}\/?\d{6,7}(A\d)?$/.test(t)) return "pub";
  if (/^\d{2}\/\d{3}\d{3}$/.test(t)) return "app";
  return null;
}
$("rsearch").addEventListener("submit", e => {
  e.preventDefault();
  const text = $("rq").value.trim();
  if (!text) return;
  const type = guessType(text);
  $("rq").value = "";
  if (type) openPatent(type, text); else runSearch(text, 1);
});

// ---------------------------------------------------------------- search (R11)
async function runSearch(q, page, push = true) {
  hidePop();
  $("busy").hidden = false;
  try {
    const res = await fetch(`/api/patent/search?q=${encodeURIComponent(q)}&page=${page}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    if (push) history.pushState({ q, page }, "", `/patent?q=${encodeURIComponent(q)}&page=${page}`);
    current = null; labelIndex = {};
    document.title = `${q} - Patent search`;
    $("sideNum").textContent = "Search results";
    const pager = () => data.pages > 1 ? `<div class="rpager"><button data-p="${page - 1}" ${page <= 1 ? "disabled" : ""}>Prev</button>
      ${Array.from({ length: data.pages }, (_, i) => `<button data-p="${i + 1}" class="${i + 1 === page ? "on" : ""}">${i + 1}</button>`).join("")}
      <button data-p="${page + 1}" ${page >= data.pages ? "disabled" : ""}>Next</button></div>` : "";
    doc.innerHTML = `<h1>${data.total.toLocaleString()} search results</h1><p class="meta">for ${esc(q)}</p>${pager()}
      <div class="results">${data.results.map((r, i) => {
        const l = r.link, img = l ? `/api/patent/thumb?type=${l.type}&n=${encodeURIComponent(l.n)}` : "";
        return `<div class="res" id="res-${i}">${l ? `<a class="plink" data-type="${l.type}" data-n="${esc(l.n)}" href="/patent?type=${l.type}&n=${encodeURIComponent(l.n)}"><img loading="lazy" src="${img}" alt="" onerror="this.style.visibility='hidden'"></a>` : "<span></span>"}
          <div><div class="t">${l ? linkFor(l.type, l.n, r.title || l.n) : esc(r.title || "")}</div>
            <div class="u">${l ? esc(`${location.host}/patent?type=${l.type}&n=${l.n}`) : `Application ${esc(r.application_number)} (not published)`}</div>
            <div>${esc([r.patent_number ? `Patent ${r.patent_number}` : r.publication_number, r.applicant, r.filing_date && `filed ${r.filing_date}`, r.status].filter(Boolean).join(" · "))}</div></div></div>`;
      }).join("") || `<p>No results. Check the search words and try again.</p>`}</div>${pager()}`;
    doc.querySelectorAll(".rpager button[data-p]").forEach(b => b.addEventListener("click", () => runSearch(q, +b.dataset.p)));
    $("sideList").innerHTML = data.results.map((r, i) => `<li><a href="#res-${i}">${esc(r.patent_number || r.publication_number || r.application_number)}</a></li>`).join("");
    $("stripList").innerHTML = ""; $("strip").classList.remove("open");
    setupScrollSpy();
    window.scrollTo(0, 0);
  } catch (e) {
    doc.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  } finally {
    $("busy").hidden = true;
  }
}

// ---------------------------------------------------------------- navigation and scroll spy (R5)
$("sidebar").addEventListener("click", e => {
  const a = e.target.closest("a[href^='#']");
  if (!a) return;
  e.preventDefault();
  const target = document.getElementById(a.getAttribute("href").slice(1));
  if (!target) return;
  window.scrollTo({ top: target.getBoundingClientRect().top + window.scrollY - 64, behavior: "smooth" });
  setTimeout(() => { target.classList.remove("flash"); void target.offsetWidth; target.classList.add("flash"); }, 420);
  if (narrow()) document.body.classList.remove("side-open");
});
function setupScrollSpy() {
  if (observer) observer.disconnect();
  const links = [...$("sidebar").querySelectorAll("a[href^='#']")];
  const targets = links.map(a => document.getElementById(a.getAttribute("href").slice(1))).filter(Boolean);
  observer = new IntersectionObserver(entries => {
    const visible = entries.filter(en => en.isIntersecting);
    if (!visible.length) return;
    const id = visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0].target.id;
    $("sidebar").querySelectorAll(".active").forEach(el => el.classList.remove("active"));
    const link = links.find(a => a.getAttribute("href") === "#" + id);
    if (!link) return;
    (link.classList.contains("snum") ? link : link.parentElement).classList.add("active");
    const parentLi = link.parentElement.parentElement.closest("li");
    if (parentLi) parentLi.classList.add("active");
    if (!$("sidebar").matches(":hover")) link.scrollIntoView({ block: "nearest" });
  }, { rootMargin: "-60px 0px -70% 0px" });
  targets.forEach(t => observer.observe(t));
}

// ---------------------------------------------------------------- popovers (R6, R7)
const pop = $("pop");
let popOwner = null, hideTimer = null;
function hidePop() { pop.hidden = true; pop.innerHTML = ""; popOwner = null; }
function placePop(anchor, side) {
  const r = anchor.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight, sx = window.scrollX, sy = window.scrollY;
  let x, y;
  if (!side) side = r.left > window.innerWidth - 500 ? "left" : r.left < 300 ? "right" : r.top < 310 ? "bottom" : "top";
  if (side === "left") { x = r.left - pw - 10; y = r.top + r.height / 2 - ph / 2; }
  else if (side === "right") { x = r.right + 10; y = r.top + r.height / 2 - ph / 2; }
  else if (side === "bottom") { x = r.left + r.width / 2 - pw / 2; y = r.bottom + 10; }
  else { x = r.left + r.width / 2 - pw / 2; y = r.top - ph - 10; }
  x = Math.max(8, Math.min(x, window.innerWidth - pw - 8));
  y = Math.max(60, Math.min(y, window.innerHeight - ph - 8));
  pop.style.left = `${x + sx}px`; pop.style.top = `${y + sy}px`;
}
function scheduleHide() {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => { if (!pop.matches(":hover") && !(popOwner && popOwner.matches(":hover"))) hidePop(); }, 100);
}
pop.addEventListener("mouseleave", scheduleHide);
pop.addEventListener("mouseenter", () => clearTimeout(hideTimer));

// R7: a numeral or figure label shows the drawing sheets it appears on.
function sheetUrl(sheet, width) {
  const page = current.drawings.pages[sheet - 1];
  return page ? `${current.drawings.image}&page=${page}&w=${width}` : null;
}
function showSheets(el) {
  const sheets = [...new Set(el.dataset.label.split("|").flatMap(l => labelIndex[l] || []))].filter(s => sheetUrl(s, 100));
  if (!sheets.length) return;
  clearTimeout(hideTimer);
  popOwner = el;
  const maxW = Math.floor(window.innerWidth / 2 / sheets.length), maxH = Math.floor(window.innerHeight / 2 / Math.max(1, sheets.length > 2 ? 2 : 1));
  pop.className = "";
  pop.innerHTML = `<div class="sheets">${sheets.map(s => `<figure><img data-sheet="${s}" src="${sheetUrl(s, 900)}" style="max-width:${maxW}px;max-height:${maxH}px" alt="Drawing ${s}"><figcaption>Drawing ${s}</figcaption></figure>`).join("")}</div>`;
  pop.hidden = false;
  placePop(el);
  pop.querySelectorAll("img").forEach(img => img.addEventListener("load", () => popOwner === el && placePop(el), { once: true }));
}
pop.addEventListener("click", e => {
  const img = e.target.closest("img[data-sheet]");
  if (img) { hidePop(); openGallery(+img.dataset.sheet); }
});

// R6: patent links show a preview card after half a second.
const previews = new Map();
let cardTimer = null;
async function showCard(el) {
  const key = `${el.dataset.type}:${el.dataset.n}`;
  if (!previews.has(key)) {
    const res = await fetch(`/api/preview?type=${encodeURIComponent(el.dataset.type)}&n=${encodeURIComponent(el.dataset.n)}`);
    previews.set(key, res.ok ? await res.json() : null);
  }
  const p = previews.get(key);
  if (!p || !el.matches(":hover")) return;
  popOwner = el;
  pop.className = "card";
  const label = displayNumber({ type: el.dataset.type, n: el.dataset.n });
  pop.innerHTML = `<h4>${esc(label)}</h4><b>${esc(p.title || "")}</b><div style="margin-top:8px">${p.image ? `<img src="${p.image}" alt="">` : ""}
    ${esc(p.abstract || [p.applicant, p.filing_date && `Filed ${p.filing_date}`, p.issue_date && `Issued ${p.issue_date}`, p.status].filter(Boolean).join(" · "))}</div><div style="clear:both"></div>`;
  pop.hidden = false;
  placePop(el, el.closest("table.bib") ? "left" : "right");
}

document.addEventListener("mouseover", e => {
  const lab = e.target.closest(".lab");
  if (lab && lab !== popOwner) { showSheets(lab); return; }
  const link = e.target.closest("a.plink");
  if (link && link !== popOwner) {
    clearTimeout(cardTimer);
    if (!pop.hidden && pop.classList.contains("card")) hidePop();
    cardTimer = setTimeout(() => showCard(link), 500);
  }
});
document.addEventListener("mouseout", e => {
  const el = e.target.closest(".lab, a.plink");
  if (!el) return;
  if (el.matches("a.plink")) clearTimeout(cardTimer);
  if (el === popOwner) scheduleHide();
});

document.addEventListener("click", e => {
  const link = e.target.closest("a.plink");
  if (link && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    clearTimeout(cardTimer); hidePop();
    openPatent(link.dataset.type, link.dataset.n);
    return;
  }
  const lab = e.target.closest(".lab");
  if (lab) { e.preventDefault(); return; }
  const more = e.target.closest(".plink-more");
  if (more) {   // R4: expand the related publications list in place
    const list = JSON.parse(more.dataset.list);
    more.outerHTML = list.map(r => r.link ? linkFor(r.link.type, r.link.n, r.number) : esc(r.number)).join(", ");
    return;
  }
  const who = e.target.closest("a.who");
  if (who) { e.preventDefault(); runSearch(who.dataset.q, 1); return; }
  const cref = e.target.closest("a.cref");
  if (cref) { const t = document.getElementById(cref.dataset.claim); if (t) { t.scrollIntoView({ behavior: "smooth", block: "center" }); t.classList.add("flash"); setTimeout(() => t.classList.remove("flash"), 1600); } return; }
  const counts = e.target.closest("[data-claims]");
  if (counts) openClaims(counts.dataset.claims);
});

// ---------------------------------------------------------------- claims dialog (R9)
function openClaims(which) {
  const claims = which === "Independent" ? current.claims.filter(c => c.independent) : current.claims;
  $("dtitle").textContent = `${which} claims`;
  $("dbody").innerHTML = claims.map(c => `<div class="claim ${c.independent ? "ind" : "dep"}">${renderParts(c.parts)}</div>`).join(which === "Independent" ? "<hr>" : "");
  $("dialog").hidden = false;
  $("dbody").scrollTop = 0;
}
$("dclose").addEventListener("click", () => { $("dialog").hidden = true; });
$("dialog").addEventListener("click", e => { if (e.target === $("dialog")) $("dialog").hidden = true; });

// ---------------------------------------------------------------- drawing strip and gallery (R8)
function sheetList() {
  const dr = current ? current.drawings : null;
  if (!dr) return [];
  if (dr.pages.length) return dr.pages.map((_, i) => ({ sheet: i + 1, url: w => sheetUrl(i + 1, w), cap: `Drawing ${i + 1}` }));
  // No full text: every PDF page is browsable instead.
  return Array.from({ length: dr.pdf_pages || 0 }, (_, i) => ({ sheet: i + 1, url: w => `${dr.image}&page=${i + 1}&w=${w}`, cap: `Page ${i + 1}` }));
}
let stripShown = false;
function buildStrip() {
  const list = sheetList();
  $("stripList").innerHTML = list.map(s => `<img loading="lazy" data-sheet="${s.sheet}" src="${s.url(220)}" alt="${s.cap}"><div class="cap">${s.cap}</div>`).join("");
  $("strip").classList.remove("open");
  stripShown = false;
  $("strip").style.display = list.length ? "" : "none";
}
function maybeShowStrip() {   // slides in once, when the drawings description is reached
  if (stripShown || !current) return;
  const anchor = [...document.querySelectorAll("#doc h3.sub")].find(h => /drawing|figure/i.test(h.textContent)) || $("description");
  if (anchor && anchor.getBoundingClientRect().top < window.innerHeight * 0.6) { $("strip").classList.add("open"); stripShown = true; }
}
$("stripTab").addEventListener("click", () => { $("strip").classList.toggle("open"); stripShown = true; });
$("stripList").addEventListener("click", e => { const img = e.target.closest("img[data-sheet]"); if (img) openGallery(+img.dataset.sheet); });

const gal = { index: 0, list: [], state: {}, timer: null, drag: null };
function gState() { return gal.state[gal.index] ??= { zoom: 1, rot: 0, x: 0, y: 0 }; }
function gApply() {
  const s = gState();
  $("gimg").style.transform = `translate(${s.x}px, ${s.y}px) scale(${s.zoom}) rotate(${s.rot}deg)`;
  $("gzoom").value = s.zoom;
}
function gShow(i) {
  const n = gal.list.length;
  gal.index = (i + n) % n;
  const item = gal.list[gal.index];
  $("gimg").src = item.url(1600);
  $("gcap").textContent = `${item.cap} of ${n}`;
  gApply();
}
function openGallery(sheet) {
  gal.list = sheetList();
  if (!gal.list.length) return;
  gal.state = {};
  $("gallery").hidden = false;
  gShow(Math.max(0, gal.list.findIndex(s => s.sheet === sheet)));
}
function closeGallery() { $("gallery").hidden = true; clearInterval(gal.timer); gal.timer = null; $("gallery").querySelector("[data-g=play]").textContent = "▶"; }
function togglePlay() {
  const btn = $("gallery").querySelector("[data-g=play]");
  if (gal.timer) { clearInterval(gal.timer); gal.timer = null; btn.textContent = "▶"; }
  else { gal.timer = setInterval(() => gShow(gal.index + 1), 3000); btn.textContent = "❚❚"; }
}
$("gallery").querySelector(".gbar").addEventListener("click", e => {
  const b = e.target.closest("[data-g]");
  if (!b) return;
  const s = gState();
  ({ prev: () => gShow(gal.index - 1), next: () => gShow(gal.index + 1), play: togglePlay, close: closeGallery,
     rotate: () => { s.rot = (s.rot + 90) % 360; gApply(); },
     reset: () => { gal.state[gal.index] = { zoom: 1, rot: 0, x: 0, y: 0 }; gApply(); } })[b.dataset.g]();
});
$("gzoom").addEventListener("input", () => { gState().zoom = +$("gzoom").value; gApply(); });
const stage = $("gallery").querySelector(".gstage");
stage.addEventListener("click", e => { if (e.target === stage && !gal.moved) closeGallery(); });
$("gimg").addEventListener("mousedown", e => { e.preventDefault(); const s = gState(); gal.drag = { x: e.clientX - s.x, y: e.clientY - s.y }; gal.moved = false; stage.style.cursor = "grabbing"; });
window.addEventListener("mousemove", e => { if (!gal.drag) return; const s = gState(); s.x = e.clientX - gal.drag.x; s.y = e.clientY - gal.drag.y; gal.moved = true; gApply(); });
window.addEventListener("mouseup", () => { gal.drag = null; stage.style.cursor = ""; setTimeout(() => { gal.moved = false; }, 0); });
document.addEventListener("keydown", e => {
  if (!$("gallery").hidden) {
    if (e.key === "ArrowRight") gShow(gal.index + 1);
    else if (e.key === "ArrowLeft") gShow(gal.index - 1);
    else if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "Escape") closeGallery();
    return;
  }
  if (e.key === "Escape") { $("dialog").hidden = true; hidePop(); }
});

// ---------------------------------------------------------------- background, favourites, views (R10, R12)
function setupBackdrop() {
  const first = sheetList()[0];
  $("backdrop").style.backgroundImage = first ? `url("${first.url(1200)}")` : "";
}
function favourites() { return store.get("favourites", []); }
function updateStar() {
  const on = current && favourites().includes(current.number.n);
  $("starBtn").textContent = on ? "★" : "☆";
  $("starBtn").classList.toggle("on", !!on);
}
$("starBtn").addEventListener("click", () => {
  if (!current) return;
  const list = favourites(), n = current.number.n, i = list.indexOf(n);
  if (i >= 0) list.splice(i, 1); else list.push(n);
  store.set("favourites", list);
  updateStar();
});
function countView(number) {
  const views = store.get("views", {});
  views[number.n] = (views[number.n] || 0) + 1;
  store.set("views", views);
  $("starBtn").title = `Favourite · viewed ${views[number.n]} time${views[number.n] === 1 ? "" : "s"} on this device`;
}

// ---------------------------------------------------------------- start
function route(push) {
  const p = new URLSearchParams(location.search);
  if (p.get("n")) openPatent(p.get("type") || guessType(p.get("n")) || "pat", p.get("n"), push);
  else if (p.get("q")) runSearch(p.get("q"), +(p.get("page") || 1), push);
}
route(false);
