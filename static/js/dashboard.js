/**
 * dashboard.js — AI Train Distance Alert Dashboard
 *
 * Structure:
 *   1. Constants & element references
 *   2. Chart initialisation (Chart.js)
 *   3. Data fetching (API polling)
 *   4. DOM update functions
 *   5. Alert system (overlay, sound, browser notifications)
 *   6. History table rendering
 *   7. Simulator control panel
 *   8. Timer management & startup
 */

"use strict";

// ============================================================
// 1. CONSTANTS & ELEMENT REFERENCES
// ============================================================

const MAX_CHART_POINTS = 100;   // keep last N readings on charts
const POLL_CURRENT_MS  = 1000;  // fetch /api/current every 1 second
const POLL_HISTORY_MS  = 5000;  // fetch /api/history every 5 seconds
const POLL_STATS_MS    = 10000; // fetch /api/statistics every 10 seconds

// Dashboard elements
const elDistance     = document.getElementById("val-distance");
const elRisk         = document.getElementById("val-risk");
const elStatus       = document.getElementById("val-status");
const elStatusBadge  = document.getElementById("status-badge");
const elSpeed        = document.getElementById("val-speed");
const elTtc          = document.getElementById("val-ttc");
const elTtcSub       = document.getElementById("ttc-sub");
const elLiveBadge    = document.getElementById("live-badge");
const elSensorStatus = document.getElementById("health-sensor");
const elLastTime     = document.getElementById("health-last-time");
const elBufferSize   = document.getElementById("health-buffer");
const elDbStatus     = document.getElementById("health-db");
const elMlStatus     = document.getElementById("health-ml");
const elTrendBadge   = document.getElementById("ai-trend-badge");

// AI panel elements
const elProxBar   = document.getElementById("bar-proximity");
const elVelBar    = document.getElementById("bar-velocity");
const elAccelBar  = document.getElementById("bar-accel");
const elAnomBar   = document.getElementById("bar-anomaly");
const elProxPct   = document.getElementById("pct-proximity");
const elVelPct    = document.getElementById("pct-velocity");
const elAccelPct  = document.getElementById("pct-accel");
const elAnomPct   = document.getElementById("pct-anomaly");
const elOverallScore = document.getElementById("ai-overall-score");

// Alert elements
const elAlertOverlay = document.getElementById("alert-overlay");
const elAlertToast   = document.getElementById("alert-toast");
const elAlertMsg     = document.getElementById("alert-message");

// Stats elements
const elStatTotal    = document.getElementById("stat-total");
const elStatMinDist  = document.getElementById("stat-min-dist");
const elStatMaxDist  = document.getElementById("stat-max-dist");
const elStatAvgRisk  = document.getElementById("stat-avg-risk");

// History table
const elHistoryBody = document.getElementById("history-tbody");

// Sound button
const elSoundBtn = document.getElementById("sound-btn");

// ============================================================
// 2. CHART INITIALISATION
// ============================================================

const CHART_OPTS_BASE = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,            // disabled for real-time performance
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: "#1a2540",
      titleColor: "#8fa3c8",
      bodyColor: "#e8f0fe",
      borderColor: "#2a3f60",
      borderWidth: 1,
    },
  },
  scales: {
    x: {
      ticks: { color: "#4a6080", maxTicksLimit: 8, font: { size: 10 } },
      grid:  { color: "rgba(42,63,96,0.3)" },
    },
    y: {
      ticks: { color: "#4a6080", font: { size: 10 } },
      grid:  { color: "rgba(42,63,96,0.3)" },
    },
  },
};

function makeGradient(ctx, color1, color2) {
  const g = ctx.createLinearGradient(0, 0, 0, 180);
  g.addColorStop(0, color1);
  g.addColorStop(1, color2);
  return g;
}

// --- Distance chart ---
const ctxDist = document.getElementById("chart-distance").getContext("2d");
const distGradient = makeGradient(ctxDist, "rgba(59,130,246,0.4)", "rgba(59,130,246,0.02)");

const chartDistance = new Chart(ctxDist, {
  type: "line",
  data: {
    labels: [],
    datasets: [{
      data: [],
      borderColor: "#3b82f6",
      backgroundColor: distGradient,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true,
    }],
  },
  options: {
    ...CHART_OPTS_BASE,
    scales: {
      ...CHART_OPTS_BASE.scales,
      y: { ...CHART_OPTS_BASE.scales.y, title: { display: true, text: "cm", color: "#4a6080", font:{size:10} } },
    },
  },
});

// --- Velocity chart ---
const ctxVel = document.getElementById("chart-velocity").getContext("2d");
const velGradient = makeGradient(ctxVel, "rgba(167,139,250,0.4)", "rgba(167,139,250,0.02)");

const chartVelocity = new Chart(ctxVel, {
  type: "line",
  data: {
    labels: [],
    datasets: [{
      data: [],
      borderColor: "#a78bfa",
      backgroundColor: velGradient,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true,
    }],
  },
  options: {
    ...CHART_OPTS_BASE,
    scales: {
      ...CHART_OPTS_BASE.scales,
      y: { ...CHART_OPTS_BASE.scales.y, title: { display: true, text: "cm/s", color: "#4a6080", font:{size:10} } },
    },
  },
});

// --- Risk score chart ---
const ctxRisk = document.getElementById("chart-risk").getContext("2d");
const riskGradient = makeGradient(ctxRisk, "rgba(245,158,11,0.4)", "rgba(245,158,11,0.02)");

const chartRisk = new Chart(ctxRisk, {
  type: "line",
  data: {
    labels: [],
    datasets: [{
      data: [],
      borderColor: "#f59e0b",
      backgroundColor: riskGradient,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true,
    }],
  },
  options: {
    ...CHART_OPTS_BASE,
    scales: {
      ...CHART_OPTS_BASE.scales,
      y: { ...CHART_OPTS_BASE.scales.y, min: 0, max: 100, title: { display: true, text: "0-100", color: "#4a6080", font:{size:10} } },
    },
  },
});

/**
 * Push one data point to a chart, trimming to MAX_CHART_POINTS.
 * Uses chart.update('none') to skip animation for real-time performance.
 */
function pushToChart(chart, label, value) {
  chart.data.labels.push(label);
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > MAX_CHART_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update("none");
}

// ============================================================
// 3. DATA FETCHING
// ============================================================

let lastStatus = "";
let isSoundOn  = false;
let audioCtx   = null;
let timers     = {};

async function fetchCurrent() {
  try {
    const res  = await fetch("/api/current");
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    updateMetricCards(data);
    updateAIPanel(data);
    updateHealthPanel(data);
    updateCharts(data);
    updateAlerts(data);
    setLive(true);
  } catch (e) {
    setLive(false);
    console.warn("fetchCurrent error:", e);
  }
}

async function fetchHistory() {
  try {
    const res  = await fetch("/api/history?limit=50");
    if (!res.ok) throw new Error(res.status);
    const rows = await res.json();
    renderHistoryTable(rows);
  } catch (e) {
    console.warn("fetchHistory error:", e);
  }
}

async function fetchStatistics() {
  try {
    const res   = await fetch("/api/statistics");
    if (!res.ok) throw new Error(res.status);
    const stats = await res.json();
    updateStats(stats);
  } catch (e) {
    console.warn("fetchStatistics error:", e);
  }
}

// ============================================================
// 4. DOM UPDATE FUNCTIONS
// ============================================================

function setLive(online) {
  if (!elLiveBadge) return;
  if (online) {
    elLiveBadge.className = "live-badge";
    elLiveBadge.querySelector(".dot").style.animation = "";
    elLiveBadge.querySelector("span:last-child").textContent = "LIVE";
  } else {
    elLiveBadge.className = "live-badge offline";
    elLiveBadge.querySelector(".dot").style.animation = "none";
    elLiveBadge.querySelector("span:last-child").textContent = "OFFLINE";
  }
}

function updateMetricCards(d) {
  // Distance
  if (elDistance) {
    elDistance.textContent = d.distance !== null ? d.distance.toFixed(1) : "--";
  }

  // Risk score
  if (elRisk) {
    elRisk.textContent = d.risk_score !== null ? d.risk_score.toFixed(0) : "--";
    // Colour the risk value
    elRisk.className = "card-value " + riskClass(d.risk_score);
  }

  // Status
  if (elStatusBadge) {
    const s = (d.status || "NORMAL").toLowerCase();
    elStatusBadge.textContent = d.status || "NORMAL";
    elStatusBadge.className = "status-badge " + s;
  }

  // Approach speed
  if (elSpeed) {
    const v = d.velocity;
    const dir = v < -0.5 ? "▼ Approaching" : v > 0.5 ? "▲ Receding" : "● Stable";
    elSpeed.textContent = v !== null ? Math.abs(v).toFixed(1) : "--";
    const sub = document.getElementById("speed-sub");
    if (sub) sub.textContent = dir;
  }

  // Time to critical
  if (elTtc) {
    const ttc = d.time_to_critical;
    if (ttc === null || ttc === undefined) {
      elTtc.textContent = "—";
      if (elTtcSub) elTtcSub.textContent = "Not approaching";
    } else if (ttc === 0) {
      elTtc.textContent = "NOW";
      if (elTtcSub) elTtcSub.textContent = "At critical distance";
    } else {
      elTtc.textContent = ttc.toFixed(1);
      if (elTtcSub) elTtcSub.textContent = "seconds to critical";
    }
  }
}

function updateAIPanel(d) {
  // Sub-scores
  setBar(elProxBar, elProxPct, d.proximity_risk || 0);
  setBar(elVelBar,  elVelPct,  d.velocity_risk  || 0);
  setBar(elAccelBar, elAccelPct, d.accel_risk   || 0);

  const anomPct = ((d.anomaly_score || 0) * 100).toFixed(1);
  setBar(elAnomBar, elAnomPct, anomPct);

  // Overall score
  if (elOverallScore) {
    elOverallScore.textContent = (d.risk_score || 0).toFixed(0);
    elOverallScore.className = "ai-overall-score " + riskClass(d.risk_score);
  }

  // Trend badge
  if (elTrendBadge) {
    const t = d.trend || "STABLE";
    const icons = { APPROACHING: "▼", RECEDING: "▲", STABLE: "●" };
    elTrendBadge.textContent = (icons[t] || "●") + " " + t;
    elTrendBadge.className = "ai-trend " + t.toLowerCase();
  }
}

function setBar(barEl, pctEl, value) {
  const v = Math.max(0, Math.min(100, parseFloat(value) || 0));
  if (barEl) barEl.style.width = v + "%";
  if (pctEl) pctEl.textContent = v.toFixed(0) + "%";
}

function updateHealthPanel(d) {
  setText(elSensorStatus, d.sensor_status || "--",
    d.sensor_status === "SIMULATED" ? "ok" :
    d.sensor_status === "HARDWARE"  ? "ok" : "bad");
  setText(elLastTime, d.timestamp ? d.timestamp.split("T")[1] : "--", "neutral");
  if (elDbStatus)  setText(elDbStatus, "ACTIVE", "ok");
  if (elMlStatus)  setText(elMlStatus, "ACTIVE", "ok");
  if (elBufferSize) elBufferSize.textContent = d.buffer_size || "--";
}

function setText(el, text, cls) {
  if (!el) return;
  el.textContent = text;
  el.className   = "health-val " + (cls || "neutral");
}

function updateCharts(d) {
  const label = d.timestamp ? d.timestamp.split("T")[1] : "";
  pushToChart(chartDistance, label, d.distance);
  pushToChart(chartVelocity, label, d.velocity);
  pushToChart(chartRisk,     label, d.risk_score);
}

function updateStats(s) {
  if (elStatTotal)   elStatTotal.textContent   = s.total_readings || 0;
  if (elStatMinDist) elStatMinDist.textContent = (s.min_distance || 0).toFixed(1) + " cm";
  if (elStatMaxDist) elStatMaxDist.textContent = (s.max_distance || 0).toFixed(1) + " cm";
  if (elStatAvgRisk) elStatAvgRisk.textContent = (s.avg_risk_score || 0).toFixed(1);
}

function riskClass(score) {
  if (score >= 80) return "text-critical";
  if (score >= 60) return "text-warning";
  if (score >= 40) return "text-caution";
  return "text-normal";
}

// ============================================================
// 5. ALERT SYSTEM
// ============================================================

function updateAlerts(d) {
  const status = (d.status || "NORMAL").toUpperCase();
  const isCritical = (status === "CRITICAL");

  // Visual overlay
  if (elAlertOverlay) {
    elAlertOverlay.classList.toggle("active", isCritical);
  }

  // Toast notification on status change
  if (status !== lastStatus && (status === "CRITICAL" || status === "WARNING")) {
    showToast(
      status === "CRITICAL"
        ? `🚨 CRITICAL — Object at ${(d.distance || 0).toFixed(1)} cm!`
        : `⚠️ WARNING — Risk score ${(d.risk_score || 0).toFixed(0)}/100`
    );
    sendBrowserNotification(status, d);
    if (isSoundOn) playAlertSound(status);
  }

  lastStatus = status;
}

function showToast(message) {
  if (!elAlertToast || !elAlertMsg) return;
  elAlertMsg.textContent = message;
  elAlertToast.classList.add("show");
  clearTimeout(elAlertToast._hideTimer);
  elAlertToast._hideTimer = setTimeout(() => {
    elAlertToast.classList.remove("show");
  }, 5000);
}

function sendBrowserNotification(status, d) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  new Notification("AI Train Alert — " + status, {
    body: `Distance: ${(d.distance || 0).toFixed(1)} cm | Risk: ${(d.risk_score || 0).toFixed(0)}/100`,
    icon: "/static/favicon.ico",
  });
}

function requestNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function playAlertSound(status) {
  // Web Audio API — no autoplay restrictions since user triggered sound toggle
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc  = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    osc.type      = "sine";
    osc.frequency.value = status === "CRITICAL" ? 880 : 660;
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.6);

    osc.start();
    osc.stop(audioCtx.currentTime + 0.6);
  } catch (e) {
    console.warn("Audio error:", e);
  }
}

// ============================================================
// 6. HISTORY TABLE
// ============================================================

function renderHistoryTable(rows) {
  if (!elHistoryBody) return;
  if (!rows || rows.length === 0) {
    elHistoryBody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:24px">No readings yet</td></tr>';
    return;
  }

  const html = rows.map(r => {
    const s = (r.status || "NORMAL").toLowerCase();
    const ts = r.timestamp ? r.timestamp.replace("T", " ") : "--";
    return `<tr>
      <td>${ts}</td>
      <td>${(r.distance || 0).toFixed(1)}</td>
      <td>${(r.velocity || 0).toFixed(2)}</td>
      <td>${(r.acceleration || 0).toFixed(3)}</td>
      <td>${(r.risk_score || 0).toFixed(1)}</td>
      <td>${(r.anomaly_score || 0).toFixed(3)}</td>
      <td><span class="tbl-badge ${s}">${r.status || "NORMAL"}</span></td>
      <td>${r.sensor_mode || "--"}</td>
    </tr>`;
  }).join("");

  elHistoryBody.innerHTML = html;
}

// ============================================================
// 7. SIMULATOR CONTROLS (MOCK MODE ONLY)
// ============================================================

async function simControl(action, extra = {}) {
  try {
    await fetch("/api/simulator/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...extra }),
    });
  } catch (e) {
    console.warn("Simulator control error:", e);
  }
}

function initSimulatorPanel() {
  const panel = document.getElementById("simulator-panel");
  if (!panel) return;   // not in mock mode

  // Scenario buttons
  document.querySelectorAll(".scen-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".scen-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      simControl("set_scenario", { scenario: btn.dataset.scenario });
    });
  });

  // Speed slider
  const speedSlider = document.getElementById("speed-slider");
  const speedVal    = document.getElementById("speed-display");
  if (speedSlider) {
    speedSlider.addEventListener("input", () => {
      const v = parseFloat(speedSlider.value);
      if (speedVal) speedVal.textContent = v.toFixed(1) + "×";
      simControl("set_speed", { speed: v });
    });
  }

  // Distance input + set button
  const distInput = document.getElementById("start-distance");
  const distBtn   = document.getElementById("btn-set-distance");
  if (distBtn) {
    distBtn.addEventListener("click", () => {
      const d = parseFloat(distInput?.value || 100);
      simControl("set_distance", { distance: d });
    });
  }

  // Pause / resume / reset buttons
  document.getElementById("btn-pause")?.addEventListener("click",  () => simControl("pause"));
  document.getElementById("btn-resume")?.addEventListener("click", () => simControl("resume"));
  document.getElementById("btn-reset")?.addEventListener("click",  () => simControl("reset"));
}

// ============================================================
// 8. TIMER MANAGEMENT & STARTUP
// ============================================================

function startPolling() {
  // Clear any existing timers to prevent duplicates
  Object.values(timers).forEach(id => clearInterval(id));

  fetchCurrent();
  fetchHistory();
  fetchStatistics();

  timers.current    = setInterval(fetchCurrent,    POLL_CURRENT_MS);
  timers.history    = setInterval(fetchHistory,    POLL_HISTORY_MS);
  timers.statistics = setInterval(fetchStatistics, POLL_STATS_MS);
}

function stopPolling() {
  Object.values(timers).forEach(id => clearInterval(id));
  timers = {};
}

// Pause polling when the browser tab is hidden (save resources)
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopPolling();
  else startPolling();
});

// Sound toggle button
if (elSoundBtn) {
  elSoundBtn.addEventListener("click", () => {
    isSoundOn = !isSoundOn;
    elSoundBtn.textContent = isSoundOn ? "🔊 Sound ON" : "🔇 Sound OFF";
    elSoundBtn.className   = "sound-btn " + (isSoundOn ? "on" : "");
    if (isSoundOn) {
      // Initialise AudioContext on user gesture (required by browsers)
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtx.resume();
      requestNotificationPermission();
    }
  });
}

// Close toast on click
if (elAlertToast) {
  elAlertToast.addEventListener("click", () => {
    elAlertToast.classList.remove("show");
  });
}

// Refresh history table manually
document.getElementById("btn-refresh-history")?.addEventListener("click", fetchHistory);

// CSV export — just navigate to the endpoint
document.getElementById("btn-export-csv")?.addEventListener("click", () => {
  window.location.href = "/api/export/csv?limit=500";
});

// Initialise everything
initSimulatorPanel();
startPolling();

console.log("AI Train Distance Alert Dashboard — initialised ✓");
