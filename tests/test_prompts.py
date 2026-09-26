from systemone_api.models import SystemOneRequest
from systemone_api.prompts import SYSTEM_PROMPT, PromptCompiler, describe


class FakeTokenizer:
    def __init__(self):
        self.messages = None

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
        self.messages = messages
        rendered = []
        for item in messages:
            content = item["content"]
            if isinstance(content, list):
                content = "".join(part["text"] for part in content)
            rendered.append(f"{item['role']}:{content}")
        return "\n".join(rendered) + "\nassistant:"


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


def test_prompt_matches_autojev_v2_3_training_contract():
    tokenizer = FakeTokenizer()
    request = SystemOneRequest.model_validate(
        {
            "state": {"message": "hello"},
            "questions": {
                "safe": {
                    "type": "noul",
                    "instructions": "Is this safe?",
                    "criteria": {"true": "Safe", "false": "Unsafe"},
                }
            },
        }
    )
    PromptCompiler(tokenizer).prepare(request)
    assert tokenizer.messages == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        'State:\n{"message": "hello"}\n\nQuestion:\nIs this safe?'
                        "\n\nOptions:\nA: true: Safe\nB: false: Unsafe"
                        "\n\nReturn only the letter code of the best option."
                    ),
                }
            ],
        },
    ]


def test_describe_preserves_strings_and_serializes_structured_state():
    assert describe("state") == "state"
    assert describe({"message": "hello"}) == '{"message": "hello"}'
