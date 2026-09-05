from fastapi import FastAPI

app = FastAPI(title="CDN Origin Server")


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