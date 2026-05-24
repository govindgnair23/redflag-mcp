"""Tests for scripts/eval_verifier.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval_verifier import compute_metrics, load_labelled_data


class TestComputeMetrics:
    def test_perfect_predictions(self):
        labels = [True, True, False, False]
        preds = [True, True, False, False]
        m = compute_metrics(labels, preds)
        assert m["tp"] == 2
        assert m["fp"] == 0
        assert m["tn"] == 2
        assert m["fn"] == 0
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0
        assert m["accuracy"] == 1.0

    def test_all_true_baseline(self):
        labels = [True, True, False, False, False]
        preds = [True, True, True, True, True]
        m = compute_metrics(labels, preds)
        assert m["tp"] == 2
        assert m["fp"] == 3
        assert m["tn"] == 0
        assert m["fn"] == 0
        assert m["recall"] == 1.0
        assert m["precision"] == 0.4

    def test_all_false_predictions(self):
        labels = [True, True, False]
        preds = [False, False, False]
        m = compute_metrics(labels, preds)
        assert m["tp"] == 0
        assert m["fn"] == 2
        assert m["tn"] == 1
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0

    def test_empty_lists(self):
        m = compute_metrics([], [])
        assert m["total"] == 0
        assert m["accuracy"] == 0.0


class TestLoadLabelledData:
    def test_loads_items_with_flag_field(self):
        items = load_labelled_data()
        assert len(items) > 0
        for item in items:
            assert "flag" in item
            assert "description" in item

    def test_known_distribution(self):
        items = load_labelled_data()
        true_count = sum(1 for i in items if i["flag"])
        false_count = sum(1 for i in items if not i["flag"])
        # Based on known labelled data: ~35 true, ~53 false
        assert true_count > 0
        assert false_count > 0
        assert true_count + false_count == len(items)
