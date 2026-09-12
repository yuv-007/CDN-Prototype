from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="CDN Origin Server")
Instrumentator().instrument(app).expose(app)


@app.get("/")
def root():
    return {
        "message": "Hello from the origin server"
    }


@app.get("/content/{content_id}")
def get_content(content_id: str):
    return {
        "content_id": content_id,
        "source": "origin"
    }