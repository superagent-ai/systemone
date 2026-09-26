from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Content = str | dict[str, JsonValue] | list[JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class NoulCriteria(StrictModel):
    positive: str = Field(default="Yes", alias="true")
    negative: str = Field(default="No", alias="false")


class NoulQuestion(StrictModel):
    type: Literal["noul"]
    instructions: Content
    criteria: NoulCriteria = Field(default_factory=NoulCriteria)


class ChoiceQuestion(StrictModel):
    type: Literal["choice"]
    instructions: Content
    criteria: dict[str, str | None] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def nonempty_keys(self):
        if any(not key.strip() for key in self.criteria):
            raise ValueError("choice criteria keys must not be blank")
        return self


class ScoreQuestion(StrictModel):
    type: Literal["score"]
    instructions: Content
    criteria: list[str] = Field(min_length=2, max_length=16)


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class SystemOneRequest(StrictModel):
    state: Content
    questions: dict[str, Question] = Field(min_length=1, max_length=64)
    model: str = Field(default="security-one", min_length=1)

    @model_validator(mode="after")
    def nonempty_question_ids(self):
        if any(not key.strip() for key in self.questions):
            raise ValueError("question ids must not be blank")
        return self


class NoulAnswer(StrictModel):
    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0, le=1)


class ChoiceAnswer(StrictModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)


class ScoreAnswer(StrictModel):
    type: Literal["score"] = "score"
    score: float = Field(ge=0)
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


class Usage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(StrictModel):
    model: str
    answers: dict[str, Answer]
    usage: Usage


class ErrorDetail(StrictModel):
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
