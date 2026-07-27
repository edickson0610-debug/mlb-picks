import math
from typing import Dict, List, Tuple
from src.config import Config


class MLBCalculators:

    PA_WEIGHTS = [4.75, 4.65, 4.55, 4.45, 4.35, 4.25, 4.15, 4.05, 3.85]

    @staticmethod
    def calculate_xwoba_ponderado(lineup: List[str], xwoba_dict: Dict[str, float]) -> float:
        if not lineup:
            return 0.315
        total_pas = 0
        weighted_sum = 0
        for i, player in enumerate(lineup[:9]):
            pa = MLBCalculators.PA_WEIGHTS[i]
            xwoba = xwoba_dict.get(player, 0.315)
            weighted_sum += pa * xwoba
            total_pas += pa
        return weighted_sum / total_pas if total_pas > 0 else 0.315

    @staticmethod
    def calculate_off_factor(xwoba: float, park_factor: float = 1.0) -> float:
        return ((xwoba * park_factor) / 0.315) ** 1.25

    @staticmethod
    def calculate_pit_factor(xwoba_against: float) -> float:
        return xwoba_against / 0.315

    @staticmethod
    def calculate_rs9(off_factor: float, pit_factor: float, park_runs: float = 100) -> float:
        return 4.40 * off_factor * pit_factor * (park_runs / 100)

    @staticmethod
    def calculate_ev(odds_decimal: float, fair_prob: float) -> float:
        return (odds_decimal * fair_prob) - 1

    @staticmethod
    def calculate_pythagenpat(rs: float, ra: float) -> float:
        if rs + ra == 0:
            return 0.500
        exponent = 1.83
        return (rs ** exponent) / (rs ** exponent + ra ** exponent)

    @staticmethod
    def odds_to_decimal(odds: int) -> float:
        if odds > 0:
            return 1 + (odds / 100)
        else:
            return 1 + (100 / abs(odds))

    @staticmethod
    def decimal_to_odds(decimal: float) -> int:
        if decimal >= 2.0:
            return int((decimal - 1) * 100)
        else:
            return int(-100 / (decimal - 1))

    @staticmethod
    def implied_probability(odds_decimal: float) -> float:
        return 1 / odds_decimal

    @staticmethod
    def calculate_run_margin(proj_total: float, line: float) -> float:
        return abs(line - proj_total)

    @staticmethod
    def calculate_score(ev: float, consistencia: float = 0.5, ventaja_climatica: float = 0.5) -> float:
        w = Config.SCORE_WEIGHTS
        score = min(1.0, (ev * w.get("ev", 5.0)) + (consistencia * w.get("consistencia", 0.1)) + (ventaja_climatica * w.get("clima", 0.0)))
        return round(max(0.0, score), 2)

    @staticmethod
    def calculate_protocol_score(metrics: Dict) -> float:
        """
        Score del Protocolo V2.6 con 7 componentes.
        Cada componente debe ser un valor 0.0 - 1.0.
        metrics dict keys:
          - duelo_abridores_score: basado en xFIP, SIERA, K/9, BB/9, HR/9
          - ofensiva_score: basado en wRC+, AVG, OBP, SLG (30d)
          - bullpen_score: basado en ERA, WHIP, K/9 (15d)
          - factor_parque_score: basado en HR, runs, hits del estadio
          - clima_score: basado en lluvia, viento, temperatura, AQI
          - umpire_score: basado en zona de strikes, tendencias
          - run_expectancy_score: basado en proyeccion de carreras
        """
        w = Config.SCORE_WEIGHTS
        score = (
            metrics.get("duelo_abridores_score", 0.5) * w["duelo_abridores"] +
            metrics.get("ofensiva_score", 0.5) * w["ofensiva"] +
            metrics.get("bullpen_score", 0.5) * w["bullpen"] +
            metrics.get("factor_parque_score", 0.5) * w["factor_parque"] +
            metrics.get("clima_score", 0.5) * w["clima"] +
            metrics.get("umpire_score", 0.5) * w["umpire"] +
            metrics.get("run_expectancy_score", 0.5) * w["run_expectancy"]
        )
        return round(min(1.0, max(0.0, score)), 2)

    @staticmethod
    def calculate_run_expectancy(xfip_abridor: float, bullpen_era: float,
                                  wrc_plus: float, park_factor: float = 1.0) -> float:
        # Formula Protocolo V2.6 Paso 4
        return ((xfip_abridor * Config.RE_ABRIDOR_WEIGHT) +
                (bullpen_era * Config.RE_BULLPEN_WEIGHT) +
                ((wrc_plus / 100) * Config.RE_OFENSIVA_WEIGHT)) * park_factor

    @staticmethod
    def calculate_run_expectancy_protocol(xfip_abridor: float, bullpen_era: float,
                                          wrc_plus: float, park_factor: float = 1.0) -> Dict:
        """Run Expectancy completo con desglose (Protocolo Paso 4)"""
        raw = ((xfip_abridor * Config.RE_ABRIDOR_WEIGHT) +
               (bullpen_era * Config.RE_BULLPEN_WEIGHT) +
               ((wrc_plus / 100) * Config.RE_OFENSIVA_WEIGHT))
        adjusted = raw * park_factor
        return {
            "raw": round(raw, 2),
            "adjusted": round(adjusted, 2),
            "components": {
                "abridor": round(xfip_abridor * Config.RE_ABRIDOR_WEIGHT, 2),
                "bullpen": round(bullpen_era * Config.RE_BULLPEN_WEIGHT, 2),
                "ofensiva": round((wrc_plus / 100) * Config.RE_OFENSIVA_WEIGHT, 2),
                "park_factor": park_factor,
            }
        }

    @staticmethod
    def calculate_consistency(past_performance: List[bool]) -> float:
        if not past_performance:
            return 0.5
        recent = past_performance[-5:]
        wins = sum(recent)
        return wins / len(recent)

    @staticmethod
    def poisson_prob(k: int, lam: float) -> float:
        """Probabilidad Poisson P(X = k) con media lam"""
        return (math.exp(-lam) * (lam ** k)) / math.factorial(k)

    @staticmethod
    def calculate_rl_probability(rs9_underdog: float, rs9_favorite: float) -> float:
        """
        Probabilidad de que el underdog cubra +1.5 usando Poisson.
        P(cubre) = sum Poisson(k; RS9_ud) * sum Poisson(j; RS9_fav)
        para todos k,j donde k - j <= 1.5
        """
        prob = 0.0
        for k in range(15):
            pk = MLBCalculators.poisson_prob(k, rs9_underdog)
            cum_j = 0.0
            for j in range(min(k + 2, 15)):
                cum_j += MLBCalculators.poisson_prob(j, rs9_favorite)
            prob += pk * cum_j
        return prob