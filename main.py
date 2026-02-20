"""ActionDash entry point.

Run with:
    uv run skrift serve --reload
"""

# Import models so SQLAlchemy metadata includes them for migrations
import actiondash.models  # noqa: F401

# Register the worker-down monitor hook
import actiondash.worker_monitor  # noqa: F401
