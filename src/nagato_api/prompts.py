import itertools
import json
import string
from dataclasses import dataclass
from typing import Any

from .models import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion, SystemOneRequest

SYSTEM_PROMPT = (
    "Apply the supplied criterion to the supplied evidence. Choose exactly one listed option. "
    "Respond with only its uppercase letter, with no explanation or reasoning."
)


def compact_json(value: Any) -> str:
    # Preserve insertion order: Nagato was trained on evidence, criterion, options.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def option_pairs(question: Question) -> list[tuple[str, str]]:
    if isinstance(question, NoulQuestion):
        return [("true", question.criteria.positive), ("false", question.criteria.negative)]
    if isinstance(question, ChoiceQuestion):
        return [
            (key, key if description is None else description)
            for key, description in question.criteria.items()
        ]
    assert isinstance(question, ScoreQuestion)
    return [(str(index), description) for index, description in enumerate(question.criteria)]


@dataclass(frozen=True)
class Branch:
    question_id: str
    question: Question
    input_ids: list[int]
    label_ids: list[int]
    option_keys: list[str]


@dataclass(frozen=True)
class Prepared:
    common_prefix_ids: list[int]
    branches: list[Branch]


class PromptCompiler:
    def __init__(self, tokenizer: Any, max_answers: int = 16):
        self.tokenizer = tokenizer
        self.labels = self._single_token_labels(max_answers)

    def _single_token_labels(self, count: int) -> list[tuple[str, int]]:
        candidates = itertools.chain(
            string.ascii_uppercase,
            ("".join(pair) for pair in itertools.product(string.ascii_uppercase, repeat=2)),
        )
        labels: list[tuple[str, int]] = []
        seen: set[int] = set()
        for text in candidates:
            ids = self.tokenizer.encode(text, add_special_tokens=False)
            if len(ids) == 1 and ids[0] not in seen and self.tokenizer.decode(ids) == text:
                labels.append((text, ids[0]))
                seen.add(ids[0])
            if len(labels) == count:
                return labels
        raise ValueError(f"tokenizer does not expose {count} distinct one-token labels")

    def prepare(self, request: SystemOneRequest) -> Prepared:
        branches: list[Branch] = []
        for question_id, question in request.questions.items():
            options = option_pairs(question)
            labels = self.labels[: len(options)]
            payload = {
                "evidence": request.state,
                "criterion": question.instructions,
                "options": [
                    {"letter": label, "description": description}
                    for (_, description), (label, _) in zip(options, labels, strict=True)
                ],
            }
            rendered = self.tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": compact_json(payload)},
                ],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            input_ids = self.tokenizer.encode(rendered, add_special_tokens=False)
            for label, token_id in labels:
                if self.tokenizer.encode(rendered + label, add_special_tokens=False) != [
                    *input_ids,
                    token_id,
                ]:
                    raise ValueError(f"answer boundary changes tokenization for slot {label}")
            branches.append(
                Branch(
                    question_id=question_id,
                    question=question,
                    input_ids=input_ids,
                    label_ids=[token_id for _, token_id in labels],
                    option_keys=[key for key, _ in options],
                )
            )
        common = list(branches[0].input_ids)
        for branch in branches[1:]:
            length = next(
                (
                    index
                    for index, pair in enumerate(zip(common, branch.input_ids, strict=False))
                    if pair[0] != pair[1]
                ),
                min(len(common), len(branch.input_ids)),
            )
            common = common[:length]
        return Prepared(common_prefix_ids=common, branches=branches)
