"""Web search tool using Brave Search API for research context."""

from __future__ import annotations

import json
import os
import ssl
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from dotenv import load_dotenv

if TYPE_CHECKING:
    from agent.workspace import Workspace

def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def web_search(
    query: str,
    num_results: int = 5,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """
    Search the web using Brave Search API and return summarized results.

    Useful for finding recent alpha research, market regime context, factor
    definitions, or any external information the agent needs.

    Saves the search results as ``search_context`` in the workspace for
    downstream tools (e.g. ``build_alphas``) to consume.
    """
    load_dotenv()
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return {"error": "no_api_key", "message": "BRAVE_API_KEY is not set in environment."}

    if not query or not query.strip():
        return {"error": "empty_query", "message": "Search query cannot be empty."}

    url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={num_results}"
    req = Request(url, headers={"X-Subscription-Token": api_key, "Accept": "application/json"})

    try:
        with urlopen(req, timeout=15, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": "search_failed", "message": f"Brave Search API error: {exc}"}

    results: list[dict[str, str]] = []
    for item in (data.get("web", {}).get("results") or [])[:num_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
        })

    summary_lines = []
    for i, r in enumerate(results, 1):
        summary_lines.append(f"{i}. **{r['title']}**\n   {r['description']}\n   Source: {r['url']}")
    summary_text = "\n\n".join(summary_lines)

    output = {
        "query": query,
        "num_results": len(results),
        "results": results,
        "summary": summary_text,
    }

    if workspace is not None:
        workspace.save_json(
            "search_context",
            output,
            description=f"Web search results for: {query[:80]}",
        )
        output["workspace_artifact"] = "search_context"

    return output
