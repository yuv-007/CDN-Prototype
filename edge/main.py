from fastapi import FastAPI
import httpx # type: ignore
import redis.asyncio as redis # type: ignore
import json
import os

app = FastAPI()

redis_client = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)


@app.get("/content/{content_id}")
async def get_content(content_id: str):

    cache_key = f"content:{content_id}"

    # Check cache
    cached_response = await redis_client.get(cache_key)

    if cached_response:
        return {
            "source": "cache",
            "data": json.loads(cached_response)
        }

    # Cache miss → request Origin
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://origin:8000/content/{content_id}"
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