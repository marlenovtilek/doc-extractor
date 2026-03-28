from __future__ import annotations

import threading
from collections.abc import Callable


class ExtractionCancelledError(RuntimeError):
    """Raised when a running extraction is cancelled by the user."""


_LOCAL = threading.local()


def set_execution_hooks(
    *,
    progress_callback: Callable[[str, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    _LOCAL.progress_callback = progress_callback
    _LOCAL.cancel_check = cancel_check


def clear_execution_hooks() -> None:
    _LOCAL.progress_callback = None
    _LOCAL.cancel_check = None


def report_progress(stage: str, detail: str = "") -> None:
    callback = getattr(_LOCAL, "progress_callback", None)
    if callback is not None:
        callback(stage, detail)


def is_cancel_requested() -> bool:
    cancel_check = getattr(_LOCAL, "cancel_check", None)
    if cancel_check is None:
        return False
    return bool(cancel_check())


def ensure_not_cancelled() -> None:
    if is_cancel_requested():
        raise ExtractionCancelledError("Extraction cancelled by user.")
