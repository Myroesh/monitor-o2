/**
 * calibration_history.js — Phase 8
 *
 * Read-only interface for browsing saved calibration sessions and inspecting point details.
 * Consumes GET /api/calibration/history and GET /api/calibration/history/<session_id>.
 */

"use strict";

document.addEventListener("DOMContentLoaded", () => {
    // ── DOM references ─────────────────────────────────────────────────────
    const dom = {
        errorAlert: document.getElementById("history-error-alert"),
        errorMsg: document.getElementById("history-error-msg"),
        btnRetry: document.getElementById("btn-retry-history"),
        emptyState: document.getElementById("history-empty-state"),
        tableContainer: document.getElementById("history-table-container"),
        tableBody: document.getElementById("history-table-body"),
        detailPanel: document.getElementById("history-detail-panel"),
        btnCloseDetail: document.getElementById("btn-close-detail"),

        // Detail elements
        detailSessionId: document.getElementById("detail-session-id"),
        detailFirmware: document.getElementById("detail-firmware"),
        detailCreatedAt: document.getElementById("detail-created-at"),
        detailSavedAt: document.getElementById("detail-saved-at"),
        detailGain: document.getElementById("detail-gain"),
        detailOffset: document.getElementById("detail-offset"),
        detailR2: document.getElementById("detail-r2"),
        detailMaxError: document.getElementById("detail-max-error"),
        detailMae: document.getElementById("detail-mae"),
        detailRepeatability: document.getElementById("detail-repeatability"),
        detailPointsBody: document.getElementById("detail-points-table-body"),
    };

    // ── Helper formatters ──────────────────────────────────────────────────
    function fmt(val, decimals = 6) {
        return val != null && !isNaN(val) ? Number(val).toFixed(decimals) : "—";
    }

    function formatLocalDate(isoString) {
        if (!isoString) return "—";
        try {
            const d = new Date(isoString);
            if (isNaN(d.getTime())) return isoString;
            return d.toLocaleString("es-ES", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            });
        } catch {
            return isoString;
        }
    }

    function formatTimestamp(ts) {
        if (ts == null) return "—";
        try {
            const d = new Date(Number(ts) * 1000);
            if (isNaN(d.getTime())) return String(ts);
            return d.toLocaleTimeString("es-ES", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                fractionalSecondDigits: 3,
            });
        } catch {
            return String(ts);
        }
    }

    // ── Fetch & Render Session List ────────────────────────────────────────
    async function loadHistory() {
        if (dom.errorAlert) dom.errorAlert.classList.add("hidden");
        if (dom.tableContainer) dom.tableContainer.classList.add("hidden");
        if (dom.emptyState) dom.emptyState.classList.add("hidden");

        try {
            const res = await fetch("/api/calibration/history");
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            }
            const sessions = await res.json();
            renderSessionList(sessions);
        } catch (err) {
            if (dom.errorAlert) {
                if (dom.errorMsg) dom.errorMsg.textContent = `Error al cargar historial: ${err.message}`;
                dom.errorAlert.classList.remove("hidden");
            }
        }
    }

    function renderSessionList(sessions) {
        if (!sessions || sessions.length === 0) {
            if (dom.emptyState) dom.emptyState.classList.remove("hidden");
            if (dom.tableContainer) dom.tableContainer.classList.add("hidden");
            return;
        }

        if (dom.emptyState) dom.emptyState.classList.add("hidden");
        if (dom.tableContainer) dom.tableContainer.classList.remove("hidden");

        dom.tableBody.innerHTML = "";
        sessions.forEach((s) => {
            const tr = document.createElement("tr");

            tr.innerHTML = `
                <td>${formatLocalDate(s.saved_at)}</td>
                <td>${s.firmware_version || "—"}</td>
                <td>${fmt(s.gain, 6)}</td>
                <td>${fmt(s.offset_kpa, 6)}</td>
                <td>${fmt(s.r_squared, 6)}</td>
                <td>${fmt(s.max_error_kpa, 6)}</td>
                <td>${fmt(s.mean_absolute_error_kpa, 6)}</td>
                <td>${fmt(s.repeatability_kpa, 6)}</td>
                <td>
                    <button type="button" class="btn btn-sm btn-primary btn-view-detail" data-id="${s.session_id}">
                        Ver detalle
                    </button>
                </td>
            `;

            dom.tableBody.appendChild(tr);
        });

        // Attach event listeners to "Ver detalle" buttons
        document.querySelectorAll(".btn-view-detail").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const sessionId = e.currentTarget.getAttribute("data-id");
                if (sessionId) loadSessionDetail(sessionId);
            });
        });
    }

    // ── Fetch & Render Session Detail ──────────────────────────────────────
    async function loadSessionDetail(sessionId) {
        try {
            const res = await fetch(`/api/calibration/history/${sessionId}`);
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            }
            const detail = await res.json();
            renderSessionDetail(detail);
        } catch (err) {
            alert(`No se pudo cargar el detalle de la sesión: ${err.message}`);
        }
    }

    function renderSessionDetail(detail) {
        if (!detail) return;

        dom.detailSessionId.textContent = detail.session_id || "—";
        dom.detailFirmware.textContent = detail.firmware_version || "—";
        dom.detailCreatedAt.textContent = formatLocalDate(detail.created_at);
        dom.detailSavedAt.textContent = formatLocalDate(detail.saved_at);
        dom.detailGain.textContent = fmt(detail.gain, 6);
        dom.detailOffset.textContent = fmt(detail.offset_kpa, 6) + " kPa";
        dom.detailR2.textContent = fmt(detail.r_squared, 6);
        dom.detailMaxError.textContent = fmt(detail.max_error_kpa, 6) + " kPa";
        dom.detailMae.textContent = fmt(detail.mean_absolute_error_kpa, 6) + " kPa";
        dom.detailRepeatability.textContent = fmt(detail.repeatability_kpa, 6) + " kPa";

        // Points table
        dom.detailPointsBody.innerHTML = "";
        const points = detail.points || [];

        points.forEach((pt) => {
            const tr = document.createElement("tr");

            // Build raw samples table inside <details>
            const samples = pt.samples || [];
            const timestamps = pt.sample_timestamps || [];
            let rawSamplesHtml = "—";

            if (samples.length > 0) {
                let rowsHtml = "";
                samples.forEach((val, idx) => {
                    const ts = timestamps[idx];
                    rowsHtml += `
                        <tr>
                            <td>#${idx + 1}</td>
                            <td>${formatTimestamp(ts)}</td>
                            <td>${fmt(val, 4)}</td>
                        </tr>
                    `;
                });

                rawSamplesHtml = `
                    <details class="raw-samples-details">
                        <summary>Ver muestras crudas (${samples.length})</summary>
                        <div class="raw-samples-table-container margin-top-xs">
                            <table class="table raw-samples-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>Hora</th>
                                        <th>P nominal (kPa)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${rowsHtml}
                                </tbody>
                            </table>
                        </div>
                    </details>
                `;
            }

            tr.innerHTML = `
                <td><strong>Paso ${pt.step_index + 1}</strong></td>
                <td>${fmt(pt.target_mmhg, 1)}</td>
                <td>${fmt(pt.target_kpa, 4)}</td>
                <td>${fmt(pt.observed_mmhg, 1)}</td>
                <td>${fmt(pt.observed_kpa, 4)}</td>
                <td>${fmt(pt.mean_p_nominal_kpa, 4)}</td>
                <td>${fmt(pt.std_p_nominal_kpa, 4)}</td>
                <td>${fmt(pt.min_p_nominal_kpa, 4)}</td>
                <td>${fmt(pt.max_p_nominal_kpa, 4)}</td>
                <td>${pt.sample_count}</td>
                <td>${pt.residual_kpa != null ? fmt(pt.residual_kpa, 6) : "—"}</td>
                <td>${rawSamplesHtml}</td>
            `;

            dom.detailPointsBody.appendChild(tr);
        });

        dom.detailPanel.classList.remove("hidden");
        dom.detailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── Event Handlers ─────────────────────────────────────────────────────
    if (dom.btnRetry) {
        dom.btnRetry.addEventListener("click", loadHistory);
    }

    if (dom.btnCloseDetail) {
        dom.btnCloseDetail.addEventListener("click", () => {
            dom.detailPanel.classList.add("hidden");
        });
    }

    // Initial load
    loadHistory();
});
