import httpx, os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": os.getenv("FOOTBALL_API_KEY", "")}

LEAGUES = {
    "PL":  "Premier League",
    "BL1": "Bundesliga",
    "SA":  "Serie A",
    "PD":  "La Liga",
    "FL1": "Ligue 1",
    "CL":  "Champions League",
}

async def fetch_league_matches(code: str, season: int | None = None):
    params = {"season": season} if season else {}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/competitions/{code}/matches", headers=HEADERS, params=params)
        if r.status_code != 200:
            print(f"Ошибка {code}: {r.status_code} {r.text}")
            return []
        return r.json().get("matches", [])

def parse_match(m: dict, league_code: str) -> dict:
    score = m.get("score", {}).get("fullTime", {})
    return {
        "id": m["id"],
        "home_id": m["homeTeam"]["id"],
        "home_name": m["homeTeam"]["name"],
        "away_id": m["awayTeam"]["id"],
        "away_name": m["awayTeam"]["name"],
        "league": league_code,
        "kickoff": datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).replace(tzinfo=None),
        "home_goals": score.get("home"),
        "away_goals": score.get("away"),
        "status": m["status"],
    }