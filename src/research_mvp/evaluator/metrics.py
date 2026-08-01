from __future__ import annotations

import math

from sklearn.metrics import auc, precision_recall_curve, roc_curve


def _undefined() -> dict[str, str]:
    return {"reason": "single_class", "status": "METRIC_UNDEFINED"}


def evaluate_binary_metrics(labels: tuple[int, ...], scores: tuple[float, ...]) -> dict[str, dict[str, float | str]]:
    if len(labels) != len(scores) or not labels:
        raise ValueError("metric inputs must have equal non-zero length")
    if any(label not in {0, 1} for label in labels):
        raise ValueError("binary targets must be 0 or 1")
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("metric scores must be finite")
    positives = tuple(score for label, score in zip(labels, scores, strict=True) if label == 1)
    negatives = tuple(score for label, score in zip(labels, scores, strict=True) if label == 0)
    if not positives or not negatives:
        undefined = _undefined()
        return {"pr_auc": dict(undefined), "roc_auc": dict(undefined)}

    false_positive_rate, true_positive_rate, _roc_thresholds = roc_curve(labels, scores)
    precision, recall, _pr_thresholds = precision_recall_curve(labels, scores)
    roc_auc = float(auc(false_positive_rate, true_positive_rate))
    pr_auc = float(auc(recall, precision))
    if not math.isfinite(roc_auc) or not math.isfinite(pr_auc):
        raise ValueError("defined metrics must be finite")
    return {
        "pr_auc": {"status": "DEFINED", "value": pr_auc},
        "roc_auc": {"status": "DEFINED", "value": roc_auc},
    }
