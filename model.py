import math

MAX_GOALS = 8
WEIGHT_ELO = 0.35

def pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def _matrix(lh, la, maxg=8, rho=-0.06):
    m = [[pois(i, lh) * pois(j, la) for j in range(maxg + 1)] for i in range(maxg + 1)]
    if rho:
        m[0][0] *= max(0.0, 1 - lh * la * rho)
        m[0][1] *= 1 + lh * rho
        m[1][0] *= 1 + la * rho
        m[1][1] *= 1 - rho
    s = sum(map(sum, m))
    return [[x / s for x in r] for r in m]

def predict(hs, as_, league_avg, elo_home=None, elo_away=None):
    home_att = (hs.goals_for / max(1, hs.matches_played)) / max(0.1, league_avg["home"])
    home_def = (hs.goals_against / max(1, hs.matches_played)) / max(0.1, league_avg["away"])
    away_att = (as_.goals_for / max(1, as_.matches_played)) / max(0.1, league_avg["away"])
    away_def = (as_.goals_against / max(1, as_.matches_played)) / max(0.1, league_avg["home"])

    lam_h = home_att * away_def * league_avg["home"]
    lam_a = away_att * home_def * league_avg["away"]

    M = _matrix(lam_h, lam_a)
    n = MAX_GOALS + 1
    
    p_home = sum(M[i][j] for i in range(n) for j in range(n) if i > j)
    p_draw = sum(M[i][i] for i in range(n))
    p_away = 1 - p_home - p_draw

    if elo_home is not None and elo_away is not None:
        from elo import elo_to_probabilities
        e_h, e_d, e_a = elo_to_probabilities(elo_home, elo_away)
        w = WEIGHT_ELO
        p_home = (1 - w) * p_home + w * e_h
        p_draw = (1 - w) * p_draw + w * e_d
        p_away = (1 - w) * p_away + w * e_a
        total_1x2 = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home/total_1x2, p_draw/total_1x2, p_away/total_1x2

    btts = sum(M[i][j] for i in range(1, n) for j in range(1, n))
    
    p_1x = p_home + p_draw
    p_x2 = p_away + p_draw
    p_12 = p_home + p_away

    all_markets = {
        "П1": p_home, "Х": p_draw, "П2": p_away,
        "1Х": p_1x, "Х2": p_x2, "12": p_12,
        "Обе забьют (Да)": btts,
        "Обе забьют (Нет)": 1 - btts,
    }

    for L in [0.5, 1.5, 2.5, 3.5]:
        over = sum(M[i][j] for i in range(n) for j in range(n) if i + j > L)
        all_markets[f"Тотал Б {L}"] = over
        all_markets[f"Тотал М {L}"] = 1 - over

    # Топ-3 вероятных счета
    flat = sorted(((M[i][j], f"{i}:{j}") for i in range(n) for j in range(n)), reverse=True)[:3]
    top_scores = ", ".join(f"{s} ({p:.0%})" for p, s in flat)

    safe_bets = {k: round(v, 3) for k, v in all_markets.items() if v >= 0.75}

    return {
        "home": round(p_home, 3),
        "draw": round(p_draw, 3),
        "away": round(p_away, 3),
        "expected_score": f"{lam_h:.1f} : {lam_a:.1f}",
        "top_scores": top_scores,
        "all_markets": {k: round(v, 3) for k, v in all_markets.items()},
        "safe_bets": safe_bets
    }