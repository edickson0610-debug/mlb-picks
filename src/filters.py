from typing import Dict, Tuple, List
from src.calculators import MLBCalculators
from src.config import Config


class ProtocolFilters:

    # ================================================================
    # REGLA DE ORO #2: Score >= 0.80 (inquebrantable)
    # ================================================================
    @staticmethod
    def filter_by_score(score: float, market: str, threshold: float = None) -> Tuple[bool, str]:
        min_score = threshold if threshold is not None else Config.MIN_SCORE
        if score < min_score:
            return False, f"Score {score:.2f} < {min_score:.2f} ({market}): RECHAZADO"
        if min_score >= Config.MIN_SCORE and score < Config.SCORE_RECHAZO_AUTOMATICO:
            return False, f"Score {score:.2f} < {Config.SCORE_RECHAZO_AUTOMATICO}: rechazo automatico"
        advice = ""
        if Config.SCORE_SWEET_SPOT_MIN <= score <= Config.SCORE_SWEET_SPOT_MAX:
            advice = " [SWEET SPOT 81.8% WR]"
        return True, f"Score {score:.2f} >= {min_score:.2f}{advice}"

    # ================================================================
    # REGLA DE ORO #5: Clima extremo = ANULACION
    # ================================================================
    @staticmethod
    def check_weather(weather: Dict) -> Tuple[bool, str]:
        precip = weather.get("precipitation", 0)
        if precip > Config.RAIN_THRESHOLD * 100:
            return False, f"Lluvia {precip}% > {Config.RAIN_THRESHOLD*100}%: ANULADO (Regla de Oro #5)"

        conditions = weather.get("conditions", "").lower()
        for kw in Config.FLOOD_KEYWORDS:
            if kw in conditions:
                return False, f"Clima extremo: {conditions}: ANULACION AUTOMATICA (Regla de Oro #5)"

        aqi = weather.get("aqi", 0)
        if aqi > Config.AQI_MAX:
            return False, f"AQI {aqi} > {Config.AQI_MAX}: ANULACION AUTOMATICA (Regla de Oro #5)"

        return True, "Clima favorable"

    @staticmethod
    def check_wind_penalty(weather: Dict) -> float:
        """Viento > 20 mph -> reducir score en 0.05 (Paso 6 protocolo)"""
        wind = weather.get("wind_speed", 0)
        if wind > Config.WIND_MAX_MPH:
            return -0.05
        return 0.0

    # ================================================================
    # REGLA DE ORO #8: Cambio de lanzador = REVISION
    # ================================================================
    @staticmethod
    def check_pitcher_change(original: str, current: str) -> Tuple[bool, str]:
        if original != current:
            return False, f"Cambio de lanzador: {original} -> {current}: REVISION DESDE CERO (Regla de Oro #8)"
        return True, "Mismo lanzador"

    # ================================================================
    # REGLA DE ORO #4: No forzar entradas sin lineups
    # ================================================================
    @staticmethod
    def check_lineups(lineups: Dict) -> Tuple[bool, str]:
        if not lineups:
            return False, "No hay lineups: esperar confirmacion (Regla de Oro #4)"
        away = lineups.get("away", [])
        home = lineups.get("home", [])
        if not away or not home:
            return False, "Lineups incompletos: esperar (Regla de Oro #4)"
        # Para backtesting: si tenemos al menos 5 bateadores de cada lado, aceptar
        if len(away) < 5 or len(home) < 5:
            return False, f"Lineups muy incompletos: away {len(away)}, home {len(home)}"
        if len(away) < 9 or len(home) < 9:
            return True, f"Lineups parciales: away {len(away)}, home {len(home)} (aceptado para backtest)"
        return True, "Lineups confirmados"

    # ================================================================
    # DUELE DE ABRIDORES (componente 1, 25%)
    # ================================================================
    @staticmethod
    def _pitcher_score(xfip: float, k9: float, bb9: float, hr9: float) -> float:
        s = 0.0
        if xfip < Config.XFIP_ELITE:
            s += 0.30
        elif xfip < Config.XFIP_GOOD:
            s += 0.20
        elif xfip < 4.00:
            s += 0.10
        if k9 > Config.K9_ELITE:
            s += 0.20
        elif k9 > 8.0:
            s += 0.10
        if bb9 < 2.0:
            s += 0.15
        elif bb9 < Config.BB9_GOOD:
            s += 0.10
        elif bb9 < 3.0:
            s += 0.05
        if hr9 < 0.8:
            s += 0.15
        elif hr9 < Config.HR9_GOOD:
            s += 0.10
        elif hr9 < 1.2:
            s += 0.05
        return min(s, 0.80) / 0.80  # normalize to 0-1

    @staticmethod
    def score_duelo_abridores(xfip_visit: float, siera_visit: float, k9_visit: float,
                               bb9_visit: float, hr9_visit: float,
                               xfip_home: float, siera_home: float, k9_home: float,
                               bb9_home: float, hr9_home: float) -> float:
        v = ProtocolFilters._pitcher_score(xfip_visit, k9_visit, bb9_visit, hr9_visit)
        h = ProtocolFilters._pitcher_score(xfip_home, k9_home, bb9_home, hr9_home)
        score = 0.50 + ((v + h) / 2) * 0.40
        return round(min(1.0, max(0.0, score)), 2)

    # ================================================================
    # OFENSIVA (componente 2, 20%)
    # ================================================================
    @staticmethod
    def score_ofensiva(wrc_plus: float, ops: float) -> float:
        score = 0.50
        if wrc_plus >= Config.WRC_PLUS_ELITE:
            score += 0.30
        elif wrc_plus >= Config.WRC_PLUS_GOOD:
            score += 0.20
        elif wrc_plus >= 100:
            score += 0.10
        else:
            score -= 0.15
        if ops >= Config.OPS_ROAD_MIN:
            score += 0.10
        else:
            score -= 0.10
        return round(min(1.0, max(0.0, score)), 2)

    # ================================================================
    # BULLPEN (componente 3, 15%)
    # ================================================================
    @staticmethod
    def score_bullpen(xfip: float, era: float, whip: float = None) -> float:
        score = 0.50
        if xfip < Config.BULLPEN_XFIP_GOOD:
            score += 0.25
        elif xfip < 4.00:
            score += 0.10
        else:
            score -= 0.10
        if era < Config.BULLPEN_ERA_GOOD:
            score += 0.15
        elif era < 4.00:
            score += 0.05
        else:
            score -= 0.10
        if whip is not None:
            if whip < 1.15:
                score += 0.10
            elif whip < 1.30:
                score += 0.05
            elif whip > 1.40:
                score -= 0.10
        return round(min(1.0, max(0.0, score)), 2)

    # ================================================================
    # FACTOR PARQUE (componente 4, 10%)
    # ================================================================
    @staticmethod
    def score_factor_parque(park_name: str) -> float:
        factor = Config.PARK_HR_FACTORS.get(park_name, 1.0)
        if factor >= 1.10:
            return 0.80
        elif factor >= 1.05:
            return 0.70
        elif factor <= 0.90:
            return 0.35
        elif factor <= 0.95:
            return 0.45
        return 0.55

    # ================================================================
    # CLIMA (componente 5, 10%)
    # ================================================================
    @staticmethod
    def score_clima(weather: Dict) -> float:
        ok, _ = ProtocolFilters.check_weather(weather)
        if not ok:
            return 0.0
        score = 0.60
        temp = weather.get("temperature", 25)
        wind = weather.get("wind_speed", 0)
        if 20 <= temp <= 28:
            score += 0.20
        elif 15 <= temp < 20 or 28 < temp <= 32:
            score += 0.10
        elif temp < 10 or temp > 35:
            score -= 0.20
        if wind < 8:
            score += 0.10
        elif wind > 15:
            score -= 0.10
        return round(min(1.0, max(0.0, score)), 2)

    # ================================================================
    # UMPIRE (componente 6, 10%)
    # ================================================================
    @staticmethod
    def score_umpire(strike_zone_accuracy: float = 0.80, bias: float = 0.0) -> float:
        score = 0.50
        if strike_zone_accuracy >= Config.UMPIRE_STRIKE_ZONE_GOOD:
            score += 0.25
        elif strike_zone_accuracy >= 0.75:
            score += 0.10
        else:
            score -= 0.15
        if bias <= Config.UMPIRE_BIAS_MAX:
            score += 0.10
        elif bias <= 0.10:
            score += 0.0
        else:
            score -= 0.10
        return round(min(1.0, max(0.0, score)), 2)

    # ================================================================
    # RUN EXPECTANCY (componente 7, 10%)
    # ================================================================
    @staticmethod
    def score_run_expectancy(run_exp_home: float, run_exp_away: float, line: float) -> float:
        total = run_exp_home + run_exp_away
        margin = abs(total - line)
        if margin >= 2.0:
            return 0.95
        elif margin >= 1.5:
            return 0.85
        elif margin >= 1.0:
            return 0.75
        elif margin >= 0.5:
            return 0.65
        return 0.45

    # ================================================================
    # SCORE COMPLETO DEL PROTOCOLO
    # ================================================================
    @staticmethod
    def calculate_full_protocol_score(duelo: float, ofensiva: float, bullpen: float,
                                       parque: float, clima: float, umpire: float,
                                       run_exp: float) -> Dict:
        metrics = {
            "duelo_abridores_score": duelo,
            "ofensiva_score": ofensiva,
            "bullpen_score": bullpen,
            "factor_parque_score": parque,
            "clima_score": clima,
            "umpire_score": umpire,
            "run_expectancy_score": run_exp,
        }
        score = MLBCalculators.calculate_protocol_score(metrics)
        return {
            "score": score,
            "metrics": metrics,
            "sweet_spot": Config.SCORE_SWEET_SPOT_MIN <= score <= Config.SCORE_SWEET_SPOT_MAX,
        }

    # ================================================================
    # FILTROS POR MERCADO
    # ================================================================

    @staticmethod
    def check_elite_pitcher(pitcher_name: str, ev: float) -> Tuple[bool, str]:
        if not pitcher_name:
            return True, ""
        for elite in Config.ELITE_PITCHERS:
            if elite.lower() in pitcher_name.lower():
                if ev < Config.ELITE_PITCHER_EXCEPTION_EV:
                    return False, f"Lanzador elite {pitcher_name}: descartado (EV {ev:.1%} < 25%)"
                else:
                    return True, f"Lanzador elite {pitcher_name}: pasa por EV > 25%"
        return True, ""

    @staticmethod
    def filter_runline_plus_1_5(odds: int, ev: float, score: float,
                                game_context: Dict, weather: Dict) -> Tuple[bool, str]:
        weather_ok, weather_reason = ProtocolFilters.check_weather(weather)
        if not weather_ok:
            return False, weather_reason

        score_ok, score_reason = ProtocolFilters.filter_by_score(score, "RL +1.5", threshold=Config.MIN_MAIN_SCORE)
        if not score_ok:
            return False, score_reason

        if ev < Config.MIN_EV_RL:
            return False, f"EV {ev:.1%} < {Config.MIN_EV_RL*100:.0f}%"
        if odds > Config.RL_ODDS_RANGE[1]:
            return False, f"Cuota {odds} > {Config.RL_ODDS_RANGE[1]} (demasiado cara, poco valor)"
        if odds < Config.MAX_RL_ODDS:
            return False, f"Cuota {odds} < {Config.MAX_RL_ODDS} (nunca pagar mas de -140)"

        # FASE 1.3: ML favorito <= -150 (priorizar, soft preference)
        ml_fav = game_context.get("ml_fav_odds", 0)
        ml_note = ""
        if ml_fav > Config.MIN_ML_FAVORITE:
            ml_note = f" | ML fav {ml_fav:+d} > {Config.MIN_ML_FAVORITE:+d} (soft)"

        # FASE 1.2: Juego cerrado (hard reject si total > 10.0, soft si > 9.0)
        total = game_context.get("total", 9)
        total_note = ""
        if total > Config.RL_TOTAL_HARD_MAX:
            return False, f"Total {total:.1f} > {Config.RL_TOTAL_HARD_MAX}, juego demasiado abierto"
        if total > Config.RL_TOTAL_SOFT_MAX:
            total_note = f" | Total {total:.1f} > {Config.RL_TOTAL_SOFT_MAX} (soft)"

        # REGLA 5: Lanzador de elite -> descartar (salvo EV > 25%)
        pitcher = game_context.get("pitcher", "")
        if pitcher:
            pit_ok, pit_reason = ProtocolFilters.check_elite_pitcher(pitcher, ev)
            if not pit_ok:
                return False, pit_reason

        # REGLA 7: Ofensiva en carretera OPS > .700 (con excepcion EV > 25%)
        ops_road = game_context.get("ops_road", 0)
        ops_note = ""
        if ops_road < Config.OPS_ROAD_MIN:
            if ev < Config.ELITE_PITCHER_EXCEPTION_EV:
                return False, f"OPS carretera {ops_road:.3f} < {Config.OPS_ROAD_MIN} (protocolo: OPS > .700)"
            ops_note = f" | OPS road {ops_road:.3f} < {Config.OPS_ROAD_MIN} (ok por EV > 25%)"

        # REGLA 6: Bullpen del underdog debe ser superior al del favorito (relativo)
        bullpen_underdog = game_context.get("bullpen_underdog_xfip", 5.0)
        bullpen_fav = game_context.get("bullpen_fav_xfip", 5.0)
        bullpen_note = ""
        if bullpen_underdog >= bullpen_fav:
            return False, f"Bullpen underdog xFIP {bullpen_underdog:.2f} no es superior al favorito {bullpen_fav:.2f}"
        if bullpen_underdog > Config.BULLPEN_XFIP_GOOD:
            bullpen_note = f" | Bullpen xFIP {bullpen_underdog:.2f} > 3.50 (soft)"

        notes = "".join([ml_note, total_note, ops_note, bullpen_note])
        return True, f"Pasa filtros RL: {score_reason}, EV {ev:.1%}{notes}"

    @staticmethod
    def filter_money_line(odds: int, fair_odds: int, ev: float, score: float) -> Tuple[bool, str]:
        score_ok, score_reason = ProtocolFilters.filter_by_score(score, "ML", threshold=Config.MIN_MAIN_SCORE)
        if not score_ok:
            return False, score_reason
        label = "Favorito" if odds < 0 else "Underdog"
        return True, f"Pasa filtros ML: {score_reason} - {label} {odds:+d}"

    @staticmethod
    def filter_totals(proj_total: float, line: float, ev: float, score: float,
                      is_over: bool, weather: Dict) -> Tuple[bool, str]:
        weather_ok, weather_reason = ProtocolFilters.check_weather(weather)
        if not weather_ok:
            return False, weather_reason

        score_ok, score_reason = ProtocolFilters.filter_by_score(score, "Totales", threshold=Config.MIN_MAIN_SCORE)
        if not score_ok:
            return False, score_reason

        margin = MLBCalculators.calculate_run_margin(proj_total, line)
        if margin < Config.MIN_RUN_MARGIN:
            return False, f"Colchon {margin:.1f} < {Config.MIN_RUN_MARGIN} (Paso 5 protocolo)"

        if not is_over:
            temp = weather.get("temperature", 25)
            if temp > Config.TEMP_MAX_UNDER:
                return False, f"Temperatura {temp}C > {Config.TEMP_MAX_UNDER}C, descartar Under"

        return True, f"Pasa filtros totales: {score_reason}"

    @staticmethod
    def filter_hr_directas(ev: float, score: float, player_xwoba: float,
                           pitcher_xwoba_against: float) -> Tuple[bool, str]:
        score_ok, score_reason = ProtocolFilters.filter_by_score(score, "HR Directas")
        if not score_ok:
            return False, score_reason
        if ev < Config.MIN_EV_RL:
            return False, f"EV {ev:.1%} < {Config.MIN_EV_RL*100:.0f}%"
        if player_xwoba < 0.340:
            return False, f"xwOBA {player_xwoba:.3f} < 0.340"
        if pitcher_xwoba_against > 0.330:
            return False, f"xwOBA contra {pitcher_xwoba_against:.3f} > 0.330"
        return True, f"Pasa filtros HR: {score_reason}"

    @staticmethod
    def filter_player_prop(k_percent: float, pitcher_k9: float, xfip: float,
                           score: float, ev: float) -> Tuple[bool, str]:
        score_ok, score_reason = ProtocolFilters.filter_by_score(score, "Player Props")
        if not score_ok:
            return False, score_reason
        if k_percent == 0 or pitcher_k9 == 0:
            return False, "Faltan datos de K% o K/9 (Paso 5 protocolo)"
        if xfip == 0:
            return False, "Falta xFIP del lanzador (Paso 5 protocolo)"
        if ev < Config.MIN_EV_PROPS:
            return False, f"EV {ev:.1%} < {Config.MIN_EV_PROPS*100:.0f}%"
        return True, f"Pasa filtros props: {score_reason}"

    @staticmethod
    def filter_player_prop_advanced(proj: Dict, market_line: float, market_odds: int,
                                     side: str, weather: Dict, score: float,
                                     h2h: Dict = None) -> Tuple[bool, str]:
        """Filtro avanzado de player props con Reglas de Oro:
        - Regla #6: datos completos (K% + xFIP + platoon split)
        - Regla #9: Sweet Spot 0.80-0.84
        - Regla #10: Viento > 20 mph penaliza
        - H2H strong signal: >.285 with 5+ AB -> edge boost
        - Contrarian: high K% vs elite K/9 -> Under hits
        """
        # Weather check (Regla de Oro #5)
        weather_ok, weather_reason = ProtocolFilters.check_weather(weather)
        if not weather_ok:
            return False, f"Clima bloquea prop: {weather_reason}"

        # Wind penalty (Regla de Oro #10)
        wind_penalty = ProtocolFilters.check_wind_penalty(weather)
        if wind_penalty < 0:
            return False, f"Viento {weather.get('wind_speed')}mph > 20: penaliza score (Regla de Oro #10)"

        # Score check
        if score < Config.MIN_SCORE:
            return False, f"Score {score:.2f} < {Config.MIN_SCORE}: RECHAZADO (Regla de Oro #2)"

        # H2H signal boost
        h2h_edge = 0.0
        if h2h:
            h2h_ab = h2h.get("ab", 0)
            h2h_avg = h2h.get("avg", 0)
            if h2h_ab >= 10:
                # Muestra significativa
                if h2h_avg >= 0.285:
                    h2h_edge = 0.03  # +3pp edge para Over hits
                elif h2h_avg <= 0.150:
                    h2h_edge = 0.03  # +3pp edge para Under hits
            elif h2h_ab >= 5:
                if h2h_avg >= 0.285:
                    h2h_edge = 0.02  # +2pp edge

        # Calculate edge
        from src.player_props import PlayerPropAnalyzer
        pa = PlayerPropAnalyzer()
        edge_result = pa.calculate_edge(proj.get("projected", 0), market_line, market_odds, side)
        effective_edge = edge_result["edge_pct"] + h2h_edge * 100

        if effective_edge < 5.0:
            return False, (f"Edge {effective_edge:.1f}pp < 5pp"
                           f"{' (+ H2H bonus)' if h2h_edge > 0 else ''}")

        return True, (f"Pasa filtros avanzados: edge={effective_edge:.1f}pp, "
                       f"score={score:.2f}, proj={proj.get('projected', '?')}, "
                       f"line={market_line}")

    # ================================================================
    # PROBABILIDAD DE VICTORIA (Paso 4 del protocolo)
    # ================================================================
    @staticmethod
    def prob_implicita(odds_decimal: float) -> float:
        return 1.0 / odds_decimal

    @staticmethod
    def check_prob_margin(prob_estimada: float, prob_implicita: float) -> Tuple[bool, float]:
        margin = prob_estimada - prob_implicita
        if margin < Config.MIN_PROB_MARGIN_ML:
            return False, margin
        return True, margin
