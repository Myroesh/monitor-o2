/**
 * monitor.js — Phase 2
 * Polls /monitor/api/telemetry every 250 ms and updates the UI + chart.
 */

"use strict";

// ── Configuration ──────────────────────────────────────────────────────────
const POLL_INTERVAL_MS = 250;
const CHART_WINDOW_S   = 60;   // seconds of history shown in the graph
const MAX_CHART_POINTS = CHART_WINDOW_S * (1000 / POLL_INTERVAL_MS); // ≈ 240

// ── DOM references ─────────────────────────────────────────────────────────
const els = {
  status:       document.getElementById("val-status"),
  o2:           document.getElementById("val-o2"),
  flow:         document.getElementById("val-flow"),
  temp:         document.getElementById("val-temp"),
  pCalibrated:  document.getElementById("val-p-calibrated"),
  vsMpx:        document.getElementById("val-vs-mpx"),
  pNominal:     document.getElementById("val-p-nominal"),
  curveSelect:  document.getElementById("curve-select"),
  chartCanvas:  document.getElementById("pressure-chart"),
};

// ── Chart setup ────────────────────────────────────────────────────────────
const chartData = {
  labels: [],
  datasets: [
    {
      label: "P calibrada (kPa)",
      data: [],
      borderColor: "#3b82f6",
      backgroundColor: "rgba(59,130,246,0.08)",
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true,
    },
  ],
};

const chart = new Chart(els.chartCanvas, {
  type: "line",
  data: chartData,
  options: {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "nearest", intersect: false },
    scales: {
      x: {
        ticks: { color: "#64748b", maxTicksLimit: 6 },
        grid:  { color: "#2a2d3a" },
      },
      y: {
        ticks: { color: "#64748b" },
        grid:  { color: "#2a2d3a" },
        title: { display: true, text: "kPa", color: "#64748b" },
      },
    },
    plugins: {
      legend: { labels: { color: "#e2e8f0" } },
    },
  },
});

// ── Curve selector ─────────────────────────────────────────────────────────
const CURVE_KEYS = {
  p_calibrated: { key: "p_calibrated_kpa", label: "P calibrada (kPa)", color: "#3b82f6" },
  p_ema:        { key: "p_ema_kpa",        label: "P EMA (kPa)",       color: "#a855f7" },
  p_nominal:    { key: "p_nominal_kpa",    label: "P nominal (kPa)",   color: "#10b981" },
};

function applySelectedCurve(history) {
  const selected = CURVE_KEYS[els.curveSelect.value] ?? CURVE_KEYS.p_calibrated;
  const dataset  = chart.data.datasets[0];
  dataset.label       = selected.label;
  dataset.borderColor = selected.color;
  dataset.backgroundColor = selected.color.replace(")", ",0.08)").replace("rgb", "rgba");

  // Rebuild chart data from history
  const labels = [];
  const values = [];
  for (const s of history) {
    const d = new Date(s.ts * 1000);
    labels.push(d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    values.push(s[selected.key]);
  }
  chart.data.labels   = labels;
  dataset.data        = values;
  chart.update("none");
}

els.curveSelect.addEventListener("change", () => {
  // Redraw immediately with cached history if available
  if (lastHistory.length) applySelectedCurve(lastHistory);
});

// ── State ──────────────────────────────────────────────────────────────────
let lastHistory = [];

// ── UI update ──────────────────────────────────────────────────────────────
function fmt(v, decimals = 2) {
  return v != null ? Number(v).toFixed(decimals) : "—";
}

function updateUI(latest, history) {
  lastHistory = history;

  const connected = latest?.connected ?? false;
  els.status.textContent  = connected ? "Conectado" : "Desconectado";
  els.status.className    = "status-badge " + (connected ? "status-ok" : "status-err");

  if (!latest) return;

  els.o2.textContent          = fmt(latest.o2_pct, 2) + " %";
  els.flow.textContent        = fmt(latest.flow_lpm, 2) + " L/min";
  els.temp.textContent        = fmt(latest.temp_c, 1) + " °C";
  els.pCalibrated.textContent = fmt(latest.p_calibrated_kpa, 3) + " kPa";
  els.vsMpx.textContent       = fmt(latest.vs_mpx_mv, 1) + " mV";
  els.pNominal.textContent    = fmt(latest.p_nominal_kpa, 3) + " kPa";

  applySelectedCurve(history);
}

// ── Polling ────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const res  = await fetch("/api/telemetry");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    updateUI(json.latest, json.history ?? []);
  } catch (err) {
    els.status.textContent = "Error";
    els.status.className   = "status-badge status-err";
    console.warn("Telemetry poll error:", err);
  }
}

// Start immediately then repeat
poll();
setInterval(poll, POLL_INTERVAL_MS);
