"""Web tools: search and fetch URLs.

Search backends (selected via ATHENA_SEARCH_BACKEND env var):
  - duckduckgo  (default, no key required, scrapes html.duckduckgo.com)
  - brave       (set BRAVE_API_KEY; free tier 2000 queries/month)
  - searxng     (set ATHENA_SEARXNG_URL=https://your-searxng-instance/)

Fetch backend: httpx, with HTML→text extraction via best-available library:
  trafilatura > beautifulsoup4 > regex fallback.

Optional installs to improve quality:
    pip install beautifulsoup4 trafilatura

Configuration env vars:
  ATHENA_SEARCH_BACKEND    duckduckgo | brave | searxng     (default: duckduckgo)
  BRAVE_API_KEY            for brave backend
  ATHENA_SEARXNG_URL       for searxng backend
  ATHENA_WEB_TIMEOUT       float seconds (default: 30)
  ATHENA_WEB_USER_AGENT    custom UA string
"""

from __future__ import annotations

import os
import re

import httpx

from ..safety.url_safety import URLSecurityDenied, validate_url
from .registry import tool

_TIMEOUT = float(
    os.environ.get("ATHENA_WEB_TIMEOUT") or "30"
)
_USER_AGENT = (
    os.environ.get("ATHENA_WEB_USER_AGENT")
    or "Mozilla/5.0 (compatible; athena/0.1; local research agent)"
)


# ---- HTML -> text extraction (graceful degradation) -------------------


def _extract_text(html: str) -> str:
    """Best-available HTML to text. Tries trafilatura, then BeautifulSoup,
    then a regex fallback. Always returns something."""
    try:
        import trafilatura  # type: ignore

        text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside", "noscript", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Collapse runs of blank lines
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    except ImportError:
        pass

    # Last-resort regex strip
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---- web_fetch tool ---------------------------------------------------


@tool(
    name="WebFetch",
    toolset="web",
    check_fn=lambda: True,
    aliases=["web_fetch"],
    description=(
        "Fetches content from a specified URL. HTML is converted to readable "
        "text (strips scripts, styles, navigation chrome). Use for reading "
        "articles, documentation, GitHub READMEs, news, or any specific page "
        "you have a URL for. The user must provide URLs explicitly — do not "
        "guess or invent them."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL starting with http:// or https://"},
            "max_chars": {
                "type": "integer",
                "description": "Truncate output to this many characters (default 50000)",
            },
            "raw": {
                "type": "boolean",
                "description": "Return raw HTML instead of extracted text (default false)",
            },
        },
        "required": ["url"],
    },
)
def WebFetch(url: str, max_chars: int = 50000, raw: bool = False) -> str:
    if not url.startswith(("http://", "https://")):
        return f"ERROR: url must start with http:// or https://, got {url!r}"
    # SSRF guard. Lets URLSecurityDenied propagate to the caller so the
    # agent surface raises rather than masking the refusal as a string.
    validate_url(url)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    def _check_redirect(response: httpx.Response) -> None:
        loc = response.headers.get("location")
        if loc and response.status_code in (301, 302, 303, 307, 308):
            # Re-validate every redirect target before httpx follows it.
            # validate_url raises URLSecurityDenied on a blocked Location,
            # which httpx surfaces as the call's outer exception.
            from urllib.parse import urljoin

            absolute = urljoin(str(response.url), loc)
            validate_url(absolute)

    try:
        with httpx.Client(
            timeout=_TIMEOUT,
            follow_redirects=True,
            event_hooks={"response": [_check_redirect]},
        ) as c:
            r = c.get(url, headers=headers)
    except URLSecurityDenied:
        raise
    except httpx.HTTPError as e:
        return f"ERROR: HTTP failure for {url}: {e}"
    ct = r.headers.get("content-type", "")
    body = r.text
    if "text/html" in ct.lower() and not raw:
        body = _extract_text(body)
    truncated = ""
    if len(body) > max_chars:
        body = body[:max_chars]
        truncated = f"\n... [truncated to {max_chars} chars]"
    return f"status={r.status_code}\ncontent-type={ct}\nurl={url}\n\n{body}{truncated}"


# ---- search backends -------------------------------------------------


def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    # URL is hardcoded to a public DuckDuckGo endpoint — not
    # user-controlled, so validate_url is not required here.
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = c.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers)
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return [
            {"error": "duckduckgo backend requires beautifulsoup4 — `pip install beautifulsoup4`"}
        ]
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[dict[str, str]] = []
    for div in soup.select("div.result, div.web-result")[:max_results]:
        a = div.select_one("a.result__a") or div.select_one("a")
        if not a:
            continue
        href = a.get("href", "")
        # DDG wraps URLs in a redirector — extract the underlying url if present
        if href.startswith("//duckduckgo.com/l/?uddg="):
            from urllib.parse import parse_qs, unquote, urlparse

            qs = parse_qs(urlparse(href).query)
            if qs.get("uddg"):
                href = unquote(qs["uddg"][0])
        snippet_el = div.select_one(".result__snippet") or div.select_one(".snippet")
        out.append(
            {
                "title": a.get_text(strip=True),
                "url": href,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
    return out


def _search_brave(query: str, max_results: int) -> list[dict[str, str]]:
    # URL is hardcoded to the public Brave search API — not
    # user-controlled, so validate_url is not required here.
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return [{"error": "BRAVE_API_KEY env var not set"}]
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [
        {
            "title": w.get("title", ""),
            "url": w.get("url", ""),
            "snippet": w.get("description", ""),
        }
        for w in (data.get("web") or {}).get("results", [])[:max_results]
    ]


def _search_searxng(query: str, max_results: int) -> list[dict[str, str]]:
    base = (
        os.environ.get("ATHENA_SEARXNG_URL") or ""
    ).rstrip("/")
    if not base:
        return [{"error": "ATHENA_SEARXNG_URL env var not set"}]
    # SearxNG base URL comes from an env var the operator sets, which
    # may legitimately be a private host. Validate so the SSRF block
    # list applies (and so allow_external_urls can opt in if needed).
    validate_url(f"{base}/search")
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
        r = c.get(
            f"{base}/search",
            params={"q": query, "format": "json", "categories": "general"},
            headers={"User-Agent": _USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {
            "title": h.get("title", ""),
            "url": h.get("url", ""),
            "snippet": h.get("content", ""),
        }
        for h in data.get("results", [])[:max_results]
    ]


# ---- web_search tool -------------------------------------------------


@tool(
    name="WebSearch",
    toolset="web",
    check_fn=lambda: True,
    aliases=["web_search"],
    description=(
        "Allows you to search the web. Returns a numbered list of result "
        "titles, URLs, and snippets. Use when you need information beyond "
        "your training data: current events, specific entities, public "
        "records, news, recent technical docs. Follow up with WebFetch on "
        "the most promising URLs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "default 8"},
        },
        "required": ["query"],
    },
)
def WebSearch(query: str, max_results: int = 8) -> str:
    backend = (
        os.environ.get("ATHENA_SEARCH_BACKEND")
        or "duckduckgo"
    ).lower()
    try:
        if backend == "brave":
            results = _search_brave(query, max_results)
        elif backend == "searxng":
            results = _search_searxng(query, max_results)
        else:
            results = _search_duckduckgo(query, max_results)
    except httpx.HTTPError as e:
        return f"ERROR: search failure ({backend}): {e}"
    if not results:
        return "(no results)"
    if isinstance(results[0], dict) and "error" in results[0]:
        return f"ERROR: {results[0]['error']}"
    lines: list[str] = [f"backend={backend}  query={query!r}", ""]
    for i, res in enumerate(results, 1):
        lines.append(f"{i}. {res.get('title', '(no title)')}")
        lines.append(f"   {res.get('url', '')}")
        if res.get("snippet"):
            lines.append(f"   {res['snippet']}")
        lines.append("")
    return "\n".join(lines).rstrip()
