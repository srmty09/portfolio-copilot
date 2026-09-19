const API_BASE = "http://localhost:8000";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showAlert(el, message) {
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
}

function hideAlert(el) {
  if (!el) return;
  el.textContent = "";
  el.classList.remove("visible");
}

// Small, deliberately non-exhaustive markdown renderer for the agent's report text
// (headings, bold/italic, bullet lists, tables, paragraphs -- the subset it actually
// uses). Escapes first, then only ever wraps already-escaped text in known-safe tags.
function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  let html = "";
  let inList = false;
  let tableRows = [];

  function inline(s) {
    return s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>");
  }

  function flushList() {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  }

  function flushTable() {
    if (!tableRows.length) return;
    html += '<table class="report-table">';
    tableRows.forEach((cells, i) => {
      const tag = i === 0 ? "th" : "td";
      html += "<tr>" + cells.map((c) => "<" + tag + ">" + inline(c.trim()) + "</" + tag + ">").join("") + "</tr>";
    });
    html += "</table>";
    tableRows = [];
  }

  lines.forEach((line) => {
    if (/^\s*\|.*\|\s*$/.test(line)) {
      if (/^[\s|:-]+$/.test(line)) return; // separator row, e.g. |---|---|
      const cells = line.trim().replace(/^\||\|$/g, "").split("|");
      tableRows.push(cells);
      return;
    }
    flushTable();

    if (/^###\s+/.test(line)) {
      flushList();
      html += "<h4>" + inline(line.replace(/^###\s+/, "")) + "</h4>";
      return;
    }
    if (/^##\s+/.test(line)) {
      flushList();
      html += "<h3>" + inline(line.replace(/^##\s+/, "")) + "</h3>";
      return;
    }
    if (/^#\s+/.test(line)) {
      flushList();
      html += "<h2>" + inline(line.replace(/^#\s+/, "")) + "</h2>";
      return;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += "<li>" + inline(line.replace(/^\s*[-*]\s+/, "")) + "</li>";
      return;
    }
    flushList();

    if (line.trim() !== "") {
      html += "<p>" + inline(line) + "</p>";
    }
  });
  flushList();
  flushTable();
  return html;
}

function getToken() {
  return localStorage.getItem("token");
}

function setToken(token) {
  localStorage.setItem("token", token);
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: "Bearer " + token } : {};
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers, authHeaders());
  const response = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Request failed with status " + response.status);
  }
  if (response.status === 204) return null;
  return response.json();
}

// --- index.html: register / login ---

const registerForm = document.getElementById("register-form");
const loginForm = document.getElementById("login-form");
const tabLogin = document.getElementById("tab-login");
const tabRegister = document.getElementById("tab-register");
const authMessage = document.getElementById("auth-message");

if (tabLogin && tabRegister) {
  tabLogin.addEventListener("click", () => {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    loginForm.style.display = "";
    registerForm.style.display = "none";
    hideAlert(authMessage);
  });
  tabRegister.addEventListener("click", () => {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    registerForm.style.display = "";
    loginForm.style.display = "none";
    hideAlert(authMessage);
  });
}

if (registerForm) {
  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("register-email").value;
    const password = document.getElementById("register-password").value;
    try {
      const data = await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(data.access_token);
      window.location.href = "dashboard.html";
    } catch (err) {
      showAlert(authMessage, err.message);
    }
  });
}

if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("login-email").value;
    const password = document.getElementById("login-password").value;
    try {
      const data = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(data.access_token);
      window.location.href = "dashboard.html";
    } catch (err) {
      showAlert(authMessage, err.message);
    }
  });
}

// --- index.html: Google sign-in ---

const googleLoginLink = document.getElementById("google-login-link");
if (googleLoginLink) {
  googleLoginLink.href = API_BASE + "/auth/google/login";
}

if (window.location.search.includes("oauth_error")) {
  showAlert(authMessage, "Google sign-in failed. Please try again or use email/password.");
}

// --- index.html: forgot password ---

const forgotPasswordLink = document.getElementById("forgot-password-link");
const backToLoginLink = document.getElementById("back-to-login-link");
const forgotPasswordForm = document.getElementById("forgot-password-form");
const authTabs = document.getElementById("auth-tabs");
const authSuccess = document.getElementById("auth-success");

function showForgotPasswordForm() {
  hideAlert(authMessage);
  hideAlert(authSuccess);
  if (authTabs) authTabs.style.display = "none";
  loginForm.style.display = "none";
  registerForm.style.display = "none";
  forgotPasswordForm.style.display = "";
}

function showLoginForm() {
  hideAlert(authMessage);
  hideAlert(authSuccess);
  if (authTabs) authTabs.style.display = "";
  forgotPasswordForm.style.display = "none";
  registerForm.style.display = "none";
  loginForm.style.display = "";
  tabLogin.classList.add("active");
  tabRegister.classList.remove("active");
}

if (forgotPasswordLink) {
  forgotPasswordLink.addEventListener("click", (event) => {
    event.preventDefault();
    showForgotPasswordForm();
  });
}
if (backToLoginLink) {
  backToLoginLink.addEventListener("click", (event) => {
    event.preventDefault();
    showLoginForm();
  });
}
if (forgotPasswordForm) {
  forgotPasswordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("forgot-email").value;
    hideAlert(authMessage);
    try {
      const data = await apiFetch("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      showAlert(authSuccess, data.message);
      forgotPasswordForm.reset();
    } catch (err) {
      showAlert(authMessage, err.message);
    }
  });
}

// --- oauth-callback.html: read the token out of the URL fragment ---

if (document.getElementById("oauth-status")) {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = hashParams.get("token");
  if (token) {
    setToken(token);
    window.location.href = "dashboard.html";
  } else {
    window.location.href = "index.html?oauth_error=1";
  }
}

// --- reset-password.html ---

const resetPasswordForm = document.getElementById("reset-password-form");
if (resetPasswordForm) {
  const resetToken = new URLSearchParams(window.location.search).get("token");
  const resetError = document.getElementById("reset-error");
  const resetSuccess = document.getElementById("reset-success");

  if (!resetToken) {
    showAlert(resetError, "This link is missing its reset token. Request a new one from the login page.");
    resetPasswordForm.style.display = "none";
  }

  resetPasswordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const newPassword = document.getElementById("reset-new-password").value;
    hideAlert(resetError);
    try {
      const data = await apiFetch("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token: resetToken, new_password: newPassword }),
      });
      showAlert(resetSuccess, data.message + " Redirecting to login...");
      resetPasswordForm.style.display = "none";
      setTimeout(() => {
        window.location.href = "index.html";
      }, 2000);
    } catch (err) {
      showAlert(resetError, err.message);
    }
  });
}

// --- dashboard.html: holdings + analysis ---

const logoutButton = document.getElementById("logout-button");
if (logoutButton) {
  logoutButton.addEventListener("click", () => {
    localStorage.removeItem("token");
    window.location.href = "index.html";
  });
}

const holdingForm = document.getElementById("holding-form");
const holdingError = document.getElementById("holding-error");
if (holdingForm) {
  holdingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const ticker = document.getElementById("holding-ticker").value;
    const shares = parseFloat(document.getElementById("holding-shares").value);
    try {
      await apiFetch("/holdings", {
        method: "POST",
        body: JSON.stringify({ ticker, shares }),
      });
      hideAlert(holdingError);
      holdingForm.reset();
      await loadHoldings();
    } catch (err) {
      showAlert(holdingError, err.message);
    }
  });
}

async function loadHoldings() {
  const holdings = await apiFetch("/holdings");
  const body = document.getElementById("holdings-body");
  const empty = document.getElementById("holdings-empty");
  body.innerHTML = "";
  if (empty) empty.style.display = holdings.length ? "none" : "block";
  holdings.forEach((holding) => {
    const row = document.createElement("tr");
    row.innerHTML =
      "<td><span class=\"ticker-chip\">" + escapeHtml(holding.ticker) + "</span></td>" +
      "<td>" + holding.shares + "</td>" +
      "<td>" + new Date(holding.added_at).toLocaleDateString() + "</td>" +
      "<td><button type=\"button\" data-id=\"" + holding.id + "\" class=\"btn-danger delete-holding\">Remove</button></td>";
    body.appendChild(row);
  });
  document.querySelectorAll(".delete-holding").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!confirm("Remove this holding?")) return;
      await apiFetch("/holdings/" + button.dataset.id, { method: "DELETE" });
      await loadHoldings();
    });
  });
}

// --- charts (hand-rolled SVG, no external charting library) ---

const CHART_COLORS = {
  categorical: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  ink: "#0b0b0b",
  inkSecondary: "#52514e",
  muted: "#898781",
  gridline: "#e1e0d9",
  axis: "#c3c2b7",
  volatilityHue: "#2a78d6",
  riskContributionHue: "#eb6834",
  gain: "#2a78d6",
  loss: "#e34948",
};

function niceAxisMax(rawMax) {
  if (!isFinite(rawMax) || rawMax <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const normalized = rawMax / magnitude;
  let niceNormalized;
  if (normalized <= 1) niceNormalized = 1;
  else if (normalized <= 2) niceNormalized = 2;
  else if (normalized <= 5) niceNormalized = 5;
  else niceNormalized = 10;
  return niceNormalized * magnitude;
}

function roundedTopBarPath(x, yTop, width, yBottom, radius) {
  const r = Math.max(0, Math.min(radius, width / 2, yBottom - yTop));
  return (
    "M" + x + "," + yBottom +
    " L" + x + "," + (yTop + r) +
    " Q" + x + "," + yTop + " " + (x + r) + "," + yTop +
    " L" + (x + width - r) + "," + yTop +
    " Q" + (x + width) + "," + yTop + " " + (x + width) + "," + (yTop + r) +
    " L" + (x + width) + "," + yBottom +
    " Z"
  );
}

function isDarkFill(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance < 0.55;
}

// Single-hue column chart comparing one metric across tickers (magnitude, not identity,
// so one hue is correct here — the axis labels already carry ticker identity).
function buildColumnChart(tickers, values, color, unit) {
  const width = 560;
  const height = 220;
  const marginTop = 24;
  const marginRight = 16;
  const marginBottom = 36;
  const marginLeft = 44;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const plotBottom = marginTop + plotHeight;

  const axisMax = niceAxisMax(Math.max(...values, 0.0001));
  const steps = 4;
  const slotWidth = plotWidth / tickers.length;
  const barWidth = Math.min(24, slotWidth * 0.5);

  let gridlines = "";
  for (let i = 0; i <= steps; i++) {
    const val = (axisMax / steps) * i;
    const y = plotBottom - (val / axisMax) * plotHeight;
    gridlines +=
      '<line x1="' + marginLeft + '" y1="' + y + '" x2="' + (marginLeft + plotWidth) + '" y2="' + y +
      '" stroke="' + (i === 0 ? CHART_COLORS.axis : CHART_COLORS.gridline) + '" stroke-width="1"/>';
    gridlines +=
      '<text x="' + (marginLeft - 8) + '" y="' + (y + 3) + '" text-anchor="end" font-size="10" fill="' +
      CHART_COLORS.muted + '">' + Math.round(val) + "</text>";
  }

  let bars = "";
  tickers.forEach((ticker, i) => {
    const value = values[i];
    const x = marginLeft + slotWidth * i + (slotWidth - barWidth) / 2;
    const barTop = plotBottom - (value / axisMax) * plotHeight;
    bars +=
      '<path d="' + roundedTopBarPath(x, barTop, barWidth, plotBottom, 4) + '" fill="' + color + '">' +
      "<title>" + escapeHtml(ticker) + ": " + value + unit + "</title></path>";
    bars +=
      '<text x="' + (x + barWidth / 2) + '" y="' + (barTop - 6) + '" text-anchor="middle" font-size="11" fill="' +
      CHART_COLORS.ink + '">' + value + unit + "</text>";
    bars +=
      '<text x="' + (x + barWidth / 2) + '" y="' + (plotBottom + 16) + '" text-anchor="middle" font-size="11" fill="' +
      CHART_COLORS.inkSecondary + '">' + escapeHtml(ticker) + "</text>";
  });

  return (
    '<svg viewBox="0 0 ' + width + " " + height + '" xmlns="http://www.w3.org/2000/svg">' + gridlines + bars + "</svg>"
  );
}

// Part-to-whole -> a single stacked bar, not a pie (pies read poorly for comparing close values).
function buildAllocationChart(tickers, allocation, valuesUsd) {
  const width = 560;
  const barHeight = 28;
  const y = 8;
  const total = tickers.reduce((sum, t) => sum + allocation[t], 0) || 1;

  let segments = "";
  let legend = "";
  let cumX = 0;
  tickers.forEach((ticker, i) => {
    const color = CHART_COLORS.categorical[i % CHART_COLORS.categorical.length];
    const share = allocation[ticker] / total;
    const segWidth = share * width;
    const inset = segWidth > 4 ? 1 : 0;
    const rectX = cumX + inset;
    const rectWidth = Math.max(0, segWidth - inset * 2);

    segments +=
      '<rect x="' + rectX + '" y="' + y + '" width="' + rectWidth + '" height="' + barHeight +
      '" rx="3" fill="' + color + '"><title>' + escapeHtml(ticker) + ": " + allocation[ticker] + "% ($" +
      valuesUsd[ticker].toLocaleString() + ")</title></rect>";

    const label = escapeHtml(ticker) + " " + Math.round(allocation[ticker]) + "%";
    const approxLabelWidth = label.length * 6.5;
    if (rectWidth >= approxLabelWidth + 8) {
      const textColor = isDarkFill(color) ? "#ffffff" : "#0b0b0b";
      segments +=
        '<text x="' + (rectX + rectWidth / 2) + '" y="' + (y + barHeight / 2 + 4) +
        '" text-anchor="middle" font-size="11" fill="' + textColor + '">' + label + "</text>";
    }

    legend +=
      '<div><span class="swatch" style="background:' + color + '"></span>' + escapeHtml(ticker) + " — $" +
      valuesUsd[ticker].toLocaleString() + " (" + allocation[ticker] + "%)</div>";

    cumX += segWidth;
  });

  const svg =
    '<svg viewBox="0 0 ' + width + " " + (barHeight + 16) + '" xmlns="http://www.w3.org/2000/svg">' + segments +
    "</svg>";
  return { svg: svg, legend: legend };
}

// Above/below a baseline (0% return) -> diverging color, not a single hue.
function buildHistogram(returns, var95) {
  const width = 560;
  const height = 220;
  const marginTop = 28;
  const marginRight = 16;
  const marginBottom = 32;
  const marginLeft = 44;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const plotBottom = marginTop + plotHeight;

  const minVal = Math.min(...returns);
  const maxVal = Math.max(...returns);
  const binCount = 24;
  const binSize = (maxVal - minVal) / binCount || 1;
  const counts = new Array(binCount).fill(0);
  returns.forEach((value) => {
    let idx = Math.floor((value - minVal) / binSize);
    if (idx >= binCount) idx = binCount - 1;
    if (idx < 0) idx = 0;
    counts[idx]++;
  });

  const axisMaxCount = niceAxisMax(Math.max(...counts, 1));
  const xScale = (value) => marginLeft + ((value - minVal) / (maxVal - minVal || 1)) * plotWidth;

  let bars = "";
  for (let i = 0; i < binCount; i++) {
    const binStart = minVal + i * binSize;
    const binEnd = binStart + binSize;
    const midpoint = (binStart + binEnd) / 2;
    const color = midpoint < 0 ? CHART_COLORS.loss : CHART_COLORS.gain;
    const x = xScale(binStart) + 1;
    const barWidth = Math.max(0, xScale(binEnd) - xScale(binStart) - 2);
    const barTop = plotBottom - (counts[i] / axisMaxCount) * plotHeight;
    bars +=
      '<rect x="' + x + '" y="' + barTop + '" width="' + barWidth + '" height="' + (plotBottom - barTop) +
      '" rx="2" fill="' + color + '"><title>' + binStart.toFixed(1) + "% to " + binEnd.toFixed(1) + "%: " +
      counts[i] + " paths</title></rect>";
  }

  const zeroX = xScale(0);
  const varX = xScale(-var95);

  const axisLine =
    '<line x1="' + marginLeft + '" y1="' + plotBottom + '" x2="' + (marginLeft + plotWidth) + '" y2="' + plotBottom +
    '" stroke="' + CHART_COLORS.axis + '" stroke-width="1"/>';
  const zeroLine =
    zeroX >= marginLeft && zeroX <= marginLeft + plotWidth
      ? '<line x1="' + zeroX + '" y1="' + marginTop + '" x2="' + zeroX + '" y2="' + plotBottom + '" stroke="' +
        CHART_COLORS.gridline + '" stroke-width="1"/>'
      : "";
  const varLine =
    '<line x1="' + varX + '" y1="' + marginTop + '" x2="' + varX + '" y2="' + plotBottom + '" stroke="' +
    CHART_COLORS.ink + '" stroke-width="1.5" stroke-dasharray="4,3"/>' +
    '<text x="' + varX + '" y="' + (marginTop - 8) + '" text-anchor="middle" font-size="11" fill="' +
    CHART_COLORS.ink + '">95% VaR: -' + var95 + "%</text>";

  const minLabel =
    '<text x="' + marginLeft + '" y="' + (plotBottom + 18) + '" text-anchor="start" font-size="10" fill="' +
    CHART_COLORS.muted + '">' + minVal.toFixed(1) + "%</text>";
  const maxLabel =
    '<text x="' + (marginLeft + plotWidth) + '" y="' + (plotBottom + 18) + '" text-anchor="end" font-size="10" fill="' +
    CHART_COLORS.muted + '">' + maxVal.toFixed(1) + "%</text>";

  return (
    '<svg viewBox="0 0 ' + width + " " + height + '" xmlns="http://www.w3.org/2000/svg">' + axisLine + zeroLine +
    bars + varLine + minLabel + maxLabel + "</svg>"
  );
}

function renderCharts(riskData) {
  const section = document.getElementById("charts-section");
  if (!section || !riskData || !riskData.volatilities) return;

  const tickers = Object.keys(riskData.volatilities);

  const allocationResult = buildAllocationChart(tickers, riskData.allocation, riskData.values_usd);
  document.getElementById("chart-allocation").innerHTML = allocationResult.svg;
  document.getElementById("allocation-legend").innerHTML = allocationResult.legend;

  document.getElementById("chart-volatility").innerHTML = buildColumnChart(
    tickers,
    tickers.map((t) => riskData.volatilities[t]),
    CHART_COLORS.volatilityHue,
    "%"
  );

  document.getElementById("chart-risk-contribution").innerHTML = buildColumnChart(
    tickers,
    tickers.map((t) => riskData.risk_contributions[t]),
    CHART_COLORS.riskContributionHue,
    "%"
  );

  if (riskData.simulated_returns_pct && riskData.simulated_returns_pct.length) {
    document.getElementById("chart-distribution").innerHTML = buildHistogram(
      riskData.simulated_returns_pct,
      riskData.var_95
    );
  }

  const tableBody = document.getElementById("risk-data-body");
  tableBody.innerHTML = "";
  tickers.forEach((ticker) => {
    const row = document.createElement("tr");
    row.innerHTML =
      "<td>" + escapeHtml(ticker) + "</td>" +
      "<td>" + riskData.allocation[ticker] + "%</td>" +
      "<td>" + riskData.volatilities[ticker] + "%</td>" +
      "<td>" + riskData.risk_contributions[ticker] + "%</td>";
    tableBody.appendChild(row);
  });

  renderVolatilityComparison(tickers, riskData.volatility_estimates || {}, riskData.volatility_source || {});

  section.style.display = "block";
}

function renderVolatilityComparison(tickers, estimates, usedSource) {
  const tbody = document.getElementById("volatility-comparison-body");
  if (!tbody) return;

  function cell(ticker, method) {
    const value = (estimates[ticker] || {})[method];
    const text = value === null || value === undefined ? "—" : value + "%";
    return usedSource[ticker] === method ? "<strong>" + text + " *</strong>" : text;
  }

  tbody.innerHTML = "";
  tickers.forEach((ticker) => {
    const row = document.createElement("tr");
    row.innerHTML =
      "<td>" + escapeHtml(ticker) + "</td>" +
      "<td>" + cell(ticker, "historical") + "</td>" +
      "<td>" + cell(ticker, "garch") + "</td>" +
      "<td>" + cell(ticker, "lstm") + "</td>";
    tbody.appendChild(row);
  });
}

function renderReport(report) {
  document.getElementById("report-placeholder").style.display = "none";
  document.getElementById("report-section").style.display = "block";
  document.getElementById("stat-var").textContent = report.var_95 + "%";
  document.getElementById("stat-risk-score").textContent = report.risk_score;
  document.getElementById("report-output").innerHTML = renderMarkdown(report.report_text);

  document.querySelectorAll("#reports-list li").forEach((li) => {
    li.classList.toggle("active", Number(li.dataset.id) === report.id);
  });

  renderCharts(report.risk_data);
}

async function loadReports() {
  const list = document.getElementById("reports-list");
  if (!list) return;
  const empty = document.getElementById("reports-empty");
  const reports = await apiFetch("/reports");
  list.innerHTML = "";
  if (empty) empty.style.display = reports.length ? "none" : "block";
  reports.forEach((report) => {
    const item = document.createElement("li");
    item.dataset.id = report.id;
    item.innerHTML =
      '<span class="report-date">' + new Date(report.created_at).toLocaleString() + "</span>" +
      '<span class="report-var">VaR ' + report.var_95 + "%</span>";
    item.addEventListener("click", async () => {
      // The list response is a lightweight summary (no report_text/risk_data,
      // which would be unbounded growth across many reports) -- fetch the full
      // report on demand when the user actually wants to view one.
      try {
        const full = await apiFetch("/reports/" + report.id);
        renderReport(full);
      } catch (err) {
        showAlert(document.getElementById("analyze-error"), err.message);
      }
    });
    list.appendChild(item);
  });
}

const analyzeButton = document.getElementById("analyze-button");
if (analyzeButton) {
  analyzeButton.addEventListener("click", async () => {
    const statusEl = document.getElementById("analyze-status");
    const spinnerEl = document.getElementById("analyze-spinner");
    const errorEl = document.getElementById("analyze-error");
    statusEl.textContent = "Analyzing... this can take up to a minute.";
    spinnerEl.classList.add("visible");
    hideAlert(errorEl);
    analyzeButton.disabled = true;
    try {
      const report = await apiFetch("/analyze", { method: "POST" });
      statusEl.textContent = "";
      renderReport(report);
      await loadReports();
    } catch (err) {
      statusEl.textContent = "";
      showAlert(errorEl, err.message);
    } finally {
      spinnerEl.classList.remove("visible");
      analyzeButton.disabled = false;
    }
  });
}

const askForm = document.getElementById("ask-form");
if (askForm) {
  askForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = document.getElementById("ask-input").value;
    const errorEl = document.getElementById("ask-error");
    const spinnerEl = document.getElementById("ask-spinner");
    const answerEl = document.getElementById("ask-answer");
    const submitButton = askForm.querySelector("button[type=submit]");
    hideAlert(errorEl);
    answerEl.innerHTML = "";
    spinnerEl.classList.add("visible");
    submitButton.disabled = true;
    try {
      const data = await apiFetch("/analyze/ask", {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      answerEl.innerHTML = renderMarkdown(data.answer);
    } catch (err) {
      showAlert(errorEl, err.message);
    } finally {
      spinnerEl.classList.remove("visible");
      submitButton.disabled = false;
    }
  });
}

const backtestButton = document.getElementById("backtest-button");
if (backtestButton) {
  backtestButton.addEventListener("click", async () => {
    const resultEl = document.getElementById("backtest-result");
    backtestButton.disabled = true;
    resultEl.style.display = "block";
    resultEl.innerHTML = '<p class="empty-state">Checking past reports against actual outcomes...</p>';
    try {
      const data = await apiFetch("/reports/backtest");
      if (!data.eligible_reports) {
        resultEl.innerHTML =
          '<p class="empty-state">' +
          escapeHtml(data.message || "No reports are old enough to backtest yet.") +
          "</p>";
      } else {
        resultEl.innerHTML =
          '<div class="stat-row">' +
          '<div class="stat-tile"><div class="stat-label">Breach rate</div><div class="stat-value">' +
          data.breach_rate +
          "%</div></div>" +
          '<div class="stat-tile"><div class="stat-label">Expected (~)</div><div class="stat-value">' +
          data.expected_rate +
          "%</div></div>" +
          '<div class="stat-tile"><div class="stat-label">Reports checked</div><div class="stat-value">' +
          data.eligible_reports +
          "</div></div>" +
          "</div>";
      }
    } catch (err) {
      resultEl.innerHTML = '<p class="alert alert-error visible">' + escapeHtml(err.message) + "</p>";
    } finally {
      backtestButton.disabled = false;
    }
  });
}

if (document.getElementById("holdings-body")) {
  if (!getToken()) {
    window.location.href = "index.html";
  } else {
    loadHoldings();
    loadReports();
  }
}
