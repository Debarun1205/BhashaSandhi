"""Tools behind intent routing: time, weather (Open-Meteo, no API key) and a grounded FAQ."""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = ZoneInfo(os.getenv("APP_TZ", "Asia/Kolkata"))
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Haldia")

TIME_WORDS = ["time", "date", "what day", "समय", "टाइम", "तारीख", "कितने बजे", "आज की तारीख",
              "সময়", "কয়টা বাজে", "তারিখ", "ସମୟ", "ତାରିଖ", "କେତେ ବାଜିଲା"]

WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "thunderstorm", 96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def keyword_intent(text: str) -> str | None:
    t = text.lower()
    return "time" if any(w in t for w in TIME_WORDS) else None


def time_info() -> str:
    now = datetime.now(TZ)
    return (f"Current local time in India: {now.strftime('%I:%M %p')}. "
            f"Date: {now.strftime('%A, %d %B %Y')}.")


def weather_info(city: str | None) -> str:
    city = (city or DEFAULT_CITY).strip()
    try:
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": city, "count": 1}, timeout=8).json()
        if not g.get("results"):
            return f"Could not find a place called '{city}'. Tell the user the city was not found."
        place = g["results"][0]
        w = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        }, timeout=8).json()["current"]
        return (f"Weather in {place['name']}: {WEATHER_CODES.get(w['weather_code'], 'unsettled')}, "
                f"temperature {round(w['temperature_2m'])} degrees Celsius, humidity "
                f"{round(w['relative_humidity_2m'])} percent, wind {round(w['wind_speed_10m'])} km/h.")
    except Exception:
        return "The weather service could not be reached. Tell the user weather is unavailable right now."


def faq_info(text: str) -> str | None:
    """Return the best-matching FAQ answer (English facts) or None."""
    try:
        with open(os.path.join(BASE, "faq.json"), encoding="utf-8") as f:
            items = json.load(f)
    except OSError:
        return None
    t = text.lower()
    best, score = None, 0
    for item in items:
        s = sum(1 for k in item["keywords"] if k.lower() in t)
        if s > score:
            best, score = item, s
    if best:
        return best["answer"]
    # No keyword hit: give the model the whole FAQ as grounding.
    return " ".join(i["answer"] for i in items)


def run_tool(intent: str, text: str, city: str | None = None) -> str | None:
    if intent == "time":
        return time_info()
    if intent == "weather":
        return weather_info(city)
    if intent == "faq":
        return faq_info(text)
    return None
