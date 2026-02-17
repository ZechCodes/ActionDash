/**
 * ActionDash - Sidebar repo management.
 *
 * Loads the user's repos from the API, renders them in the sidebar,
 * handles client-side search, repo filtering, and monitoring toggles.
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

    // Get current repo filter from URL
    function getCurrentRepo() {
        const params = new URLSearchParams(window.location.search);
        return params.get("repo") || null;
    }

    // --- Load repos ---

    async function loadRepos() {
        try {
            const [reposResp, monitoredResp] = await Promise.all([
                fetch("/api/repos", { credentials: "same-origin" }),
                fetch("/api/repos/monitored", { credentials: "same-origin" }),
            ]);

            const reposData = await reposResp.json();
            const monitoredData = await monitoredResp.json();

            if (reposData.no_token) {
                repoItemsEl.innerHTML = `
                    <div class="sidebar-placeholder">
                        <p>Connect GitHub to manage repos</p>
                        <a href="/auth/login/github" class="sidebar-connect-btn">Connect GitHub</a>
                    </div>
                `;
                return;
            }

            allRepos = reposData.repos || [];
            monitoredSet = new Set(
                (monitoredData.repos || []).map(function (r) { return r.repo_full_name; })
            );

            renderRepos(allRepos);
        } catch (err) {
            repoItemsEl.innerHTML = '<div class="sidebar-loading">Failed to load repos</div>';
        }
    }

    // --- Render ---

    function renderRepos(repos) {
        const currentRepo = getCurrentRepo();

        if (repos.length === 0) {
            repoItemsEl.innerHTML = '<div class="sidebar-loading">No repos found</div>';
            return;
        }

        repoItemsEl.innerHTML = repos.map(function (repo) {
            const isActive = currentRepo === repo.full_name;
            const isMonitored = monitoredSet.has(repo.full_name);
            const repoName = repo.full_name.split("/").pop();
            const ownerName = repo.full_name.split("/")[0];

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
        }).join("");

        // Attach click handlers
        repoItemsEl.querySelectorAll(".sidebar-repo-item").forEach(function (item) {
            // Clicking the repo name filters the dashboard
            item.addEventListener("click", function (e) {
                // Don't navigate when clicking the toggle
                if (e.target.closest(".monitor-toggle")) return;
                var repo = item.dataset.repo;
                var current = getCurrentRepo();
                navigateToRepo(repo === current ? null : repo);
            });
        });

        // Attach toggle handlers
        repoItemsEl.querySelectorAll('.monitor-toggle input').forEach(function (input) {
            input.addEventListener("change", function (e) {
                e.stopPropagation();
                toggleMonitoring(input.dataset.repo, input.checked);
            });
        });
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
