"""Classification and taxonomy-aware evaluation helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Mapping

from cosqli.utils.cluster import get_single_key_of_injection_sql


POSITIVE_LABEL = "malicious"
NEGATIVE_LABEL = "benign"
VALID_LABELS = frozenset({POSITIVE_LABEL, NEGATIVE_LABEL})


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def compute_classification_metrics(results: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compute exhaustive binary security-classification metrics.

    An output outside the supported label set counts as an error. Invalid
    malicious predictions become false negatives and invalid benign predictions
    become false positives, preserving agreement with strict exact-match
    accuracy while keeping the confusion matrix exhaustive.
    """
    true_positive = true_negative = false_positive = false_negative = 0
    invalid_predictions = 0
    supports = defaultdict(int)

    for item in results:
        truth = str(item.get("ground_truth", "")).strip().lower()
        prediction = str(item.get("predicted_answer", "")).strip().lower()
        if truth not in VALID_LABELS:
            raise ValueError(f"Unsupported ground-truth label: {truth!r}")
        supports[truth] += 1
        if prediction not in VALID_LABELS:
            invalid_predictions += 1
            if truth == POSITIVE_LABEL:
                false_negative += 1
            else:
                false_positive += 1
            continue

        actual_positive = truth == POSITIVE_LABEL
        predicted_positive = prediction == POSITIVE_LABEL
        if actual_positive and predicted_positive:
            true_positive += 1
        elif actual_positive:
            false_negative += 1
        elif predicted_positive:
            false_positive += 1
        else:
            true_negative += 1

    total = true_positive + true_negative + false_positive + false_negative
    accuracy = _safe_divide(true_positive + true_negative, total)
    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    specificity = _safe_divide(true_negative, true_negative + false_positive)
    f1 = _safe_divide(2 * precision * recall, precision + recall)
    false_positive_rate = _safe_divide(false_positive, false_positive + true_negative)
    false_negative_rate = _safe_divide(false_negative, false_negative + true_positive)
    balanced_accuracy = (recall + specificity) / 2
    mcc_denominator = (
        (true_positive + false_positive)
        * (true_positive + false_negative)
        * (true_negative + false_positive)
        * (true_negative + false_negative)
    ) ** 0.5

    return {
        "schema_version": 1,
        "total": total,
        "correct": true_positive + true_negative,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": specificity,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
        "balanced_accuracy": balanced_accuracy,
        "matthews_correlation": _safe_divide(
            true_positive * true_negative - false_positive * false_negative,
            mcc_denominator,
        ),
        "prediction_validity_rate": _safe_divide(total - invalid_predictions, total),
        "invalid_prediction_count": invalid_predictions,
        "class_support": {
            POSITIVE_LABEL: supports[POSITIVE_LABEL],
            NEGATIVE_LABEL: supports[NEGATIVE_LABEL],
        },
        "confusion_matrix": {
            "true_positive": true_positive,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
        },
    }


def compute_cluster_metrics(results: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Compute classification metrics for every canonical taxonomy cluster."""
    grouped: Dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[get_single_key_of_injection_sql(dict(item))].append(item)
    return {
        cluster: compute_classification_metrics(items)
        for cluster, items in sorted(grouped.items())
    }
