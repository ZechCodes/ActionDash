/**
 * ActionDash - Sidebar repo management.
 *
 * Loads the user's repos from the API, renders them in the sidebar,
 * handles client-side search, repo filtering, and monitoring toggles.
 *
 * Caches the repo list in localStorage for instant rendering on
 * subsequent page loads, then refreshes in the background and
 * animates in any new repos.
 */

(function () {
    "use strict";

    // Expose API for settings page integration
    window.ActionDash = window.ActionDash || {};

    const repoItemsEl = document.getElementById("repo-items");
    const searchInput = document.getElementById("repo-search");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    const sidebarBackdrop = document.getElementById("sidebar-backdrop");

    // --- Mobile sidebar toggle ---
    function openSidebar() {
        sidebar.classList.add("open");
        sidebarBackdrop.classList.add("open");
        sidebarToggle.classList.add("open");
    }

    function closeSidebar() {
        sidebar.classList.remove("open");
        sidebarBackdrop.classList.remove("open");
        sidebarToggle.classList.remove("open");
    }

    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", function () {
            if (sidebar.classList.contains("open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    }

    if (sidebarBackdrop) {
        sidebarBackdrop.addEventListener("click", closeSidebar);
    }

    // If no repo items container, we're not on a page with a sidebar
    if (!repoItemsEl) return;

    // Check if this is a placeholder (no GitHub token)
    if (repoItemsEl.querySelector(".sidebar-placeholder")) {
        // No GitHub token — sidebar shows placeholder, nothing to do
        return;
    }

    let allRepos = [];
    let monitoredSet = new Set();

    // --- Cache helpers ---

    var userId = repoItemsEl.dataset.userId || "";
    var CACHE_KEY = "actiondash:sidebar-cache:" + userId;

    function readCache() {
        try {
            var raw = localStorage.getItem(CACHE_KEY);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (e) {
            return null;
        }
    }

    function writeCache(repos, monitored) {
        try {
            localStorage.setItem(CACHE_KEY, JSON.stringify({
                ts: Date.now(),
                repos: repos,
                monitored: Array.from(monitored)
            }));
        } catch (e) {
            // localStorage full or unavailable — ignore
        }
    }

    function clearCache() {
        try {
            localStorage.removeItem(CACHE_KEY);
        } catch (e) {
            // ignore
        }
    }

    // Get current repo filter from URL
    function getCurrentRepo() {
        const params = new URLSearchParams(window.location.search);
        return params.get("repo") || null;
    }

    // --- Shared HTML builder ---

    function buildRepoItemHtml(repo, currentRepo) {
        var isActive = currentRepo === repo.full_name;
        var isMonitored = monitoredSet.has(repo.full_name);
        var repoName = repo.full_name.split("/").pop();
        var ownerName = repo.full_name.split("/")[0];

        return (
            '<div class="sidebar-repo-item' + (isActive ? ' active' : '') + '" data-repo="' + escapeAttr(repo.full_name) + '">' +
                '<span class="sidebar-repo-name" title="' + escapeAttr(repo.full_name) + '">' +
                    '<span class="sidebar-repo-name-text">' +
                        (repo.private ? '<span class="sidebar-repo-lock" title="Private"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="2.5" y="7" width="11" height="8" rx="2.5"/><path d="M5 7V5a3 3 0 0 1 6 0v2" stroke-linecap="round"/></svg></span>' : '') +
                        escapeHtml(repoName) +
                    '</span>' +
                    '<span class="sidebar-repo-owner">' + escapeHtml(ownerName) + '</span>' +
                '</span>' +
                '<label class="monitor-toggle" title="' + (isMonitored ? 'Disable' : 'Enable') + ' monitoring">' +
                    '<input type="checkbox"' + (isMonitored ? ' checked' : '') + ' data-repo="' + escapeAttr(repo.full_name) + '">' +
                    '<span class="monitor-toggle-slider"></span>' +
                '</label>' +
            '</div>'
        );
    }

    // --- Load repos (two-phase) ---

    async function loadRepos() {
        var cached = readCache();
        var hadCache = false;

        // Phase 1: instant render from cache
        if (cached && cached.repos && cached.repos.length > 0) {
            allRepos = cached.repos;
            monitoredSet = new Set(cached.monitored || []);
            renderRepos(allRepos);
            hadCache = true;
        }

        // Phase 2: background fetch
        var oldRepos = allRepos.slice();
        var oldMonitored = new Set(monitoredSet);

        try {
            var [reposResp, monitoredResp] = await Promise.all([
                fetch("/api/repos", { credentials: "same-origin" }),
                fetch("/api/repos/monitored", { credentials: "same-origin" }),
            ]);

            var reposData = await reposResp.json();
            var monitoredData = await monitoredResp.json();

            if (reposData.no_token) {
                clearCache();
                repoItemsEl.innerHTML = '\n' +
                    '                    <div class="sidebar-placeholder">\n' +
                    '                        <p>Connect GitHub to manage repos</p>\n' +
                    '                        <a href="/auth/login/github" class="sidebar-connect-btn">Connect GitHub</a>\n' +
                    '                    </div>\n' +
                    '                ';
                return;
            }

            allRepos = reposData.repos || [];
            monitoredSet = new Set(
                (monitoredData.repos || []).map(function (r) { return r.repo_full_name; })
            );

            if (hadCache && !isSearchActive()) {
                applyDiff(oldRepos, allRepos, oldMonitored, monitoredSet);
            } else if (hadCache && isSearchActive()) {
                // Re-render with current search filter
                filterRepos(searchInput.value.trim());
            } else {
                // First visit — stagger-animate all repos in
                repoItemsEl.classList.add("sidebar-repo-stagger");
                renderRepos(allRepos);
                // Remove stagger class after animations finish
                setTimeout(function () {
                    repoItemsEl.classList.remove("sidebar-repo-stagger");
                }, 600);
            }

            writeCache(allRepos, monitoredSet);
        } catch (err) {
            if (!hadCache) {
                repoItemsEl.innerHTML = '<div class="sidebar-loading">Failed to load repos</div>';
            }
            // With cache: silently keep stale render
        }
    }

    function isSearchActive() {
        return searchInput && searchInput.value.trim().length > 0;
    }

    // --- Diff & animated insertion ---

    function applyDiff(oldRepos, newRepos, oldMonitored, newMonitored) {
        var oldNames = oldRepos.map(function (r) { return r.full_name; });
        var newNames = newRepos.map(function (r) { return r.full_name; });
        var oldSet = new Set(oldNames);
        var newSet = new Set(newNames);

        var removed = oldNames.filter(function (n) { return !newSet.has(n); });
        var added = newNames.filter(function (n) { return !oldSet.has(n); });

        // Check for monitored-state changes on existing repos
        var monitorChanged = newNames.filter(function (n) {
            return oldSet.has(n) && (oldMonitored.has(n) !== newMonitored.has(n));
        });

        // If nothing changed at all, skip
        if (removed.length === 0 && added.length === 0 && monitorChanged.length === 0) {
            // Check order change
            var orderSame = oldNames.length === newNames.length &&
                oldNames.every(function (n, i) { return n === newNames[i]; });
            if (orderSame) return;
            // Order-only change — silent full re-render
            renderRepos(newRepos);
            return;
        }

        // Remove DOM elements for removed repos
        removed.forEach(function (name) {
            var el = repoItemsEl.querySelector('.sidebar-repo-item[data-repo="' + CSS.escape(name) + '"]');
            if (el) el.remove();
        });

        // Update monitored checkboxes
        monitorChanged.forEach(function (name) {
            var input = repoItemsEl.querySelector('input[data-repo="' + CSS.escape(name) + '"]');
            if (input) {
                input.checked = newMonitored.has(name);
                var label = input.closest(".monitor-toggle");
                if (label) label.title = (newMonitored.has(name) ? "Disable" : "Enable") + " monitoring";
            }
        });

        // Insert new repos at correct positions
        if (added.length > 0) {
            insertNewRepos(added, newRepos);
        }
    }

    function insertNewRepos(addedNames, allNewRepos) {
        var currentRepo = getCurrentRepo();
        var newRepoMap = {};
        allNewRepos.forEach(function (r) { newRepoMap[r.full_name] = r; });

        addedNames.forEach(function (name) {
            var repo = newRepoMap[name];
            if (!repo) return;

            var html = buildRepoItemHtml(repo, currentRepo);
            var temp = document.createElement("div");
            temp.innerHTML = html;
            var newEl = temp.firstElementChild;
            newEl.classList.add("sidebar-repo-new");

            // Find correct insertion index
            var targetIndex = allNewRepos.indexOf(repo);
            var children = repoItemsEl.children;

            if (targetIndex >= children.length) {
                repoItemsEl.appendChild(newEl);
            } else {
                repoItemsEl.insertBefore(newEl, children[targetIndex]);
            }

            // Attach event listeners
            attachRepoItemListeners(newEl);

            // Remove animation class after it finishes
            newEl.addEventListener("animationend", function () {
                newEl.classList.remove("sidebar-repo-new");
            }, { once: true });
        });
    }

    // --- Render ---

    function renderRepos(repos) {
        var currentRepo = getCurrentRepo();

        if (repos.length === 0) {
            repoItemsEl.innerHTML = '<div class="sidebar-loading">No repos found</div>';
            return;
        }

        repoItemsEl.innerHTML = repos.map(function (repo) {
            return buildRepoItemHtml(repo, currentRepo);
        }).join("");

        // Attach click and toggle handlers
        repoItemsEl.querySelectorAll(".sidebar-repo-item").forEach(function (item) {
            attachRepoItemListeners(item);
        });
    }

    function attachRepoItemListeners(item) {
        item.addEventListener("click", function (e) {
            if (e.target.closest(".monitor-toggle")) return;
            var repo = item.dataset.repo;
            var current = getCurrentRepo();
            navigateToRepo(repo === current ? null : repo);
        });

        var input = item.querySelector(".monitor-toggle input");
        if (input) {
            input.addEventListener("change", function (e) {
                e.stopPropagation();
                toggleMonitoring(input.dataset.repo, input.checked);
            });
        }
    }

    // --- Navigation ---

    function navigateToRepo(repoFullName) {
        var url = new URL("/", window.location.origin);
        if (repoFullName) {
            url.searchParams.set("repo", repoFullName);
        }
        window.location.href = url.toString();
    }

    // --- Search ---

    function filterRepos(query) {
        if (!query) {
            renderRepos(allRepos);
            return;
        }
        var lower = query.toLowerCase();
        var filtered = allRepos.filter(function (r) {
            return r.full_name.toLowerCase().includes(lower);
        });
        renderRepos(filtered);
    }

    if (searchInput) {
        searchInput.addEventListener("input", function () {
            filterRepos(searchInput.value.trim());
        });
    }

    // --- Monitoring toggle ---

    async function toggleMonitoring(repoFullName, enable) {
        var method = enable ? "POST" : "DELETE";
        try {
            var resp = await fetch("/api/repos/" + repoFullName + "/monitor", {
                method: method,
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            });
            var data = await resp.json();

            if (data.ok || resp.ok) {
                if (enable) {
                    monitoredSet.add(repoFullName);
                } else {
                    monitoredSet.delete(repoFullName);
                }
                writeCache(allRepos, monitoredSet);
            } else {
                // Revert toggle on failure
                var input = repoItemsEl.querySelector('input[data-repo="' + CSS.escape(repoFullName) + '"]');
                if (input) input.checked = !enable;
            }
        } catch (err) {
            // Revert toggle on network error
            var input = repoItemsEl.querySelector('input[data-repo="' + CSS.escape(repoFullName) + '"]');
            if (input) input.checked = !enable;
        }
    }

    // --- Util ---

    function escapeHtml(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function escapeAttr(str) {
        if (!str) return "";
        return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // --- Init ---

    window.ActionDash.loadRepos = loadRepos;
    loadRepos();
})();
