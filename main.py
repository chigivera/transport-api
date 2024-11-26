from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openrouteservice as ors
import requests
from bs4 import BeautifulSoup
import datetime
import folium
from fastapi.responses import JSONResponse
import os

app = FastAPI()

# Initialize ORS client
ors_client = ors.Client(key='5b3ce3597851110001cf6248903814bdbe7a40ffa6e8e9005e290f43')  # Replace with a valid API key

# Helper functions
def calculate_fuel_consumption(distance_km, profile, fuel_type):
    rates = {
        "driving-hgv": {"diesel": 40, "gasoline": 50},
        "driving-car": {"diesel": 5, "gasoline": 6.5},
    }
    return (distance_km / 100) * rates[profile][fuel_type]

def fetch_fuel_prices(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        div_element = soup.find("div", id="graphPageLeft")
        fuel_prices = {}
        if div_element:
            first_table = div_element.find("table")
            if first_table:
                for row in first_table.find("tbody").find_all("tr"):
                    fuel_type = row.find("a").text.strip()
                    mad_price = row.find_all("td")[1].text.strip()
                    fuel_prices[fuel_type] = mad_price
        return fuel_prices
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

class RouteRequest(BaseModel):
    start_location: str
    end_location: str
    profile: str
    fuel_type: str

@app.post("/calculate-route/")
def calculate_route(data: RouteRequest):
    try:
        # Geocode the start and end locations
        start = ors_client.pelias_search(text=data.start_location)['features'][0]['geometry']['coordinates']
        end = ors_client.pelias_search(text=data.end_location)['features'][0]['geometry']['coordinates']

        # Define vehicle and delivery jobs
        vehicles = [ors.optimization.Vehicle(id=0, profile=data.profile, start=start)]
        deliveries = [ors.optimization.Job(id=0, location=end)]

        # Make optimization request
        result = ors_client.optimization(vehicles=vehicles, jobs=deliveries, geometry=True)

        # Extract route distance and duration
        route_distance_km = result['routes'][0]['distance'] / 1000  # Convert meters to kilometers
        route_duration_sec = result['routes'][0]['duration']       # Duration in seconds
        route_duration = str(datetime.timedelta(seconds=route_duration_sec))  # Convert to HH:MM:SS format

        # Fetch fuel prices
        fuel_prices_url = "https://www.globalpetrolprices.com/Morocco/"
        fuel_prices = fetch_fuel_prices(fuel_prices_url)
        if "error" in fuel_prices:
            raise HTTPException(status_code=500, detail=fuel_prices["error"])
        
        # Get fuel price for the given type
        fuel_price = float(fuel_prices.get(f"{data.fuel_type.title()} prices", "0").replace(",", "."))
        if fuel_price == 0:
            raise HTTPException(status_code=400, detail="Fuel price not found")

        # Calculate transport cost
        consumption = calculate_fuel_consumption(route_distance_km, data.profile, data.fuel_type)
        cost = consumption * fuel_price

        # Create a map using Folium
        map_file = "route_map.html"
        m = folium.Map(location=list(reversed(start)), zoom_start=12)
        folium.Marker(location=list(reversed(start)), icon=folium.Icon(color="red", icon="car", prefix='fa')).add_to(m)
        folium.Marker(location=list(reversed(end)), icon=folium.Icon(color="green", icon="car", prefix='fa')).add_to(m)

        # Add routes to the map
        decoded = ors.convert.decode_polyline(result['routes'][0]['geometry'])
        folium.PolyLine(locations=[list(reversed(coord)) for coord in decoded['coordinates']], color="blue").add_to(m)

        # Save the map to an HTML file
        m.save(map_file)

        # Construct the iframe
        iframe_html = f"<iframe src='{map_file}' width='100%' height='600' style='border:none;'></iframe>"

        # Return response
        return {
            "distance_km": round(route_distance_km, 2),
            "duration": route_duration,
            "transport_cost_mad": round(cost, 2),
            "map_iframe": iframe_html  # Add iframe HTML as a field
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def read_root():
    return {"message": "Welcome to the Transport Cost API"}
