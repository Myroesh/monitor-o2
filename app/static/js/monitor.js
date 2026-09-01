/**
 * monitor.js — Phase 2 & Phase 5 (Audited & Enhanced)
 * Polls /api/telemetry every 250 ms and updates metric cards + 3 real-time charts:
 * 1. Presión (p_calibrated_kpa / p_ema_kpa / p_nominal_kpa)
 * 2. Pureza de O₂ (o2_pct) — invalidates on oxygen_valid === false
 * 3. Flujo (flow_lpm) — independent of oxygen_valid, valid flow_lpm = 0.0 displayed/plotted
 *
 * Single polling loop, shared history array.
 */

"use strict";

const POLL_INTERVAL_MS = 250;

// ── DOM references ─────────────────────────────────────────────────────────
const els = {
  status:         document.getElementById("val-status"),
  o2:             document.getElementById("val-o2"),
  flow:           document.getElementById("val-flow"),
  temp:           document.getElementById("val-temp"),
  pCalibrated:    document.getElementById("val-p-calibrated"),
  vsMpx:          document.getElementById("val-vs-mpx"),
  pNominal:       document.getElementById("val-p-nominal"),
  curveSelect:    document.getElementById("curve-select"),
  pressureCanvas: document.getElementById("pressure-chart"),
  o2Canvas:       document.getElementById("o2-chart"),
  flowCanvas:     document.getElementById("flow-chart"),
};

// ── Chart Helper Factory ───────────────────────────────────────────────────
function createLineChart(canvasEl, yTitle, defaultLabel, borderColor, backgroundColor) {
  if (!canvasEl) return null;
  return new Chart(canvasEl, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: defaultLabel,
          data: [],
          borderColor: borderColor,
          backgroundColor: backgroundColor,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
          spanGaps: false, // Do not draw line across null values (invalid data)
        },
      ],
    },
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
          title: { display: true, text: yTitle, color: "#64748b" },
        },
      },
      plugins: {
        legend: { labels: { color: "#e2e8f0" } },
      },
    },
  });
}

// Instantiate 3 real-time line charts
const pressureChart = createLineChart(els.pressureCanvas, "kPa", "P calibrada (kPa)", "#3b82f6", "rgba(59,130,246,0.08)");
const o2Chart       = createLineChart(els.o2Canvas, "%", "Pureza O₂ (%)", "#06b6d4", "rgba(6,182,212,0.08)");
const flowChart     = createLineChart(els.flowCanvas, "L/min", "Flujo (L/min)", "#f59e0b", "rgba(245,158,11,0.08)");

// ── Pressure Curve selector ────────────────────────────────────────────────
const CURVE_KEYS = {
  p_calibrated: { key: "p_calibrated_kpa", label: "P calibrada (kPa)", color: "#3b82f6", bg: "rgba(59,130,246,0.08)" },
  p_ema:        { key: "p_ema_kpa",        label: "P EMA (kPa)",       color: "#a855f7", bg: "rgba(168,85,247,0.08)" },
  p_nominal:    { key: "p_nominal_kpa",    label: "P nominal (kPa)",   color: "#10b981", bg: "rgba(16,185,129,0.08)" },
};

function formatTimestamp(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ── Update all 3 charts from single shared history array ──────────────────
function updateCharts(history) {
  if (!history) return;

  const labels = history.map(s => formatTimestamp(s.ts));

  // 1. Update Pressure Chart
  if (pressureChart) {
    const selectedCurve = CURVE_KEYS[els.curveSelect ? els.curveSelect.value : "p_calibrated"] ?? CURVE_KEYS.p_calibrated;
    const pDataset = pressureChart.data.datasets[0];
    pDataset.label = selectedCurve.label;
    pDataset.borderColor = selectedCurve.color;
    pDataset.backgroundColor = selectedCurve.bg;
    pDataset.data = history.map(s => (s[selectedCurve.key] != null ? s[selectedCurve.key] : null));

    pressureChart.data.labels = labels;
    pressureChart.update("none");
  }

  // 2. Update Oxygen Purity Chart (Filter invalid data when oxygen_valid === false)
  if (o2Chart) {
    const o2Dataset = o2Chart.data.datasets[0];
    o2Dataset.data = history.map(s => {
      if (s.oxygen_valid === false || s.o2_pct == null) {
        return null; // Skip invalid O2 samples without inserting false zero drops
      }
      return s.o2_pct;
    });
    o2Chart.data.labels = labels;
    o2Chart.update("none");
  }

  // 3. Update Flow Chart (Independent of oxygen_valid, only null if flow_lpm not available)
  if (flowChart) {
    const flowDataset = flowChart.data.datasets[0];
    flowDataset.data = history.map(s => {
      if (s.flow_lpm == null) {
        return null;
      }
      return s.flow_lpm;
    });
    flowChart.data.labels = labels;
    flowChart.update("none");
  }
}

if (els.curveSelect) {
  els.curveSelect.addEventListener("change", () => {
    if (lastHistory.length) updateCharts(lastHistory);
  });
}

// ── State ──────────────────────────────────────────────────────────────────
let lastHistory = [];

// ── UI update ──────────────────────────────────────────────────────────────
function fmt(v, decimals = 2) {
  return v != null ? Number(v).toFixed(decimals) : "—";
}

function updateUI(latest, history) {
  lastHistory = history;

  const connected = latest?.connected ?? false;
  if (els.status) {
    els.status.textContent = connected ? "Conectado" : "Desconectado";
    els.status.className   = "status-badge " + (connected ? "status-ok" : "status-err");
  }

  if (latest) {
    const o2Valid = latest.oxygen_valid !== false;
    if (els.o2)          els.o2.textContent          = (o2Valid && latest.o2_pct != null) ? fmt(latest.o2_pct, 2) + " %" : "—";
    if (els.flow)        els.flow.textContent        = latest.flow_lpm != null ? fmt(latest.flow_lpm, 2) + " L/min" : "—";
    if (els.temp)        els.temp.textContent        = fmt(latest.temp_c, 1) + " °C";
    if (els.pCalibrated) els.pCalibrated.textContent = fmt(latest.p_calibrated_kpa, 3) + " kPa";
    if (els.vsMpx)       els.vsMpx.textContent       = fmt(latest.vs_mpx_mv, 1) + " mV";
    if (els.pNominal)    els.pNominal.textContent    = fmt(latest.p_nominal_kpa, 3) + " kPa";
  }

  updateCharts(history);
}

// ── Polling ────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const res  = await fetch("/api/telemetry");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    updateUI(json.latest, json.history ?? []);
  } catch (err) {
    if (els.status) {
      els.status.textContent = "Error";
      els.status.className   = "status-badge status-err";
    }
    console.warn("Telemetry poll error:", err);
  }
}

// Start immediately then repeat every 250 ms
poll();
setInterval(poll, POLL_INTERVAL_MS);
