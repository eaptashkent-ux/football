elo_code = '''from datetime import datetime

INITIAL_ELO = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 100.0

def update_elo(elo_home, elo_away, home_goals, away_goals):
    expected_home = 1.0 / (1.0 + 10 ** ((elo_away - (elo_home + HOME_ADVANTAGE)) / 400.0))
    if home_goals > away_goals: actual_home = 1.0
    elif home_goals == away_goals: actual_home = 0.5
    else: actual_home = 0.0
    gd = abs(home_goals - away_goals)
    gd_mult = 1.0 if gd <= 1 else (1.5 if gd == 2 else 1.75 + (gd - 3) / 8.0)
    change = K_FACTOR * gd_mult * (actual_home - expected_home)
    return elo_home + change, elo_away - change

def elo_to_probabilities(elo_home, elo_away):
    diff = elo_home + HOME_ADVANTAGE - elo_away
    exp_home = 1.0 / (1.0 + 10 ** (-diff / 400.0))
    p_draw = 0.30 * (2.718 ** (-abs(diff) / 400.0))
    p_home = max(0.01, exp_home - 0.5 * p_draw)
    p_away = max(0.01, (1.0 - exp_home) - 0.5 * p_draw)
    p_draw = max(0.01, p_draw)
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total
'''

model_code = '''from math import exp, factorial

MAX_GOALS = 7
WEIGHT_ELO = 0.35

def poisson_pmf(k, lam):
    return exp(-lam) * (lam ** k) / factorial(k)

def predict(hs, as_, league_avg, elo_home=None, elo_away=None):
    home_att = (hs.goals_for / max(1, hs.matches_played)) / max(0.1, league_avg["home"])
    home_def = (hs.goals_against / max(1, hs.matches_played)) / max(0.1, league_avg["away"])
    away_att = (as_.goals_for / max(1, as_.matches_played)) / max(0.1, league_avg["away"])
    away_def = (as_.goals_against / max(1, as_.matches_played)) / max(0.1, league_avg["home"])

    lam_h = home_att * away_def * league_avg["home"]
    lam_a = away_att * home_def * league_avg["away"]

    p_h = p_d = p_a = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_a)
            if h > a: p_h += p
            elif h == a: p_d += p
            else: p_a += p
    total = p_h + p_d + p_a
    ph, pd, pa = p_h/total, p_d/total, p_a/total

    if elo_home is not None and elo_away is not None:
        from elo import elo_to_probabilities
        e_h, e_d, e_a = elo_to_probabilities(elo_home, elo_away)
        w = WEIGHT_ELO
        ph = (1 - w) * ph + w * e_h
        pd = (1 - w) * pd + w * e_d
        pa = (1 - w) * pa + w * e_a
        total = ph + pd + pa
        ph, pd, pa = ph/total, pd/total, pa/total

    return {
        "home": round(ph, 3), "draw": round(pd, 3), "away": round(pa, 3),
        "expected_score": f"{lam_h:.1f} : {lam_a:.1f}",
        "elo_home": round(elo_home, 0) if elo_home else None,
        "elo_away": round(elo_away, 0) if elo_away else None
    }
'''

main_code = '''from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from sqlalchemy import select, and_
import asyncio

from db import init_db, Session, Team, Match, TeamStats, TeamElo
from api import LEAGUES, fetch_league_matches, parse_match
from elo import INITIAL_ELO, update_elo
from model import predict

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/admin/sync")
async def sync_season(season: int = 2024):
    async with Session() as s:
        total = 0
        for code in LEAGUES:
            raw = await fetch_league_matches(code, season)
            for m in raw:
                pm = parse_match(m, code)
                for tid, tname in [(pm["home_id"], pm["home_name"]), (pm["away_id"], pm["away_name"])]:
                    if not await s.get(Team, tid):
                        s.add(Team(id=tid, name=tname, league=code))
                existing = await s.get(Match, pm["id"])
                if existing:
                    existing.home_goals = pm["home_goals"]
                    existing.away_goals = pm["away_goals"]
                    existing.status = pm["status"]
                else:
                    s.add(Match(**{k: pm[k] for k in ("id","home_id","away_id","league","kickoff","home_goals","away_goals","status")}))
                total += 1
            await s.commit()
            await asyncio.sleep(7)
    return {"ok": True, "matches_loaded": total}

@app.post("/admin/rebuild")
async def rebuild():
    async with Session() as s:
        matches = (await s.execute(select(Match).where(Match.home_goals.is_not(None)).order_by(Match.kickoff))).scalars().all()
        elo_map = {}
        stats_map = {}
        for m in matches:
            for tid in (m.home_id, m.away_id):
                elo_map.setdefault(tid, INITIAL_ELO)
                stats_map.setdefault((tid, m.league), {"matches": 0, "gf": 0, "ga": 0})
            
            new_h, new_a = update_elo(elo_map[m.home_id], elo_map[m.away_id], m.home_goals, m.away_goals)
            elo_map[m.home_id], elo_map[m.away_id] = new_h, new_a
            
            for tid, gf, ga in ((m.home_id, m.home_goals, m.away_goals), (m.away_id, m.away_goals, m.home_goals)):
                d = stats_map[(tid, m.league)]
                d["matches"] += 1; d["gf"] += gf; d["ga"] += ga

        for tid, elo in elo_map.items():
            row = await s.get(TeamElo, tid)
            if row: row.elo = elo
            else: s.add(TeamElo(team_id=tid, elo=elo))

        for (tid, lg), d in stats_map.items():
            row = await s.get(TeamStats, (tid, lg))
            if row:
                row.matches_played, row.goals_for, row.goals_against = d["matches"], d["gf"], d["ga"]
            else:
                s.add(TeamStats(team_id=tid, league=lg, matches_played=d["matches"], goals_for=d["gf"], goals_against=d["ga"]))
        await s.commit()
    return {"ok": True, "matches_processed": len(matches), "teams_updated": len(elo_map)}

@app.get("/matches/today")
async def today_matches():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with Session() as s:
        rows = (await s.execute(select(Match).where(Match.kickoff >= now).order_by(Match.kickoff).limit(20))).scalars().all()
        teams = {t.id: t.name for t in (await s.execute(select(Team))).scalars()}
    return [{"id": m.id, "homeTeam": teams.get(m.home_id), "awayTeam": teams.get(m.away_id), "league": m.league, "kickoff": m.kickoff.isoformat()} for m in rows]

@app.get("/matches/{match_id}/analysis")
async def analysis(match_id: int):
    async with Session() as s:
        m = await s.get(Match, match_id)
        if not m: raise HTTPException(404, "match not found")
        hs = await s.get(TeamStats, (m.home_id, m.league))
        as_ = await s.get(TeamStats, (m.away_id, m.league))
        elo_h = await s.get(TeamElo, m.home_id)
        elo_a = await s.get(TeamElo, m.away_id)

        all_stats = (await s.execute(select(TeamStats).where(TeamStats.league == m.league))).scalars().all()
        total_m = sum(t.matches_played for t in all_stats) or 1
        avg_gf = sum(t.goals_for for t in all_stats) / total_m
        league_avg = {"home": avg_gf * 0.55, "away": avg_gf * 0.45}

    if not hs or not as_ or hs.matches_played == 0:
        raise HTTPException(400, "not enough data")

    pred = predict(hs, as_, league_avg, elo_h.elo if elo_h else None, elo_a.elo if elo_a else None)
    return {"match_id": match_id, "prediction": pred}
'''

with open("elo.py", "w", encoding="utf-8") as f: f.write(elo_code)
with open("model.py", "w", encoding="utf-8") as f: f.write(model_code)
with open("main.py", "w", encoding="utf-8") as f: f.write(main_code)
print("Мозг успешно установлен! Файлы обновлены.")