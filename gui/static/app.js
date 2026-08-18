"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let workflows = [];
let logLines = 0;
let pollTimer = null;

// ---- Tabs -----------------------------------------------------------------
$$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
        $$(".tab").forEach((t) => t.classList.remove("active"));
        $$(".panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        $("#tab-" + tab.dataset.tab).classList.add("active");
        if (tab.dataset.tab === "results") loadResults();
        if (tab.dataset.tab === "publish") loadPublishOptions();
    });
});

// ---- Config ---------------------------------------------------------------
async function loadConfig() {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    workflows = cfg.workflows || [];

    const roomSel = $("#room");
    roomSel.innerHTML = "";
    (cfg.rooms || []).forEach((r) => roomSel.append(new Option(r, r)));
    if (!cfg.rooms || cfg.rooms.length === 0) {
        roomSel.append(new Option("(no rooms configured in .env)", ""));
    }

    const scenSel = $("#scenario");
    scenSel.innerHTML = "";
    scenSel.append(new Option("all (every workflow)", "all"));
    workflows.forEach((w) => scenSel.append(new Option(w.name, w.name)));
    updateScenarioHint();
}

function updateScenarioHint() {
    const name = $("#scenario").value;
    const wf = workflows.find((w) => w.name === name);
    $("#scenario-hint").textContent = wf ? wf.description : "Runs every workflow in sequence.";
}
$("#scenario").addEventListener("change", updateScenarioHint);

// ---- Mode toggle ----------------------------------------------------------
$("#mode").addEventListener("change", () => {
    const scenario = $("#mode").value === "scenario";
    $(".mode-scenario").hidden = !scenario;
    $(".mode-passive").hidden = scenario;
});

// ---- Run ------------------------------------------------------------------
$("#run-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#run-error").textContent = "";
    const payload = {
        mode: $("#mode").value,
        room: $("#room").value,
        scenario: $("#scenario").value,
        iterations: $("#iterations").value,
        headless: $("#headless").checked,
        skip_login: $("#skip_login").checked,
        duration: $("#duration").value,
        api_threshold: $("#api_threshold").value,
        output_dir: $("#output_dir").value,
    };
    const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
        $("#run-error").textContent = data.error || "Failed to start run.";
        return;
    }
    $("#log").textContent = "";
    logLines = 0;
    setRunning(true);
    startPolling();
});

$("#stop-btn").addEventListener("click", async () => {
    await fetch("/api/run/stop", { method: "POST" });
});

function setRunning(running) {
    $("#run-btn").disabled = running;
    $("#stop-btn").disabled = !running;
}

function setStatus(status) {
    const pill = $("#run-status");
    pill.textContent = status;
    pill.className = "status-pill " + status;
}

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 1000);
    pollStatus();
}

async function pollStatus() {
    const res = await fetch("/api/run/status?since=" + logLines);
    const data = await res.json();
    if (data.lines && data.lines.length) {
        const log = $("#log");
        log.textContent += data.lines.join("\n") + "\n";
        log.scrollTop = log.scrollHeight;
        logLines = data.total_lines;
    }
    setStatus(data.status);
    if (data.status !== "running") {
        setRunning(false);
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

// ---- Results --------------------------------------------------------------
$("#refresh-results").addEventListener("click", loadResults);

async function loadResults() {
    const res = await fetch("/api/results");
    const data = await res.json();
    const wrap = $("#results-cards");
    wrap.innerHTML = "";
    if (!data.reports || data.reports.length === 0) {
        wrap.innerHTML = '<p class="empty">No reports found under results/ yet. Run a test first.</p>';
        return;
    }
    data.reports.forEach((r) => wrap.append(renderResultCard(r)));
}

function metric(label, value) {
    return `<div class="metric"><span class="m-label">${label}</span><span class="m-value">${value || "&mdash;"}</span></div>`;
}

function renderResultCard(r) {
    const div = document.createElement("div");
    div.className = "rcard";
    const badge = { PASS: "badge-pass", FAIL: "badge-fail" }[r.status] || "badge-unknown";
    const title = r.title || `${(r.workflow || "Report").toUpperCase()} - Room ${r.room || ""}`;
    div.innerHTML = `
        <div class="rcard-head">
            <span class="rcard-title">${title}</span>
            <span class="badge ${badge}">${r.status || "UNKNOWN"}</span>
        </div>
        <div class="rcard-body">
            <div class="metrics">
                ${metric("Room", r.room)}
                ${metric("Workflow", r.workflow)}
                ${metric("Date", r.date || r.timestamp)}
                ${metric("Actions", `${r.actions_passed || 0}/${r.actions_total || 0}`)}
                ${metric("Avg API", r.avg_api)}
                ${metric("P95 API", r.p95_api)}
            </div>
            <div class="rcard-actions">
                <a class="btn btn-primary" href="${r.report_url}/report.html" target="_blank">View Report</a>
                <button class="btn" data-dir="${r.dir}" data-title="${title}">Publish</button>
            </div>
        </div>`;
    div.querySelector("button[data-dir]").addEventListener("click", () => {
        gotoPublish(r.dir, title);
    });
    return div;
}

// ---- Publish --------------------------------------------------------------
async function loadPublishOptions() {
    const res = await fetch("/api/results");
    const data = await res.json();
    const sel = $("#publish-select");
    sel.innerHTML = "";
    (data.reports || []).forEach((r) => {
        const label = `${r.title || r.workflow || r.slug} — ${r.date || r.timestamp || r.slug}`;
        sel.append(new Option(label, r.dir));
    });
    if (!data.reports || data.reports.length === 0) {
        sel.append(new Option("(no reports to publish)", ""));
    }
}

function gotoPublish(dir, title) {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    document.querySelector('.tab[data-tab="publish"]').classList.add("active");
    $("#tab-publish").classList.add("active");
    loadPublishOptions().then(() => {
        $("#publish-select").value = dir;
        $("#publish-title").value = title || "";
    });
}

$("#stage-btn").addEventListener("click", async () => {
    const dir = $("#publish-select").value;
    if (!dir) return;
    $("#stage-btn").disabled = true;
    $("#stage-summary").innerHTML = "Sanitizing and staging…";
    $("#stage-output").hidden = false;
    $("#push-output").textContent = "";
    try {
        const res = await fetch("/api/publish/stage", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dir, title: $("#publish-title").value }),
        });
        const data = await res.json();
        if (!res.ok) {
            $("#stage-summary").innerHTML = `<span class="warn">${data.error || "Stage failed."}</span>`;
            return;
        }
        renderStageSummary(data);
    } finally {
        $("#stage-btn").disabled = false;
    }
});

function renderStageSummary(data) {
    const git = data.git || {};
    let html = "";
    if (data.safe_to_push) {
        html += `<p class="ok">✓ Sanitized. No leftover internal IPs detected.</p>`;
    } else {
        html += `<p class="warn">⚠ Leftover IPs found in:</p><ul>` +
            data.ip_offenders.map((f) => `<li><code>${f}</code></li>`).join("") + `</ul>`;
    }
    html += `<p>Hub now lists <strong>${data.report_count}</strong> report(s).</p>`;

    if (!git.available) {
        html += `<p class="warn">Git not ready: ${git.reason || "unknown"}</p>`;
    } else if (git.changes.length === 0) {
        html += `<p>Branch <code>${git.branch}</code>: no pending changes (already published).</p>`;
    } else {
        html += `<p>Branch <code>${git.branch}</code> — pending changes:</p><ul>` +
            git.changes.map((c) => `<li><code>${c}</code></li>`).join("") + `</ul>`;
    }
    $("#stage-summary").innerHTML = html;

    $("#override-wrap").hidden = data.safe_to_push;
    $("#allow-override").checked = false;
    $("#commit-message").value = `Add ${data.title} to hub`;
    updatePushEnabled(data, git);

    $("#allow-override").onchange = () => updatePushEnabled(data, git);
}

function updatePushEnabled(data, git) {
    const gitReady = git.available && git.changes.length > 0;
    const ipOk = data.safe_to_push || $("#allow-override").checked;
    $("#push-btn").disabled = !(gitReady && ipOk);
}

$("#push-btn").addEventListener("click", async () => {
    $("#push-btn").disabled = true;
    $("#push-output").textContent = "Pushing…";
    const res = await fetch("/api/publish/push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            message: $("#commit-message").value,
            allow_ip_override: $("#allow-override").checked,
        }),
    });
    const data = await res.json();
    if (data.ok) {
        $("#push-output").textContent = "✓ Published.\n\n" +
            (data.steps || []).map((s) => `$ ${s.cmd}\n${s.out}`).join("\n\n");
    } else {
        $("#push-output").textContent = "✗ " + (data.error || "Push failed.") + "\n\n" +
            (data.steps || []).map((s) => `$ ${s.cmd}\n${s.out}`).join("\n\n");
        $("#push-btn").disabled = false;
    }
});

// ---- Init -----------------------------------------------------------------
loadConfig();
