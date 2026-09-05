from fastapi import FastAPI
import httpx

app = FastAPI()


@app.get("/content/{content_id}")
async def get_content(content_id: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://origin:8000/content/{content_id}"
        )

    return response.json()