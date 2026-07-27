# PROTOCOLO V2.6 - SCORE SYSTEM 7 COMPONENTES
# Integracion completa: MLB Stats API + Protocol Data Fetcher
# Score >= 0.80 = MUY ALTA CONFIANZA (Sweet Spot 0.80-0.84 = 81.8% WR historico)

## ARQUITECTURA DE DATOS

### Fuentes de Datos
| Componente | API | Datos Obtenidos |
|---|---|---|
| **Duelo abridores** | MLB Stats API (`/people/{id}/stats`) | K/9, BB/9, HR/9, ERA, WHIP, xFIP estimado |
| **Ofensiva** | MLB Stats API (`/teams/{id}/stats?group=hitting`) | OPS, SLG, AVG, OBP, HR, Runs |
| **Bullpen** | MLB Stats API (roster + filtro relevistas) | ERA, WHIP, K/9 (promedio ponderado por IP) |
| **Factor parque** | Config.PARK_HR_FACTORS (static) | Factor HR del estadio |
| **Clima** | OpenWeatherMap API + fallback simulado | Temperatura, viento, precipitacion, AQI |
| **Umpire** | Default (0.80 accuracy, 0.02 bias) | Valor fijo hasta integrar Umpire Scorecards |
| **Run expectancy** | Calculado de xFIP + Bullpen ERA + wRC+ estimado | Proyeccion de carreras |

### Pipeline (src/data_fetcher.py -> ProtocolDataFetcher)
1. `get_daily_games()` -> Schedule con hydrate=probablePitcher,weather
2. `get_pitcher_stats(id)` -> K/9, BB/9, HR/9, ERA, WHIP, xFIP estimado
3. `get_team_hitting_stats(id)` -> OPS, SLG, AVG del equipo
4. `get_bullpen_stats(id)` -> ERA, WHIP de relevistas (filtrados por rol)
5. `get_weather(venue)` -> OpenWeatherMap + fallback estacional
6. `get_full_game_context(game_id)` -> TODO lo anterior en una llamada

### Score System (7 componentes, suma pesos = 1.00)
| Componente | Peso | Funcion | Datos usados |
|---|---|---|---|
| Duelo abridores | 25% | `score_duelo_abridores()` | K/9, BB/9, HR/9, xFIP_est |
| Ofensiva | 20% | `score_ofensiva()` | wRC+ estimado desde OPS, OPS |
| Bullpen | 15% | `score_bullpen()` | ERA, WHIP (promedio relevistas) |
| Factor parque | 10% | `score_factor_parque()` | Nombre del estadio |
| Clima | 10% | `score_clima()` | Temperatura, viento, precipitacion |
| Umpire | 10% | `score_umpire()` | Accuracy, bias (default) |
| Run expectancy | 10% | `score_run_expectancy()` | Proyeccion vs linea |

## REGLAS DE ORO (INQUEBRANTABLES)

| # | Regla | Donde se aplica |
|---|-------|-----------------|
| 1 | Calendario MLB SIEMPRE primero | `get_daily_games()` |
| 2 | **Score >= 0.80 para aprobar** | `filter_by_score()` - NUNCA bajar de 0.80 |
| 3 | Underdogs solo con score >= 0.80 | `filter_money_line()` |
| 4 | No forzar entradas sin lineups | `check_lineups()` - esperar confirmacion |
| 5 | Clima extremo = ANULACION | `check_weather()` - lluvia >50%, AQI >200, flood |
| 6 | Player Props requieren datos completos | `filter_player_prop_advanced()` - K% + xFIP + H2H + clima |
| 7 | Totales requieren Run Expectancy | `filter_totals()` - colchon >= 0.5 runs |
| 8 | Cambio de lanzador = REVISION | `check_pitcher_change()` - reevaluar desde cero |
| 9 | Sweet Spot 0.80-0.84 es OPTIMO | Validado: 81.8% WR vs 50.0% para >= 0.85 |
| 10 | Viento > 20 mph penaliza score -0.05 | `check_wind_penalty()` |
| 11 | H2H > .285 con 5+ AB = edge +3pp | `filter_player_prop_advanced()` + `player_props.py` |
| 12 | Batter K% vs pitcher K/9 -> K props | `project_batter_strikeouts()` + `signal.py` |
| 13 | Player props sin lineups usan roster fallback | `_get_batter_ids_from_roster()` |
| 14 | Contrarian: high K% vs elite K/9 -> Under hits | `filter_player_prop_advanced()` calcula edge inverso |

## SCORE CALIBRACION
- **0.80-0.84 (Sweet Spot)**: 81.8% WR -> APROBAR
- **0.85+**: ~50.0% WR -> REVISAR (mucho ruido, underdogs largos)
- **0.70-0.79**: ~60.0% WR -> RECHAZAR (datos insuficientes)
- **< 0.70**: RECHAZAR automaticamente

## COMANDOS PRINCIPALES

### Dashboard en vivo (recomendado)
```
python run_dashboard.py
```
Corre analisis HOY, genera `dashboard_live.html` con datos embebidos, abre el navegador automaticamente.
Incluye: score system, player props, edges vs mercado en vivo, picks tracker, parley builder.

### Analisis CLI
```
python src/main.py
```
(Obtiene juegos de HOY, verifica pitchers, analiza cada juego, guarda JSON)

### Backtest (requiere datos historicos)
```
python backtest_protocol_v26.py
```

## Archivos Clave
| Archivo | Proposito |
|---|---|
| `src/data_fetcher.py` | ProtocolDataFetcher - API MLB + Weather |
| `src/filters.py` | ProtocolFilters - score system + reglas de oro |
| `src/calculators.py` | MLBCalculators - formulas + protocol score |
| `src/config.py` | Config - thresholds, pesos, constantes |
| `src/main.py` | BaseballAnalyzer - orquestacion completa |
| `src/player_props.py` | PlayerPropAnalyzer - H2H, proyecciones, edge detection |
| `backtest_protocol_v26.py` | Backtest del protocolo |

## Player Props System (PlayerPropAnalyzer)

### Fuentes de datos
| Fuente | API | Datos |
|---|---|---|
| Batter vs Pitcher H2H | MLB `/people/{id}/stats?stats=vsPlayer&opposingPlayerId={pid}` | AVG, AB, H, HR, K, BB, OPS desde enfrentamientos reales |
| Batter season | MLB `/people/{id}/stats?group=hitting` | AVG, OPS, HR, K%, BB% |
| Pitcher season | MLB `/people/{id}/stats?group=pitching` | K/9, BB/9, HR/9, xFIP |
| Roster fallback | MLB `/teams/{id}/roster` | Bateadores sin incluir pitchers |
| Weather | OpenWeatherMap + fallback | Temp, wind, precipitation |

### Mercados disponibles
| Prop | Funcion | Proyeccion base |
|---|---|---|
| Pitcher Strikeouts | `project_pitcher_strikeouts()` | K/9 * 5.5 IP, ajustado por K% de la alineacion |
| Batter Hits Over/Under | `project_batter_hits()` | Season AVG * 4 AB, blend con H2H AVG, ajuste clima |
| Batter Strikeouts | `project_batter_strikeouts()` | Batter K% * 4 AB, blend con H2H K, ajuste pitcher |
| Batter Home Runs | `project_batter_home_run()` | HR/AB rate * 4 AB, ajuste park factor + clima |

### Estrategias implementadas
1. **H2H History**: batter hits >= .285 with 5+ AB vs pitcher -> Over hits edge
2. **Contrarian**: batter K% > 30% vs pitcher high K/9 -> Over K's
3. **Platoon**: (pendiente Statcast datos) -> ajuste por handedness
4. **Weather boost**: temp 20-30C, wind < 12mph -> +5% hitting, mal clima -> -10%
5. **Park factor**: HR ajustado por estadio (x0.87 Petco, x1.25 Coors)

### Edge calculation vs The Odds API
```python
edge = calculate_edge(projection, market_line, market_odds, side)
# Retorna: {edge_pct, ev_pct, our_prob, implied_prob, recommendation}
# recommendation: STRONG_BET (>8pp), BET (>5pp), NO_BET (>2pp), PASS
```

### Nearest The Odds API endpoints
```
GET /v4/sports/baseball_mlb/events/{eventId}/odds?markets=player_strikeouts,batter_hits,batter_home_runs
```
Requiere API key de the-odds-api.com (free tier: 500 req/mes)

## Cache
- `api_cache/` - Cache de 6h para llamadas MLB API
- Cache en memoria: pitchers, bateadores, rosters, team stats
- Limpiar con: `Remove-Item -Recurse api_cache/`
