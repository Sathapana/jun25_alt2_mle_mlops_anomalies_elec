"""Seuillage dynamique non paramétrique et élagage des séquences (Hundman et al., KDD 2018)."""

from __future__ import annotations

import numpy as np
import pandas as pd


class DynamicThresholdDetector:
    """Implémente l'évaluation non paramétrique des résidus (NASA Telemanom) :
    1. Lissage EWMA des erreurs absolues |residual|.
    2. Recherche du seuil optimal epsilon* = mu + z* * sigma maximisant le gain de variance.
    3. Élagage (pruning) des séquences candidates selon une baisse minimale relative `p`.
    """

    def __init__(
        self,
        ewma_span: int = 4,
        z_min: float = 2.0,
        z_max: float = 10.0,
        z_steps: int = 33,
        pruning_p: float = 0.13,
    ) -> None:
        self.ewma_span = ewma_span
        self.z_min = z_min
        self.z_max = z_max
        self.z_steps = z_steps
        self.pruning_p = pruning_p

    def compute_ewma_errors(self, residuals: pd.Series) -> pd.Series:
        """Lisse la valeur absolue des résidus par moyenne mobile exponentielle."""
        abs_err = residuals.abs().fillna(0.0)
        return abs_err.ewm(span=self.ewma_span, adjust=False).mean()

    def find_optimal_threshold(self, ewma_errors: np.ndarray) -> float:
        """Trouve le seuil non paramétrique epsilon* = mu + z* * sigma (Hundman et al., 2018)."""
        if len(ewma_errors) == 0:
            return 0.0

        mu = float(np.mean(ewma_errors))
        sigma = float(np.std(ewma_errors))
        if sigma <= 1e-12:
            return mu + 1e-6

        best_score = -1.0
        best_eps = mu + self.z_min * sigma

        for z in np.linspace(self.z_min, self.z_max, self.z_steps):
            eps = mu + float(z) * sigma
            above = ewma_errors > eps
            n_anom = int(np.sum(above))
            if n_anom == 0 or n_anom == len(ewma_errors):
                continue

            normal_vals = ewma_errors[~above]
            delta_mu = (mu - float(np.mean(normal_vals))) / (mu if mu > 0 else 1.0)
            delta_sigma = (sigma - float(np.std(normal_vals))) / sigma

            # Nombre de séquences contiguës au-dessus de eps
            padded = np.concatenate(([False], above, [False]))
            n_seqs = int(np.sum(padded[1:] & ~padded[:-1]))

            denom = n_anom + (n_seqs**2)
            score = (delta_mu + delta_sigma) / max(denom, 1)
            if score > best_score:
                best_score = score
                best_eps = eps

        return best_eps

    def _prune_sequences(
        self,
        ewma_errors: np.ndarray,
        eps: float,
    ) -> np.ndarray:
        """Élagage des séquences d'anomalies : ne conserve que les pics décroissant d'au moins `p`."""
        above = ewma_errors > eps
        if not np.any(above):
            return above

        # Identification des séquences contiguës (start, end, max_val)
        sequences: list[tuple[int, int, float]] = []
        in_seq = False
        start_idx = 0
        for i, flag in enumerate(above):
            if flag and not in_seq:
                in_seq = True
                start_idx = i
            elif not flag and in_seq:
                in_seq = False
                sequences.append((start_idx, i, float(np.max(ewma_errors[start_idx:i]))))
        if in_seq:
            sequences.append((start_idx, len(ewma_errors), float(np.max(ewma_errors[start_idx:]))))

        normal_vals = ewma_errors[~above]
        max_non_anom = float(np.max(normal_vals)) if len(normal_vals) > 0 else eps

        # Tri décroissant par pic maximal
        sorted_seqs = sorted(sequences, key=lambda x: x[2], reverse=True)
        e_max = [seq[2] for seq in sorted_seqs] + [max_non_anom]

        keep_count = 0
        for i in range(len(sorted_seqs)):
            prev_val = e_max[i]
            next_val = e_max[i + 1]
            pct_decrease = (prev_val - next_val) / prev_val if prev_val > 0 else 0.0
            if pct_decrease >= self.pruning_p:
                keep_count = i + 1

        pruned_mask = np.zeros_like(above, dtype=bool)
        for start_i, end_i, _ in sorted_seqs[:keep_count]:
            pruned_mask[start_i:end_i] = True

        return pruned_mask

    def detect(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applique le seuillage dynamique par `unique_id` et produit les colonnes du contrat P2."""
        if "residual" not in df.columns:
            raise ValueError("La colonne `residual` est requise avant le seuillage dynamique.")

        results: list[pd.DataFrame] = []
        for uid, group in df.groupby("unique_id", group_keys=False):
            g = group.sort_values("ds").copy()
            ewma = self.compute_ewma_errors(g["residual"])
            ewma_arr = ewma.to_numpy(dtype=float)

            eps = self.find_optimal_threshold(ewma_arr)
            is_anom = self._prune_sequences(ewma_arr, eps)

            # Si le contrôle qualité P1 a signalé une erreur de capteur, ne pas classer en anomalie réseau
            if "quality_flag" in g.columns:
                valid_quality = (g["quality_flag"] == "OK").to_numpy()
                is_anom = is_anom & valid_quality

            g["ewma_error"] = ewma_arr
            g["threshold_eps"] = eps
            g["anomaly_score"] = np.where(eps > 0, ewma_arr / eps, 0.0)
            g["is_anomaly"] = is_anom
            g["alert_id"] = [f"{uid}_{ts.strftime('%Y%m%dT%H%M%SZ')}" for ts in pd.to_datetime(g["ds"], utc=True)]
            if "qualification" not in g.columns:
                g["qualification"] = None
            results.append(g)

        return pd.concat(results, ignore_index=True)
