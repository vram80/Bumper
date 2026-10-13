"use strict";
const out = document.getElementById("out");
const input = document.getElementById("q");
let current = null, scope = "all";

// [label, getter, formatter, rank key, high value = harder prosecution?]
const BASIC = [
  ["Allowance rate", r => r.basic.allowance_rate, (v, r) => `${fmt.pct(v)} <small>(${r.basic.allowed}/${r.basic.disposed})</small>`, "allowance_rate", false],
  ["Actions per allowance", r => r.basic.actions_per_allowance, v => fmt.num(v), "actions_per_allowance", true],
  ["Actions per abandonment", r => r.basic.actions_per_abandonment, v => fmt.num(v), "actions_per_abandonment", true],
  ["Months to first action", r => r.basic.months_to_first_action, v => fmt.num(v, 0), "months_to_first_action", true],
  ["Months to first allowance", r => r.basic.months_to_first_allowance, v => fmt.num(v, 0), "months_to_first_allowance", true],
];

function distTable(title, dist, labels) {
  const rows = Object.entries(labels).map(([k, label]) =>
    `<tr><td>${label}</td><td class="num">${fmt.pct(dist.rates[k])}</td><td class="num">${dist.counts[k]}</td></tr>`).join("");
  return `<div class="card"><h3>${title} <small>(${dist.total} tracked)</small></h3>
    <table><tr><th>Outcome</th><th class="num">Share</th><th class="num">Count</th></tr>${rows}</table></div>`;
}

function interviewTable(title, iv) {
  return `<div class="card"><h3>${title}</h3><table>
    <tr><td>Interviews held</td><td class="num">${fmt.int(iv.interviews)}</td></tr>
    <tr><td>Allowance rate with interview</td><td class="num">${fmt.pct(iv.allowance_rate_with)} <small>(${iv.disposed_with} disposed)</small></td></tr>
    <tr><td>Actions per interview</td><td class="num">${fmt.num(iv.actions_per_interview)}</td></tr></table></div>`;
}

function render() {
  const d = current, r = d.report, ranks = d.rank[scope];
  const basicRows = BASIC.map(([label, get, f, key, hard]) => {
    const p = ranks[key];
    return `<tr><td>${label}</td><td class="num">${f(get(r), r)}</td>
      <td class="num"><span class="pill" style="background:${rankColor(p, hard)}">${fmt.pct(p)}</span></td></tr>`;
  }).join("");
  const exp = r.experience, ap = r.appeals;
  const afLabels = { rce: "RCE filed", appeal_brief: "Appeal brief filed", allowance: "Allowed", reopen: "New office action" };
  out.innerHTML = `
    <h1>${esc(r.examiner)}</h1>
    <div class="sub">Art unit ${esc(d.art_unit ?? "–")} · ${exp.applications} applications on file ·
      window ${r.window_start} to ${r.as_of}</div>
    <div class="tabs">
      <button data-scope="all" class="${scope === "all" ? "on" : ""}">Rank vs all examiners (${d.peer_counts.all})</button>
      <button data-scope="art_unit" class="${scope === "art_unit" ? "on" : ""}">Rank vs art unit ${esc(d.art_unit ?? "")} (${d.peer_counts.art_unit})</button>
    </div>
    <div class="grid">
      <div class="card"><h3>Core statistics <small>last 3 years</small></h3>
        <table><tr><th></th><th class="num">Value</th><th class="num">Percentile</th></tr>${basicRows}</table></div>
      <div class="card"><h3>Appeals <small>last 3 years</small></h3><table>
        <tr><td>Board decisions</td><td class="num">${ap.decisions}</td></tr>
        <tr><td>Affirmance rate (full affirmances only)</td><td class="num">${fmt.pct(ap.affirmance_rate)}</td></tr>
        <tr><td>Affirmed in part</td><td class="num">${ap.affirmed_in_part}</td></tr>
        <tr><td>Reversed</td><td class="num">${ap.reversed}</td></tr></table></div>
      ${distTable("After-final responses", r.after_final, afLabels)}
      ${distTable("AFCP 2.0 requests", r.afcp, afLabels)}
      ${distTable("Pre-appeal requests", r.pre_appeal, { proceed_to_board: "Proceed to board", reopen_or_allow: "Reopened or allowed" })}
      ${distTable("Appeal briefs", r.appeal_brief, { reopen: "Prosecution reopened", answer_or_decision: "Examiner's answer / decision", allowance: "Allowed", defective: "Held defective" })}
      ${interviewTable("Examiner-initiated interviews", r.examiner_interviews)}
      ${interviewTable("Applicant-initiated interviews", r.applicant_interviews)}
      <div class="card"><h3>Experience <small>all years</small></h3><table>
        <tr><td>Non-final rejections</td><td class="num">${exp.nonfinal_rejections}</td></tr>
        <tr><td>Final rejections</td><td class="num">${exp.final_rejections}</td></tr>
        <tr><td>Restrictions</td><td class="num">${exp.restrictions}</td></tr>
        <tr><td>Examiner's answers</td><td class="num">${exp.examiner_answers}</td></tr>
        <tr><td>Ex parte Quayle actions</td><td class="num">${exp.ex_parte_quayle}</td></tr>
        <tr><td>Earliest action on file</td><td class="num">${exp.first_action_date ?? "–"}</td></tr></table></div>
    </div>
    <div class="charts">
      <div class="card"><h3>Allowance rate by year</h3><canvas id="rateChart"></canvas></div>
      <div class="card"><h3>Dispositions</h3><canvas id="dispChart"></canvas></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>Office actions over time <small>months since filing</small></h3><canvas id="actChart"></canvas></div>
    <div class="card apps"><h3>Applications</h3><table>
      <tr><th>Application</th><th>Filed</th><th>Title</th><th>Status</th><th class="num">Actions</th></tr>
      ${d.applications.map(a => `<tr><td>${esc(a.app_no)}</td><td>${a.filed ?? ""}</td><td>${esc(a.title)}</td>
        <td>${esc(a.status)}</td><td class="num">${a.actions}</td></tr>`).join("")}</table></div>`;

  out.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => { scope = b.dataset.scope; render(); }));
  if (!window.Chart) return;
  const years = Object.keys(d.charts.allowance_by_year);
  const auYears = d.charts.art_unit_allowance_by_year;
  drawChart("rateChart", { type: "line", data: { labels: years, datasets: [
    { label: "Examiner", data: years.map(y => d.charts.allowance_by_year[y].rate), borderColor: "#2f5bd3" },
    { label: "Art unit", data: years.map(y => auYears[y]?.rate ?? null), borderColor: "#9aa3b2", borderDash: [4, 4] },
  ] }, options: { scales: { y: { min: 0, max: 1, ticks: { callback: v => Math.round(v * 100) + "%" } } } } });
  const disp = d.charts.dispositions;
  drawChart("dispChart", { type: "doughnut", data: { labels: ["Allowed", "Abandoned", "Pending", "Pre-exam abandoned"],
    datasets: [{ data: [disp.allowed, disp.abandoned, disp.pending, disp.preexam_abandoned],
      backgroundColor: ["#1f9d55", "#d64545", "#4f7cc4", "#c3c9d4"] }] } });
  const colors = { nonfinal: "#e08a2e", final: "#d64545", restriction: "#8e6bc4", quayle: "#c99a2e", examiner_answer: "#555", allowance: "#1f9d55" };
  const groups = {};
  d.charts.actions.forEach(p => { (groups[p.kind] ??= []).push({ x: Date.parse(p.date), y: p.months }); });
  drawChart("actChart", { type: "scatter", data: { datasets: Object.entries(groups).map(([k, pts]) =>
    ({ label: k.replace("_", " "), data: pts, backgroundColor: colors[k] ?? "#888" })) },
    options: { scales: { x: { ticks: { callback: v => new Date(v).getFullYear() } }, y: { title: { display: true, text: "months" } } } } });
}

async function load(name) {
  history.replaceState(null, "", `/examiner?id=${encodeURIComponent(name)}`);
  input.value = name;
  out.innerHTML = `<div class="empty">Loading…</div>`;
  const res = await fetch(`/api/examiner?id=${encodeURIComponent(name)}`);
  if (!res.ok) { out.innerHTML = `<div class="empty">No data for ${esc(name)}.</div>`; return; }
  current = await res.json();
  render();
}

autocomplete(input, "/api/examiner/suggest", load);
const initial = new URLSearchParams(location.search).get("id");
if (initial) load(initial);
