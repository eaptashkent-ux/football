from datetime import datetime

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
