import os

from mcp.server.fastmcp import FastMCP

from .pipeline import run_search
from .schemas import SearchRequest

mcp = FastMCP("trovia")


@mcp.tool()
async def web_search(
    query: str,
    search_depth: str = "basic",
    max_chunks: int | None = None,
    max_chunks_to_rerank: int | None = None,
    max_chunks_per_page: int | None = None,
) -> str:
    """Search the web and return relevant, source-cited passages as Markdown.

    search_depth: "basic" (fast) or "advanced" (reads at least 8 pages, returns twice as many passages).
    max_chunks: most passages to return in total (default: the user's setting, normally 6; doubled for advanced).
    max_chunks_to_rerank: most candidate passages to score (default: the user's setting, normally 300). Rarely worth changing.
    max_chunks_per_page: most passages returned from any one page (default: the user's setting, normally 2).
    """
    depth = search_depth if search_depth in ("basic", "advanced") else "basic"
    try:
        req = SearchRequest(
            query=query,
            search_depth=depth,
            top_k_chunks=max_chunks,
            max_chunks_to_rerank=max_chunks_to_rerank,
            max_chunks_per_url=max_chunks_per_page,
        )
    except ValueError as e:
        return f"Invalid search options: {e}"
    resp = await run_search(req)
    if resp.error:
        return f"Search failed: {resp.error}"
    return resp.synthesized_context or "No results found."


if __name__ == "__main__":
    # stdio for IDE/agent integration; MCP_TRANSPORT=sse for an HTTP server
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
