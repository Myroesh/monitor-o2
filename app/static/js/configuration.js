/**
 * configuration.js — Phase 4 (Audited & Firmware-Aligned)
 * Manages device configuration UI, parameter validation, real-time ratio calculations,
 * explicit user confirmation, and REST API communication.
 */

"use strict";

const dom = {
    // Info fields
    infoStatus: document.getElementById("info-status"),
    infoFirmware: document.getElementById("info-firmware"),
    infoUptime: document.getElementById("info-uptime"),
    infoAds1115: document.getElementById("info-ads1115"),
    infoAdsRate: document.getElementById("info-ads-rate"),
    infoVsMpx: document.getElementById("info-vs-mpx"),
    infoCalibOrigin: document.getElementById("info-calib-origin"),
    infoOcsFrames: document.getElementById("info-ocs-frames"),

    // Editable form fields
    inputGain: document.getElementById("input-gain"),
    inputOffset: document.getElementById("input-offset"),
    inputRtopAin0: document.getElementById("input-rtop-ain0"),
    inputRbottomAin0: document.getElementById("input-rbottom-ain0"),
    calcRatioAin0: document.getElementById("calc-ratio-ain0"),
    inputRtopAin1: document.getElementById("input-rtop-ain1"),
    inputRbottomAin1: document.getElementById("input-rbottom-ain1"),
    calcRatioAin1: document.getElementById("calc-ratio-ain1"),

    // Actions & Alert
    btnSaveConfig: document.getElementById("btn-save-config"),
    configAlert: document.getElementById("config-alert"),
};

function formatUptime(seconds) {
    if (seconds == null) return "—";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    let res = "";
    if (d > 0) res += `${d}d `;
    res += `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s (${seconds}s)`;
    return res;
}

function updateCalculatedRatios() {
    const rtop0 = parseFloat(dom.inputRtopAin0.value) || 0;
    const rbottom0 = parseFloat(dom.inputRbottomAin0.value) || 0;
    if (rbottom0 > 0 && (rtop0 + rbottom0) > 0) {
        const ratio0 = rbottom0 / (rtop0 + rbottom0);
        dom.calcRatioAin0.textContent = ratio0.toFixed(6);
    } else {
        dom.calcRatioAin0.textContent = "—";
    }

    const rtop1 = parseFloat(dom.inputRtopAin1.value) || 0;
    const rbottom1 = parseFloat(dom.inputRbottomAin1.value) || 0;
    if (rbottom1 > 0 && (rtop1 + rbottom1) > 0) {
        const ratio1 = rbottom1 / (rtop1 + rbottom1);
        dom.calcRatioAin1.textContent = ratio1.toFixed(6);
    } else {
        dom.calcRatioAin1.textContent = "—";
    }
}

// Recalculate ratios live on input change
[dom.inputRtopAin0, dom.inputRbottomAin0, dom.inputRtopAin1, dom.inputRbottomAin1].forEach(input => {
    input.addEventListener("input", updateCalculatedRatios);
});

function showAlert(message, isError = false) {
    dom.configAlert.textContent = message;
    dom.configAlert.classList.remove("hidden", "alert-info", "alert-danger", "alert-success");
    dom.configAlert.classList.add(isError ? "alert-danger" : "alert-success");
}

async function loadConfig() {
    try {
        const res = await fetch("/api/config");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Render read-only device information
        dom.infoStatus.textContent = data.status || (data.connected ? "Conectado" : "Desconectado");
        dom.infoFirmware.textContent = data.firmware_version || "—";
        dom.infoUptime.textContent = formatUptime(data.uptime_seconds);
        dom.infoAds1115.textContent = `${data.ads1115_status || 'OK'} (${data.ads1115_i2c_address || '0x48'})`;
        dom.infoAdsRate.textContent = data.ads1115_data_rate || "128 SPS";
        dom.infoVsMpx.textContent = `${data.vs_mpx_mv} mV`;
        dom.infoCalibOrigin.textContent = data.calibration_origin || "—";
        dom.infoOcsFrames.textContent = `OK: ${data.ocs3f_frames_ok} / Errores: ${data.ocs3f_frames_error}`;

        // Render editable form fields
        dom.inputGain.value = data.gain;
        dom.inputOffset.value = data.offset;
        dom.inputRtopAin0.value = data.rtop_ain0;
        dom.inputRbottomAin0.value = data.rbottom_ain0;
        dom.inputRtopAin1.value = data.rtop_ain1;
        dom.inputRbottomAin1.value = data.rbottom_ain1;

        updateCalculatedRatios();
    } catch (err) {
        console.error("Error cargando configuración:", err);
        showAlert("Error al cargar la configuración del dispositivo.", true);
    }
}

dom.btnSaveConfig.addEventListener("click", async () => {
    const gain = parseFloat(dom.inputGain.value);
    const offset = parseFloat(dom.inputOffset.value);
    const rtop0 = parseFloat(dom.inputRtopAin0.value);
    const rbottom0 = parseFloat(dom.inputRbottomAin0.value);
    const rtop1 = parseFloat(dom.inputRtopAin1.value);
    const rbottom1 = parseFloat(dom.inputRbottomAin1.value);

    // Client-side format & range validation (aligned with firmware)
    if (isNaN(gain) || gain <= 0.10 || gain >= 10.0) {
        showAlert("GAIN debe estar estrictamente entre 0.10 y 10.0", true);
        return;
    }
    if (isNaN(offset) || offset <= -500.0 || offset >= 500.0) {
        showAlert("OFFSET debe estar estrictamente entre -500.0 y 500.0 kPa", true);
        return;
    }
    if ([rtop0, rbottom0, rtop1, rbottom1].some(r => isNaN(r) || r < 100 || r > 1000000)) {
        showAlert("Las resistencias deben estar entre 100 Ω y 1,000,000 Ω", true);
        return;
    }

    const ratio0 = rbottom0 / (rtop0 + rbottom0);
    const ratio1 = rbottom1 / (rtop1 + rbottom1);

    if (ratio0 <= 0.05 || ratio0 >= 0.95 || ratio1 <= 0.05 || ratio1 >= 0.95) {
        showAlert("Los ratios calculados deben estar estrictamente entre 0.05 y 0.95", true);
        return;
    }

    // Explicit user confirmation prompt required by specification
    const confirmed = window.confirm(
        "Confirmación de Cambios:\n\n" +
        "¿Está seguro de que desea aplicar estos nuevos parámetros a la simulación actual?\n\n" +
        `GAIN: ${gain}\n` +
        `OFFSET: ${offset} kPa\n` +
        `Rtop AIN0: ${rtop0} Ω / Rbottom AIN0: ${rbottom0} Ω (Ratio: ${ratio0.toFixed(6)})\n` +
        `Rtop AIN1: ${rtop1} Ω / Rbottom AIN1: ${rbottom1} Ω (Ratio: ${ratio1.toFixed(6)})`
    );

    if (!confirmed) return;

    const payload = {
        gain: gain,
        offset: offset,
        rtop_ain0: rtop0,
        rbottom_ain0: rbottom0,
        rtop_ain1: rtop1,
        rbottom_ain1: rbottom1,
    };

    try {
        dom.btnSaveConfig.disabled = true;
        const res = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || `HTTP ${res.status}`);
        }

        showAlert("Configuración guardada exitosamente en la simulación.");
        loadConfig();
    } catch (err) {
        showAlert(`Error al guardar configuración: ${err.message}`, true);
    } finally {
        dom.btnSaveConfig.disabled = false;
    }
});

// Initial load
loadConfig();
