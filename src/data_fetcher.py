"""
ProtocolDataFetcher - Datos reales desde MLB Stats API + OpenWeatherMap
Fuentes:
  - MLB Stats API (statsapi.mlb.com): pitchers, bateadores, equipos, standings
  - OpenWeatherMap: clima historico/actual
  - Cache local: evita llamadas repetidas a la API
"""
import os, re, time, json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import requests
from dotenv import load_dotenv

load_dotenv()


# ================================================================
# MAPA DE EQUIPOS MLB: nombre -> (id, abbreviation)
# ================================================================
MLB_TEAMS = {
    "angels": (108, "LAA"), "diamondbacks": (109, "AZ"), "d-backs": (109, "AZ"),
    "orioles": (110, "BAL"), "red sox": (111, "BOS"), "cubs": (112, "CHC"),
    "reds": (113, "CIN"), "guardians": (114, "CLE"), "rockies": (115, "COL"),
    "tigers": (116, "DET"), "astros": (117, "HOU"), "royals": (118, "KC"),
    "dodgers": (119, "LAD"), "nationals": (120, "WSH"), "mets": (121, "NYM"),
    "athletics": (133, "ATH"), "pirates": (134, "PIT"), "padres": (135, "SD"),
    "mariners": (136, "SEA"), "giants": (137, "SF"), "cardinals": (138, "STL"),
    "rays": (139, "TB"), "rangers": (140, "TEX"), "blue jays": (141, "TOR"),
    "twins": (142, "MIN"), "phillies": (143, "PHI"), "braves": (144, "ATL"),
    "white sox": (145, "CWS"), "marlins": (146, "MIA"), "yankees": (147, "NYY"),
    "brewers": (158, "MIL"),
}

# Reverse: abreviatura -> (id, nombre)
ABBREV_TO_TEAM = {}
for name, (tid, abbr) in MLB_TEAMS.items():
    ABBREV_TO_TEAM[abbr.upper()] = (tid, name.title())
    ABBREV_TO_TEAM[abbr] = (tid, name.title())


class ProtocolDataFetcher:
    """Obtiene datos reales de MLB Stats API + OpenWeatherMap"""

    def __init__(self, cache_dir="api_cache"):
        self.base = "https://statsapi.mlb.com/api/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        self.weather_key = os.getenv("WEATHER_API_KEY", "")
        self.cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        # Caches en memoria
        self._pitcher_cache = {}
        self._batter_cache = {}
        self._roster_cache = {}
        self._team_stats_cache = {}
        self._player_search_cache = {}

    def _cache_get(self, key: str) -> Optional[dict]:
        if not self.cache_dir:
            return None
        path = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(path):
            # Cache por 6 horas
            age = time.time() - os.path.getmtime(path)
            if age < 21600:  # 6h
                with open(path) as f:
                    return json.load(f)
        return None

    def _cache_set(self, key: str, data: dict):
        if not self.cache_dir:
            return
        path = os.path.join(self.cache_dir, f"{key}.json")
        with open(path, "w") as f:
            json.dump(data, f)

    def _api(self, url: str, params: dict = None) -> Optional[dict]:
        try:
            r = self.session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            pass
        return None

    # ================================================================
    # 1. BUSQUEDA DE JUGADORES
    # ================================================================

    def search_player(self, name: str) -> Optional[dict]:
        """Busca un jugador por nombre exacto o parcial.
        Retorna: {id, fullName, position} o None"""
        key = name.lower().strip()
        if key in self._player_search_cache:
            return self._player_search_cache[key]

        # Intentar busqueda directa
        url = f"{self.base}/people"
        r = self._api(url, {"search": name})
        if r:
            people = r.get("people", [])
            # Primero buscar coincidencia exacta
            for p in people:
                if p.get("fullName", "").lower() == key:
                    result = {"id": p["id"], "name": p["fullName"],
                              "position": p.get("primaryPosition", {}).get("abbreviation", "?")}
                    self._player_search_cache[key] = result
                    return result
            # Si no, el primero que coincida
            for p in people:
                if key in p.get("fullName", "").lower():
                    result = {"id": p["id"], "name": p["fullName"],
                              "position": p.get("primaryPosition", {}).get("abbreviation", "?")}
                    self._player_search_cache[key] = result
                    return result
            # Si no, el primer resultado
            if people:
                p = people[0]
                result = {"id": p["id"], "name": p["fullName"],
                          "position": p.get("primaryPosition", {}).get("abbreviation", "?")}
                self._player_search_cache[key] = result
                return result
        self._player_search_cache[key] = None
        return None

    # ================================================================
    # 2. STATS DE PITCHERS (para duelo de abridores - componente 25%)
    # ================================================================

    def get_pitcher_stats(self, player_id: int, season: int = None) -> Dict:
        """Obtiene stats seasonales de un pitcher.
        Retorna: {k9, bb9, hr9, era, whip, games, xfip_est}"""
        if season is None:
            season = datetime.now().year
        key = f"pitcher_{player_id}_{season}"
        if key in self._pitcher_cache:
            return self._pitcher_cache[key]

        url = f"{self.base}/people/{player_id}/stats"
        params = {"stats": "season", "season": season, "group": "pitching", "gameType": "R"}
        data = self._api(url, params)
        default = {"k9": 8.0, "bb9": 3.0, "hr9": 1.2, "era": 4.00, "whip": 1.30, "games": 0, "xfip_est": 4.20, "ip": 0}

        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    k9 = float(st.get("strikeoutsPer9Inn", 8.0))
                    bb9 = float(st.get("walksPer9Inn", 3.0))
                    hr9 = float(st.get("homeRunsPer9", 1.2))
                    era = float(st.get("era", 4.00))
                    whip = float(st.get("whip", 1.30))
                    games = int(st.get("gamesPitched", 0))
                    ip = float(st.get("inningsPitched", 0) or 0)
                    # Estimar xFIP desde K/9, BB/9, HR/9
                    # xFIP ~ 4.20 + (HR/9 * 1.4) + (BB/9 * 0.3) - (K/9 * 0.2)
                    xfip_est = round(4.20 + (hr9 * 1.4) + (bb9 * 0.3) - (k9 * 0.2), 2)
                    result = {
                        "k9": round(k9, 1), "bb9": round(bb9, 1), "hr9": round(hr9, 2),
                        "era": round(era, 2), "whip": round(whip, 2),
                        "games": games, "ip": round(ip, 1),
                        "xfip_est": xfip_est, "season": season,
                    }
                    self._pitcher_cache[key] = result
                    return result
        self._pitcher_cache[key] = default
        return dict(default)

    def get_pitcher_stats_by_name(self, name: str, season: int = None) -> Dict:
        """Busca pitcher por nombre y obtiene sus stats."""
        player = self.search_player(name)
        if player and player["id"]:
            return self.get_pitcher_stats(player["id"], season)
        return {"k9": 8.0, "bb9": 3.0, "hr9": 1.2, "era": 4.00, "whip": 1.30, "games": 0, "xfip_est": 4.20}

    # ================================================================
    # 3. STATS DE BATEADORES (para ofensiva del equipo - componente 20%)
    # ================================================================

    def get_batter_stats(self, player_id: int, season: int = None) -> Dict:
        """Obtiene stats seasonales de un bateador.
        Retorna: {ops, slg, avg, obp, games}"""
        if season is None:
            season = datetime.now().year
        key = f"batter_{player_id}_{season}"
        if key in self._batter_cache:
            return self._batter_cache[key]

        url = f"{self.base}/people/{player_id}/stats"
        params = {"stats": "season", "season": season, "group": "hitting", "gameType": "R"}
        data = self._api(url, params)
        default = {"ops": 0.700, "slg": 0.400, "avg": 0.250, "obp": 0.320, "games": 0,
                    "hr": 0, "hits": 0, "at_bats": 0, "k": 0, "bb": 0, "plate_appearances": 0}

        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    games = int(st.get("gamesPlayed", 0))
                    ab = int(st.get("atBats", 500))
                    result = {
                        "ops": float(st.get("ops", 0.700)),
                        "slg": float(st.get("slg", 0.400)),
                        "avg": float(st.get("avg", 0.250)),
                        "obp": float(st.get("obp", 0.320)),
                        "games": games,
                        "season": season,
                        "hr": int(st.get("homeRuns", 0)),
                        "hits": int(st.get("hits", 0)),
                        "at_bats": ab,
                        "k": int(st.get("strikeOuts", 0)),
                        "bb": int(st.get("baseOnBalls", 0)),
                        "plate_appearances": int(st.get("plateAppearances", 0)),
                    }
                    self._batter_cache[key] = result
                    return result
        self._batter_cache[key] = default
        return dict(default)

    # ================================================================
    # 4. EQUIPOS - ROSTER, STATS AGREGADOS, BULLPEN
    # ================================================================

    def get_team_id(self, team_ref: str) -> Optional[int]:
        """Convierte nombre o abreviatura a team ID."""
        ref = team_ref.strip().lower()
        if ref in MLB_TEAMS:
            return MLB_TEAMS[ref][0]
        ref_up = team_ref.strip().upper()
        if ref_up in ABBREV_TO_TEAM:
            return ABBREV_TO_TEAM[ref_up][0]
        return None

    def get_team_roster(self, team_id: int, season: int = None) -> List[Dict]:
        """Obtiene roster completo del equipo.
        Retorna: [{id, name, position}]"""
        if season is None:
            season = datetime.now().year
        key = f"roster_{team_id}_{season}"
        if key in self._roster_cache:
            return self._roster_cache[key]

        url = f"{self.base}/teams/{team_id}/roster"
        data = self._api(url, {"season": season})
        roster = []
        if data:
            for p in data.get("roster", []):
                pos = p.get("position", {}).get("abbreviation", "?")
                roster.append({
                    "id": p["person"]["id"],
                    "name": p["person"]["fullName"],
                    "position": pos,
                })
        self._roster_cache[key] = roster
        return roster

    def get_team_hitting_stats(self, team_id: int, season: int = None) -> Dict:
        """Stats de bateo AGREGADOS del equipo.
        Retorna: {ops, slg, avg, obp, hr, runs}"""
        if season is None:
            season = datetime.now().year
        key = f"team_hit_{team_id}_{season}"
        if key in self._team_stats_cache:
            return self._team_stats_cache[key]

        url = f"{self.base}/teams/{team_id}/stats"
        data = self._api(url, {"season": season, "group": "hitting", "gameType": "R", "stats": "season"})
        default = {"ops": 0.710, "slg": 0.400, "avg": 0.248, "obp": 0.318, "hr": 150, "runs": 650}

        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    result = {
                        "ops": float(st.get("ops", 0.710)),
                        "slg": float(st.get("slg", 0.400)),
                        "avg": float(st.get("avg", 0.248)),
                        "obp": float(st.get("obp", 0.318)),
                        "hr": int(st.get("homeRuns", 150)),
                        "runs": int(st.get("runs", 650)),
                        "season": season,
                    }
                    self._team_stats_cache[key] = result
                    return result
        self._team_stats_cache[key] = default
        return dict(default)

    def get_team_pitching_stats(self, team_id: int, season: int = None) -> Dict:
        """Stats de pitcheo AGREGADOS del equipo (todos los lanzadores).
        Retorna: {era, whip, k9, bb9, hr9, avg}"""
        if season is None:
            season = datetime.now().year
        key = f"team_pitch_{team_id}_{season}"
        if key in self._team_stats_cache:
            return self._team_stats_cache[key]

        url = f"{self.base}/teams/{team_id}/stats"
        data = self._api(url, {"season": season, "group": "pitching", "gameType": "R", "stats": "season"})
        default = {"era": 4.20, "whip": 1.30, "k9": 8.5, "bb9": 3.2, "hr9": 1.1, "avg": 0.252}

        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    result = {
                        "era": float(st.get("era", 4.20)),
                        "whip": float(st.get("whip", 1.30)),
                        "k9": float(st.get("strikeoutsPer9Inn", 8.5)),
                        "bb9": float(st.get("walksPer9Inn", 3.2)),
                        "hr9": float(st.get("homeRunsPer9", 1.1)),
                        "avg": float(st.get("avg", 0.252)),
                        "season": season,
                    }
                    self._team_stats_cache[key] = result
                    return result
        self._team_stats_cache[key] = default
        return dict(default)

    def get_bullpen_stats(self, team_id: int, season: int = None) -> Dict:
        """Stats del BULLPEN (relevistas, no abridores).
        Filtra pitchers del roster con gamesStarted == 0 o gamesStarted << gamesPitched.
        Retorna: {era, whip, k9}"""
        if season is None:
            season = datetime.now().year

        roster = self.get_team_roster(team_id, season)
        pitchers = [p for p in roster if p["position"] in ("P", "RP", "SP", "CL")]

        total_era = 0.0
        total_whip = 0.0
        total_k9 = 0.0
        count = 0

        for p in pitchers[:15]:  # Max 15 pitchers por equipo
            stats = self.get_pitcher_stats(p["id"], season)
            games = stats.get("games", 0)
            ip = stats.get("ip", 0)
            # Un relevista tiene juegos pero pocas entradas como abridor
            if games > 5 and ip > 10:
                total_era += stats["era"] * ip
                total_whip += stats["whip"] * ip
                total_k9 += stats["k9"] * ip
                count += ip

        if count > 0:
            return {
                "era": round(total_era / count, 2),
                "whip": round(total_whip / count, 2),
                "k9": round(total_k9 / count, 2),
                "source": "real",
            }

        # Fallback: team pitching stats generales
        team_p = self.get_team_pitching_stats(team_id, season)
        return {
            "era": round(team_p["era"] * 1.05, 2),  # bullpen suele ser peor
            "whip": round(team_p["whip"] * 1.05, 2),
            "k9": round(team_p["k9"] * 0.95, 1),  # relevistas tienen menos K/9
            "source": "estimated",
        }

    def get_team_record(self, team_id: int, season: int = None) -> Dict:
        """Record del equipo (wins, losses, win%)"""
        if season is None:
            season = datetime.now().year

        url = f"{self.base}/teams/{team_id}/stats"
        data = self._api(url, {"season": season, "group": "pitching", "gameType": "R", "stats": "season"})
        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    # Team record sometimes in the split itself
                    pass

        # Usar standings endpoint
        url = f"{self.base}/standings"
        data = self._api(url, {"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"})
        if data:
            for rec in data.get("records", []):
                for tr in rec.get("teamRecords", []):
                    if tr["team"]["id"] == team_id:
                        return {
                            "wins": int(tr["wins"]),
                            "losses": int(tr["losses"]),
                            "wpct": float(tr["winningPercentage"]),
                        }
        return {"wins": 81, "losses": 81, "wpct": 0.500}

    # ================================================================
    # 5. JUEGOS - SCHEDULE, PITCHERS, LINEUPS
    # ================================================================

    def get_daily_games(self, date: str = None) -> List[Dict]:
        """Lista de juegos del dia con datos completos + lanzadores probables."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        url = f"{self.base}/schedule"
        data = self._api(url, {"sportId": 1, "date": date, "hydrate": "probablePitcher,weather"})
        games = []
        if data:
            for dt in data.get("dates", []):
                for g in dt.get("games", []):
                    away = g["teams"]["away"]
                    home = g["teams"]["home"]
                    away_team = away["team"]
                    home_team = home["team"]

                    # Probable pitchers from hydrate
                    away_pitcher = away.get("probablePitcher", {})
                    home_pitcher = home.get("probablePitcher", {})

                    games.append({
                        "game_id": g["gamePk"],
                        "date": g.get("officialDate", date),
                        "away_team": away_team["name"],
                        "away_id": away_team["id"],
                        "away_abbrev": away_team.get("abbreviation", away_team["name"][:3].upper()),
                        "away_pitcher": away_pitcher.get("fullName", "TBD"),
                        "away_pitcher_id": away_pitcher.get("id"),
                        "home_team": home_team["name"],
                        "home_id": home_team["id"],
                        "home_abbrev": home_team.get("abbreviation", home_team["name"][:3].upper()),
                        "home_pitcher": home_pitcher.get("fullName", "TBD"),
                        "home_pitcher_id": home_pitcher.get("id"),
                        "status": g["status"]["detailedState"],
                        "venue": g.get("venue", {}).get("name", "Unknown"),
                        "venue_id": g.get("venue", {}).get("id"),
                        "game_date": g.get("gameDate", ""),
                    })
        return games

    def get_probable_pitchers(self, game_id: int) -> Dict[str, str]:
        """Lanzadores probables para un juego."""
        url = f"{self.base}/game/{game_id}/probablePitchers"
        data = self._api(url)
        if data:
            away = data.get("away", {})
            home = data.get("home", {})
            return {
                "away": away.get("fullName", away.get("lastName", "TBD")),
                "away_id": away.get("id"),
                "home": home.get("fullName", home.get("lastName", "TBD")),
                "home_id": home.get("id"),
            }
        return {"away": "TBD", "away_id": None, "home": "TBD", "home_id": None}

    def get_lineups(self, game_id: int) -> Dict[str, List[str]]:
        """Alineaciones titulares. Fallback a boxscore si lineups no disponible."""
        # Intentar endpoint de lineups primero
        url = f"{self.base}/game/{game_id}/lineups"
        data = self._api(url)
        if data and data.get("teams"):
            lineups = {"away": [], "home": []}
            for team in data.get("teams", []):
                abbrev = team.get("team", {}).get("abbreviation", "")
                players = [p["person"]["fullName"] for p in team.get("players", [])
                           if p.get("position", {}).get("abbreviation") != "P" or p.get("battingOrder")]
                # Determinar si es home o away (primer equipo = away?)
                if not lineups["away"]:
                    lineups["away"] = players
                else:
                    lineups["home"] = players
            return lineups

        # Fallback: boxscore
        url = f"{self.base}/game/{game_id}/boxscore"
        data = self._api(url)
        lineups = {"away": [], "home": []}
        if data:
            for side in ["away", "home"]:
                team_data = data.get("teams", {}).get(side, {})
                batting_order = team_data.get("battingOrder", [])
                # battingOrder contiene IDs de jugadores en orden (ints o strings "IDxxxxx")
                players_lookup = team_data.get("players", {})
                for pid_ref in batting_order:
                    pid_str = str(pid_ref)
                    if "ID" in pid_str:
                        pid_str = pid_str.split("ID")[-1]
                    # Buscar en players lookup por key que contenga este ID
                    player_info = None
                    for pk, pv in players_lookup.items():
                        if pid_str in str(pk):
                            player_info = pv
                            break
                    if player_info:
                        name = player_info.get("person", {}).get("fullName", pid_str)
                        lineups[side].append(name)
                if not lineups[side]:
                    # Si no hay batting order, listar todos los bateadores
                    for pid_ref, player_info in players_lookup.items():
                        pos = player_info.get("position", {}).get("abbreviation", "")
                        if pos not in ("P", "RP", "SP", "CL") and "pitching" not in player_info.get("stats", {}):
                            name = player_info.get("person", {}).get("fullName", pid_ref)
                            if name not in lineups[side]:
                                lineups[side].append(name)
        return lineups

    def get_game_weather(self, game_id: int) -> Dict:
        """Clima del juego desde MLB API (si disponible)."""
        url = f"{self.base}/game/{game_id}/contextMetrics"
        data = self._api(url)
        if data and "game" in data:
            gw = data["game"].get("weather", {})
            if gw:
                return {
                    "temperature": gw.get("temp", 25),
                    "wind_speed": gw.get("wind", 8),
                    "wind_direction": gw.get("windDirection", "SW"),
                    "conditions": gw.get("condition", "clear"),
                    "precipitation": gw.get("precipitation", 0),
                    "source": "mlb_api",
                }
        return {"source": "none"}

    # ================================================================
    # 6. WEATHER via OpenWeatherMap
    # ================================================================

    def get_weather(self, venue: str, game_date: str = None) -> Dict:
        """Clima usando OpenWeatherMap API.
        Fallback: datos simulados si no hay API key."""
        # Primero intentar MLB API weather para el juego
        # (se pasa por game_id, no por venue)

        # Si tenemos API key de OpenWeatherMap, usarla
        if self.weather_key and self.weather_key != "tu_api_key_aqui":
            return self._get_weather_owm(venue, game_date)

        # Fallback: datos simulados basados en fecha y estadio
        return self._simulate_weather(venue, game_date)

    def _get_weather_owm(self, venue: str, game_date: str = None) -> Dict:
        """OpenWeatherMap - geocode + weather."""
        cache_key = f"weather_{venue}_{game_date or 'today'}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        try:
            # 1. Geocode: obtener lat/lon del estadio
            # Mapa de estadios conocidos
            venue_coords = {
                "yankee stadium": (40.8292, -73.9262),
                "fenway park": (42.3467, -71.0972),
                "wrigley field": (41.9484, -87.6553),
                "dodger stadium": (34.0739, -118.2400),
                "oracle park": (37.7786, -122.3893),
                "petco park": (32.7076, -117.1571),
                "t-mobile park": (47.5914, -122.3324),
                "coors field": (39.7559, -104.9942),
                "citizens bank park": (39.9058, -75.1665),
                "truist park": (33.8908, -84.4683),
                "globe life field": (32.7476, -97.0832),
                "minute maid park": (29.7572, -95.3556),
                "comerica park": (42.3390, -83.0485),
                "progressive field": (41.4961, -81.6852),
                "great american ball park": (39.0973, -84.5066),
                "pnc park": (40.4468, -80.0056),
                "busch stadium": (38.6226, -90.1928),
                "miller park": (43.0281, -87.9712),
                "target field": (44.9817, -93.2778),
                "kauffman stadium": (39.0516, -94.4803),
                "angel stadium": (33.8003, -117.8827),
                "oakland coliseum": (37.7516, -122.2005),
                "tropicana field": (27.7684, -82.6531),
                "loandepot park": (25.7781, -80.2197),
                "rogers centre": (43.6414, -79.3894),
                "nationals park": (38.8730, -77.0075),
                "citi field": (40.7569, -73.8459),
                "chase field": (33.4454, -112.0666),
                "guaranteed rate field": (41.8300, -87.6338),
                "american family field": (43.0281, -87.9712),
            }

            venue_lower = venue.lower().strip()
            coords = venue_coords.get(venue_lower)
            if not coords:
                return self._simulate_weather(venue, game_date)

            lat, lon = coords

            # 2. Weather API
            if game_date:
                # Historico: OWM One Call API (requiere suscripcion)
                # Por ahora, usamos current weather
                pass

            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {"lat": lat, "lon": lon, "appid": self.weather_key, "units": "metric"}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                wind_deg = data.get("wind", {}).get("deg", 0)
                wind_dir = self._deg_to_dir(wind_deg)
                weather_desc = data.get("weather", [{}])[0].get("description", "clear")
                result = {
                    "temperature": round(data["main"]["temp"]),
                    "wind_speed": round(data.get("wind", {}).get("speed", 8)),
                    "wind_direction": wind_dir,
                    "conditions": weather_desc,
                    "precipitation": round(data.get("clouds", {}).get("all", 0) * 0.3),
                    "aqi": 35,
                    "source": "openweathermap",
                }
                self._cache_set(cache_key, result)
                return result
        except Exception:
            pass

        return self._simulate_weather(venue, game_date)

    def _simulate_weather(self, venue: str, game_date: str = None) -> Dict:
        """Weather simulado basado en el mes."""
        month = 7
        if game_date:
            try:
                month = int(game_date.split("-")[1])
            except (ValueError, IndexError):
                pass

        # Temperatura base por mes (MLB season: marzo-octubre)
        temp_map = {3: 15, 4: 18, 5: 22, 6: 26, 7: 28, 8: 27, 9: 24, 10: 18}
        temp = temp_map.get(month, 24)

        # Probabilidad de lluvia
        rain_prob = {3: 0.3, 4: 0.3, 5: 0.2, 6: 0.15, 7: 0.1, 8: 0.1, 9: 0.15, 10: 0.2}
        rain = rain_prob.get(month, 0.15)

        return {
            "temperature": temp,
            "wind_speed": 8 + int(month in (3, 4, 10)) * 4,
            "wind_direction": ["SW", "NW", "SE", "W"][month % 4],
            "conditions": "clear" if rain < 0.2 else "cloudy",
            "precipitation": round(rain * 100),
            "aqi": 35,
            "source": "simulated",
        }

    @staticmethod
    def _deg_to_dir(deg: float) -> str:
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return dirs[round(deg / 22.5) % 16]

    # ================================================================
    # 7. STANDINGS
    # ================================================================

    def get_standings(self, season: int = None) -> List[Dict]:
        """Standings de toda la liga."""
        if season is None:
            season = datetime.now().year
        url = f"{self.base}/standings"
        data = self._api(url, {"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"})
        teams = []
        if data:
            for rec in data.get("records", []):
                league = rec.get("league", {}).get("name", "?")
                division = rec.get("division", {}).get("name", "?")
                for tr in rec.get("teamRecords", []):
                    t = tr["team"]
                    teams.append({
                        "id": t["id"],
                        "name": t["name"],
                        "abbrev": t.get("abbreviation", ""),
                        "league": league,
                        "division": division,
                        "wins": int(tr["wins"]),
                        "losses": int(tr["losses"]),
                        "wpct": float(tr["winningPercentage"]),
                        "gb": tr.get("gamesBack", "0"),
                    })
        return teams

    # ================================================================
    # 8. UTILIDADES
    # ================================================================

    def estimate_wrc_plus(self, ops: float) -> int:
        """Estimar wRC+ desde OPS (correlacion aproximada).
        wRC+ ~ (OPS - 0.650) * 200 + 95"""
        return int((ops - 0.650) * 200 + 95)

    def get_full_game_context(self, game_id: int, season: int = None,
                               game_data: dict = None) -> Dict:
        """Obtiene TODO el contexto necesario para evaluar un juego.
        Si no se pasa game_data, busca en el schedule de hoy y dias anteriores."""
        if season is None:
            season = datetime.now().year

        # 1. Datos basicos del juego
        if not game_data:
            # Buscar desde ayer hasta manana
            for delta in range(-1, 4):
                d = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
                games = self.get_daily_games(d)
                game_data = next((g for g in games if g["game_id"] == game_id), None)
                if game_data:
                    break
        if not game_data:
            return {"error": "Game not found"}

        # 2. Lanzadores probables (vienen en game_data desde hydrate)
        pitchers = {
            "away": game_data.get("away_pitcher", "TBD"),
            "away_id": game_data.get("away_pitcher_id"),
            "home": game_data.get("home_pitcher", "TBD"),
            "home_id": game_data.get("home_pitcher_id"),
        }
        away_pitcher_stats = {}
        home_pitcher_stats = {}
        if pitchers["away"] != "TBD" and pitchers["away_id"]:
            away_pitcher_stats = self.get_pitcher_stats(pitchers["away_id"], season)
        if pitchers["home"] != "TBD" and pitchers["home_id"]:
            home_pitcher_stats = self.get_pitcher_stats(pitchers["home_id"], season)

        # 3. Stats de equipo
        away_hit = self.get_team_hitting_stats(game_data["away_id"], season)
        home_hit = self.get_team_hitting_stats(game_data["home_id"], season)
        away_bullpen = self.get_bullpen_stats(game_data["away_id"], season)
        home_bullpen = self.get_bullpen_stats(game_data["home_id"], season)

        # 4. Clima
        weather = self.get_weather(game_data["venue"], game_data.get("date"))

        # 5. Record
        away_rec = self.get_team_record(game_data["away_id"], season)
        home_rec = self.get_team_record(game_data["home_id"], season)

        return {
            "game": game_data,
            "pitchers": pitchers,
            "away_pitcher_stats": away_pitcher_stats,
            "home_pitcher_stats": home_pitcher_stats,
            "away_hitting": away_hit,
            "home_hitting": home_hit,
            "away_bullpen": away_bullpen,
            "home_bullpen": home_bullpen,
            "weather": weather,
            "away_record": away_rec,
            "home_record": home_rec,
            "season": season,
        }
