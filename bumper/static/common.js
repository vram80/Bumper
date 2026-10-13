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
