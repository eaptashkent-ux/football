from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
import asyncio

from db import init_db, Session, Team, Match, TeamStats, TeamElo
from api import LEAGUES, fetch_league_matches, parse_match
from elo import INITIAL_ELO, update_elo
from model import predict

# --- ФУНКЦИИ СИНХРОНИЗАЦИИ ---
async def perform_sync(season=2026):
    print(f"[АВТО] Скачиваю матчи сезона {season}...")
    async with Session() as s:
        total = 0
        for code in LEAGUES:
            try:
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
            except Exception as e:
                print(f"Ошибка лиги {code}: {e}")
            await asyncio.sleep(7)
    print(f"[АВТО] Скачано матчей: {total}")

async def perform_rebuild():
    print("[АВТО] Пересчитываю математику (Эло)...")
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

# --- ФОНОВЫЙ ПРОЦЕСС (РАБОТАЕТ САМ) ---
async def daily_updater():
    while True:
        try:
            # Проверяем, есть ли в базе матчи на будущее
            async with Session() as s:
                tomorrow = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
                future_match = (await s.execute(select(Match).where(Match.kickoff >= tomorrow).limit(1))).scalars().first()
            
            # Если будущих матчей нет, значит база устарела (или пустая) - обновляем!
            if not future_match:
                await perform_sync(2026)
                await perform_rebuild()
        except Exception as e:
            print(f"Ошибка автообновления: {e}")
        
        # Ждем 12 часов и проверяем снова
        await asyncio.sleep(12 * 3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Запускаем фоновый автообновлятор
    asyncio.create_task(daily_updater())
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/matches/today")
async def today_matches():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start_date = now - timedelta(days=1)
    
    async with Session() as s:
        rows = (await s.execute(
            select(Match).where(Match.kickoff >= start_date).order_by(Match.kickoff)
        )).scalars().all()
        teams = {t.id: t.name for t in (await s.execute(select(Team))).scalars()}
        
    return [{
        "id": m.id, "homeTeam": teams.get(m.home_id), "awayTeam": teams.get(m.away_id), 
        "league": m.league, "kickoff": m.kickoff.isoformat() if m.kickoff else None
    } for m in rows]

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