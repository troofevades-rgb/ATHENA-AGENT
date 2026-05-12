"""One-way migration from Hermes (the predecessor agent) into ocode v2.

The entry point lives at :mod:`ocode.migration.hermes_import`. The per-domain
importers (skills, memory, sessions, config, MCP, cron, credentials) each
expose a single function that takes ``source``, ``dest``, and a
:class:`~ocode.migration.report.Report` to record outcomes.

Migration writes always run under ``write_origin="migration"`` so the
curator can identify imported content and leave it alone until it sees
local activity.
"""
