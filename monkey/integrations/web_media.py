"""Pictures, videos and weather.

- Images: Brave Search image API if a key is set, otherwise Wikimedia Commons (free, no key).
- Videos: YouTube Data API v3 (free daily quota with a Google API key).
- Weather: US National Weather Service API (free, no key).
"""
from __future__ import annotations

import time

import httpx

UA = {"User-Agent": "MonkeyDesktopAssistant/0.1"}


def brave_images(api_key: str, query: str, count: int) -> list[dict]:
    r = httpx.get(
        "https://api.search.brave.com/res/v1/images/search",
        params={"q": query, "count": count, "safesearch": "strict"},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for item in r.json().get("results", [])[:count]:
        out.append({
            "title": item.get("title", ""),
            "src": item.get("properties", {}).get("url") or item.get("thumbnail", {}).get("src", ""),
            "thumb": item.get("thumbnail", {}).get("src", ""),
            "page": item.get("url", ""),
        })
    return out


def commons_images(query: str, count: int) -> list[dict]:
    r = httpx.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": count, "prop": "imageinfo",
            "iiprop": "url", "iiurlwidth": 800,
        },
        headers=UA, timeout=15,
    )
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {})
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        out.append({
            "title": p.get("title", "").removeprefix("File:").rsplit(".", 1)[0],
            "src": info.get("thumburl") or info.get("url", ""),
            "thumb": info.get("thumburl", ""),
            "page": info.get("descriptionurl", ""),
        })
    return out


def youtube_search(api_key: str, query: str, count: int) -> list[dict]:
    r = httpx.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"part": "snippet", "type": "video", "maxResults": count, "q": query,
                "safeSearch": "moderate", "videoEmbeddable": "true", "key": api_key},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for item in r.json().get("items", []):
        vid = item["id"]["videoId"]
        sn = item["snippet"]
        out.append({
            "id": vid, "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "embed": f"https://www.youtube-nocookie.com/embed/{vid}",
        })
    return out


class NWSWeather:
    def __init__(self, lat_lon_getter):
        self._ll = lat_lon_getter
        self._points: tuple[tuple[float, float], dict] | None = None
        self._cache: tuple[float, dict] | None = None

    def __call__(self) -> dict:
        if self._cache and time.time() - self._cache[0] < 600:
            return self._cache[1]
        lat, lon = self._ll()
        if not self._points or self._points[0] != (lat, lon):
            r = httpx.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=UA, timeout=15)
            r.raise_for_status()
            self._points = ((lat, lon), r.json()["properties"])
        props = self._points[1]
        r = httpx.get(props["forecast"], headers=UA, timeout=15)
        r.raise_for_status()
        periods = r.json()["properties"]["periods"][:4]
        out = {
            "location": f"{props.get('relativeLocation', {}).get('properties', {}).get('city', '')}",
            "periods": [{"name": p["name"], "temp": f"{p['temperature']}°{p['temperatureUnit']}",
                         "wind": f"{p.get('windSpeed', '')} {p.get('windDirection', '')}".strip(),
                         "short": p["shortForecast"], "detail": p["detailedForecast"],
                         "icon": p.get("icon", "")} for p in periods],
        }
        self._cache = (time.time(), out)
        return out
