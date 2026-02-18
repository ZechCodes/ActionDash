/**
 * Worker Admin — realtime activity feed and stats.
 *
 * Hydrates from /admin/worker/events on load, then listens for
 * sk:notification events of type "worker_activity" for live updates.
 */
(function () {
    "use strict";

    var feed = document.getElementById("activity-feed");
    var feedEmpty = document.getElementById("feed-empty");
    var feedCount = document.getElementById("feed-count");
    var healthDot = document.getElementById("health-dot");
    var healthLabel = document.getElementById("health-label");

    var statActive = document.getElementById("stat-active");
    var statPolled = document.getElementById("stat-polled");
    var statBroadcasts = document.getElementById("stat-broadcasts");
    var statErrors = document.getElementById("stat-errors");

    var MAX_FEED_ITEMS = 200;
    var STALE_THRESHOLD_MS = 90 * 1000;
    var lastHeartbeatAt = 0;
    var staleTimer = null;
    var eventCount = 0;

    // ── Event rendering ──

    var EVENT_CONFIG = {
        worker_started: { icon: "\u25B6", cls: "ev-started", label: "Worker Started" },
        poll_heartbeat: { icon: "\u2764", cls: "ev-heartbeat", label: "Heartbeat" },
        recovery_completed: { icon: "\u2714", cls: "ev-recovery", label: "Recovery Completed" },
        poll_error: { icon: "\u2718", cls: "ev-error", label: "Poll Error" },
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
            default:
                return JSON.stringify(payload);
        }
    }

    function createEventCard(event, payload, isoTime) {
        var cfg = EVENT_CONFIG[event] || { icon: "\u2022", cls: "ev-heartbeat", label: event };

        var card = document.createElement("div");
        card.className = "event-card";

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

    function addEventToFeed(event, payload, isoTime, prepend) {
        if (feedEmpty) {
            feedEmpty.remove();
            feedEmpty = null;
        }

        var card = createEventCard(event, payload, isoTime);

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

    // ── Stats from heartbeat ──

    function updateStats(payload) {
        var stats = payload.stats || {};
        statActive.textContent = stats.active != null ? stats.active : "\u2014";
        statPolled.textContent = stats.polled != null ? stats.polled : "\u2014";
        statBroadcasts.textContent = stats.broadcast != null ? stats.broadcast : "\u2014";
        statErrors.textContent = stats.errors != null ? stats.errors : "\u2014";
    }

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
            updateStats(payload);
            markHealthy();
        } else if (event === "worker_started") {
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

    fetch("/admin/worker/events")
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            var events = data.events || [];
            if (!events.length) return;

            // Events come newest-first from API; render in that order
            for (var i = 0; i < events.length; i++) {
                var ev = events[i];
                addEventToFeed(ev.event, ev.payload, ev.at, false);
            }

            // Use the most recent heartbeat to set stats
            for (var j = 0; j < events.length; j++) {
                if (events[j].event === "poll_heartbeat") {
                    updateStats(events[j].payload);
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
    }, 15000);

    // Start stale detection
    resetStaleTimer();
})();
