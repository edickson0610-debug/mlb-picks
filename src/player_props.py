"""
PlayerPropAnalyzer - Proyecciones de player props con edge detection
Fuentes:
  - MLB Stats API: vsPlayer (batter vs pitcher H2H), season stats, game logs
  - The Odds API: market lines (cuando haya API key)
  - Weather: OpenWeatherMap

Estrategias:
  1. H2H History: batter hits >.285 with 5+ AB -> bet Over
  2. Contrarian: batter K% high vs pitcher K/9 high -> bet Over K's
  3. Power: pitcher HR/9 high vs batter SLG high -> bet Over HR
  4. Weather: buen clima -> boost hitting, mal clima -> supress
  5. Edge: proyeccion propia vs mercado (The Odds API)
"""
import os, json, math
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from src.data_fetcher import ProtocolDataFetcher
from src.config import Config
from src.odds_client import OddsAPIClient


class PlayerPropAnalyzer:
    """Analiza player props usando datos de MLB API + The Odds API"""

    def __init__(self, fetcher: ProtocolDataFetcher = None):
        self.fetcher = fetcher or ProtocolDataFetcher()
        self.odds = OddsAPIClient()
        self._player_cache = {}

    # ================================================================
    # 1. BATER VS PITCHER - HEAD TO HEAD
    # ================================================================

    def get_batter_vs_pitcher(self, batter_id: int, pitcher_id: int,
                               season: int = None) -> Dict:
        """Historial H2H: batter vs pitcher.
        Retorna: {ab, hits, avg, hr, bb, k, ops, games}"""
        if season is None:
            season = datetime.now().year

        url = f"{self.fetcher.base}/people/{batter_id}/stats"
        params = {
            "stats": "vsPlayer",
            "group": "hitting",
            "opposingPlayerId": pitcher_id,
            "season": season,
        }
        data = self.fetcher._api(url, params)
        default = {"ab": 0, "hits": 0, "avg": 0.0, "hr": 0, "bb": 0, "k": 0, "ops": 0.0, "games": 0}

        if data:
            for s in data.get("stats", []):
                if s.get("type", {}).get("displayName") == "vsPlayerTotal":
                    for sp in s.get("splits", []):
                        st = sp["stat"]
                        ab = int(st.get("atBats", 0))
                        hits = int(st.get("hits", 0))
                        result = {
                            "ab": ab,
                            "hits": hits,
                            "avg": float(st.get("avg", 0.0)),
                            "hr": int(st.get("homeRuns", 0)),
                            "bb": int(st.get("baseOnBalls", 0)),
                            "k": int(st.get("strikeOuts", 0)),
                            "ops": float(st.get("ops", 0.0)),
                            "games": int(st.get("gamesPlayed", 0)),
                            "season": season,
                        }
                        return result
        return default

    def get_batter_season(self, batter_id: int, season: int = None) -> Dict:
        """Stats seasonales del bateador."""
        return self.fetcher.get_batter_stats(batter_id, season)

    def get_pitcher_season(self, pitcher_id: int, season: int = None) -> Dict:
        """Stats seasonales del pitcher."""
        return self.fetcher.get_pitcher_stats(pitcher_id, season)

    # ================================================================
    # 2. PROYECCIONES DE PLAYER PROPS
    # ================================================================

    def project_pitcher_strikeouts(self, pitcher_id: int, batter_ids: List[int],
                                    season: int = None, weather: Dict = None) -> Dict:
        """Proyecta strikeouts del pitcher vs esta alineacion."""
        pstats = self.get_pitcher_season(pitcher_id, season)
        k9 = pstats.get("k9", 8.0)
        ip = pstats.get("ip", 100)

        # K/9 base
        k_per_game = k9 * 5.5 / 9  # ~5.5 IP esperadas

        # Ajuste por linea de bateadores
        total_batters = len(batter_ids)
        if total_batters == 0:
            return {"projected": round(k_per_game, 1), "k9": k9, "avg_batter_k_pct": 0.250, "confidence": 0.3}

        avg_k_pct = 0.0
        for bid in batter_ids[:9]:  # Top 9 bateadores
            bstats = self.get_batter_season(bid, season)
            ab = float(bstats.get("games", 100)) * 3.5  # estimado
            k = bstats.get("k", int(ab * 0.22))  # fallback
            avg_k_pct += k / max(1, ab)

        avg_k_pct /= min(9, total_batters)

        # Factor de ajuste por K% de la alineacion
        # Si la alineacion tiene K% alto, el pitcher suma mas K's
        if avg_k_pct > 0.25:
            k_per_game *= 1.10
        elif avg_k_pct < 0.18:
            k_per_game *= 0.90

        # Ajuste por clima (viento favorable = menos K's)
        if weather:
            wind = weather.get("wind_speed", 8)
            if wind > 15:
                k_per_game *= 0.95  # Viento fuerte afecta a todos

        return {
            "projected": round(k_per_game, 1),
            "k9": k9,
            "avg_batter_k_pct": round(avg_k_pct, 3),
            "confidence": round(min(0.9, 0.3 + ip / 200), 2),
        }

    def project_batter_hits(self, batter_id: int, pitcher_id: int,
                             season: int = None, weather: Dict = None) -> Dict:
        """Proyecta hits del bateador vs este pitcher.
        Usa: H2H history + season stats + platoon + weather"""
        bstats = self.get_batter_season(batter_id, season)
        pstats = self.get_pitcher_season(pitcher_id, season)
        h2h = self.get_batter_vs_pitcher(batter_id, pitcher_id, season)

        # 1. Season AVG -> hits per game
        season_avg = float(bstats.get("avg", 0.250))
        season_hits = int(bstats.get("hits", 50))
        season_games = int(bstats.get("games", 100))
        hits_per_game = season_hits / max(1, season_games)

        # 2. H2H adjustment (sample size matters)
        h2h_ab = h2h.get("ab", 0)
        h2h_avg = h2h.get("avg", 0.0)

        if h2h_ab >= 10:
            # 40% weight on H2H, 60% on season
            blended_avg = h2h_avg * 0.4 + season_avg * 0.6
            h2h_weight = 0.4
        elif h2h_ab >= 5:
            blended_avg = h2h_avg * 0.25 + season_avg * 0.75
            h2h_weight = 0.25
        else:
            blended_avg = season_avg
            h2h_weight = 0.0

        # 3. Platoon adjustment (if we know batter/pitcher handedness)
        # For now, simplified

        # 4. Weather adjustment
        weather_boost = 1.0
        if weather:
            temp = weather.get("temperature", 25)
            wind = weather.get("wind_speed", 8)
            if 20 <= temp <= 30 and wind < 12:
                weather_boost = 1.05  # Buen clima = +5%
            elif temp < 10 or wind > 18:
                weather_boost = 0.90  # Mal clima = -10%

        # 5. Expected AB (assuming 4 AB/game)
        expected_ab = 4.0

        # 6. Projected hits
        proj_hits = blended_avg * expected_ab * weather_boost

        # 7. Edge detection
        # Si H2H muestra .285+ con 5+ AB -> strong signal
        strong_signal = h2h_ab >= 5 and h2h_avg >= 0.285

        return {
            "projected": round(proj_hits, 2),
            "season_avg": season_avg,
            "h2h_avg": h2h_avg,
            "h2h_ab": h2h_ab,
            "h2h_weight": h2h_weight,
            "blended_avg": round(blended_avg, 3),
            "weather_boost": round(weather_boost, 3),
            "strong_signal": strong_signal,
            "confidence": round(min(0.9, 0.3 + h2h_ab / 40), 2),
        }

    def project_batter_strikeouts(self, batter_id: int, pitcher_id: int,
                                   season: int = None, weather: Dict = None) -> Dict:
        """Proyecta K's del bateador vs este pitcher."""
        bstats = self.get_batter_season(batter_id, season)
        pstats = self.get_pitcher_season(pitcher_id, season)
        h2h = self.get_batter_vs_pitcher(batter_id, pitcher_id, season)

        # Batter K% (season)
        ab = float(bstats.get("at_bats", 0))
        k = float(bstats.get("k", 0))
        if ab < 20:
            # Muestra muy pequena -> usar K% por defecto de la liga (~22%)
            batter_k_pct = 0.22
        else:
            batter_k_pct = k / max(1, ab)

        # Pitcher K/9
        k9 = pstats.get("k9", 8.0)

        # H2H K% (if enough sample)
        h2h_k = 0
        if h2h.get("ab", 0) >= 5:
            h2h_k = h2h.get("k", 0) / max(1, h2h.get("ab", 5))

        # Blend
        if h2h.get("ab", 0) >= 10:
            k_pct = h2h_k * 0.4 + batter_k_pct * 0.6
        elif h2h.get("ab", 0) >= 5:
            k_pct = h2h_k * 0.25 + batter_k_pct * 0.75
        else:
            k_pct = batter_k_pct

        # Expected AB = 4
        proj_k = k_pct * 4.0

        # Ajuste por calidad del pitcher
        # Pitcher elite (K/9 > 10) aumenta K%
        if k9 > 10:
            proj_k *= 1.15
        elif k9 > 9:
            proj_k *= 1.08

        return {
            "projected": round(proj_k, 2),
            "batter_k_pct": round(batter_k_pct * 100, 1),
            "pitcher_k9": k9,
            "h2h_k": round(h2h_k * 100, 1) if h2h.get("ab", 0) >= 5 else None,
            "confidence": round(min(0.9, 0.3 + h2h.get("ab", 0) / 40), 2),
        }

    def project_batter_home_run(self, batter_id: int, pitcher_id: int,
                                 season: int = None, weather: Dict = None,
                                 venue: str = None) -> Dict:
        """Proyecta HR del bateador vs este pitcher."""
        bstats = self.get_batter_season(batter_id, season)
        pstats = self.get_pitcher_season(pitcher_id, season)
        h2h = self.get_batter_vs_pitcher(batter_id, pitcher_id, season)

        # Batter HR rate
        hr = int(bstats.get("hr", 0))
        ab = float(bstats.get("at_bats", 0))
        if ab < 20:
            hr_rate = 0.04  # ~4% de HR/AB = ~25 HR en 600 AB
        else:
            hr_rate = hr / max(1, ab)

        # Pitcher HR/9
        hr9 = pstats.get("hr9", 1.2)

        # H2H HR
        h2h_hr = h2h.get("hr", 0)
        h2h_ab = h2h.get("ab", 0)
        h2h_hr_rate = h2h_hr / max(1, h2h_ab) if h2h_ab >= 5 else None

        # Blend
        if h2h_hr_rate and h2h_ab >= 10:
            blended = h2h_hr_rate * 0.3 + hr_rate * 0.7
        elif h2h_hr_rate and h2h_ab >= 5:
            blended = h2h_hr_rate * 0.2 + hr_rate * 0.8
        else:
            blended = hr_rate

        # Ajuste por pitcher
        if hr9 > 1.4:
            blended *= 1.20
        elif hr9 < 0.8:
            blended *= 0.75

        # Ajuste por parque (HR-friendly)
        park_factor = 1.0
        if venue:
            park_factor = Config.PARK_HR_FACTORS.get(venue, 1.0)
        blended *= park_factor

        # Ajuste por clima
        if weather:
            wind = weather.get("wind_speed", 8)
            wdir = weather.get("wind_direction", "SW")
            if wdir in Config.HR_WIND_DIRECTIONS and wind > 8:
                blended *= (1.0 + wind / 30)

        # Expected AB = 4
        proj_hr = blended * 4.0

        return {
            "projected": round(proj_hr, 3),
            "hr_rate_season": round(hr_rate * 100, 2),
            "pitcher_hr9": hr9,
            "park_factor": park_factor,
            "h2h_hr": h2h_hr,
            "h2h_ab": h2h_ab,
            "confidence": round(min(0.7, 0.2 + h2h_ab / 50), 2),
        }

    # ================================================================
    # 3. EDGE DETECTION VS THE ODDS API
    # ================================================================

    def calculate_edge(self, projection: float, market_line: float,
                       market_odds: int, side: str = "over") -> Dict:
        """
        Calcula el edge entre nuestra proyeccion y el mercado.
        market_line: la linea O/U (ej: 5.5 K's, 0.5 HR)
        market_odds: odds americanos (ej: -110)
        side: 'over' o 'under'

        Retorna: {edge_pct, expected_value, recommendation}
        """
        # Probabilidad implicita del mercado
        if market_odds < 0:
            implied_prob = abs(market_odds) / (abs(market_odds) + 100)
        else:
            implied_prob = 100 / (market_odds + 100)

        if side == "over":
            # Nuestra proyeccion supera la linea? -> Over tiene valor
            diff = projection - market_line
            if diff > 0:
                # Estimacion de probabilidad de que cubra
                our_prob = min(0.95, 0.5 + diff * 0.15)
            else:
                our_prob = max(0.05, 0.5 + diff * 0.15)
        else:
            diff = market_line - projection
            if diff > 0:
                our_prob = min(0.95, 0.5 + diff * 0.15)
            else:
                our_prob = max(0.05, 0.5 + diff * 0.15)

        # EV
        if market_odds < 0:
            decimal_odds = 1 + (100 / abs(market_odds))
        else:
            decimal_odds = 1 + (market_odds / 100)

        ev = (decimal_odds * our_prob) - 1
        edge = our_prob - implied_prob

        return {
            "projection": projection,
            "market_line": market_line,
            "market_odds": market_odds,
            "side": side,
            "our_prob": round(our_prob, 3),
            "implied_prob": round(implied_prob, 3),
            "edge_pct": round(edge * 100, 1),
            "ev_pct": round(ev * 100, 1),
            "recommendation": "STRONG BET" if edge > 0.08 else
                              "BET" if edge > 0.05 else
                              "NO BET" if edge > 0.02 else
                              "PASS",
        }

    # ================================================================
    # 4. ANALIZADOR COMPLETO DE PROPS
    # ================================================================

    def _get_batter_ids_from_roster(self, team_id: int, season: int = None, max_batters: int = 9) -> List[Dict]:
        """Obtiene [{id, name}] de bateadores desde el roster (fallback cuando lineups no disponibles)."""
        roster = self.fetcher.get_team_roster(team_id, season)
        batters = []
        for p in roster:
            pos = p.get("position", "")
            if pos not in ("P", "RP", "SP", "CL"):
                batters.append({"id": p["id"], "name": p["name"]})
            if len(batters) >= max_batters:
                break
        return batters

    def analyze_game_props(self, game_id: int, season: int = None) -> Dict:
        """Analiza todos los player props relevantes para un juego."""
        ctx = self.fetcher.get_full_game_context(game_id, season)
        if "error" in ctx:
            return {"error": ctx["error"]}

        g = ctx["game"]
        away_pitcher_id = ctx["pitchers"].get("away_id")
        home_pitcher_id = ctx["pitchers"].get("home_id")
        weather = ctx["weather"]
        venue = g.get("venue", "")

        # Get lineups (fallback a roster si no disponibles)
        lineups = self.fetcher.get_lineups(game_id)
        away_batters = []
        home_batters = []

        # Convert lineup names to IDs
        for name in lineups.get("away", []):
            p = self.fetcher.search_player(name)
            if p:
                away_batters.append({"id": p["id"], "name": p["name"]})
        for name in lineups.get("home", []):
            p = self.fetcher.search_player(name)
            if p:
                home_batters.append({"id": p["id"], "name": p["name"]})

        # Fallback: use roster-based batters if lineups empty
        if not away_batters and g.get("away_id"):
            away_batters = self._get_batter_ids_from_roster(g["away_id"], season)
        if not home_batters and g.get("home_id"):
            home_batters = self._get_batter_ids_from_roster(g["home_id"], season)

        results = {
            "game": f"{g['away_team']} @ {g['home_team']}",
            "venue": venue,
            "weather": weather,
            "pitcher_props": {},
            "batter_props": [],
        }

        # -- PITCHER STRIKEOUTS
        if away_pitcher_id:
            k_proj = self.project_pitcher_strikeouts(away_pitcher_id, [b["id"] for b in home_batters], season, weather)
            results["pitcher_props"][f"{ctx['pitchers']['away']} K"] = k_proj
        if home_pitcher_id:
            k_proj = self.project_pitcher_strikeouts(home_pitcher_id, [b["id"] for b in away_batters], season, weather)
            results["pitcher_props"][f"{ctx['pitchers']['home']} K"] = k_proj

        # -- BATTER PROPS (top 3 per team)
        for batter_info, pitcher_id, side in \
            [(b, home_pitcher_id, "away") for b in away_batters[:3]] + \
            [(b, away_pitcher_id, "home") for b in home_batters[:3]]:

            batter_id = batter_info["id"]
            name = batter_info["name"]
            if not batter_id or not pitcher_id:
                continue

            # Get projections
            hits = self.project_batter_hits(batter_id, pitcher_id, season, weather)
            ks = self.project_batter_strikeouts(batter_id, pitcher_id, season, weather)
            hr = self.project_batter_home_run(batter_id, pitcher_id, season, weather, venue)

            # H2H data
            h2h = self.get_batter_vs_pitcher(batter_id, pitcher_id, season)

            results["batter_props"].append({
                "batter": name,
                "team": side,
                "h2h": h2h,
                "hits_projection": hits,
                "strikeouts_projection": ks,
                "hr_projection": hr,
                # Strong signals
                "signals": {
                    "h2h_over_285": h2h.get("avg", 0) >= 0.285 and h2h.get("ab", 0) >= 5,
                    "h2h_under_150": h2h.get("avg", 0) <= 0.150 and h2h.get("ab", 0) >= 10,
                    "high_k_rate": ks.get("projected", 0) > 1.0,
                    "hr_threat": hr.get("projected", 0) > 0.15,
                },
            })

        return results

    # ================================================================
    # 5. LIVE MARKET EDGE (The Odds API)
    # ================================================================

    def analyze_with_market(self, game_id: int, season: int = None) -> Dict:
        """Analiza player props Y compara con odds en vivo de The Odds API."""
        proj = self.analyze_game_props(game_id, season)
        if "error" in proj:
            return proj

        # Add market data
        ctx = self.fetcher.get_full_game_context(game_id, season)
        g = ctx.get("game", {})
        event_id = self.odds.match_mlb_event(g.get("away_team", ""), g.get("home_team", ""))

        market_results = {
            "pitcher_k_edges": [],
            "game_odds": {},
        }

        if event_id:
            # -- PITCHER STRIKEOUTS market comparison
            best_k = self.odds.get_best_pitcher_k_odds(event_id)
            market_results["pitcher_k_odds"] = best_k

            for k_odds in best_k:
                pitcher_name = k_odds["pitcher"]
                line = k_odds.get("line", 5.5)
                over_odds = k_odds.get("over_odds", 100)
                under_odds = k_odds.get("under_odds", -110)

                # Find our projection for this pitcher
                our_proj = None
                for pname, pproj in proj.get("pitcher_props", {}).items():
                    if pitcher_name.lower() in pname.lower():
                        our_proj = pproj
                        break

                if our_proj:
                    proj_k = our_proj["projected"]

                    # Edge for Over
                    edge_over = self.calculate_edge(proj_k, line, over_odds, "over")
                    edge_under = self.calculate_edge(proj_k, line, under_odds, "under")

                    market_results["pitcher_k_edges"].append({
                        "pitcher": pitcher_name,
                        "our_proj": proj_k,
                        "market_line": line,
                        "over_odds": over_odds,
                        "under_odds": under_odds,
                        "over_edge": edge_over,
                        "under_edge": edge_under,
                        "best_over_book": k_odds.get("over_bookmaker", k_odds.get("bookmaker", "")),
                        "best_under_book": k_odds.get("under_bookmaker", k_odds.get("bookmaker", "")),
                    })

            # -- GAME ODDS (h2h, spread, total)
            odds_data = self.odds.get_game_odds(event_id)
            if odds_data:
                for bm in odds_data.get("bookmakers", [])[:3]:
                    bk = bm["title"]
                    for m in bm.get("markets", []):
                        mk = m["key"]
                        outcomes = [(o["name"], o.get("point"), o["price"]) for o in m.get("outcomes", [])]
                        if mk not in market_results["game_odds"]:
                            market_results["game_odds"][mk] = []
                        market_results["game_odds"][mk].append({
                            "bookmaker": bk,
                            "outcomes": outcomes,
                        })

        proj["market"] = market_results
        return proj

    def print_market_report(self, result: Dict):
        """Imprime reporte con comparacion de mercado."""
        if "error" in result:
            print(f"ERROR: {result['error']}")
            return

        self.print_prop_report(result)

        market = result.get("market", {})
        edges = market.get("pitcher_k_edges", [])

        if edges:
            print(f"\n  {'='*75}")
            print(f"  MERCADO EN VIVO - Pitcher Strikeouts")
            print(f"  {'='*75}")
            print(f"  {'Pitcher':<20} {'Proj':<6} {'Line':<6} {'Over':<8} {'EV(O)':<8} {'Edge(O)':<10} {'Under':<8} {'EV(U)':<8} {'Edge(U)':<10}")
            print(f"  {'-'*18} {'-'*4} {'-'*4} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*6} {'-'*8}")
            for e in edges:
                ov = e["over_edge"]
                un = e["under_edge"]
                print(f"  {e['pitcher']:<20} {e['our_proj']:<6} {e['market_line']:<6} "
                      f"{e['over_odds']:<8} {ov['ev_pct']:<8} {ov['edge_pct']:<10} "
                      f"{e['under_odds']:<8} {un['ev_pct']:<8} {un['edge_pct']:<10}")
                if ov['recommendation'] in ("BET", "STRONG BET"):
                    print(f"    -> {ov['recommendation']} OVER {e['market_line']} @ {e['over_odds']} ({e['best_over_book']})")
                if un['recommendation'] in ("BET", "STRONG BET"):
                    print(f"    -> {un['recommendation']} UNDER {e['market_line']} @ {e['under_odds']} ({e['best_under_book']})")

    # ================================================================
    # 6. REPORTE
    # ================================================================

    def print_prop_report(self, results: Dict):
        """Imprime reporte formateado de player props."""
        if "error" in results:
            print(f"ERROR: {results['error']}")
            return

        print(f"\n{'='*75}")
        print(f"  PLAYER PROPS - {results['game']}")
        print(f"  Venue: {results['venue']} | Weather: {results['weather'].get('temperature', '?')}C, "
              f"Wind: {results['weather'].get('wind_speed', '?')}mph")
        print(f"{'='*75}")

        # Pitcher props
        print(f"\n  PITCHER STRIKEOUTS:")
        print(f"  {'Pitcher':<25} {'Proj':<8} {'K/9':<8} {'Conf':<8}")
        print(f"  {'-'*23} {'-'*6} {'-'*6} {'-'*6}")
        for name, proj in results.get("pitcher_props", {}).items():
            print(f"  {name:<25} {proj['projected']:<8} {proj['k9']:<8} {proj['confidence']:<8}")

        # Batter props
        print(f"\n  BATTER PROPS (top 3 por equipo):")
        for bp in results.get("batter_props", []):
            name = bp["batter"]
            side = bp["team"]
            h2h = bp.get("h2h", {})
            hits = bp.get("hits_projection", {})
            ks = bp.get("strikeouts_projection", {})
            hr = bp.get("hr_projection", {})
            signals = bp.get("signals", {})

            print(f"\n  {name} ({side.upper()})")
            print(f"    H2H vs pitcher: {h2h.get('ab', 0)} AB, .{h2h.get('avg', 0)*1000:.0f} AVG, "
                  f"{h2h.get('hr', 0)} HR, {h2h.get('k', 0)} K")
            print(f"    Hits: {hits.get('projected', '?')} (blended .{hits.get('blended_avg', 0)*1000:.0f}) "
                  f"{'SIGNAL!' if hits.get('strong_signal') else ''}")
            print(f"    K's: {ks.get('projected', '?')} (K% {ks.get('batter_k_pct', '?')}%)")
            print(f"    HR: {hr.get('projected', '?')} (park x{hr.get('park_factor', 1.0)})")

            if any(signals.values()):
                active = [k for k, v in signals.items() if v]
                print(f"    SIGNALS: {', '.join(active)}")
