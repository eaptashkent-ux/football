from fastapi import FastAPI
from contextlib import asynccontextmanager
import httpx
import asyncio
import math

# Если db.py не нужен для этого теста, можно закомментировать
# from db import init_db

ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/"
LEAGUES = [
    ("football", "soccer/", "eng.1", "АПЛ"),
    ("football", "soccer/", "esp.1", "Ла Лига"),
    ("football", "soccer/", "ger.1", "Бундеслига"),
    ("football", "soccer/", "ita.1", "Серия А"),
    ("football", "soccer/", "fra.1", "Лига 1"),
    ("hockey", "hockey/", "nhl", "НХЛ"),
    ("basketball", "basketball/", "nba", "НБА"),
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    # await init_db()
    yield

# ВОТ ЭТА СТРОЧКА БЫЛА ПОТЕРЯНА!
app = FastAPI(lifespan=lifespan)

# --- МАТЕМАТИКА СТАВОК ---
def devig(odds):
    if not odds or not all(odds): return [0.33, 0.33, 0.34]
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]

def pmf(l, n=10):
    return [math.exp(-l) * l ** k / math.factorial(k) for k in range(n)]

def _res(lh, la, n=9):
    a, b = pmf(lh, n), pmf(la, n)
    w = d = 0.0
    for i in range(n):
        for j in range(n):
            p = a[i] * b[j]
            if i > j: w += p
            elif i == j: d += p
    return w, d

def fit_football(pH, pD, pA):
    def err(lh, la):
        w, d = _res(lh, la)
        return (w - pH) ** 2 + (d - pD) ** 2 + ((1 - w - d) - pA) ** 2
    best = (9, 1.3, 1.1)
    for i in range(3, 42):
        for j in range(3, 36):
            e = err(i * .1, j * .1)
            if e < best[0]: best = (e, i * .1, j * .1)
    return best[1], best[2]

def predict_football(odds):
    pH, pD, pA = devig([odds.get("h", 2.0), odds.get("d", 3.0), odds.get("a", 2.5)])
    lh, la = fit_football(pH, pD, pA)
    a, b = pmf(lh, 10), pmf(la, 10)
    w, d = 0, 0
    tot = [0]*20
    btts = 0
    for i in range(10):
        for j in range(10):
            p = a[i]*b[j]
            tot[i+j] += p
            if i > 0 and j > 0: btts += p

    markets = {
        "1": pH, "X": pD, "2": pA,
        "1X": pH + pD, "X2": pD + pA, "12": pH + pA,
        "Обе забьют (Да)": btts,
        "Тотал Б 0.5": sum(tot[1:]),
        "Тотал Б 1.5": sum(tot[2:]),
        "Тотал Б 2.5": sum(tot[3:]),
        "Тотал Б 3.5": sum(tot[4:]),
    }
    safe = {k: round(v, 2) for k, v in markets.items() if v >= 0.75}
    return {k: round(v, 2) for k, v in markets.items()}, safe

# --- ПОЛУЧЕНИЕ МАТЧЕЙ ---
async def fetch_espn_matches():
    matches = []
    async with httpx.AsyncClient() as client:
        for sport, path, lid, name in LEAGUES:
            try:
                url = f"{ESPN_API}{path}{lid}/scoreboard"
                r = await client.get(url, timeout=10)
                if r.status_code != 200: continue
                
                data = r.json()
                for event in data.get("events", []):
                    comp = event["competitions"][0]
                    status = event["status"]["type"]
                    
                    home_team = next(t for t in comp["competitors"] if t["homeAway"] == "home")
                    away_team = next(t for t in comp["competitors"] if t["homeAway"] == "away")
                    
                    odds_data = comp.get("odds", [{}])[0]
                    ml = odds_data.get("moneyline", {})
                    
                    def am_to_dec(am):
                        if not am: return None
                        try:
                            v = float(am.replace("+",""))
                            return 1 + v/100 if v > 0 else 1 + 100/abs(v)
                        except: return None

                    odds = {
                        "h": am_to_dec(ml.get("home", {}).get("close", {}).get("odds")),
                        "a": am_to_dec(ml.get("away", {}).get("close", {}).get("odds")),
                        "d": am_to_dec(ml.get("draw", {}).get("close", {}).get("odds")),
                    }

                    # Заглушка
                    if not odds["h"] or not odds["a"]:
                        odds["h"] = 1.8
                        odds["a"] = 4.0
                        odds["d"] = 3.5

                    all_markets, safe_bets = {}, {}
                    if sport == "football":
                        all_markets, safe_bets = predict_football(odds)
                    else:
                        all_markets = {"П1": 0.45, "П2": 0.55}

                    matches.append({
                        "id": int(event["id"]),
                        "homeTeam": home_team["team"]["displayName"],
                        "awayTeam": away_team["team"]["displayName"],
                        "league": name,
                        "kickoff": event["date"],
                        "homeScore": home_team.get("score", "0"),
                        "awayScore": away_team.get("score", "0"),
                        "status": status["state"], 
                        "detail": status.get("shortDetail", ""),
                        "odds": odds,
                        "markets": all_markets,
                        "safe_bets": safe_bets
                    })
            except Exception as e:
                print(f"Ошибка загрузки {name}: {e}")
    return matches

@app.get("/matches/today")
async def today_matches():
    matches = await fetch_espn_matches()
    order = {"in": 0, "pre": 1, "post": 2}
    matches.sort(key=lambda x: (order.get(x["status"], 3), x["kickoff"]))
    return matches