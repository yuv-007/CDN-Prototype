from fastapi import FastAPI
import httpx # type: ignore
import redis.asyncio as redis # type: ignore
import json
import os
from fastapi.responses import Response as FastAPIResponse
from prometheus_client import Counter, CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

Instrumentator().instrument(app).expose(app)
EDGE_ID = os.getenv("EDGE_ID", "unknown")

requests_total = Counter(
    "cdn_requests_total",
    "Total number of requests received by the CDN edge",
    ["edge"]
)

cache_hits_total = Counter(
    "cdn_cache_hits_total",
    "Total number of cache hits",
    ["edge"]
)

cache_misses_total = Counter(
    "cdn_cache_misses_total",
    "Total number of cache misses",
    ["edge"]
)

ORIGIN_HOST = os.getenv("ORIGIN_HOST", "origin")

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=6379,
    decode_responses=True
)


@app.get("/content/{content_id}")
async def get_content(content_id: str):
    requests_total.labels(edge=EDGE_ID).inc()
    cache_key = f"content:{content_id}"

    # Check cache
    cached_response = await redis_client.get(cache_key)

    if cached_response:
        cache_hits_total.labels(edge=EDGE_ID).inc()
        return {
            "source": "cache",
            "data": json.loads(cached_response)
        }

    # Cache miss → request Origin
    cache_misses_total.labels(edge=EDGE_ID).inc()
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://{ORIGIN_HOST}:8000/content/{content_id}"
        )

    origin_data = response.json()

    # Store response in Redis
    CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))  # Default TTL is 60 seconds
    await redis_client.set(
        cache_key,
        json.dumps(origin_data),
        ex=CACHE_TTL
    )

    return {
        "source": "origin",
        "data": origin_data
    }

@app.get("/metrics")
async def metrics():
    return FastAPIResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )