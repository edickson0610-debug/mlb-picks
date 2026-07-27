"""
BaseballAnalyzer V2.6 - Protocolo integrado con datos REALES de MLB API
Score System 7 componentes | Datos: MLB Stats API + OpenWeatherMap
"""
import json
from datetime import datetime
from typing import Dict, List

from src.data_fetcher import ProtocolDataFetcher
from src.calculators import MLBCalculators
from src.filters import ProtocolFilters
from src.config import Config
from src.player_props import PlayerPropAnalyzer


class BaseballAnalyzer:
    def __init__(self):
        self.fetcher = ProtocolDataFetcher()
        self.calc = MLBCalculators()
        self.filters = ProtocolFilters()
        self.props = PlayerPropAnalyzer(self.fetcher)

    def analyze_game(self, game_id: int, season: int = None, game_data: dict = None) -> Dict:
        """Evalua un juego completo usando el Protocolo V2.6 con datos reales."""
        result = {
            "protocol": "V2.6 - Score System 7 componentes",
            "phases": {}, "markets": {}, "score": 0, "score_components": {},
        }

        # ============================================================
        # FASE 1: CARGAR CONTEXTO COMPLETO
        # ============================================================
        ctx = self.fetcher.get_full_game_context(game_id, season, game_data)
        if "error" in ctx:
            return {"error": f"FASE 1: {ctx['error']}"}

        g = ctx["game"]
        result["phases"]["calendar"] = {"status": "OK", "game": f"{g['away_team']} @ {g['home_team']}"}
        result["phases"]["venue"] = g["venue"]

        # ============================================================
        # FASE 2: LANZADORES Y LINEUPS
        # ============================================================
        pitchers = ctx["pitchers"]
        if pitchers["away"] == "TBD" or pitchers["home"] == "TBD":
            return {"error": f"FASE 2: Abridor TBD - esperar confirmacion"}
        result["phases"]["pitchers"] = {"status": "CONFIRMADOS", "away": pitchers["away"], "home": pitchers["home"]}

        lineups = self.fetcher.get_lineups(game_id)
        lineups_ok, lineups_reason = self.filters.check_lineups(lineups)
        result["phases"]["lineups"] = {"status": "OK" if lineups_ok else "ESPERANDO", "reason": lineups_reason}
        if not lineups_ok and not Config.ALLOW_NO_LINEUP_PROPS:
            result["error"] = f"FASE 2: {lineups_reason}"
            return result

        ap = ctx["away_pitcher_stats"]
        hp = ctx["home_pitcher_stats"]

        # ============================================================
        # FASE 3: CLIMA
        # ============================================================
        weather = ctx["weather"]
        weather_ok, weather_reason = self.filters.check_weather(weather)
        wind_penalty = self.filters.check_wind_penalty(weather)
        result["phases"]["weather"] = {
            "status": "OK" if weather_ok else "ANULADO",
            "reason": weather_reason, "wind_penalty": wind_penalty,
            "source": weather.get("source", "?"),
        }
        if not weather_ok:
            result["error"] = f"FASE 3: {weather_reason}"
            return result

        # ============================================================
        # FASE 4: 7 COMPONENTES DEL SCORE
        # ============================================================

        # -- 4a. DUELO ABRIDORES (25%)
        duelo_score = self.filters.score_duelo_abridores(
            ap.get("xfip_est", 4.2), ap.get("xfip_est", 4.2) + 0.3,
            ap.get("k9", 8.0), ap.get("bb9", 3.0), ap.get("hr9", 1.2),
            hp.get("xfip_est", 4.2), hp.get("xfip_est", 4.2) + 0.3,
            hp.get("k9", 8.0), hp.get("bb9", 3.0), hp.get("hr9", 1.2),
        )

        # -- 4b. OFENSIVA (20%)
        ah = ctx["away_hitting"]
        hh = ctx["home_hitting"]
        ofensiva_a = self.filters.score_ofensiva(
            self.fetcher.estimate_wrc_plus(ah.get("ops", 0.710)), ah.get("ops", 0.710))
        ofensiva_h = self.filters.score_ofensiva(
            self.fetcher.estimate_wrc_plus(hh.get("ops", 0.710)), hh.get("ops", 0.710))

        # -- 4c. BULLPEN (15%)
        ab = ctx["away_bullpen"]
        hb = ctx["home_bullpen"]
        bullpen_a = self.filters.score_bullpen(
            ab.get("xfip_est", ab.get("era", 4.0) + 0.3) if "xfip_est" in ap else ab.get("era", 4.0) + 0.3,
            ab.get("era", 4.0), ab.get("whip", 1.30))
        bullpen_h = self.filters.score_bullpen(
            hb.get("xfip_est", hb.get("era", 4.0) + 0.3) if "xfip_est" in hp else hb.get("era", 4.0) + 0.3,
            hb.get("era", 4.0), hb.get("whip", 1.30))

        # -- 4d. FACTOR PARQUE (10%)
        parque_score = self.filters.score_factor_parque(g["venue"])

        # -- 4e. CLIMA (10%)
        clima_score = self.filters.score_clima(weather)

        # -- 4f. UMPIRE (10%)
        umpire_score = self.filters.score_umpire(0.80, 0.02)

        # -- 4g. RUN EXPECTANCY (10%)
        run_exp_h = ap.get("xfip_est", 4.2) * 0.6 + ab.get("era", 4.0) * 0.3 + \
                    (self.fetcher.estimate_wrc_plus(hh.get("ops", 0.710)) / 100) * 0.1
        run_exp_a = hp.get("xfip_est", 4.2) * 0.6 + hb.get("era", 4.0) * 0.3 + \
                    (self.fetcher.estimate_wrc_plus(ah.get("ops", 0.710)) / 100) * 0.1
        re_score = self.filters.score_run_expectancy(run_exp_h, run_exp_a, 8.5)

        # ============================================================
        # FASE 5: SCORE COMPLETO
        # ============================================================
        ofensiva_min = min(ofensiva_a, ofensiva_h)
        bullpen_min = min(bullpen_a, bullpen_h)

        full = self.filters.calculate_full_protocol_score(
            duelo=duelo_score, ofensiva=ofensiva_min, bullpen=bullpen_min,
            parque=parque_score, clima=clima_score, umpire=umpire_score, run_exp=re_score,
        )

        # Consistencia desde historial
        past = self._load_history()
        consistencia = self.calc.calculate_consistency(past)

        result["metrics"] = {
            "duelo_abridores": {"score": duelo_score, "away": pitchers["away"], "home": pitchers["home"],
                                "away_k9": ap.get("k9", "?"), "home_k9": hp.get("k9", "?")},
            "ofensiva": {"away": ofensiva_a, "home": ofensiva_h,
                         "away_ops": ah.get("ops", "?"), "home_ops": hh.get("ops", "?")},
            "bullpen": {"away": bullpen_a, "home": bullpen_h,
                        "away_era": ab.get("era", "?"), "home_era": hb.get("era", "?")},
            "factor_parque": {"score": parque_score, "park": g["venue"]},
            "clima": {"score": clima_score, "temp": weather.get("temperature", "?"),
                      "wind": weather.get("wind_speed", "?")},
            "umpire": umpire_score,
            "run_expectancy": {"score": re_score, "home_re": round(run_exp_h, 2), "away_re": round(run_exp_a, 2)},
        }

        # ============================================================
        # FASE 6: MERCADOS
        # ============================================================

        protocol_score = full["score"]
        total_implied = run_exp_h + run_exp_a
        # Determinar underdog: el equipo con menor proyeccion de carreras
        is_home_underdog = run_exp_h < run_exp_a
        underdog_team = g["home_team"] if is_home_underdog else g["away_team"]
        fav_team = g["home_team"] if not is_home_underdog else g["away_team"]
        rs9_ud = run_exp_h if is_home_underdog else run_exp_a
        rs9_fav = run_exp_a if is_home_underdog else run_exp_h

        # -- Runline +1.5 (Poisson real, EV >= 15%, confianza Muy Alta / Alta)
        rl_prob = self.calc.calculate_rl_probability(rs9_ud, rs9_fav)
        odds_rl = Config.MAX_RL_ODDS  # -140 (peor cuota permitida por protocolo)
        ev_rl = self.calc.calculate_ev(self.calc.odds_to_decimal(odds_rl), rl_prob)
        # ML favorito: fair odds (proxy de mercado)
        win_pct_fav = self.calc.calculate_pythagenpat(rs9_fav, rs9_ud)
        ml_fav_odds = self.calc.decimal_to_odds(1 / max(0.01, win_pct_fav))
        rl_ctx = {
            "total": total_implied,
            "ops_road": ah.get("ops", 0.700),
            "pitcher": pitchers["away"] if is_home_underdog else pitchers["home"],
            "bullpen_underdog_xfip": hb.get("era", 4.0) + 0.3 if is_home_underdog else ab.get("era", 4.0) + 0.3,
            "bullpen_fav_xfip": ab.get("era", 4.0) + 0.3 if is_home_underdog else hb.get("era", 4.0) + 0.3,
            "ml_fav_odds": ml_fav_odds,
        }
        rl_approved, rl_reason = self.filters.filter_runline_plus_1_5(odds_rl, ev_rl, protocol_score, rl_ctx, weather)
        rl_team_pick = f"{underdog_team} +1.5"
        # Confianza: Muy Alta (EV >= 15%), Alta (EV >= 5%)
        if ev_rl >= Config.MIN_EV_RL:
            rl_confidence = "\U0001f525\U0001f525\U0001f525 Muy Alta"
        elif ev_rl >= 0.05:
            rl_confidence = "\U0001f525\U0001f525 Alta"
        else:
            rl_confidence = "Baja"
        result["markets"]["runline_plus_1_5"] = {
            "decision": "APROBADO" if rl_approved else "NO APROBADO",
            "score": protocol_score, "protocol_score": protocol_score,
            "rl_prob": round(rl_prob, 3), "ev": f"{ev_rl*100:.1f}%",
            "ml_fav_odds": ml_fav_odds,
            "confianza": rl_confidence,
            "reason": rl_reason,
            "side": underdog_team, "team_pick": rl_team_pick,
        }

        # -- Totales (usa protocol_score + run margin como confianza)
        line = 8.5
        margin = total_implied - line
        # Probabilidad derivada del colchon de proyeccion
        if abs(margin) >= 2.0:
            over_prob = 0.70; under_prob = 0.65
        elif abs(margin) >= 1.5:
            over_prob = 0.65; under_prob = 0.60
        elif abs(margin) >= 1.0:
            over_prob = 0.60; under_prob = 0.55
        elif abs(margin) >= 0.5:
            over_prob = 0.55; under_prob = 0.53
        else:
            over_prob = 0.50; under_prob = 0.50
        ev_over = self.calc.calculate_ev(self.calc.odds_to_decimal(-110), over_prob)
        ev_under = self.calc.calculate_ev(self.calc.odds_to_decimal(-110), under_prob)
        over_approved, over_reason = self.filters.filter_totals(total_implied, line, ev_over, protocol_score, True, weather)
        result["markets"]["total_over"] = {
            "decision": "APROBADO" if over_approved else "NO APROBADO",
            "score": protocol_score, "protocol_score": protocol_score,
            "line": line, "projection": round(total_implied, 2),
            "ev": f"{ev_over*100:.1f}%", "reason": over_reason,
        }

        under_approved, under_reason = self.filters.filter_totals(total_implied, line, ev_under, protocol_score, False, weather)
        result["markets"]["total_under"] = {
            "decision": "APROBADO" if under_approved else "NO APROBADO",
            "score": protocol_score, "protocol_score": protocol_score,
            "line": line, "projection": round(total_implied, 2),
            "ev": f"{ev_under*100:.1f}%", "reason": under_reason,
        }

        # -- HR Props
        hr_players = []
        for player in lineups.get("home", [])[:5]:
            player_data = self.fetcher.search_player(player)
            if player_data and player_data["id"]:
                batter = self.fetcher.get_batter_stats(player_data["id"], ctx["season"])
                ev_hr = self.calc.calculate_ev(self.calc.odds_to_decimal(350), 0.035)
                score_hr = self.calc.calculate_score(ev_hr, consistencia, clima_score)
                xwoba_est = batter.get("slg", 0.400) * 0.8
                hr_ok, hr_reason = self.filters.filter_hr_directas(ev_hr, score_hr, xwoba_est, 0.320)
                if hr_ok:
                    hr_players.append({"player": player, "score": score_hr, "ev": f"{ev_hr*100:.1f}%", "ops": batter.get("ops", "?")})
        result["markets"]["hr_directas"] = {
            "players": hr_players if hr_players else [],
            "note": "" if hr_players else "Ninguna HR aprobo filtros",
        }

        # -- Money Line (usa protocol_score + fair_odds, sin sesgo underdog/favorito)
        win_pct = self.calc.calculate_pythagenpat(run_exp_h, run_exp_a)
        fair_odds = self.calc.decimal_to_odds(1 / max(0.01, win_pct))
        ev_ml = self.calc.calculate_ev(self.calc.odds_to_decimal(fair_odds), win_pct)
        ml_approved, ml_reason = self.filters.filter_money_line(fair_odds, fair_odds, ev_ml, protocol_score)
        ml_side = g["home_team"] if win_pct >= 0.5 else g["away_team"]
        result["markets"]["money_line"] = {
            "decision": "APROBADO" if ml_approved else "NO APROBADO",
            "score": protocol_score, "protocol_score": protocol_score,
            "ev": f"{ev_ml*100:.1f}%", "fair_odds": fair_odds,
            "prob_margin": 0, "win_pct": round(win_pct, 3),
            "side": ml_side, "team_pick": f"{ml_side} ML ({fair_odds:+d})",
            "reason": ml_reason,
        }

        # -- Player props with live market (PlayerPropAnalyzer + OddsAPIClient)
        player_props_result = self.props.analyze_with_market(game_id, ctx["season"])
        approved_props = []
        for bp in player_props_result.get("batter_props", []):
            signals = bp.get("signals", {})
            h2h = bp.get("h2h", {})
            ks = bp.get("strikeouts_projection", {})
            hits = bp.get("hits_projection", {})
            h2h_avg = h2h.get("avg", 0)
            h2h_ab = h2h.get("ab", 0)
            k_pct = ks.get("batter_k_pct", 0)
            pitcher_k9 = ks.get("pitcher_k9", 0)
            proj_hits = hits.get("projected", 0)
            if signals.get("h2h_over_285"):
                approved_props.append({
                    "batter": bp["batter"],
                    "market": "Hits Over 0.5",
                    "signal": "H2H > .285",
                    "h2h_avg": round(h2h_avg, 3),
                    "h2h_ab": h2h_ab,
                    "proj_hits": proj_hits,
                    "k_pct": k_pct,
                    "pitcher_k9": pitcher_k9,
                })
            if signals.get("high_k_rate"):
                approved_props.append({
                    "batter": bp["batter"],
                    "market": "K's Over 0.5",
                    "signal": "High K rate",
                    "proj_k": ks.get("projected", 0),
                    "k_pct": k_pct,
                    "pitcher_k9": pitcher_k9,
                })
        # Market-based edges (pitcher strikeouts vs live odds)
        market_edges = []
        for k_edge in player_props_result.get("market", {}).get("pitcher_k_edges", []):
            over = k_edge["over_edge"]
            under = k_edge["under_edge"]
            if over["recommendation"] in ("BET", "STRONG BET"):
                market_edges.append({
                    "pitcher": k_edge["pitcher"],
                    "side": "Over",
                    "line": k_edge["market_line"],
                    "odds": k_edge["over_odds"],
                    "our_proj": k_edge["our_proj"],
                    "ev_pct": over["ev_pct"],
                    "edge_pct": over["edge_pct"],
                    "bookmaker": k_edge["best_over_book"],
                    "rec": over["recommendation"],
                })
            if under["recommendation"] in ("BET", "STRONG BET"):
                market_edges.append({
                    "pitcher": k_edge["pitcher"],
                    "side": "Under",
                    "line": k_edge["market_line"],
                    "odds": k_edge["under_odds"],
                    "our_proj": k_edge["our_proj"],
                    "ev_pct": under["ev_pct"],
                    "edge_pct": under["edge_pct"],
                    "bookmaker": k_edge["best_under_book"],
                    "rec": under["recommendation"],
                })
        result["markets"]["player_props"] = {
            "players": approved_props if approved_props else [],
            "market_edges": market_edges if market_edges else [],
            "note": "" if (approved_props or market_edges) else "Ningun prop aprobo filtros",
        }

        # ============================================================
        # FASE 7: SCORE GLOBAL
        # ============================================================
        result["score"] = full["score"]
        result["score_components"] = full["metrics"]
        result["sweet_spot"] = full["sweet_spot"]
        result["markets_approved"] = sum([rl_approved, over_approved, under_approved, ml_approved, len(hr_players) > 0])

        return result

    def _load_history(self) -> List[bool]:
        try:
            with open("historial_jugadas.json") as f:
                data = json.load(f)
            if not isinstance(data, list) or not data:
                return []
            return [entry.get("won", False) for entry in data[-10:]]
        except (FileNotFoundError, json.JSONDecodeError, KeyError, IndexError):
            return []


def main():
    """Demo: analiza juegos de HOY con datos reales."""
    analyzer = BaseballAnalyzer()
    fetcher = ProtocolDataFetcher()

    print("=" * 75)
    print("  PROTOCOLO V2.6 - ANALISIS CON DATOS REALES")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 75)

    # Obtener juegos de hoy
    games = fetcher.get_daily_games()
    if not games:
        print("\n[INFO] No hay juegos hoy.\n")
        return

    print(f"\n  Juegos encontrados: {len(games)}\n")

    all_results = []
    for g in games[:5]:  # Max 5 juegos por ejecucion
        gid = g["game_id"]
        print(f"  [{gid}] {g['away_team']} @ {g['home_team']} ({g['venue']})")
        print(f"    Estado: {g['status']}")

        if g["status"] not in ("Scheduled", "Preview", "Pre-Game"):
            print(f"    [SKIP] Juego no disponible (status: {g['status']})")
            continue

        # Verificar pitchers (vienen en el schedule con hydrate)
        if g.get("away_pitcher", "TBD") == "TBD" or g.get("home_pitcher", "TBD") == "TBD":
            print(f"    [SKIP] Pitchers TBD")
            continue

        print(f"    Pitchers: {g['away_pitcher']} @ {g['home_pitcher']}")

        # Analizar juego
        result = analyzer.analyze_game(gid)
        if "error" in result:
            print(f"    [ERROR] {result['error']}")
            continue

        score = result["score"]
        sweet = result["sweet_spot"]
        approved = result["markets_approved"]
        print(f"    Score: {score} | Sweet Spot: {sweet} | Mercados: {approved}")
        result["game"] = f"{g['away_team']} @ {g['home_team']}"
        all_results.append(result)

    if all_results:
        # Resumen
        print(f"\n{'='*75}")
        print("  RESUMEN DE ANALISIS")
        print(f"{'='*75}")
        for r in all_results:
            markets = [k for k, v in r["markets"].items() if v.get("decision") == "APROBADO"]
            print(f"  {r['game']:<45} Score: {r['score']} | Aprobados: {markets}")

        # Guardar
        fn = f"analysis_live_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        total_edges = sum(len(r["markets"]["player_props"].get("market_edges", [])) for r in all_results)
        output = {
            "timestamp": datetime.now().isoformat(),
            "protocol": "V2.6 - Score System 7 Componentes + Player Props",
            "total_games": len(all_results),
            "total_edges": total_edges,
            "odds_remaining": analyzer.props.odds.get_remaining(),
            "results": all_results,
        }
        with open(fn, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n[SAVE] {fn}")
    else:
        print("\n[INFO] No se pudo analizar ningun juego.")


if __name__ == "__main__":
    main()
