"""Per-platform desktop backends (T6-04.3).

Backends implement :class:`athena.computer.contract.DesktopBackend`.
The observe surface (screenshot / active_app / accessibility_tree)
lands first; :meth:`perform` is wired only by T6-04.5 after the
kill switch + gate are in place.
"""
