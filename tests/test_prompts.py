from nagato_api.models import SystemOneRequest
from nagato_api.prompts import PromptCompiler, compact_json


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        if len(text) <= 2 and text.isalpha() and text.isupper():
            return [sum(ord(char) for char in text)]
        if "assistant:" in text and text[-1:].isalpha() and text[-1:].isupper():
            return [1000 + ord(char) for char in text[:-1]] + [ord(text[-1])]
        return [1000 + ord(char) for char in text]

    def decode(self, ids):
        value = ids[0]
        if 65 <= value <= 90:
            return chr(value)
        return "?"

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and add_generation_prompt and not enable_thinking
        return "\n".join(f"{item['role']}:{item['content']}" for item in messages) + "\nassistant:"


def test_compiler_preserves_ids_and_one_token_labels():
    request = SystemOneRequest.model_validate(
        {
            "state": {"message": "hello"},
            "questions": {
                "safe": {"type": "noul", "instructions": "Is this safe?"},
                "route": {
                    "type": "choice",
                    "instructions": "Where?",
                    "criteria": {"a": "Alpha", "b": "Beta", "c": None},
                },
            },
        }
    )
    prepared = PromptCompiler(FakeTokenizer()).prepare(request)
    assert [branch.question_id for branch in prepared.branches] == ["safe", "route"]
    assert prepared.branches[0].option_keys == ["true", "false"]
    assert prepared.branches[1].option_keys == ["a", "b", "c"]
    assert prepared.branches[1].label_ids == [65, 66, 67]
    assert len(prepared.common_prefix_ids) > 0


def test_training_payload_order_is_stable():
    rendered = compact_json(
        {"evidence": "state", "criterion": "question", "options": [{"letter": "A"}]}
    )
    assert rendered.startswith(
        '{"evidence": "state", "criterion": "question", "options": [{"letter": "A"}'
    )
