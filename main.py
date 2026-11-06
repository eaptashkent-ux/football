"""Прогноз матча: хоккей, волейбол, баскетбол, футбол.

Примеры:
  python main.py --sport football --home "Manchester City" --away "Brighton"
  python main.py --sport football --home "Manchester City" --away "Brighton" \
      --absent-home "De Bruyne:M" --absent-away "Welbeck:F?" --odds "1=1.45,X=5,2=7,btts_y=1.8,over_2.5=1.6"
  python main.py --demo --sport hockey --home "SKA" --away "CSKA"

Ключи (переменные окружения):  API_SPORTS_KEY, ODDS_API_KEY
"""
import argparse
import csv
import datetime as dt
import os
import sys

from models import ROLE_HELP, confidence, predict
from providers import ApiSports, Demo, ProviderError, fetch_odds

sys.stdout.reconfigure(encoding="utf-8")


def parse_absent(items):
    out = []
    for s in items or []:
        name, _, role = s.partition(":")
        doubt = role.endswith("?")
        out.append(dict(name=name.strip(), role=(role.rstrip("?").strip().upper() or "U"), doubt=doubt))
    return out


def parse_odds(s):
    out = {}
    for part in (s or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = float(v)
    return out


def form_line(ms):
    return " ".join("W" if m["gf"] > m["ga"] else "D" if m["gf"] == m["ga"] else "L" for m in ms[:6])


def market_probs(odds, primary):
    """Вероятности рынка основного исхода без маржи букмекера."""
    if not all(i in odds for i in primary):
        return {}
    inv = {i: 1 / odds[i] for i in primary}
    s = sum(inv.values())
    return {i: v / s for i, v in inv.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sport", required=True, choices=["football", "hockey", "basketball", "volleyball"])
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--n", type=int, default=10, help="сколько последних матчей брать (по умолч. 10)")
    ap.add_argument("--absent-home", action="append", metavar="ИМЯ:РОЛЬ", help="'?' в конце = под вопросом")
    ap.add_argument("--absent-away", action="append", metavar="ИМЯ:РОЛЬ")
    ap.add_argument("--odds", help="свои коэффициенты: 1=1.45,X=5,2=7,btts_y=1.8,over_2.5=1.6,ml_h=1.5")
    ap.add_argument("--league-key", help="ключ лиги The Odds API (soccer_epl, icehockey_nhl, basketball_nba) для автозагрузки кэфов")
    ap.add_argument("--line", type=float, action="append", default=[], help="доп. линия тотала")
    ap.add_argument("--demo", action="store_true", help="синтетические данные для проверки")
    ap.add_argument("--min-prob", type=float, default=0.65, help="порог для списка «сильных» исходов")
    a = ap.parse_args()

    key = os.environ.get("API_SPORTS_KEY")
    if a.demo or not key:
        if not a.demo:
            print("! Нет API_SPORTS_KEY - работаю на ДЕМО-данных (это не реальная форма команд).\n")
        src = Demo()
    else:
        src = ApiSports(key)

    try:
        hm, am = src.form(a.sport, a.home, a.n), src.form(a.sport, a.away, a.n)
        if not hm or not am:
            sys.exit("Нет завершённых матчей для одной из команд - прогноз невозможен.")
        ah, aa, note = src.absences(a.sport, a.home, a.away)
    except (ProviderError, Exception) as e:  # сеть, лимит, неверный ключ
        sys.exit(f"Ошибка загрузки данных: {e}")
    ah += parse_absent(a.absent_home)
    aa += parse_absent(a.absent_away)

    odds = parse_odds(a.odds)
    if a.league_key and os.environ.get("ODDS_API_KEY"):
        try:
            odds = {**fetch_odds(os.environ["ODDS_API_KEY"], a.league_key, a.sport, a.home, a.away), **odds}
        except Exception as e:
            print(f"! Коэффициенты не загружены: {e}")

    pred = predict(a.sport, hm, am, ah, aa, a.line)
    mk = pred["markets"]
    mprobs = market_probs(odds, pred["primary"])
    conf = confidence(pred, mprobs)

    print(f"=== {a.home} - {a.away}  [{a.sport}]  источник: {src.name}")
    print(f"Форма {a.home}: {form_line(hm)}  (в среднем {sum(m['gf'] for m in hm)/len(hm):.2f}:{sum(m['ga'] for m in hm)/len(hm):.2f})")
    print(f"Форма {a.away}: {form_line(am)}  (в среднем {sum(m['gf'] for m in am)/len(am):.2f}:{sum(m['ga'] for m in am)/len(am):.2f})")
    for side, lst in ((a.home, ah), (a.away, aa)):
        if lst:
            print(f"Отсутствуют у {side}: " + ", ".join(f"{p['name']} ({p['role']}{'?' if p.get('doubt') else ''})" for p in lst))
    print(note)
    print("Роли:", ROLE_HELP[a.sport])
    print()
    for line in pred["info"]:
        print(line)
    print("\nВсе рынки (вероятность по модели):")
    for i, (label, p) in sorted(mk.items(), key=lambda kv: -kv[1][1]):
        mark = ""
        if i in odds:
            edge = p * odds[i] - 1
            kelly = max(0.0, edge / (odds[i] - 1)) * 0.25
            mark = f"  кэф {odds[i]:.2f}  edge {edge:+.1%}" + (f"  ставка ≤ {min(kelly, 0.05):.1%} банка (¼ Келли)" if edge > 0.03 else "")
        print(f"  {p:6.1%}  {label}{mark}")

    strong = [(p, l) for l, p in mk.values() if p >= a.min_prob]
    print(f"\nИсходы с вероятностью ≥ {a.min_prob:.0%}: " + (", ".join(f"{l} ({p:.0%})" for p, l in sorted(strong, reverse=True)) or "нет"))
    level = "высокая" if conf >= 65 else "средняя" if conf >= 45 else "низкая"
    print(f"Надёжность прогноза: {conf}/90 ({level}) - зависит от объёма данных, чёткости перевеса и согласия с рынком.")
    if not odds:
        print("Коэффициенты не заданы: value-анализ (edge) не посчитан. Добавь --odds или --league-key.")
    print("\nЭто вероятности модели, а не гарантия: даже исход на 80% проигрывает в каждом пятом матче,"
          "\nа букмекеры закладывают маржу ~5%. Ставь только на положительный edge и не рискуй нужными деньгами.")

    with open(os.path.join(os.path.dirname(__file__), "predictions.csv"), "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for i, (label, p) in mk.items():
            w.writerow([dt.date.today(), a.sport, a.home, a.away, i, f"{p:.4f}", odds.get(i, "")])


if __name__ == "__main__":
    main()
