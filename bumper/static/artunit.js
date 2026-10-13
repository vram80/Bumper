"use strict";
const out = document.getElementById("out");
const input = document.getElementById("q");

async function load(unit) {
  history.replaceState(null, "", `/artunit?id=${encodeURIComponent(unit)}`);
  input.value = unit;
  const res = await fetch(`/api/artunit?id=${encodeURIComponent(unit)}`);
  if (!res.ok) { out.innerHTML = `<div class="empty">No data for art unit ${esc(unit)}.</div>`; return; }
  const d = await res.json(), b = d.report.basic;
  out.innerHTML = `
    <h1>Art unit ${esc(d.art_unit)}</h1>
    <div class="sub">${d.examiners.length} examiners · ${b.disposed} dispositions in the last 3 years</div>
    <div class="grid">
      <div class="card"><h3>Unit totals</h3><table>
        <tr><td>Allowance rate</td><td class="num">${fmt.pct(b.allowance_rate)}</td></tr>
        <tr><td>Actions per allowance</td><td class="num">${fmt.num(b.actions_per_allowance)}</td></tr>
        <tr><td>Actions per abandonment</td><td class="num">${fmt.num(b.actions_per_abandonment)}</td></tr>
        <tr><td>Months to first action</td><td class="num">${fmt.num(b.months_to_first_action, 0)}</td></tr>
        <tr><td>Months to first allowance</td><td class="num">${fmt.num(b.months_to_first_allowance, 0)}</td></tr></table></div>
      <div class="card"><h3>Allowance rate by year</h3><canvas id="rateChart"></canvas></div>
    </div>
    <div class="card apps"><h3>Examiners</h3><table>
      <tr><th>Examiner</th><th class="num">Disposed</th><th class="num">Allowance</th><th class="num">Actions/allow</th><th class="num">Months to 1st</th></tr>
      ${d.examiners.map(e => `<tr><td><a href="/examiner?id=${encodeURIComponent(e.name)}">${esc(e.name)}</a></td>
        <td class="num">${e.disposed}</td><td class="num">${fmt.pct(e.allowance_rate)}</td>
        <td class="num">${fmt.num(e.actions_per_allowance)}</td><td class="num">${fmt.num(e.months_to_first_action, 0)}</td></tr>`).join("")}
    </table></div>`;
  if (!window.Chart) return;
  const years = Object.keys(d.charts.allowance_by_year);
  drawChart("rateChart", { type: "bar", data: { labels: years, datasets: [{ label: "Allowance rate",
    data: years.map(y => d.charts.allowance_by_year[y].rate), backgroundColor: "#2f5bd3" }] },
    options: { scales: { y: { min: 0, max: 1, ticks: { callback: v => Math.round(v * 100) + "%" } } } } });
}

autocomplete(input, "/api/artunit/suggest", load);
const initial = new URLSearchParams(location.search).get("id");
if (initial) load(initial);
