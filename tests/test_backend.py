import math

import pytest

from systemone_api.backend import parse_generation


def test_selected_logprobs_are_reordered_to_requested_ids():
    generation = parse_generation(
        {
            "meta_info": {
                "completion_tokens": 1,
                "prompt_tokens": 12,
                "cached_tokens": 7,
                "output_token_ids_logprobs": [[[math.log(0.2), 20], [math.log(0.8), 10]]],
            }
        },
        [10, 20],
    )
    assert generation.logprobs == pytest.approx([math.log(0.8), math.log(0.2)])
    assert generation.input_tokens == 12
    assert generation.cached_tokens == 7


def test_rejects_missing_selected_label():
    with pytest.raises(KeyError):
        parse_generation(
            {
                "meta_info": {
                    "completion_tokens": 1,
                    "prompt_tokens": 1,
                    "output_token_ids_logprobs": [[[0.0, 10]]],
                }
            },
            [10, 20],
        )
