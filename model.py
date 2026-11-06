from math import exp, factorial

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

    # Матрица вероятностей точных счетов
    matrix = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            matrix[(h, a)] = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_a)

    # Считаем базовые исходы (1X2)
    p_home = sum(p for (h, a), p in matrix.items() if h > a)
    p_draw = sum(p for (h, a), p in matrix.items() if h == a)
    p_away = sum(p for (h, a), p in matrix.items() if h < a)
    total_1x2 = p_home + p_draw + p_away
    
    # Смешиваем с Эло (если есть)
    if elo_home is not None and elo_away is not None:
        from elo import elo_to_probabilities
        e_h, e_d, e_a = elo_to_probabilities(elo_home, elo_away)
        w = WEIGHT_ELO
        p_home = (1 - w) * p_home + w * e_h
        p_draw = (1 - w) * p_draw + w * e_d
        p_away = (1 - w) * p_away + w * e_a
        total_1x2 = p_home + p_draw + p_away
        p_home, p_draw, p_away = p_home/total_1x2, p_draw/total_1x2, p_away/total_1x2

    # Считаем остальные рынки на основе матрицы счета
    p_btts_yes = sum(p for (h, a), p in matrix.items() if h > 0 and a > 0)
    
    p_total_over_05 = sum(p for (h, a), p in matrix.items() if h + a > 0.5)
    p_total_over_15 = sum(p for (h, a), p in matrix.items() if h + a > 1.5)
    p_total_over_25 = sum(p for (h, a), p in matrix.items() if h + a > 2.5)
    p_total_over_35 = sum(p for (h, a), p in matrix.items() if h + a > 3.5)

    p_it1_over_05 = sum(p for (h, a), p in matrix.items() if h > 0.5)
    p_it1_over_15 = sum(p for (h, a), p in matrix.items() if h > 1.5)
    p_it2_over_05 = sum(p for (h, a), p in matrix.items() if a > 0.5)
    p_it2_over_15 = sum(p for (h, a), p in matrix.items() if a > 1.5)

    p_1x = p_home + p_draw
    p_x2 = p_away + p_draw
    p_12 = p_home + p_away

    # Форы (Европейский гандикап)
    p_home_plus_15 = sum(p for (h, a), p in matrix.items() if h + 1.5 > a)
    p_away_plus_15 = sum(p for (h, a), p in matrix.items() if a + 1.5 > h)

    # Собираем все исходы в словарь для удобства
    all_markets = {
        "П1": p_home, "Х": p_draw, "П2": p_away,
        "1Х": p_1x, "Х2": p_x2, "12": p_12,
        "Обе забьют (Да)": p_btts_yes,
        "Тотал Б 0.5": p_total_over_05,
        "Тотал Б 1.5": p_total_over_15,
        "Тотал Б 2.5": p_total_over_25,
        "Тотал Б 3.5": p_total_over_35,
        "ИТ1 Б 0.5": p_it1_over_05,
        "ИТ1 Б 1.5": p_it1_over_15,
        "ИТ2 Б 0.5": p_it2_over_05,
        "ИТ2 Б 1.5": p_it2_over_15,
        "Фора 1 (+1.5)": p_home_plus_15,
        "Фора 2 (+1.5)": p_away_plus_15
    }

    # Фильтруем ставки с проходимостью >= 75% (самые безопасные)
    safe_bets = {k: round(v, 3) for k, v in all_markets.items() if v >= 0.75}

    return {
        "home": round(p_home, 3),
        "draw": round(p_draw, 3),
        "away": round(p_away, 3),
        "expected_score": f"{lam_h:.1f} : {lam_a:.1f}",
        "all_markets": {k: round(v, 3) for k, v in all_markets.items()},
        "safe_bets": safe_bets  # <--- Самые надежные ставки
    }