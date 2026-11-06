code = '''from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint

Base = declarative_base()
engine = create_async_engine("sqlite+aiosqlite:///football.db")
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    league = Column(String, nullable=False)

class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    home_id = Column(Integer, ForeignKey("teams.id"))
    away_id = Column(Integer, ForeignKey("teams.id"))
    league = Column(String)
    kickoff = Column(DateTime)
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    status = Column(String, default="SCHEDULED")

class TeamStats(Base):
    __tablename__ = "team_stats"
    team_id = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    league = Column(String, primary_key=True)
    matches_played = Column(Integer, default=0)
    goals_for = Column(Integer, default=0)
    goals_against = Column(Integer, default=0)
    recent_matches = Column(Integer, default=0)
    recent_weighted_gf = Column(Float, default=0.0)
    recent_weighted_ga = Column(Float, default=0.0)

class TeamElo(Base):
    __tablename__ = "team_elo"
    team_id = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    elo = Column(Float, default=1500.0)
    matches_played = Column(Integer, default=0)
    last_update = Column(DateTime, nullable=True)

class TeamAlias(Base):
    __tablename__ = "team_aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    alias = Column(String, nullable=False)
    alias_normalized = Column(String, nullable=False, index=True)
    source = Column(String, default="auto")
    __table_args__ = (UniqueConstraint("team_id", "alias_normalized", name="uq_team_alias"),)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)'''

with open("db.py", "w", encoding="utf-8") as f:
    f.write(code)