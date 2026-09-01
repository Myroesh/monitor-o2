/**
 * calibration.js — Phase 3 & Phase 5 (Audited & Refined)
 * Manages guided calibration wizard, time-window non-blocking sample measurement,
 * results rendering, and real hardware NVS calibration application.
 */

"use strict";

const MMHG_TO_KPA = 0.133322;

const dom = {
    stepper: document.getElementById("calibration-stepper"),
    wizardCard: document.getElementById("wizard-card"),
    wizardStepTitle: document.getElementById("wizard-step-title"),
    wizardStepBadge: document.getElementById("wizard-step-badge"),
    observedInput: document.getElementById("observed-mmhg-input"),
    observedKpaLabel: document.getElementById("observed-kpa-label"),
    btnStartMeasure: document.getElementById("btn-start-measure"),
    measureStatus: document.getElementById("measure-status"),
    measureStatusText: document.getElementById("measure-status-text"),
    statsBox: document.getElementById("stats-box"),
    statMean: document.getElementById("stat-mean"),
    statStd: document.getElementById("stat-std"),
    statMin: document.getElementById("stat-min"),
    statMax: document.getElementById("stat-max"),
    statCount: document.getElementById("stat-count"),
    btnPrevStep: document.getElementById("btn-prev-step"),
    btnRepeatStep: document.getElementById("btn-repeat-step"),
    btnNextStep: document.getElementById("btn-next-step"),
    resultsCard: document.getElementById("results-card"),
    resGain: document.getElementById("res-gain"),
    resOffset: document.getElementById("res-offset"),
    resR2: document.getElementById("res-r2"),
    resMaxError: document.getElementById("res-max-error"),
    resMae: document.getElementById("res-mae"),
    resRepeatability: document.getElementById("res-repeatability"),
    pointsTableBody: document.getElementById("points-table-body"),
    btnRestartCalibration: document.getElementById("btn-restart-calibration"),

    // Apply NVS real hardware elements
    applyNvsContainer: document.getElementById("apply-nvs-container"),
    btnApplyCalibration: document.getElementById("btn-apply-calibration"),
    applyNvsAlert: document.getElementById("apply-nvs-alert"),
    applyNvsVerifiedInfo: document.getElementById("apply-nvs-verified-info"),
    nvsGain: document.getElementById("nvs-gain"),
    nvsOffset: document.getElementById("nvs-offset"),
    nvsRatio0: document.getElementById("nvs-ratio0"),
    nvsRatio1: document.getElementById("nvs-ratio1"),
    nvsOrigin: document.getElementById("nvs-origin"),
};

let currentState = null;
let pollTimer = null;

function startPolling() {
    if (!pollTimer) {
        pollTimer = setInterval(fetchState, 250);
    }
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function fetchState() {
    try {
        const res = await fetch("/api/calibration/state");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        currentState = await res.json();
        render();

        if (currentState && currentState.measuring_step !== null) {
            startPolling();
        } else {
            stopPolling();
        }
    } catch (err) {
        console.error("Error fetching calibration state:", err);
    }
}

function updateObservedKpaLabel() {
    const val = parseFloat(dom.observedInput.value) || 0.0;
    dom.observedKpaLabel.textContent = (val * MMHG_TO_KPA).toFixed(4);
}

dom.observedInput.addEventListener("input", async () => {
    updateObservedKpaLabel();
    if (!currentState) return;
    const curIdx = currentState.current_step;
    const val = parseFloat(dom.observedInput.value) || 0.0;

    try {
        const res = await fetch("/api/calibration/update-point", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ step_index: curIdx, observed_mmhg: val }),
        });
        if (res.ok) {
            currentState = await res.json();
            if (currentState.status === "completed") {
                renderResults();
            }
        }
    } catch (err) {
        console.error("Error updating observed pressure:", err);
    }
});

dom.btnStartMeasure.addEventListener("click", async () => {
    if (!currentState) return;
    const curIdx = currentState.current_step;

    try {
        const res = await fetch("/api/calibration/measure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ step_index: curIdx, target_duration_s: 4.0, min_samples: 10 }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        currentState = await res.json();
        startPolling();
        render();
    } catch (err) {
        console.error("Error starting measurement:", err);
    }
});

dom.btnPrevStep.addEventListener("click", async () => {
    try {
        const res = await fetch("/api/calibration/prev", { method: "POST" });
        if (res.ok) {
            currentState = await res.json();
            render();
        }
    } catch (err) {
        console.error("Error going to previous step:", err);
    }
});

dom.btnRepeatStep.addEventListener("click", async () => {
    if (!currentState) return;
    const curIdx = currentState.current_step;
    try {
        const res = await fetch("/api/calibration/repeat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ step_index: curIdx }),
        });
        if (res.ok) {
            currentState = await res.json();
            render();
        }
    } catch (err) {
        console.error("Error repeating step:", err);
    }
});

dom.btnNextStep.addEventListener("click", async () => {
    try {
        const res = await fetch("/api/calibration/next", { method: "POST" });
        if (res.ok) {
            currentState = await res.json();
            render();
        }
    } catch (err) {
        console.error("Error going to next step:", err);
    }
});

dom.btnRestartCalibration.addEventListener("click", async () => {
    try {
        const res = await fetch("/api/calibration/start", { method: "POST" });
        if (res.ok) {
            currentState = await res.json();
            render();
        }
    } catch (err) {
        console.error("Error restarting calibration:", err);
    }
});

async function repeatPointFromResults(stepIdx) {
    try {
        const res = await fetch("/api/calibration/repeat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ step_index: stepIdx }),
        });
        if (res.ok) {
            currentState = await res.json();
            render();
        }
    } catch (err) {
        console.error("Error repeating point from results:", err);
    }
}

function renderStepper() {
    if (!currentState) return;
    const points = currentState.points;
    const curStep = currentState.current_step;

    dom.stepper.innerHTML = "";
    points.forEach((pt, idx) => {
        const stepEl = document.createElement("div");
        stepEl.className = `stepper-item ${idx === curStep ? "active" : ""} ${pt.status === "completed" ? "completed" : ""}`;
        stepEl.textContent = `${pt.target_mmhg} mmHg`;
        stepEl.addEventListener("click", async () => {
            try {
                const res = await fetch("/api/calibration/repeat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ step_index: idx }),
                });
                if (res.ok) {
                    currentState = await res.json();
                    render();
                }
            } catch (err) {
                console.error("Error switching step via stepper:", err);
            }
        });
        dom.stepper.appendChild(stepEl);
    });
}

function renderWizard() {
    if (!currentState) return;
    const curStep = currentState.current_step;
    const pt = currentState.points[curStep];

    dom.wizardStepTitle.textContent = `Paso ${curStep + 1} de ${currentState.total_steps} — Punto ${pt.target_mmhg} mmHg (${pt.target_kpa} kPa)`;

    if (pt.status === "completed") {
        dom.wizardStepBadge.textContent = "Completado";
        dom.wizardStepBadge.className = "status-badge status-ok";
        dom.measureStatus.classList.add("hidden");
        dom.btnStartMeasure.disabled = false;
    } else if (pt.status === "measuring") {
        const elapsed = (pt.elapsed_seconds || 0.0).toFixed(1);
        const targetDur = (pt.target_duration_seconds || 4.0).toFixed(1);
        const samples = pt.samples_received || 0;
        const freq = (pt.effective_frequency_hz || 0.0).toFixed(1);

        dom.wizardStepBadge.textContent = "Midiendo...";
        dom.wizardStepBadge.className = "status-badge status-warning";
        dom.measureStatus.classList.remove("hidden");
        dom.measureStatusText.textContent = `Capturando... ${elapsed}s / ${targetDur}s (${samples} muestras, ${freq} Hz)`;
        dom.btnStartMeasure.disabled = true;
    } else if (pt.status === "insufficient_samples") {
        dom.wizardStepBadge.textContent = "Captura insuficiente";
        dom.wizardStepBadge.className = "status-badge status-err";
        dom.measureStatus.classList.remove("hidden");
        dom.measureStatusText.textContent = `Error: Tiempo transcurrido sin alcanzar el mínimo de ${pt.min_samples_required || 10} muestras.`;
        dom.btnStartMeasure.disabled = false;
    } else {
        dom.wizardStepBadge.textContent = "Pendiente";
        dom.wizardStepBadge.className = "status-badge status-pending";
        dom.measureStatus.classList.add("hidden");
        dom.btnStartMeasure.disabled = false;
    }

    if (document.activeElement !== dom.observedInput) {
        dom.observedInput.value = pt.observed_mmhg;
        updateObservedKpaLabel();
    }

    if (pt.samples && pt.samples.length > 0) {
        dom.statsBox.classList.remove("hidden");
        dom.statMean.textContent = pt.stats.mean.toFixed(4) + " kPa";
        dom.statStd.textContent = pt.stats.std.toFixed(4) + " kPa";
        dom.statMin.textContent = pt.stats.min.toFixed(4) + " kPa";
        dom.statMax.textContent = pt.stats.max.toFixed(4) + " kPa";
        dom.statCount.textContent = pt.stats.count;
    } else {
        dom.statsBox.classList.add("hidden");
    }

    dom.btnPrevStep.disabled = curStep === 0;
}

async function checkHardwareModeAndShowApplyButton() {
    if (!currentState || currentState.status !== "completed" || !currentState.results) {
        if (dom.applyNvsContainer) dom.applyNvsContainer.classList.add("hidden");
        return;
    }

    try {
        const res = await fetch("/api/config");
        if (!res.ok) return;
        const cfg = await res.json();

        // Show apply container only in real WebSocket mode when ESP32 is connected
        if (cfg.is_simulated === false && cfg.connected) {
            if (dom.applyNvsContainer) dom.applyNvsContainer.classList.remove("hidden");
        } else {
            if (dom.applyNvsContainer) dom.applyNvsContainer.classList.add("hidden");
        }
    } catch (err) {
        console.error("Error comprobando modo de dispositivo:", err);
    }
}

function renderResults() {
    if (!currentState || !currentState.results) {
        dom.resultsCard.classList.add("hidden");
        if (dom.applyNvsContainer) dom.applyNvsContainer.classList.add("hidden");
        return;
    }

    dom.resultsCard.classList.remove("hidden");
    const res = currentState.results;

    dom.resGain.textContent = res.gain.toFixed(6);
    dom.resOffset.textContent = res.offset.toFixed(6) + " kPa";
    dom.resR2.textContent = res.r_squared.toFixed(6);
    dom.resMaxError.textContent = res.max_error.toFixed(6) + " kPa";
    dom.resMae.textContent = res.mean_absolute_error.toFixed(6) + " kPa";
    dom.resRepeatability.textContent = res.repeatability.toFixed(6) + " kPa";

    dom.pointsTableBody.innerHTML = "";
    currentState.points.forEach((pt, idx) => {
        const tr = document.createElement("tr");

        const residualVal = (res.residuals && res.residuals[idx] !== undefined)
            ? res.residuals[idx].toFixed(6) + " kPa"
            : "—";

        tr.innerHTML = `
            <td>Punto ${idx + 1}</td>
            <td>${pt.target_mmhg}</td>
            <td>${pt.observed_mmhg}</td>
            <td>${pt.observed_kpa.toFixed(4)}</td>
            <td>${pt.stats ? pt.stats.mean.toFixed(4) : "—"}</td>
            <td>${residualVal}</td>
            <td>
                <button type="button" class="btn btn-sm btn-warning btn-repeat-pt" data-idx="${idx}">
                    Repetir punto
                </button>
            </td>
        `;
        dom.pointsTableBody.appendChild(tr);
    });

    document.querySelectorAll(".btn-repeat-pt").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const idx = parseInt(e.target.getAttribute("data-idx"), 10);
            repeatPointFromResults(idx);
        });
    });

    checkHardwareModeAndShowApplyButton();
}

if (dom.btnApplyCalibration) {
    dom.btnApplyCalibration.addEventListener("click", async () => {
        if (!currentState || !currentState.results) return;
        const res = currentState.results;

        const confirmed = window.confirm(
            "Confirmar Aplicación de Calibración al ESP32:\n\n" +
            "¿Está seguro de que desea aplicar los siguientes parámetros calculados a la memoria NVS del ESP32?\n\n" +
            `GAIN nuevo: ${res.gain.toFixed(6)}\n` +
            `OFFSET nuevo: ${res.offset.toFixed(6)} kPa\n` +
            `R²: ${res.r_squared.toFixed(6)}\n` +
            `Error Máximo: ${res.max_error.toFixed(6)} kPa\n` +
            `MAE: ${res.mean_absolute_error.toFixed(6)} kPa\n\n` +
            "Las 4 resistencias del divisor de tensión actuales del dispositivo se conservarán intactas."
        );

        if (!confirmed) return;

        try {
            dom.btnApplyCalibration.disabled = true;
            const resp = await fetch("/api/calibration/apply", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });

            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.error || `HTTP ${resp.status}`);
            }

            if (dom.applyNvsAlert) {
                dom.applyNvsAlert.textContent = data.message || "Calibración aplicada y verificada en NVS";
                dom.applyNvsAlert.className = "alert alert-success margin-top-sm";
                dom.applyNvsAlert.classList.remove("hidden");
            }

            const calib = data.calibration || {};
            if (dom.nvsGain) dom.nvsGain.textContent = (calib.gain || res.gain).toFixed(6);
            if (dom.nvsOffset) dom.nvsOffset.textContent = ((calib.offset_kpa || calib.offset || res.offset)).toFixed(6) + " kPa";
            if (dom.nvsRatio0) dom.nvsRatio0.textContent = calib.ratio_ain0 ? calib.ratio_ain0.toFixed(6) : "—";
            if (dom.nvsRatio1) dom.nvsRatio1.textContent = calib.ratio_ain1 ? calib.ratio_ain1.toFixed(6) : "—";
            if (dom.nvsOrigin) dom.nvsOrigin.textContent = calib.origin || "NVS";

            if (dom.applyNvsVerifiedInfo) {
                dom.applyNvsVerifiedInfo.classList.remove("hidden");
            }
        } catch (err) {
            if (dom.applyNvsAlert) {
                dom.applyNvsAlert.textContent = `Error al aplicar calibración: ${err.message}`;
                dom.applyNvsAlert.className = "alert alert-danger margin-top-sm";
                dom.applyNvsAlert.classList.remove("hidden");
            }
        } finally {
            dom.btnApplyCalibration.disabled = false;
        }
    });
}

function render() {
    renderStepper();
    renderWizard();
    renderResults();
}

// Initial fetch on page load
fetchState();
