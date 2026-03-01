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
                    // Disable Skrift's default blur/focus handlers so SSE stays alive
                    window.removeEventListener("blur", sn._onBlur);
                    window.removeEventListener("focus", sn._onFocus);

                    // On mobile, browsers kill background connections despite the above.
                    // Reconnect via visibilitychange when the page regains focus.
                    document.addEventListener("visibilitychange", function () {
                        if (document.visibilityState === "visible" && sn.status !== "connected") {
                            sn._onFocus();
                        }
                    });
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

        // Update daily chart
        refreshDailyChart();
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

        // Remove step progress when run completes successfully (keep on failure)
        if (run.status === "completed" && run.conclusion !== "failure") {
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
        var displayJob = null;
        var isFailed = false;
        var jobIds = Object.keys(jobs);
        for (var i = 0; i < jobIds.length; i++) {
            var job = jobs[jobIds[i]];
            if (job.status === "in_progress" && job.current_step) {
                displayJob = job;
                break;
            }
        }

        // Fall back to first failed job with a current step
        if (!displayJob) {
            for (var i = 0; i < jobIds.length; i++) {
                var job = jobs[jobIds[i]];
                if (job.conclusion === "failure" && job.current_step) {
                    displayJob = job;
                    isFailed = true;
                    break;
                }
            }
        }

        var el = card.querySelector(".run-step-progress");

        if (!displayJob) {
            if (el) el.remove();
            return;
        }

        if (!el) {
            el = document.createElement("div");
            el.className = "run-step-progress";
            var runInfo = card.querySelector(".run-info");
            if (runInfo) runInfo.appendChild(el);
        }

        var indicatorClass = isFailed ? "step-indicator-failed" : "step-indicator";
        el.className = isFailed ? "run-step-progress step-failed" : "run-step-progress";
        el.innerHTML =
            '<span class="' + indicatorClass + '"></span>' +
            '<span class="step-name">' + escapeHtml(displayJob.current_step) + '</span>' +
            '<span class="step-count">' + displayJob.completed_steps + '/' + displayJob.total_steps + '</span>';
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
        if (run.step_summary) {
            card.dataset.stepSummary = JSON.stringify(run.step_summary);
        }

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
        const avatarUrl = run.actor_avatar_url || "https://github.com/ghost.png?s=48";
        const avatar = `<img src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(run.actor_login || "")}" class="actor-avatar" width="24" height="24">`;
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
        const chartCard = document.getElementById("daily-chart-card");
        if (chartCard && chartCard.nextElementSibling) {
            content.insertBefore(section, chartCard.nextElementSibling);
        } else if (content) {
            content.appendChild(section);
        }
    }

    // ── Daily activity chart ──

    var dailyChart = document.getElementById("daily-chart");
    var dailyTooltip = document.getElementById("daily-chart-tooltip");
    var dailyData = [];

    function renderDailyChart(data) {
        dailyData = data;
        if (!dailyChart) return;

        // Use the actual rendered height minus padding (8px top + 8px bottom)
        var barHeight = dailyChart.clientHeight - 16;
        if (barHeight < 10) barHeight = 104; // fallback

        var maxTotal = 0;
        for (var i = 0; i < data.length; i++) {
            var total = data[i].success + data[i].failure;
            if (total > maxTotal) maxTotal = total;
        }

        dailyChart.innerHTML = "";
        for (var i = 0; i < data.length; i++) {
            var total = data[i].success + data[i].failure;
            var successPx = maxTotal > 0 ? Math.max(Math.round(data[i].success / maxTotal * barHeight), 2) : 0;
            var failurePx = maxTotal > 0 ? Math.max(Math.round(data[i].failure / maxTotal * barHeight), 2) : 0;
            if (data[i].success === 0) successPx = 0;
            if (data[i].failure === 0) failurePx = 0;

            var bar = document.createElement("div");
            bar.className = "daily-bar";
            bar.setAttribute("data-idx", i);
            if (failurePx > 0) {
                var fail = document.createElement("div");
                fail.className = "daily-bar-failure";
                fail.style.height = failurePx + "px";
                bar.appendChild(fail);
            }
            if (successPx > 0) {
                var success = document.createElement("div");
                success.className = "daily-bar-success";
                success.style.height = successPx + "px";
                bar.appendChild(success);
            }
            if (total === 0) {
                var empty = document.createElement("div");
                empty.className = "daily-bar-empty";
                bar.appendChild(empty);
            }
            dailyChart.appendChild(bar);
        }
    }

    // Tooltip interaction
    if (dailyChart) {
        dailyChart.addEventListener("mousemove", function (e) {
            if (!dailyData.length) return;

            var rect = dailyChart.getBoundingClientRect();
            var x = e.clientX - rect.left;
            var idx = Math.min(
                Math.floor(x / rect.width * dailyData.length),
                dailyData.length - 1
            );
            if (idx < 0) idx = 0;

            var day = dailyData[idx];
            var dateObj = new Date(day.date + "T00:00:00");
            var dateStr = dateObj.toLocaleDateString(undefined, {
                weekday: "short", month: "short", day: "numeric"
            });

            dailyTooltip.innerHTML =
                '<div class="tt-date">' + escapeHtml(dateStr) + '</div>' +
                '<div class="tt-success">\u25CF ' + day.success + ' completed</div>' +
                '<div class="tt-failure">\u25CF ' + day.failure + ' failed</div>';

            var tx = e.clientX + 14;
            var ty = e.clientY - 60;
            if (tx + 180 > window.innerWidth) tx = e.clientX - 190;
            if (ty < 4) ty = e.clientY + 14;
            dailyTooltip.style.left = tx + "px";
            dailyTooltip.style.top = ty + "px";
            dailyTooltip.classList.add("visible");
        });

        dailyChart.addEventListener("mouseleave", function () {
            dailyTooltip.classList.remove("visible");
        });
    }

    function refreshDailyChart() {
        var url = "/api/daily-runs";
        if (currentRepo) url += "?repo=" + encodeURIComponent(currentRepo);
        fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                renderDailyChart(data.days || []);
            })
            .catch(function () {}); // Silently fail
    }

    // Fetch chart data on page load
    refreshDailyChart();

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

    // Hydrate step progress from server-rendered data attributes
    document.querySelectorAll("[data-step-summary]").forEach(function(card) {
        try {
            var summary = JSON.parse(card.dataset.stepSummary);
            updateStepProgress(parseInt(card.dataset.runId), summary);
        } catch (e) {
            // Ignore parse errors
        }
    });

    // Run immediately and then every second
    updateActorTimes();
    setInterval(updateActorTimes, 1000);

})();
