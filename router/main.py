from fastapi import FastAPI, Request, HTTPException
import httpx
import math
import redis.asyncio as redis
import json
import geoip2.database
import geoip2.errors
import os
    
app = FastAPI()

ORIGIN_HOST = os.getenv("ORIGIN_HOST", "origin")

geoip_reader = geoip2.database.Reader(
    "router/geoip/GeoLite2-City.mmdb"
)

fallback_redis = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)
@app.get("/ip")
async def get_client_ip(request: Request):
    client_ip = request.headers.get("X-Real-IP")

    return {
        "client_ip": client_ip
    }

def get_location_from_ip(client_ip):

    try:
        response = geoip_reader.city(client_ip)

        latitude = response.location.latitude
        longitude = response.location.longitude

        return latitude, longitude

    except geoip2.errors.AddressNotFoundError:
        return None, None
    
# --------------------------------------------------
# CDN Edge locations
# --------------------------------------------------

edges = [
    {
        "id": "mumbai",
        "host": "35.154.233.143",
        "lat": 19.0760,
        "lon": 72.8777
    },
    {
        "id": "virginia",
        "host": "184.192.2.185",
        "lat": 37.4316,
        "lon": -78.6569
    },
    {
        "id": "japan",
        "host": "54.92.8.201",
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
    f"http://52.78.19.134:8000/content/{content_id}"
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

@app.api_route(
    "/content/{content_id}",
    methods=["GET"]
)
async def route_request(
    content_id: str,
    request: Request
):

    
    
    client_ip = request.headers.get("X-Real-IP")

    # Development/testing override
    test_ip = request.query_params.get("test_ip")

    if test_ip:
        client_ip = test_ip

    # No IP → fallback
    if client_ip is None:
        return await fallback_response(content_id)

    # ----------------------------------------------
    # Convert IP → geographic coordinates
    # ----------------------------------------------

    client_lat, client_lon = get_location_from_ip(client_ip)
    
    if client_lat is None or client_lon is None:
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