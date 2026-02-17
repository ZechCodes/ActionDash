/**
 * ActionDash - Realtime dashboard updates via Skrift SSE notifications.
 *
 * Listens to the Skrift notification stream at /notifications/stream and
 * processes workflow_run and workflow_job events to update the UI live.
 */

(function () {
    "use strict";

    // Current repo filter from URL
    const currentRepo = new URLSearchParams(window.location.search).get("repo");

    // --- Connection status indicator (driven by Skrift's SSE events) ---

    const indicator = document.createElement("div");
    indicator.className = "connection-status disconnected";
    indicator.textContent = "Connecting...";
    var masthead = document.querySelector(".dash-masthead");
    if (masthead) {
        masthead.appendChild(indicator);
    } else {
        document.body.appendChild(indicator);
    }

    var sseKeptAlive = false;
    document.addEventListener("sk:notification-status", function (e) {
        if (e.detail.status === "connected") {
            indicator.className = "connection-status connected";
            indicator.textContent = "Live";
            setTimeout(function () { indicator.style.opacity = "0.4"; }, 3000);

            // Keep SSE alive when tab loses focus (step progress needs continuous updates)
            if (!sseKeptAlive) {
                sseKeptAlive = true;
                var sn = window.__skriftNotifications;
                if (sn && sn._onBlur) {
                    window.removeEventListener("blur", sn._onBlur);
                    window.removeEventListener("focus", sn._onFocus);
                }
            }
        } else if (e.detail.status === "suspended") {
            indicator.className = "connection-status disconnected";
            indicator.textContent = "Disconnected";
            indicator.style.opacity = "1";
        } else {
            indicator.className = "connection-status disconnected";
            indicator.textContent = "Reconnecting...";
            indicator.style.opacity = "1";
        }
    });

    // --- Notification data (driven by Skrift's SSE events) ---

    document.addEventListener("sk:notification", function (e) {
        handleNotification(e.detail);
    });

    // --- Notification handler ---

    function handleNotification(data) {
        if (data.type === "workflow_run" && data.run) {
            // When filtering by repo, only show updates for that repo
            if (currentRepo && data.run.repo_full_name !== currentRepo) return;
            updateWorkflowRun(data.run, data.action);
        } else if (data.type === "workflow_job" && data.job) {
            if (currentRepo && data.job.repo_full_name !== currentRepo) return;
            updateWorkflowJob(data.job, data.action);
        } else if (data.type === "step_progress" && data.jobs) {
            if (currentRepo && data.repo_full_name !== currentRepo) return;
            updateStepProgress(data.run_id, data.jobs);
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
                iconEl.innerHTML = "&#9654;";
            } else {
                iconEl.classList.add("queued");
                iconEl.innerHTML = "&#9679;";
            }
        }

        // Update active badge
        var badgeEl = card.querySelector(".active-badge");
        if (run.status !== "completed") {
            if (!badgeEl) {
                badgeEl = document.createElement("span");
                badgeEl.className = "active-badge";
                var workflow = card.querySelector(".run-workflow");
                if (workflow) workflow.appendChild(badgeEl);
            }
            badgeEl.textContent = run.status.replace("_", " ");
        } else if (badgeEl) {
            badgeEl.remove();
        }

        // Remove step progress when run completes
        if (run.status === "completed") {
            var stepEl = card.querySelector(".run-step-progress");
            if (stepEl) stepEl.remove();
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
                iconEl.innerHTML = "&#9654;";
            } else {
                iconEl.classList.add("queued");
                iconEl.innerHTML = "&#9679;";
            }
        }
    }

    function updateStepProgress(runId, jobs) {
        var card = document.querySelector('[data-run-id="' + runId + '"]');
        if (!card) return;

        // Find first in-progress job with a current step
        var activeJob = null;
        var jobIds = Object.keys(jobs);
        for (var i = 0; i < jobIds.length; i++) {
            var job = jobs[jobIds[i]];
            if (job.status === "in_progress" && job.current_step) {
                activeJob = job;
                break;
            }
        }

        var el = card.querySelector(".run-step-progress");

        if (!activeJob) {
            // No active step — remove element if present
            if (el) el.remove();
            return;
        }

        if (!el) {
            el = document.createElement("div");
            el.className = "run-step-progress";
            var runInfo = card.querySelector(".run-info");
            if (runInfo) runInfo.appendChild(el);
        }

        el.innerHTML =
            '<span class="step-indicator"></span>' +
            '<span class="step-name">' + escapeHtml(activeJob.current_step) + '</span>' +
            '<span class="step-count">' + activeJob.completed_steps + '/' + activeJob.total_steps + '</span>';
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
            statusIcon = '<span class="status-icon in-progress">&#9654;</span>';
        } else {
            statusIcon = '<span class="status-icon queued">&#9679;</span>';
        }

        const badge = run.status !== "completed"
            ? `<span class="active-badge">${escapeHtml(run.status.replace("_", " "))}</span>`
            : "";
        const sha = run.head_sha ? `<span>${escapeHtml(run.head_sha)}</span>` : "";
        const avatar = run.actor_avatar_url
            ? `<img src="${escapeHtml(run.actor_avatar_url)}" alt="${escapeHtml(run.actor_login || "")}" class="actor-avatar" width="24" height="24">`
            : "";
        const actorName = run.actor_login ? `<div class="actor-name">${escapeHtml(run.actor_login)}</div>` : "";
        const startedAt = run.run_started_at || "";

        card.innerHTML = `
            <div class="run-status-indicator">${statusIcon}</div>
            <div class="run-info">
                <div class="run-workflow">
                    <a href="/runs/${run.run_id}" class="run-workflow-name">${escapeHtml(run.workflow_name)}</a>
                    ${badge}
                </div>
                <div class="run-meta">
                    <span><span class="meta-icon">&#9783;</span> ${escapeHtml(run.repo_full_name)}</span>
                    <span><span class="meta-icon">&#9095;</span> ${escapeHtml(run.head_branch || "unknown")}</span>
                    ${sha}
                    <span>${escapeHtml(run.event)} &middot; #${run.run_number}</span>
                </div>
            </div>
            <div class="run-actor">
                ${avatar}
                <div>
                    ${actorName}
                    <div class="actor-time" data-started="${escapeHtml(startedAt)}">${formatTimeAgo(startedAt)}</div>
                </div>
                <a href="${escapeHtml(run.html_url)}" target="_blank" rel="noopener" class="run-link" title="View on GitHub">&#x2197;</a>
            </div>
        `;

        return card;
    }

    function createActiveSection(firstCard) {
        const section = document.createElement("section");
        section.className = "dash-section";
        section.innerHTML = `
            <h2 class="dash-section-title"><span class="pulse-dot"></span> Active Runs <span class="section-count">1</span></h2>
            <div class="run-list" id="active-runs"></div>
        `;
        const runList = section.querySelector(".run-list");
        runList.appendChild(firstCard);

        // Insert before the recent runs section
        const content = document.querySelector(".dash-main") || document.querySelector(".sk-content");
        const statsBar = document.getElementById("stats-bar");
        if (statsBar && statsBar.nextElementSibling) {
            content.insertBefore(section, statsBar.nextElementSibling);
        } else if (content) {
            content.appendChild(section);
        }
    }

    function refreshStats() {
        var url = "/api/stats";
        if (currentRepo) url += "?repo=" + encodeURIComponent(currentRepo);
        fetch(url, { credentials: "same-origin" })
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

    // --- Relative time display for actor-time elements ---

    function formatTimeAgo(dateStr) {
        if (!dateStr) return "";
        var then = new Date(dateStr);
        if (isNaN(then.getTime())) return "";
        var seconds = Math.floor((Date.now() - then.getTime()) / 1000);
        if (seconds < 0) return "just now";
        if (seconds < 60) return seconds + "s ago";
        var minutes = Math.floor(seconds / 60);
        if (minutes < 60) return minutes + "m ago";
        var hours = Math.floor(minutes / 60);
        if (hours < 24) return hours + "h ago";
        var days = Math.floor(hours / 24);
        return days + "d ago";
    }

    function updateActorTimes() {
        var els = document.querySelectorAll(".actor-time[data-started]");
        for (var i = 0; i < els.length; i++) {
            var started = els[i].getAttribute("data-started");
            els[i].textContent = formatTimeAgo(started);
        }
    }

    // Run immediately and then every second
    updateActorTimes();
    setInterval(updateActorTimes, 1000);

})();
