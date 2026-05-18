"""JSON structured logging via ``python-json-logger``.

When the observability plugin activates, every ``athena.*`` log line
becomes one JSON object on stderr (the chat-IO discipline that ACP
relies on — stdout is reserved for protocol traffic, stderr for
operator-facing diagnostics).

The configuration is opt-in via the plugin so users not running with
observability enabled keep the human-friendly default format.
"""
from __future__ import annotations

import logging
import sys


def install_json_logging(
    *,
    level: str | int = "INFO",
    logger_name: str = "athena",
    static_fields: dict[str, str] | None = None,
) -> logging.Handler:
    """Replace ``logger_name``'s handlers with a JSON formatter on
    stderr. Returns the installed handler so callers can remove it
    on plugin deactivation.

    Idempotent — calling twice replaces the previous handler rather
    than stacking duplicates, so toggling the plugin off/on doesn't
    produce double-printed lines.
    """
    from pythonjsonlogger import jsonlogger

    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    if static_fields:
        # Defaults attach to every record without requiring callers
        # to pass them in via ``extra=``.
        for key, value in static_fields.items():
            formatter._defaults = {  # type: ignore[attr-defined]
                **getattr(formatter, "_defaults", {}),
                key: value,
            }
    handler.setFormatter(formatter)

    logger = logging.getLogger(logger_name)
    # Remove any prior JSON handler installed by us; preserve user-
    # added handlers untouched. We tag our handler with an attribute
    # for identification.
    for existing in list(logger.handlers):
        if getattr(existing, "_athena_observability", False):
            logger.removeHandler(existing)
    handler._athena_observability = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    if isinstance(level, str):
        logger.setLevel(level.upper())
    else:
        logger.setLevel(level)
    return handler


def uninstall_json_logging(
    handler: logging.Handler | None = None,
    *,
    logger_name: str = "athena",
) -> None:
    """Remove the JSON handler from ``logger_name``.

    When ``handler`` is given, drop that specific handler;
    otherwise drop every handler tagged ``_athena_observability``.
    Safe to call when nothing's installed.
    """
    logger = logging.getLogger(logger_name)
    if handler is not None:
        logger.removeHandler(handler)
        return
    for existing in list(logger.handlers):
        if getattr(existing, "_athena_observability", False):
            logger.removeHandler(existing)
