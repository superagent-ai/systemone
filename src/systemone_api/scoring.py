import math

from .models import ChoiceAnswer, NoulAnswer, ScoreAnswer


def normalize(logprobs: list[float], temperature: float) -> list[float]:
    if len(logprobs) < 2 or any(math.isnan(value) or value == math.inf for value in logprobs):
        raise ValueError("invalid label log probabilities")
    peak = max(logprobs)
    if peak == -math.inf:
        raise ValueError("all label probabilities are zero")
    weights = [math.exp((value - peak) / temperature) for value in logprobs]
    total = math.fsum(weights)
    return [weight / total for weight in weights]


def confidence(probabilities: list[float]) -> float:
    entropy = -math.fsum(p * math.log(p) for p in probabilities if p > 0)
    return min(1.0, max(0.0, 1.0 - entropy / math.log(len(probabilities))))


def noul_answer(logprobs: list[float], temperature: float) -> NoulAnswer:
    probabilities = normalize(logprobs, temperature)
    return NoulAnswer(noul=probabilities[0])


def choice_answer(keys: list[str], logprobs: list[float], temperature: float) -> ChoiceAnswer:
    probabilities = normalize(logprobs, temperature)
    distribution = dict(zip(keys, probabilities, strict=True))
    return ChoiceAnswer(
        choice=max(distribution, key=distribution.__getitem__),
        probabilities=distribution,
        confidence=confidence(probabilities),
    )


def score_answer(criteria: list[str], logprobs: list[float], temperature: float) -> ScoreAnswer:
    probabilities = normalize(logprobs, temperature)
    keys = [str(index) for index in range(len(criteria))]
    return ScoreAnswer(
        score=math.fsum(index * probability for index, probability in enumerate(probabilities)),
        legend=dict(zip(keys, criteria, strict=True)),
        probabilities=dict(zip(keys, probabilities, strict=True)),
        confidence=confidence(probabilities),
    )
