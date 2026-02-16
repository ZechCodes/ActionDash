/**
 * ActionDash - Settings page interactions.
 */

(function() {
    "use strict";

    var btn = document.getElementById('monitor-all-btn');
    var progress = document.getElementById('monitor-all-progress');
    var status = document.getElementById('monitor-all-status');

    if (!btn) return;

    btn.addEventListener('click', async function() {
        if (!confirm('This will create webhooks on all your GitHub repos. Continue?')) return;

        btn.disabled = true;
        progress.style.display = 'flex';
        status.textContent = 'Setting up webhooks...';

        try {
            var resp = await fetch('/api/repos/monitor-all', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
            });
            var data = await resp.json();

            if (data.ok) {
                status.textContent = 'Done! Enabled: ' + data.enabled + ', Skipped: ' + data.skipped + ', Failed: ' + data.failed;
                if (window.ActionDash && window.ActionDash.loadRepos) {
                    window.ActionDash.loadRepos();
                }
            } else {
                status.textContent = 'Error: ' + (data.error || 'Unknown error');
            }
        } catch (err) {
            status.textContent = 'Network error';
        }

        setTimeout(function() { btn.disabled = false; }, 3000);
    });
})();
