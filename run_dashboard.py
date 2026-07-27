"""
run_dashboard.py - Analiza MLB HOY y abre el dashboard en el navegador
Uso: python run_dashboard.py
Genera dashboard_live.html con datos embebidos (base64) y lo abre automaticamente.
"""
import os, sys, json, webbrowser
from datetime import datetime

PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)

os.chdir(PROJ)
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJ, ".env"))
from src.main import BaseballAnalyzer
from src.data_fetcher import ProtocolDataFetcher

# ================================================================
# 1. CORRE ANALISIS
# ================================================================
print("=" * 60)
print("  MLB PROTOCOLO V2.6 - DASHBOARD EN VIVO")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

analyzer = BaseballAnalyzer()
fetcher = ProtocolDataFetcher()

games = fetcher.get_daily_games()
if not games:
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    games = fetcher.get_daily_games(yesterday)
    print(f"\n  (No hay juegos hoy, usando ayer: {yesterday})")

if not games:
    print("\n[ERROR] No hay juegos disponibles.")
    sys.exit(1)

print(f"\n  Juegos encontrados: {len(games)}")

all_results = []
for g in games:
    gid = g["game_id"]
    status = g["status"]
    print(f"\n  [{gid}] {g['away_team']} @ {g['home_team']} ({status})")

    if status not in ("Scheduled", "Preview", "Pre-Game"):
        print(f"    Status: {status} - saltando")
        continue

    if g.get("away_pitcher", "TBD") == "TBD" or g.get("home_pitcher", "TBD") == "TBD":
        print(f"    [SKIP] Pitchers TBD")
        continue

    print(f"    Pitchers: {g['away_pitcher']} vs {g['home_pitcher']}")

    result = analyzer.analyze_game(gid)
    if "error" in result:
        print(f"    [INFO] {result['error']}")
        result["game"] = f"{g['away_team']} @ {g['home_team']}"
        result["partial"] = True
        all_results.append(result)
        continue

    score = result["score"]
    sweet = result["sweet_spot"]
    pp = result["markets"]["player_props"]
    edges = pp.get("market_edges", [])
    signals = pp.get("players", [])
    edge_str = f", {len(edges)} edges" if edges else ""
    sig_str = f", {len(signals)} senales" if signals else ""
    print(f"    Score: {score}{' [SWEET SPOT]' if sweet else ''}{edge_str}{sig_str}")
    result["game"] = f"{g['away_team']} @ {g['home_team']}"
    all_results.append(result)

total_edges = sum(len(r["markets"]["player_props"].get("market_edges", [])) for r in all_results if not r.get("partial"))
total_signals = sum(len(r["markets"]["player_props"].get("players", [])) for r in all_results if not r.get("partial"))

# ================================================================
# AUTO-PARLEY GENERATOR
# Genera las mejores combinaciones de 2 a 6 legs
# ================================================================
import math

def decimal_odds(american):
    """American -> decimal"""
    if american >= 0:
        return 1 + american / 100.0
    else:
        return 1 + 100.0 / abs(american)

def implied_prob(american):
    """American -> implied probability"""
    if american >= 0:
        return 100.0 / (american + 100)
    else:
        return abs(american) / (abs(american) + 100.0)

def _parse_ev(ev_str):
    if not ev_str:
        return 0
    try:
        return float(str(ev_str).replace("%", ""))
    except:
        return 0

def _underdog_team(game, markets):
    """Return the underdog team name from game string + market data."""
    ml = markets.get("money_line", {})
    fair_odds = ml.get("fair_odds", 0) or 0
    parts = game.split(" @ ")
    if len(parts) != 2:
        return parts[0] if parts else "N/A"
    away, home = parts[0], parts[1]
    # fair_odds < 0 => home favorite => away underdog
    # fair_odds > 0 => home underdog
    return away if fair_odds < 0 else home

def generate_auto_parleys(results):
    """Generate optimal parley combinations from ALL approved markets.
    
    Priority: RL +1.5 > Totales > ML underdog >> Player props (only >=10pp edge).
    """
    all_legs = []

    for r in results:
        if r.get("partial"):
            continue
        game = r.get("game", "Juego")
        markets = r.get("markets", {})
        protocol_score = r.get("score", 0)

        # ================================================================
        # 1. RUNLINE +1.5 - Primary parley leg (backtest: 80% WR)
        # ================================================================
        rl = markets.get("runline_plus_1_5", {})
        if rl.get("decision") == "APROBADO":
            rl_ev = _parse_ev(rl.get("ev"))
            underdog = rl.get("side") or _underdog_team(game, markets)
            if rl_ev > 0:
                odds_dec = decimal_odds(-135)
                win_prob = (1 + rl_ev / 100.0) / odds_dec
                all_legs.append({
                    "game": game,
                    "label": f"{underdog} RL +1.5",
                    "odds": -135,
                    "odds_decimal": round(odds_dec, 2),
                    "ev_pct": rl_ev,
                    "edge_pct": rl_ev,
                    "rec": "BET" if rl_ev >= 5 else ("STRONG BET" if rl_ev >= 8 else "WEAK"),
                    "win_prob": round(win_prob, 4),
                    "bookmaker": "",
                    "type": "rl",
                    "protocol_score": protocol_score,
                })

        # ================================================================
        # 2. TOTALES - Over/Under
        # ================================================================
        for side, mkt in [("Over", "total_over"), ("Under", "total_under")]:
            t = markets.get(mkt, {})
            t_ev = _parse_ev(t.get("ev"))
            line = t.get("line", 8.5)
            if t.get("decision") == "APROBADO" and t_ev > 0:
                odds_dec = decimal_odds(-110)
                win_prob = (1 + t_ev / 100.0) / odds_dec
                all_legs.append({
                    "game": game,
                    "label": f"{side} {line}",
                    "odds": -110,
                    "odds_decimal": round(odds_dec, 2),
                    "ev_pct": t_ev,
                    "edge_pct": t_ev,
                    "rec": "BET" if t_ev >= 5 else ("STRONG BET" if t_ev >= 8 else "WEAK"),
                    "win_prob": round(win_prob, 4),
                    "bookmaker": "",
                    "type": "total",
                    "protocol_score": protocol_score,
                })

        # ================================================================
        # 3. MONEY LINE - Sin sesgo, usa el side del modelo
        # ================================================================
        ml = markets.get("money_line", {})
        ml_ev = _parse_ev(ml.get("ev"))
        fair_odds = ml.get("fair_odds", 0) or 0
        if ml.get("decision") == "APROBADO":
            ml_side = ml.get("side") or _underdog_team(game, markets)
            odds_dec = decimal_odds(fair_odds)
            win_prob = ml.get("win_pct", 0) or 0.5
            all_legs.append({
                "game": game,
                "label": f"{ml_side} ML",
                "odds": fair_odds,
                "odds_decimal": round(odds_dec, 2),
                "ev_pct": ml_ev if ml_ev > 0 else 5.0,
                "edge_pct": ml_ev if ml_ev > 0 else 5.0,
                "rec": "BET",
                "win_prob": round(win_prob, 4),
                "bookmaker": "Fair odds",
                "type": "ml",
                "protocol_score": protocol_score,
            })

        # ================================================================
        # 4. PLAYER PROPS - ONLY if edge >= 10pp (muy muy bueno)
        # ================================================================
        pp = markets.get("player_props", {})
        edges = pp.get("market_edges", [])
        for e in edges:
            edge_pct = e.get("edge_pct", 0)
            if edge_pct >= 10:  # Solo edges excepcionales
                ev_pct = e.get("ev_pct", 0)
                odds = e.get("odds", 0)
                if ev_pct > 0:
                    win_prob = (1 + ev_pct / 100.0) / decimal_odds(odds)
                    all_legs.append({
                        "game": game,
                        "label": f"{e['pitcher']} {e['side']} {e['line']}K",
                        "odds": odds,
                        "odds_decimal": round(decimal_odds(odds), 2),
                        "ev_pct": ev_pct,
                        "edge_pct": edge_pct,
                        "rec": "STRONG BET",
                        "win_prob": round(win_prob, 4),
                        "bookmaker": e.get("bookmaker", ""),
                        "type": "edge",
                        "protocol_score": protocol_score,
                    })

    if len(all_legs) < 2:
        return []

    # Sort: protocol_score desc, then EV desc (game confidence first)
    all_legs.sort(key=lambda x: (x.get("protocol_score", 0), x["ev_pct"]), reverse=True)

    auto_parleys = []

    # Helper to compute combined odds/EV for a set of legs
    def _compute_parley(legs):
        dec = 1.0
        win = 1.0
        for leg in legs:
            dec *= leg["odds_decimal"]
            if leg["win_prob"] > 0:
                win *= leg["win_prob"]
        ev = round((dec * win - 1) * 100, 1) if win < 1 else 0
        american = round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))
        american_str = f"+{american}" if american > 0 else str(american)
        return dec, win, ev, american_str

    # Generate only the best 3 parleys:
    # 1. Top 2 legs (best overall)
    # 2. Diverso 3 legs (max 1 per game, 3 legs)
    # 3. Diverso 4 legs (if enough legs)

    # Top 2
    if len(all_legs) >= 2:
        top2 = all_legs[:2]
        dec, win, ev, odds_str = _compute_parley(top2)
        stars = 5 if all(l["rec"] == "STRONG BET" for l in top2) else (
                4 if all(l["rec"] in ("STRONG BET", "BET") for l in top2) else 3)
        if ev > 0:
            auto_parleys.append({
                "n": 2, "label": "Top 2 legs", "odds": odds_str,
                "odds_decimal": round(dec, 2), "ev_pct": ev, "stars": stars,
                "legs": [{"label": l["label"], "game": l["game"], "odds": l["odds"],
                           "odds_decimal": l["odds_decimal"], "ev_pct": l["ev_pct"],
                           "edge_pct": l["edge_pct"], "type": l["type"]} for l in top2],
            })

    # Diverso: max 1 leg per game
    used_games = set()
    diverse_legs = []
    for leg in all_legs:
        if leg["game"] not in used_games:
            diverse_legs.append(leg)
            used_games.add(leg["game"])

    # Diverso 3 legs
    if len(diverse_legs) >= 3:
        d3 = diverse_legs[:3]
        dec, win, ev, odds_str = _compute_parley(d3)
        if ev > 0:
            auto_parleys.append({
                "n": 3, "label": "Diverso 3 legs", "odds": odds_str,
                "odds_decimal": round(dec, 2), "ev_pct": ev, "stars": 5,
                "legs": [{"label": l["label"], "game": l["game"], "odds": l["odds"],
                           "odds_decimal": l["odds_decimal"], "ev_pct": l["ev_pct"],
                           "edge_pct": l["edge_pct"], "type": l["type"]} for l in d3],
            })

    # Diverso 4 legs (if enough legs)
    if len(diverse_legs) >= 4:
        d4 = diverse_legs[:4]
        dec, win, ev, odds_str = _compute_parley(d4)
        if ev > 0:
            auto_parleys.append({
                "n": 4, "label": "Diverso 4 legs", "odds": odds_str,
                "odds_decimal": round(dec, 2), "ev_pct": ev, "stars": 4,
                "legs": [{"label": l["label"], "game": l["game"], "odds": l["odds"],
                           "odds_decimal": l["odds_decimal"], "ev_pct": l["ev_pct"],
                           "edge_pct": l["edge_pct"], "type": l["type"]} for l in d4],
            })

    # Sort: best EV first
    auto_parleys.sort(key=lambda x: x["ev_pct"], reverse=True)
    return auto_parleys[:3]  # Max 3 parleys

auto_parleys = generate_auto_parleys(all_results)
if auto_parleys:
    print(f"\n  Parleys automaticos generados: {len(auto_parleys)}")
    for ap in auto_parleys[:5]:
        print(f"    [{ap['stars']}*] {ap['label']}: {ap['odds']} (EV {ap['ev_pct']}%)")
else:
    print("\n  No hay suficientes picks para parleys automaticos.")

# ================================================================
# 2. GENERA DASHBOARD HTML
# ================================================================
print("\n  Generando dashboard...")

dashboard_path = os.path.join(PROJ, "dashboard.html")
out_path = os.path.join(PROJ, "dashboard_live.html")

if not os.path.exists(dashboard_path):
    print("[ERROR] dashboard.html no encontrado")
    sys.exit(1)

with open(dashboard_path, "r", encoding="utf-8") as f:
    html = f.read()

analysis_data = {
    "timestamp": datetime.now().isoformat(),
    "protocol": "V2.6 - Score System 7 Componentes + Player Props",
    "total_games": len(all_results),
    "total_edges": total_edges,
    "total_signals": total_signals,
    "odds_remaining": analyzer.props.odds.get_remaining(),
    "results": all_results,
    "auto_parleys": auto_parleys,
}
# Write data to separate JS file (avoids HTML escaping issues entirely)
data_js_path = os.path.join(PROJ, "dashboard_data.js")
with open(data_js_path, "w", encoding="utf-8") as f:
    f.write("var __EMBEDDED_DATA__ = ")
    json.dump(analysis_data, f, ensure_ascii=False)
    f.write(";\n")
print(f"  Datos guardados: {data_js_path}")

# Add script tag for data file right before the main script
html = html.replace('<script>', '<script src="dashboard_data.js"></script>\n<script>')

# Set data variable in main script
html = html.replace(
    'let data = null;',
    'let data = __EMBEDDED_DATA__;\n// (loaded from dashboard_data.js)'
)

# Hide the file upload since we have data
html = html.replace(
    '<label class="file-label" for="json-upload">+ Cargar JSON</label>',
    '<label class="file-label" for="json-upload" style="display:none">+ Cargar JSON</label>'
)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"  Dashboard generado: {out_path}")

# ================================================================
# 3. ABRE EN EL NAVEGADOR
# ================================================================
webbrowser.open("file://" + out_path)

print(f"\n{'=' * 60}")
print(f"  DASHBOARD ABIERTO EN EL NAVEGADOR")
print(f"  Edges encontrados: {total_edges}")
print(f"  Senales encontradas: {total_signals}")
print(f"  Odds API restantes: {analyzer.props.odds.get_remaining()}")
print(f"{'=' * 60}")
