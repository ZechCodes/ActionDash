/**
 * Worker Admin — realtime activity feed and 24h uptime chart.
 *
 * Hydrates from /admin/worker/events and /admin/worker/uptime on load,
 * then listens for sk:notification events of type "worker_activity"
 * for live updates.
 */
(function () {
    "use strict";

    var feed = document.getElementById("activity-feed");
    var feedEmpty = document.getElementById("feed-empty");
    var feedCount = document.getElementById("feed-count");
    var healthDot = document.getElementById("health-dot");
    var healthLabel = document.getElementById("health-label");

    var uptimeBar = document.getElementById("uptime-bar");
    var uptimePctEl = document.getElementById("uptime-pct");
    var uptimeTooltip = document.getElementById("uptime-tooltip");

    var MAX_FEED_ITEMS = 200;
    var STALE_THRESHOLD_MS = 90 * 1000;
    var BUCKET_MINUTES = 5;
    var NUM_BUCKETS = 24 * 60 / BUCKET_MINUTES;
    var REFRESH_INTERVAL_MS = BUCKET_MINUTES * 60 * 1000;
    var lastHeartbeatAt = 0;
    var staleTimer = null;
    var eventCount = 0;

    // ── Uptime chart state ──

    var currentBuckets = [];
    var chartStartTime = null;

    // ── Event rendering ──

    var EVENT_CONFIG = {
        worker_started: { icon: "\u25B6", cls: "ev-started", label: "Worker Started" },
        poll_heartbeat: { icon: "\u2764", cls: "ev-heartbeat", label: "Heartbeat" },
        recovery_completed: { icon: "\u2714", cls: "ev-recovery", label: "Recovery Completed" },
        poll_error: { icon: "\u2718", cls: "ev-error", label: "Poll Error" },
        worker_down: { icon: "\u2718", cls: "ev-error", label: "Worker Down" },
        worker_recovered: { icon: "\u2714", cls: "ev-recovery", label: "Worker Recovered" },
    };

    function formatTimeAgo(isoStr) {
        var then = new Date(isoStr).getTime();
        var diff = Math.max(0, Date.now() - then);
        var s = Math.floor(diff / 1000);
        if (s < 60) return s + "s ago";
        var m = Math.floor(s / 60);
        if (m < 60) return m + "m ago";
        var h = Math.floor(m / 60);
        if (h < 24) return h + "h ago";
        return Math.floor(h / 24) + "d ago";
    }

    function pad2(n) { return n < 10 ? "0" + n : "" + n; }

    function formatLocalTime(date) {
        return pad2(date.getHours()) + ":" + pad2(date.getMinutes());
    }

    function buildDetail(event, payload) {
        switch (event) {
            case "worker_started":
                return payload.webhook_url || "";
            case "poll_heartbeat":
                var stats = payload.stats || {};
                return (
                    "cycle " + (payload.cycle || 0) +
                    " \u00B7 cached " + (payload.cached_runs || 0) +
                    " \u00B7 active " + (stats.active || 0) +
                    " \u00B7 polled " + (stats.polled || 0) +
                    " \u00B7 broadcast " + (stats.broadcast || 0)
                );
            case "recovery_completed":
                return (
                    (payload.repo || "") +
                    " #" + (payload.run_id || "") +
                    " \u2192 " + (payload.conclusion || "")
                );
            case "poll_error":
                return payload.message || "Unknown error";
            case "worker_down":
                return "Down for " + (payload.minutes_down || "?") + " minutes";
            case "worker_recovered":
                return "Worker is back online";
            default:
                return JSON.stringify(payload);
        }
    }

    function createEventCard(event, payload, isoTime) {
        var cfg = EVENT_CONFIG[event] || { icon: "\u2022", cls: "ev-heartbeat", label: event };

        var card = document.createElement("div");
        card.className = "event-card";
        card.setAttribute("data-event", event);

        var icon = document.createElement("div");
        icon.className = "event-icon " + cfg.cls;
        icon.textContent = cfg.icon;

        var body = document.createElement("div");
        body.className = "event-body";

        var lbl = document.createElement("div");
        lbl.className = "event-label";
        lbl.textContent = cfg.label;

        var detail = document.createElement("div");
        detail.className = "event-detail";
        detail.textContent = buildDetail(event, payload);

        body.appendChild(lbl);
        body.appendChild(detail);

        var time = document.createElement("div");
        time.className = "event-time";
        time.setAttribute("data-iso", isoTime);
        time.textContent = formatTimeAgo(isoTime);

        card.appendChild(icon);
        card.appendChild(body);
        card.appendChild(time);

        return card;
    }

    function addEventToFeed(event, payload, isoTime, prepend, hbCount) {
        if (feedEmpty) {
            feedEmpty.remove();
            feedEmpty = null;
        }

        // Group consecutive heartbeats into a single card
        if (event === "poll_heartbeat") {
            var adjacent = prepend ? feed.firstElementChild : feed.lastElementChild;
            if (adjacent && adjacent.getAttribute("data-event") === "poll_heartbeat") {
                var prev = parseInt(adjacent.getAttribute("data-hb-count") || "1", 10);
                var count = prev + (hbCount || 1);
                adjacent.setAttribute("data-hb-count", count);
                adjacent.querySelector(".event-label").textContent = "Heartbeat \u00D7" + count;
                if (prepend) {
                    // Live event is newer — update detail and timestamp
                    adjacent.querySelector(".event-detail").textContent = buildDetail(event, payload);
                    var ts = adjacent.querySelector(".event-time");
                    ts.setAttribute("data-iso", isoTime);
                    ts.textContent = formatTimeAgo(isoTime);
                }
                return;
            }
        }

        var card = createEventCard(event, payload, isoTime);
        if (event === "poll_heartbeat") {
            var initCount = hbCount || 1;
            card.setAttribute("data-hb-count", initCount);
            if (initCount > 1) {
                card.querySelector(".event-label").textContent = "Heartbeat \u00D7" + initCount;
            }
        }

        if (prepend) {
            feed.insertBefore(card, feed.firstChild);
        } else {
            feed.appendChild(card);
        }

        // Trim old items
        while (feed.children.length > MAX_FEED_ITEMS) {
            feed.removeChild(feed.lastChild);
        }

        eventCount = feed.children.length;
        feedCount.textContent = eventCount;
    }

    // ── Uptime chart ──

    function renderUptimeChart(buckets, startIso) {
        currentBuckets = buckets;
        chartStartTime = new Date(startIso);

        var cursor = document.createElement("div");
        cursor.className = "uptime-cursor";
        cursor.id = "uptime-cursor";

        var html = "";
        for (var i = 0; i < buckets.length; i++) {
            html += '<div class="uptime-seg ' + buckets[i] + '"></div>';
        }
        uptimeBar.innerHTML = html;
        uptimeBar.appendChild(cursor);

        updateUptimePct();
    }

    function updateUptimePct() {
        var known = 0;
        var up = 0;
        for (var i = 0; i < currentBuckets.length; i++) {
            if (currentBuckets[i] !== "unknown") {
                known++;
                if (currentBuckets[i] === "up") up++;
            }
        }
        if (known > 0) {
            var pct = (up / known * 100).toFixed(1);
            uptimePctEl.textContent = pct + "%";
            uptimePctEl.className = "uptime-pct" + (parseFloat(pct) < 95 ? " poor" : "");
        } else {
            uptimePctEl.textContent = "\u2014";
            uptimePctEl.className = "uptime-pct";
        }
    }

    function updateChartSegment(idx, status) {
        if (idx < 0 || idx >= currentBuckets.length) return;
        if (status === "up") {
            currentBuckets[idx] = "up";
        } else if (status === "error" && currentBuckets[idx] !== "up") {
            currentBuckets[idx] = "error";
        } else {
            return;
        }

        var segs = uptimeBar.querySelectorAll(".uptime-seg");
        if (segs[idx]) {
            segs[idx].className = "uptime-seg " + currentBuckets[idx];
        }
        updateUptimePct();
    }

    function getBucketIndex(isoTime) {
        if (!chartStartTime) return -1;
        var elapsed = (new Date(isoTime).getTime() - chartStartTime.getTime()) / 1000;
        var idx = Math.floor(elapsed / (BUCKET_MINUTES * 60));
        if (idx < 0 || idx >= NUM_BUCKETS) return -1;
        return idx;
    }

    function fetchUptime() {
        fetch("/admin/worker/uptime")
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                renderUptimeChart(data.buckets || [], data.start);
            })
            .catch(function (err) {
                console.warn("Failed to load uptime data:", err);
            });
    }

    // ── Uptime tooltip ──

    uptimeBar.addEventListener("mousemove", function (e) {
        if (!currentBuckets.length || !chartStartTime) return;

        var rect = uptimeBar.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var idx = Math.min(
            Math.floor(x / rect.width * currentBuckets.length),
            currentBuckets.length - 1
        );
        if (idx < 0) idx = 0;

        // Position cursor
        var cursor = document.getElementById("uptime-cursor");
        if (cursor) cursor.style.left = x + "px";

        // Compute bucket time range
        var bucketStart = new Date(chartStartTime.getTime() + idx * BUCKET_MINUTES * 60000);
        var bucketEnd = new Date(bucketStart.getTime() + BUCKET_MINUTES * 60000);
        var timeStr = formatLocalTime(bucketStart) + " \u2013 " + formatLocalTime(bucketEnd);

        var status = currentBuckets[idx];
        var statusLabel = status === "up" ? "Operational" : status === "error" ? "Error" : "No Data";

        uptimeTooltip.innerHTML =
            '<div class="tt-time">' + timeStr + '</div>' +
            '<div class="tt-status ' + status + '">\u25CF ' + statusLabel + '</div>';

        // Position tooltip, keeping it within viewport
        var tx = e.clientX + 14;
        var ty = e.clientY - 50;
        if (tx + 160 > window.innerWidth) tx = e.clientX - 170;
        if (ty < 4) ty = e.clientY + 14;
        uptimeTooltip.style.left = tx + "px";
        uptimeTooltip.style.top = ty + "px";
        uptimeTooltip.classList.add("visible");
    });

    uptimeBar.addEventListener("mouseleave", function () {
        uptimeTooltip.classList.remove("visible");
    });

    // ── Health tracking ──

    function markHealthy() {
        lastHeartbeatAt = Date.now();
        healthDot.className = "health-dot healthy";
        healthLabel.textContent = "Connected";
        resetStaleTimer();
    }

    function markStale() {
        healthDot.className = "health-dot stale";
        healthLabel.textContent = "No heartbeat";
    }

    function resetStaleTimer() {
        if (staleTimer) clearTimeout(staleTimer);
        staleTimer = setTimeout(markStale, STALE_THRESHOLD_MS);
    }

    // ── Handle incoming event ──

    function handleWorkerEvent(payload, isoTime) {
        var event = payload.event || "unknown";

        addEventToFeed(event, payload, isoTime, true);

        if (event === "poll_heartbeat") {
            markHealthy();
            var idx = getBucketIndex(isoTime);
            if (idx >= 0) updateChartSegment(idx, "up");
        } else if (event === "poll_error") {
            var errIdx = getBucketIndex(isoTime);
            if (errIdx >= 0) updateChartSegment(errIdx, "error");
        } else if (event === "worker_started") {
            markHealthy();
        } else if (event === "worker_down") {
            healthDot.className = "health-dot stale";
            healthLabel.textContent = "Worker down";
        } else if (event === "worker_recovered") {
            markHealthy();
        }
    }

    // ── SSE listener ──

    document.addEventListener("sk:notification", function (e) {
        var data = e.detail;
        if (data.type !== "worker_activity") return;

        var payload = data.payload || data;
        var isoTime = data.notified_at || new Date().toISOString();
        handleWorkerEvent(payload, isoTime);
    });

    // ── Hydrate from API ──

    fetchUptime();

    fetch("/admin/worker/events")
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            var events = data.events || [];
            if (!events.length) return;

            // Events come newest-first from API; render in that order
            for (var i = 0; i < events.length; i++) {
                var ev = events[i];
                addEventToFeed(ev.event, ev.payload, ev.at, false, ev.hb_count || 0);
            }

            // Use the most recent heartbeat to set health status
            for (var j = 0; j < events.length; j++) {
                if (events[j].event === "poll_heartbeat") {
                    // Check if it's recent enough to mark healthy
                    var age = Date.now() - new Date(events[j].at).getTime();
                    if (age < STALE_THRESHOLD_MS) {
                        markHealthy();
                    } else {
                        healthDot.className = "health-dot stale";
                        healthLabel.textContent = "Last heartbeat " + formatTimeAgo(events[j].at);
                    }
                    break;
                }
            }
        })
        .catch(function (err) {
            console.warn("Failed to load worker events:", err);
        });

    // ── Refresh relative times periodically ──

    setInterval(function () {
        var times = feed.querySelectorAll(".event-time[data-iso]");
        for (var i = 0; i < times.length; i++) {
            times[i].textContent = formatTimeAgo(times[i].getAttribute("data-iso"));
        }
    }, 1000);

    // ── Refresh uptime chart periodically ──

    setInterval(fetchUptime, REFRESH_INTERVAL_MS);

    // Start stale detection
    resetStaleTimer();
})();
