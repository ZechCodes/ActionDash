/**
 * ActionDash - Realtime dashboard updates via Skrift SSE notifications.
 *
 * Listens to the Skrift notification stream at /notifications/stream and
 * processes workflow_run and workflow_job events to update the UI live.
 */

(function () {
    "use strict";

    const RECONNECT_DELAY = 3000;
    let eventSource = null;

    // --- Connection status indicator ---

    function createConnectionIndicator() {
        const el = document.createElement("div");
        el.className = "connection-status disconnected";
        el.textContent = "Connecting...";
        document.body.appendChild(el);
        return el;
    }

    const indicator = createConnectionIndicator();

    function setConnected() {
        indicator.className = "connection-status connected";
        indicator.textContent = "Live";
        // Fade out after 3s
        setTimeout(() => { indicator.style.opacity = "0.4"; }, 3000);
    }

    function setDisconnected() {
        indicator.className = "connection-status disconnected";
        indicator.textContent = "Reconnecting...";
        indicator.style.opacity = "1";
    }

    // --- SSE connection ---

    function connect() {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource("/notifications/stream");

        eventSource.addEventListener("notification", function (e) {
            const data = JSON.parse(e.data);
            handleNotification(data);
        });

        eventSource.addEventListener("sync", function () {
            setConnected();
        });

        eventSource.addEventListener("open", function () {
            // Connection opened, but wait for "sync" to confirm fully ready
        });

        eventSource.addEventListener("error", function () {
            setDisconnected();
            eventSource.close();
            setTimeout(connect, RECONNECT_DELAY);
        });
    }

    // --- Notification handler ---

    function handleNotification(data) {
        if (data.type === "workflow_run" && data.run) {
            updateWorkflowRun(data.run, data.action);
        } else if (data.type === "workflow_job" && data.job) {
            updateWorkflowJob(data.job, data.action);
        }
    }

    // --- DOM update helpers ---

    function updateWorkflowRun(run, action) {
        const existingCard = document.querySelector(`[data-run-id="${run.run_id}"]`);

        if (existingCard) {
            // Update existing card in-place
            updateRunCard(existingCard, run);
            flashCard(existingCard);

            // Move between active/recent sections as needed
            reclassifyRun(existingCard, run);
        } else {
            // Create new card
            const card = createRunCard(run);
            const targetList = isActive(run)
                ? document.getElementById("active-runs")
                : document.getElementById("recent-runs");

            if (targetList) {
                targetList.prepend(card);
                flashCard(card);
            } else if (isActive(run)) {
                // Need to create the active section
                createActiveSection(card);
            }

            // Remove empty state if present
            const emptyState = document.querySelector(".empty-state");
            if (emptyState) emptyState.remove();
        }

        // Update stats
        refreshStats();
    }

    function updateWorkflowJob(job, action) {
        const existingCard = document.querySelector(`[data-job-id="${job.job_id}"]`);

        if (existingCard) {
            updateJobCard(existingCard, job);
            flashCard(existingCard);
        }
        // Jobs on detail page only — new jobs added on page refresh
    }

    function isActive(run) {
        return ["requested", "in_progress", "queued"].includes(run.status);
    }

    function flashCard(card) {
        card.classList.remove("flash-update");
        // Force reflow to restart animation
        void card.offsetWidth;
        card.classList.add("flash-update");
    }

    function updateRunCard(card, run) {
        // Update the status class
        card.className = card.className.replace(
            /run-(success|failure|cancelled|in_progress|requested|queued|neutral|timed_out|skipped|action_required|stale)/,
            ""
        );
        card.classList.add(`run-${run.conclusion || run.status}`);

        // Update status icon
        const iconEl = card.querySelector(".status-icon");
        if (iconEl) {
            iconEl.className = "status-icon";
            if (run.status === "completed") {
                if (run.conclusion === "success") {
                    iconEl.classList.add("success");
                    iconEl.innerHTML = "&#10003;";
                } else if (run.conclusion === "failure") {
                    iconEl.classList.add("failure");
                    iconEl.innerHTML = "&#10007;";
                } else if (run.conclusion === "cancelled") {
                    iconEl.classList.add("cancelled");
                    iconEl.innerHTML = "&#9711;";
                } else {
                    iconEl.classList.add("neutral");
                    iconEl.innerHTML = "&#8226;";
                }
            } else if (run.status === "in_progress") {
                iconEl.classList.add("in-progress");
                iconEl.innerHTML = '<span class="spinner"></span>';
            } else {
                iconEl.classList.add("queued");
                iconEl.innerHTML = "&#9679;";
            }
        }
    }

    function updateJobCard(card, job) {
        card.className = card.className.replace(
            /job-(success|failure|cancelled|in_progress|queued|neutral)/,
            ""
        );
        card.classList.add(`job-${job.conclusion || job.status}`);

        const iconEl = card.querySelector(".status-icon");
        if (iconEl) {
            iconEl.className = "status-icon";
            if (job.status === "completed") {
                if (job.conclusion === "success") {
                    iconEl.classList.add("success");
                    iconEl.innerHTML = "&#10003;";
                } else if (job.conclusion === "failure") {
                    iconEl.classList.add("failure");
                    iconEl.innerHTML = "&#10007;";
                } else {
                    iconEl.classList.add("neutral");
                    iconEl.innerHTML = "&#8226;";
                }
            } else if (job.status === "in_progress") {
                iconEl.classList.add("in-progress");
                iconEl.innerHTML = '<span class="spinner"></span>';
            } else {
                iconEl.classList.add("queued");
                iconEl.innerHTML = "&#9679;";
            }
        }
    }

    function reclassifyRun(card, run) {
        const activeList = document.getElementById("active-runs");
        const recentList = document.getElementById("recent-runs");

        if (isActive(run) && activeList && !activeList.contains(card)) {
            activeList.prepend(card);
        } else if (!isActive(run) && recentList && activeList && activeList.contains(card)) {
            // Move from active to top of recent
            activeList.removeChild(card);
            recentList.prepend(card);

            // Remove active section if empty
            if (activeList.children.length === 0) {
                const section = activeList.closest(".dash-section");
                if (section) section.remove();
            }
        }
    }

    function createRunCard(run) {
        const card = document.createElement("article");
        card.className = `run-card run-${run.conclusion || run.status}`;
        card.dataset.runId = run.run_id;
        card.id = `run-${run.run_id}`;

        let statusIcon;
        if (run.status === "completed") {
            if (run.conclusion === "success") {
                statusIcon = '<span class="status-icon success">&#10003;</span>';
            } else if (run.conclusion === "failure") {
                statusIcon = '<span class="status-icon failure">&#10007;</span>';
            } else if (run.conclusion === "cancelled") {
                statusIcon = '<span class="status-icon cancelled">&#9711;</span>';
            } else {
                statusIcon = '<span class="status-icon neutral">&#8226;</span>';
            }
        } else if (run.status === "in_progress") {
            statusIcon = '<span class="status-icon in-progress"><span class="spinner"></span></span>';
        } else {
            statusIcon = '<span class="status-icon queued">&#9679;</span>';
        }

        const sha = run.head_sha ? `<span class="run-sha">${run.head_sha}</span>` : "";
        const avatar = run.actor_avatar_url
            ? `<img src="${run.actor_avatar_url}" alt="${run.actor_login || ""}" class="actor-avatar" width="24" height="24">`
            : "";
        const actorName = run.actor_login ? `<span class="actor-name">${run.actor_login}</span>` : "";

        card.innerHTML = `
            <div class="run-status-indicator">${statusIcon}</div>
            <div class="run-info">
                <div class="run-header">
                    <a href="/runs/${run.run_id}" class="run-workflow-name">${escapeHtml(run.workflow_name)}</a>
                    <span class="run-repo">${escapeHtml(run.repo_full_name)}</span>
                </div>
                <div class="run-meta">
                    <span class="run-branch">${escapeHtml(run.head_branch || "unknown")}</span>
                    ${sha}
                    <span class="run-event">${escapeHtml(run.event)}</span>
                    <span class="run-number">#${run.run_number}</span>
                </div>
            </div>
            <div class="run-actor">${avatar}${actorName}</div>
            <div class="run-actions">
                <a href="${escapeHtml(run.html_url)}" target="_blank" rel="noopener" class="run-link" title="View on GitHub">&#x2197;</a>
            </div>
        `;

        return card;
    }

    function createActiveSection(firstCard) {
        const section = document.createElement("section");
        section.className = "dash-section";
        section.innerHTML = `
            <h2 class="dash-section-title"><span class="pulse-dot"></span> Active Runs</h2>
            <div class="run-list" id="active-runs"></div>
        `;
        const runList = section.querySelector(".run-list");
        runList.appendChild(firstCard);

        // Insert before the recent runs section
        const content = document.querySelector(".sk-content");
        const statsBar = document.getElementById("stats-bar");
        if (statsBar && statsBar.nextElementSibling) {
            content.insertBefore(section, statsBar.nextElementSibling);
        } else if (content) {
            content.appendChild(section);
        }
    }

    function refreshStats() {
        fetch("/api/stats", { credentials: "same-origin" })
            .then((r) => r.json())
            .then((stats) => {
                setTextIfExists("stat-active", stats.active_count);
                setTextIfExists("stat-success", stats.success_count);
                setTextIfExists("stat-failure", stats.failure_count);
                setTextIfExists("stat-rate", stats.success_rate + "%");
            })
            .catch(() => {}); // Silently fail
    }

    function setTextIfExists(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Init ---
    connect();
})();
