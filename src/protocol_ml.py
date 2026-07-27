"""
ProtocolML - ML layer on top of the Protocol V2.6 score system.
Uses the 7 component scores + derived metrics as features for GradientBoosting.
Predicts: home_win, runline_plus_1_5_cover, total_over
"""
import json
import os
import pickle
import numpy as np
from collections import defaultdict
from datetime import datetime

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
from sklearn.preprocessing import StandardScaler

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ml_models")
os.makedirs(MODEL_PATH, exist_ok=True)


class ProtocolML:
    def __init__(self):
        self.models = {}
        self.scalers = {}
        self._load_models()

    def _model_path(self, target):
        return os.path.join(MODEL_PATH, f"protocol_ml_{target}.pkl")

    def _scaler_path(self, target):
        return os.path.join(MODEL_PATH, f"protocol_scaler_{target}.pkl")

    def _load_models(self):
        for target in ["home_win", "rl_cover", "total_over"]:
            mp = self._model_path(target)
            sp = self._scaler_path(target)
            if os.path.exists(mp) and os.path.exists(sp):
                try:
                    with open(mp, "rb") as f:
                        self.models[target] = pickle.load(f)
                    with open(sp, "rb") as f:
                        self.scalers[target] = pickle.load(f)
                except Exception:
                    pass

    def _extract_features(self, metrics: dict) -> np.ndarray:
        c = metrics
        return np.array([
            c.get("duelo_abridores_score", 0.5),
            c.get("ofensiva_score", 0.5),
            c.get("bullpen_score", 0.5),
            c.get("factor_parque_score", 0.5),
            c.get("clima_score", 0.5),
            c.get("umpire_score", 0.5),
            c.get("run_expectancy_score", 0.5),
            c.get("duelo_abridores_score", 0.5) - c.get("ofensiva_score", 0.5),
            c.get("bullpen_score", 0.5) - c.get("ofensiva_score", 0.5),
        ])

    def predict(self, metrics: dict) -> dict:
        features = self._extract_features(metrics).reshape(1, -1)
        result = {}
        for target in ["home_win", "rl_cover", "total_over"]:
            if target in self.models and target in self.scalers:
                X = self.scalers[target].transform(features)
                prob = self.models[target].predict_proba(X)[0, 1]
                result[target] = round(float(prob), 3)
            else:
                result[target] = None
        return result

    def train(self, samples: list):
        targets = {
            "home_win": np.array([s["home_won"] for s in samples]),
            "rl_cover": np.array([s["rl_covered"] for s in samples]),
            "total_over": np.array([s["total_over"] for s in samples]),
        }
        X_raw = np.array([self._extract_features(s["metrics"]) for s in samples])

        results = {}
        for target_name in targets:
            y = targets[target_name]
            pos_rate = y.mean()
            if pos_rate < 0.05 or pos_rate > 0.95:
                print(f"  [SKIP] {target_name}: clase desbalanceada ({pos_rate:.1%})")
                continue

            tscv = TimeSeriesSplit(n_splits=5)
            accs, losses, briers = [], [], []
            best_clf = None
            best_scaler = None
            best_loss = float("inf")

            for train_idx, test_idx in tscv.split(X_raw):
                X_train, X_test = X_raw[train_idx], X_raw[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]

                scaler = StandardScaler()
                X_train_s = scaler.fit_transform(X_train)
                X_test_s = scaler.transform(X_test)

                clf = GradientBoostingClassifier(
                    n_estimators=200, max_depth=3, learning_rate=0.08,
                    min_samples_leaf=20, subsample=0.8, random_state=42,
                )
                clf.fit(X_train_s, y_train)
                y_pred = clf.predict(X_test_s)
                y_prob = clf.predict_proba(X_test_s)[:, 1]

                acc = accuracy_score(y_test, y_pred)
                loss = log_loss(y_test, y_prob)
                brier = brier_score_loss(y_test, y_prob)
                accs.append(acc)
                losses.append(loss)
                briers.append(brier)

                if loss < best_loss:
                    best_loss = loss
                    best_clf = clf
                    best_scaler = scaler

            y_all_prob = best_clf.predict_proba(best_scaler.transform(X_raw))[:, 1]

            results[target_name] = {
                "accuracy": float(np.mean(accs)),
                "log_loss": float(np.mean(losses)),
                "brier": float(np.mean(briers)),
                "calibration": self._calibration_bins(y, y_all_prob),
            }

            self.models[target_name] = best_clf
            self.scalers[target_name] = best_scaler
            with open(self._model_path(target_name), "wb") as f:
                pickle.dump(best_clf, f)
            with open(self._scaler_path(target_name), "wb") as f:
                pickle.dump(best_scaler, f)
            print(f"  [OK] {target_name}: CV acc={np.mean(accs):.3f}, loss={np.mean(losses):.3f}, brier={np.mean(briers):.3f}")

        return results

    def _calibration_bins(self, y_true, y_prob, bins=5):
        result = {}
        for i in range(bins):
            lo, hi = i / bins, (i + 1) / bins
            mask = (y_prob >= lo) & (y_prob < hi)
            n = int(mask.sum())
            if n > 0:
                pred = float(y_prob[mask].mean())
                actual = float(y_true[mask].mean())
                result[f"{lo:.1f}-{hi:.1f}"] = {"n": n, "pred": round(pred, 3), "actual": round(actual, 3)}
        return result
