import math

import pytest

from nagato_api.scoring import choice_answer, confidence, noul_answer, score_answer


def test_noul_is_probability_of_true():
    answer = noul_answer([math.log(0.8), math.log(0.2)], 1.0)
    assert answer.noul == pytest.approx(0.8)


def test_choice_returns_full_distribution_and_argmax():
    answer = choice_answer(["a", "b", "c"], [0.0, 2.0, 1.0], 1.0)
    assert answer.choice == "b"
    assert sum(answer.probabilities.values()) == pytest.approx(1.0)
    assert 0 <= answer.confidence <= 1


def test_score_is_expected_zero_based_level():
    answer = score_answer(["low", "medium", "high"], [-100.0, -100.0, 0.0], 1.0)
    assert answer.score == pytest.approx(2.0)
    assert answer.legend == {"0": "low", "1": "medium", "2": "high"}


def test_uniform_distribution_has_zero_confidence():
    assert confidence([0.25, 0.25, 0.25, 0.25]) == pytest.approx(0.0)
