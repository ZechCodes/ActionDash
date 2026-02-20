"""Worker-down notification monitor.

Listens for ``worker_activity`` heartbeat notifications via the
``NOTIFICATION_SENT`` hook and launches a background task that checks
every 60 s whether the worker has gone silent.  After 5 minutes of
silence it sends periodic ``worker_down`` alerts; when the heartbeat
resumes it sends a single ``worker_recovered`` notification.
"""

import asyncio
import logging
import time

from skrift.lib.hooks import hooks, NOTIFICATION_SENT
from skrift.lib.notifications import Notification, NotificationMode, notify_user

logger = logging.getLogger(__name__)

_DOWN_THRESHOLD = 300  # seconds (5 minutes) before alerting
_CHECK_INTERVAL = 60   # seconds between monitor loop ticks

# ── In-memory state ──

_last_heartbeat: float = 0.0       # time.monotonic() of last heartbeat
_tracked_users: set[str] = set()   # user IDs that receive worker events
_alerting: bool = False            # currently in "down" state
_monitor_task: asyncio.Task | None = None


# ── NOTIFICATION_SENT hook ──

async def _on_notification_sent(
    notification: Notification,
    scope: str,
    scope_id: str | None,
) -> None:
    """Called by Skrift every time a notification is dispatched."""
    if notification.type != "worker_activity":
        return
    if notification.payload.get("event") != "poll_heartbeat":
        return

    global _last_heartbeat, _alerting, _monitor_task

    _last_heartbeat = time.monotonic()

    if scope == "user" and scope_id:
        _tracked_users.add(scope_id)

    # If we were alerting, the worker just came back — send recovery
    if _alerting:
        _alerting = False
        await _notify_all(
            event="worker_recovered",
            group="worker-down",
            mode=NotificationMode.EPHEMERAL,
        )

    # Lazy-start the monitor loop on the first heartbeat
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_monitor_loop())


async def _notify_all(
    *,
    event: str,
    group: str,
    mode: NotificationMode,
    **extra,
) -> None:
    """Send a worker_activity notification to every tracked user."""
    for uid in list(_tracked_users):
        try:
            await notify_user(
                uid,
                "worker_activity",
                group=group,
                mode=mode,
                event=event,
                **extra,
            )
        except Exception:
            logger.warning("worker_monitor: failed to notify user %s", uid)


async def _monitor_loop() -> None:
    """Background loop that detects worker silence and emits alerts."""
    global _alerting

    while True:
        await asyncio.sleep(_CHECK_INTERVAL)

        if _last_heartbeat == 0.0:
            continue

        elapsed = time.monotonic() - _last_heartbeat

        if elapsed > _DOWN_THRESHOLD:
            _alerting = True
            minutes_down = int(elapsed / 60)
            await _notify_all(
                event="worker_down",
                group="worker-down",
                mode=NotificationMode.QUEUED,
                minutes_down=minutes_down,
            )


# ── Register the hook on import ──

hooks.add_action(NOTIFICATION_SENT, _on_notification_sent)
