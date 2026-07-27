"""
OddsAPIClient - The Odds API v4 integration
Obtains: live market lines (h2h, spreads, totals) + player props (pitcher strikeouts)
Free tier: 500 req/month, 3 bookmakers, US+AU regions
"""
import os, json, time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

load_dotenv()


class OddsAPIClient:
    """Cliente para The Odds API v4"""

    def __init__(self, cache_dir="api_cache"):
        self.base = "https://api.the-odds-api.com/v4"
        self.api_key = os.getenv("ODDS_API_KEY", "")
        self.cache_dir = cache_dir
        self.remaining = 500
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # ================================================================
    # API LLAMADAS
    # ================================================================

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        if not self.api_key or self.api_key == "tu_api_key_aqui":
            return None
        url = f"{self.base}{path}"
        p = {"apiKey": self.api_key}
        if params:
            p.update(params)
        try:
            r = requests.get(url, params=p, timeout=15)
            self.remaining = int(r.headers.get("x-requests-remaining", self.remaining))
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def get_remaining(self) -> int:
        return self.remaining

    # ================================================================
    # 1. SPORTS (free, no quota)
    # ================================================================

    def get_sports(self) -> List[Dict]:
        data = self._get("/sports")
        return data if data else []

    # ================================================================
    # 2. MLB EVENTS (free, no quota)
    # ================================================================

    def get_mlb_events(self) -> List[Dict]:
        data = self._get("/sports/baseball_mlb/events")
        return data if data else []

    def match_mlb_event(self, away_team: str, home_team: str) -> Optional[str]:
        """Find OddsAPI event ID by team names."""
        events = self.get_mlb_events()
        for e in events:
            if away_team.lower() in e.get("away_team", "").lower() and \
               home_team.lower() in e.get("home_team", "").lower():
                return e["id"]
        return None

    # ================================================================
    # 3. ODDS (h2h, spreads, totals) - 1 credit per region per market
    # ================================================================

    def get_game_odds(self, event_id: str, markets: str = "h2h,spreads,totals",
                      regions: str = "us") -> Optional[Dict]:
        return self._get(f"/sports/baseball_mlb/events/{event_id}/odds", {
            "markets": markets,
            "regions": regions,
            "oddsFormat": "american",
        })

    def parse_moneyline(self, odds_data: Dict, team_name: str) -> Optional[int]:
        """Extract moneyline odds for a specific team."""
        for bm in odds_data.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m["key"] == "h2h":
                    for o in m["outcomes"]:
                        if team_name.lower() in o.get("name", "").lower():
                            return o["price"]
        return None

    def parse_spread(self, odds_data: Dict, team_name: str) -> Optional[Tuple[float, int]]:
        """Extract spread (point, odds) for a specific team."""
        for bm in odds_data.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m["key"] == "spreads":
                    for o in m["outcomes"]:
                        if team_name.lower() in o.get("name", "").lower():
                            return (o["point"], o["price"])
        return None

    def parse_total(self, odds_data: Dict, side: str = "Over") -> Optional[Tuple[float, int]]:
        """Extract total (point, odds) for Over or Under."""
        for bm in odds_data.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m["key"] == "totals":
                    for o in m["outcomes"]:
                        if o.get("name", "").lower() == side.lower():
                            return (o["point"], o["price"])
        return None

    # ================================================================
    # 4. PLAYER PROPS (non-featured markets, event-specific)
    # ================================================================

    def get_player_props(self, event_id: str,
                          markets: str = "pitcher_strikeouts",
                          regions: str = "us") -> Optional[Dict]:
        return self._get(f"/sports/baseball_mlb/events/{event_id}/odds", {
            "markets": markets,
            "regions": regions,
            "oddsFormat": "american",
        })

    def parse_pitcher_strikeouts(self, props_data: Dict) -> List[Dict]:
        """
        Parse pitcher strikeouts from API response.
        Retorna: [{pitcher, line, over_odds, under_odds, bookmaker}]
        """
        results = []
        for bm in props_data.get("bookmakers", []):
            bk_name = bm["title"]
            for m in bm.get("markets", []):
                if m["key"] != "pitcher_strikeouts":
                    continue
                # Group by pitcher (from description field)
                by_pitcher = {}
                for o in m.get("outcomes", []):
                    pitcher = o.get("description", "Unknown")
                    if pitcher not in by_pitcher:
                        by_pitcher[pitcher] = {"pitcher": pitcher, "bookmaker": bk_name}
                    side = o.get("name", "")
                    point = o.get("point")
                    price = o.get("price")
                    if side == "Over":
                        by_pitcher[pitcher]["over_line"] = point
                        by_pitcher[pitcher]["over_odds"] = price
                    elif side == "Under":
                        by_pitcher[pitcher]["under_line"] = point
                        by_pitcher[pitcher]["under_odds"] = price
                    # Also capture line from either side
                    if point is not None:
                        by_pitcher[pitcher]["line"] = point
                results.extend(by_pitcher.values())
        return results

    # ================================================================
    # 5. BEST ODDS (across all bookmakers)
    # ================================================================

    def get_best_pitcher_k_odds(self, event_id: str) -> List[Dict]:
        """Get best Over and Under odds for each pitcher's strikeouts."""
        data = self.get_player_props(event_id)
        if not data:
            return []
        props = self.parse_pitcher_strikeouts(data)

        # Group by pitcher, find best odds
        best = {}
        for p in props:
            pitcher = p["pitcher"]
            if pitcher not in best:
                best[pitcher] = p
            else:
                # Better Over = higher odds, Better Under = less negative odds
                if p.get("over_odds", -9999) > best[pitcher].get("over_odds", -9999):
                    best[pitcher]["over_odds"] = p["over_odds"]
                    best[pitcher]["over_bookmaker"] = p["bookmaker"]
                if p.get("under_odds", 9999) > best[pitcher].get("under_odds", 9999):
                    best[pitcher]["under_odds"] = p["under_odds"]
                    best[pitcher]["under_bookmaker"] = p["bookmaker"]
                best[pitcher]["available"] = best[pitcher].get("available", []) + [p["bookmaker"]]

        return list(best.values())

    # ================================================================
    # 6. UTILIDADES
    # ================================================================

    @staticmethod
    def american_to_decimal(odds: int) -> float:
        if odds < 0:
            return 1 + (100 / abs(odds))
        return 1 + (odds / 100)

    @staticmethod
    def implied_prob(odds: int) -> float:
        if odds < 0:
            return abs(odds) / (abs(odds) + 100)
        return 100 / (odds + 100)
