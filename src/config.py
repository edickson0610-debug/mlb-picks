import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
    WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    ODDS_API_KEY = os.getenv("ODDS_API_KEY")

    # ============================================================
    # PROTOCOLO V2.6 - SCORE SYSTEM (7 componentes)
    # Basado en protocolo de alta confianza: score >= 0.80
    # Sweet spot optimo: 0.80 - 0.84 (81.8% WR historico)
    # ============================================================

    # UMBRALES DE SCORE
    MIN_SCORE = 0.80               # Regla de oro: NUNCA bajar de 0.80 (player props, HR)
    MIN_MAIN_SCORE = 0.60          # Mercados principales (RL, ML, Totales) - backtest RL 80% WR
    SCORE_SWEET_SPOT_MIN = 0.80    # Rango optimo inicio
    SCORE_SWEET_SPOT_MAX = 0.84    # Rango optimo fin
    SCORE_RECHAZO_AUTOMATICO = 0.75  # Por debajo: rechazo automatico

    # PESOS DE LOS 7 COMPONENTES (total = 1.00)
    SCORE_WEIGHTS = {
        "duelo_abridores": 0.25,    # xFIP, SIERA, K/9, BB/9, HR/9
        "ofensiva": 0.20,           # wRC+, AVG, OBP, SLG (30d)
        "bullpen": 0.15,            # ERA, WHIP, K/9 (15d)
        "factor_parque": 0.10,      # HR, runs, hits (Statcast)
        "clima": 0.10,              # lluvia, viento, temperatura, AQI
        "umpire": 0.10,             # zona de strikes, tendencias
        "run_expectancy": 0.10,     # proyeccion de carreras
    }

    # ============================================================
    # RUN EXPECTANCY (formula del protocolo paso 4)
    # RE = (xFIP_abridor * 0.6) + (Bullpen_ERA * 0.3)
    #      + (wRC+_ofensivo / 100 * 0.1) * FactorParque
    # ============================================================
    RE_ABRIDOR_WEIGHT = 0.6
    RE_BULLPEN_WEIGHT = 0.3
    RE_OFENSIVA_WEIGHT = 0.1

    # PROBABILIDAD PYTHAGOREAN
    PYTHAG_EXPONENT = 1.83

    # ============================================================
    # FILTROS POR MERCADO (PASO 5 del protocolo)
    # ============================================================

    # Money Line
    MIN_PROB_MARGIN_ML = 0.05      # Prob estimada > Prob implicita por >= 5pp
    MAX_ML_ODDS = -120
    MIN_ML_ODDS = 110

    # Runline +1.5 (Protocolo Real: EV >= 15%, priorizar Total <= 9.0, ML fav <= -150)
    MAX_RL_ODDS = -140
    RL_ODDS_RANGE = (-140, -120)
    MIN_EV_RL = 0.15               # Protocolo: EV >= 15% para aprobar Runline +1.5
    RL_TOTAL_SOFT_MAX = 9.0        # Priorizar juegos cerrados (soft threshold)
    RL_TOTAL_HARD_MAX = 10.0       # Rechazo solo si total > 10.0
    MIN_ML_FAVORITE = -150         # Soft preference (priorizar, no hard reject)

    # Totales
    MIN_RUN_MARGIN = 0.50          # Colchon minimo (protocolo paso 5)
    MAX_TOTALS_PER_DAY = 4
    PRIORITY_LINES = [7.5, 8, 8.5, 9, 9.5]

    # Player Props
    MIN_EV_PROPS = 0.15            # Props requieren EV mas alto (usa odds reales de mercado)
    PROP_REQUIREMENTS = ["k_percent", "k9", "xfip", "platoon_split"]

    # ============================================================
    # FILTRO DE CLIMA (PASO 6 del protocolo)
    # ============================================================
    RAIN_THRESHOLD = 0.50           # Lluvia > 50% -> No aprobar
    AQI_MAX = 200                   # AQI > 200 -> Anular
    WIND_MAX_MPH = 20               # Viento > 20 mph -> Reducir score en 0.05
    FLOOD_KEYWORDS = ["flood", "thunderstorm", "tornado", "hurricane"]
    TEMP_MAX_UNDER = 30             # Temperatura > 30C -> descartar Under

    # ============================================================
    # DUELE DE ABRIDORES (componente 1, 25%)
    # ============================================================
    XFIP_GOOD = 3.50                # xFIP bueno (por debajo)
    XFIP_ELITE = 3.00               # xFIP elite
    SIERA_GOOD = 3.80
    K9_ELITE = 10.0                 # K/9 elite
    BB9_GOOD = 2.5                  # BB/9 bueno (por debajo)
    HR9_GOOD = 1.0                  # HR/9 bueno (por debajo)

    # ============================================================
    # OFENSIVA (componente 2, 20%)
    # ============================================================
    WRC_PLUS_GOOD = 105             # wRC+ bueno
    WRC_PLUS_ELITE = 120            # wRC+ elite
    OPS_ROAD_MIN = 0.700            # OPS minimo en carretera

    # ============================================================
    # BULLPEN (componente 3, 15%)
    # ============================================================
    BULLPEN_METRICS = ["xfip", "siera", "k_bb", "whip"]
    BULLPEN_XFIP_GOOD = 3.50
    BULLPEN_ERA_GOOD = 3.50

    # ============================================================
    # FACTOR PARQUE (componente 4, 10%)
    # ============================================================
    PARK_HR_FACTORS = {
        "Coors Field": 1.25, "Great American Ball Park": 1.15,
        "Citizens Bank Park": 1.12, "Yankee Stadium": 1.10,
        "Fenway Park": 1.08, "American Family Field": 1.07,
        "Globe Life Field": 1.05, "Chase Field": 1.04,
        "Truist Park": 1.03, "Oracle Park": 0.90,
        "Petco Park": 0.88, "T-Mobile Park": 0.87,
        "Oakland Coliseum": 0.85, "Citi Field": 0.92,
        "Kauffman Stadium": 0.88, "Comerica Park": 0.95,
        "Target Field": 0.96, "Wrigley Field": 0.97,
        "PNC Park": 0.93, "Busch Stadium": 0.91,
        "Dodger Stadium": 1.02, "Angel Stadium": 1.01,
        "Minute Maid Park": 1.06, "Tropicana Field": 0.92,
        "Rogers Centre": 1.04, "Nationals Park": 0.98,
        "Marlins Park": 0.89, "Guaranteed Rate Field": 1.00,
        "Progressive Field": 0.96,
    }

    # ============================================================
    # UMPIRE (componente 6, 10%)
    # ============================================================
    UMPIRE_STRIKE_ZONE_GOOD = 0.80  # Tasa de llamado correcto
    UMPIRE_BIAS_MAX = 0.05          # Sesgo maximo permitido

    # ============================================================
    # PITCHERS ELITE (anulacion Over en totales)
    # ============================================================
    ELITE_PITCHERS = ["Skenes", "Wheeler", "Skubal", "Yamamoto", "Sale",
                      "Strider", "deGrom", "Ohtani", "Burnes", "Cole",
                      "Sasaki", "Misiorowski", "Greene", "Gilbert",
                      "Kirby", "Valdez", "Alcantara", "Gausman",
                      "Webb", "Castillo", "Gallen", "Nola",
                      "Fried", "Snell", "Cease"]
    ELITE_PITCHER_EXCEPTION_EV = 0.25

    # ============================================================
    # ENTRADAS DIARIAS (selector)
    # ============================================================
    MAX_ENTRIES_PER_DAY = 8
    MIN_ENTRIES_PER_DAY = 6
    MAX_PER_MARKET = 2

    # ============================================================
    # PLAYER PROPS - REGLAS DE ORO
    # ============================================================
    ALLOW_NO_LINEUP_PROPS = True    # True: player props funcionan sin lineups (usa roster fallback)
    PROP_H2H_MIN_AB = 5             # Min AB para considerar H2H signal
    PROP_H2H_AVG_THRESHOLD = 0.285  # Min AVG para H2H strong signal
    PROP_CONTRARIAN_K_PCT = 0.30    # K% minimo para considerar contrarian Under

    # ============================================================
    # VIENTO (para analisis de HR y totales)
    # ============================================================
    HR_WIND_DIRECTIONS = ["SW", "SSW", "S", "SSE", "SE", "W", "WSW", "NW", "WNW"]
    WIND_HR_THRESHOLD = 8           # mph minimo para afectar HR
    WIND_SUPPRESSION_THRESHOLD = 10  # mph minimo para suprimir HR
