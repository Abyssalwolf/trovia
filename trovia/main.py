import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from . import __version__, reranker
from .config import get_settings
from .pipeline import run_search
from .schemas import SearchRequest, SearchResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trovia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().warmup:
        try:
            await asyncio.to_thread(reranker.get_ranker)  # load (and if needed download) the model
            log.info("reranker model warm")
        except Exception as e:  # offline, download host down, ... - start anyway
            log.warning("reranker model not loaded yet (%s: %s); will retry on the first search", type(e).__name__, e)
    yield


app = FastAPI(title="Trovia", version=__version__, lifespan=lifespan)


def _request_host(request: Request) -> str:
    host = request.headers.get("host", "").lower()
    if host.startswith("["):  # IPv6 literal such as [::1]:8000
        return host.split("]")[0] + "]"
    return host.split(":")[0]


@app.middleware("http")
async def only_local_hosts(request: Request, call_next):
    """Refuse requests whose Host header is not ours. Stops a web page from reaching this
    service through DNS rebinding (a hostile site pointing its own name at 127.0.0.1)."""
    allowed = get_settings().allowed_host_list
    if "*" not in allowed and _request_host(request) not in allowed:
        return PlainTextResponse("Invalid host header", status_code=400)
    return await call_next(request)


@app.post("/v1/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    return await run_search(req)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
