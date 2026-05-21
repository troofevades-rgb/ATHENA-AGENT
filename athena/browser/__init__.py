"""Persistent CDP browser tools (T4-03).

One Playwright browser context per athena session. Cookies +
localStorage + open pages survive across tool calls within the
session, so a multi-step web workflow (search → click results
→ paginate → screenshot → extract) reasons over the SAME
browser state rather than relaunching per call.

Sync throughout — athena's runtime is sync; we use Playwright's
``sync_api`` so every tool call is a straight function call.
Public surface lives in :mod:`athena.browser.tools` (the
``browser_*`` tool registrations); :mod:`athena.browser.session`
holds the persistent-context manager + the ContextVar that
threads it through the agent.
"""

from __future__ import annotations
