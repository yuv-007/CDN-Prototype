from fastapi import FastAPI, Request, HTTPException
import httpx
import math
import redis.asyncio as redis
import json

app = FastAPI()

fallback_redis = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)

# --------------------------------------------------
# CDN Edge locations
# --------------------------------------------------

edges = [
    {
        "id": "mumbai",
        "host": "edge-mumbai",
        "lat": 19.0760,
        "lon": 72.8777
    },
    {
        "id": "virginia",
        "host": "edge-virginia",
        "lat": 37.4316,
        "lon": -78.6569
    },
    {
        "id": "japan",
        "host": "edge-japan",
        "lat": 35.6762,
        "lon": 139.6503
    }
]

# --------------------------------------------------
# Default route for health check ("/")
# --------------------------------------------------


@app.get("/")
def root():
    return {
        "message": "Hello from the Geographic router",
        "edges": [edge["id"] for edge in edges]

    }



# --------------------------------------------------
# Haversine distance
# --------------------------------------------------

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two geographic
    coordinates using the Haversine formula.

    Returns distance in kilometers.
    """

    R = 6371  # Earth's radius in kilometers

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# --------------------------------------------------
# Find geographically closest Edge
# --------------------------------------------------

def find_closest_edge(client_lat, client_lon):

    closest_edge = None
    shortest_distance = float("inf")

    for edge in edges:

        distance = calculate_distance(
            client_lat,
            client_lon,
            edge["lat"],
            edge["lon"]
        )

        if distance < shortest_distance:
            shortest_distance = distance
            closest_edge = edge

    return closest_edge, shortest_distance


# --------------------------------------------------
# Route request
# --------------------------------------------------


@app.api_route(
    "/content/{content_id}",
    methods=["GET"]
)
async def route_request(
    content_id: str,
    request: Request
):

    
    # ----------------------------------------------
    # No location → fallback to Origin
    # ----------------------------------------------


    async def fallback_response(content_id: str):
        cache_key = f"content:{content_id}"

        cached_response = await fallback_redis.get(cache_key)

        if cached_response:
            return {
                "selected_edge": "fallback",
                "source": "cache",
                "data": json.loads(cached_response)
            }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://origin:8000/content/{content_id}"
            )

        origin_data = response.json()

        CACHE_TTL = 60

        await fallback_redis.set(
            cache_key,
            json.dumps(origin_data),
            ex=CACHE_TTL
        )

        return {
            "selected_edge": "fallback",
            "source": "origin",
            "data": origin_data
        }

    # ----------------------------------------------
    # Get client's geographic coordinates
    # ----------------------------------------------

    client_lat = request.query_params.get("lat")
    client_lon = request.query_params.get("lon")

    # No coordinates → fallback
    if client_lat is None or client_lon is None:
        return await fallback_response(content_id)

    # Invalid coordinates → fallback
    try:
        client_lat = float(client_lat)
        client_lon = float(client_lon)

    except ValueError:
        return await fallback_response(content_id)

    # ----------------------------------------------
    # Find closest Edge
    # ----------------------------------------------

    selected_edge, distance = find_closest_edge(
        client_lat,
        client_lon
    )


    # ----------------------------------------------
    # Forward request to selected Edge
    # ----------------------------------------------

    edge_url = (
        f"http://{selected_edge['host']}:8001"
        f"/content/{content_id}"
    )

    async with httpx.AsyncClient() as client:

        response = await client.get(
            edge_url,
            timeout=10.0
        )


    # ----------------------------------------------
    # Return Edge response
    # ----------------------------------------------
    edge_data = response.json()

    return {
    "selected_edge": selected_edge["id"],
    "distance_km": round(distance, 2),
    "source": edge_data["source"],
    "data": edge_data["data"]
}