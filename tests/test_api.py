from dataclasses import dataclass

from fastapi.testclient import TestClient

from systemone_api.api import create_app
from systemone_api.config import Settings
from systemone_api.models import ChoiceAnswer, SystemOneResponse, Usage
from systemone_api.service import Evaluation


class FakeBackend:
    async def healthy(self):
        return True


@dataclass
class FakeService:
    backend: FakeBackend = FakeBackend()

    async def evaluate(self, request):
        return Evaluation(
            response=SystemOneResponse(
                model=request.model,
                answers={
                    "team": ChoiceAnswer(
                        choice="security",
                        probabilities={"security": 0.9, "support": 0.1},
                        confidence=0.531,
                    )
                },
                usage=Usage(input_tokens=42, output_tokens=2),
            ),
            prefix_tokens=20,
            cached_tokens=18,
            prepare_ms=1.0,
            prefill_ms=2.0,
            branches_ms=3.0,
        )


def client():
    settings = Settings(api_keys="test-key", model_path="unused")
    return TestClient(create_app(settings, service=FakeService()))


def payload():
    return {
        "model": "openjev",
        "state": "Suspicious input",
        "questions": {
            "team": {
                "type": "choice",
                "instructions": "Who handles this?",
                "criteria": {"security": "Security", "support": "Support"},
            }
        },
    }


def test_systemone_wire_contract():
    with client() as api:
        response = api.post(
            "/v1/systemone", json=payload(), headers={"Authorization": "Bearer test-key"}
        )
    assert response.status_code == 200
    assert response.json()["answers"]["team"]["choice"] == "security"
    assert response.json()["usage"] == {"input_tokens": 42, "output_tokens": 2}
    assert response.headers["x-systemone-prefix-tokens"] == "20"
    assert "x-systemone-request-id" in response.headers


def test_auth_is_required_for_api_routes():
    with client() as api:
        response = api.post("/v1/systemone", json=payload())
    assert response.status_code == 401
    assert response.json() == {"error": {"message": "Missing or invalid API key"}}


def test_secondary_api_key_is_accepted():
    settings = Settings(
        api_keys="primary-key",
        api_keys_secondary="testing-key",
        model_path="unused",
    )
    with TestClient(create_app(settings, service=FakeService())) as api:
        response = api.post(
            "/v1/systemone",
            json=payload(),
            headers={"Authorization": "Bearer testing-key"},
        )
    assert response.status_code == 200


def test_health_is_public():
    with client() as api:
        response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_advertises_bearer_auth_and_systemone_route():
    with client() as api:
        schema = api.get("/openapi.json").json()
    operation = schema["paths"]["/v1/systemone"]["post"]
    assert operation["security"]
    assert any(
        value["scheme"] == "bearer" for value in schema["components"]["securitySchemes"].values()
    )
    assert schema["info"]["title"] == "SystemOne API"


def test_models_use_systemone_identity():
    with client() as api:
        response = api.get("/v1/models", headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 200
    body = response.json()
    assert "security-one" in {model["id"] for model in body["data"]}
    assert "systemone" in {model["id"] for model in body["data"]}
    assert {model["owned_by"] for model in body["data"]} == {"systemone"}
    assert "nagato" not in response.text.lower()


def test_openrouter_models_document_is_public_and_current():
    with client() as api:
        response = api.get("/models")
    assert response.status_code == 200
    model = response.json()["data"][0]
    assert model["schema_version"] == "2.4"
    assert model["id"] == "security-one"
    assert model["hugging_face_id"] == "superagent-ai/security-one-27b"
    assert model["quantization"] == "bf16"
    assert model["input_modalities"][0]["supported_inputs"]["max_context_length"] == {
        "value": 65_536,
        "unit": "token",
    }
    assert model["input_modalities"][0]["pricing"][0]["cost_usd"] == "0.00000005"
    assert model["output_modalities"][0]["pricing"][0]["cost_usd"] == "0"


def test_model_defaults_to_security_one():
    request = payload()
    del request["model"]
    with client() as api:
        response = api.post(
            "/v1/systemone", json=request, headers={"Authorization": "Bearer test-key"}
        )
    assert response.status_code == 200
    assert response.json()["model"] == "security-one"


def test_invalid_question_returns_422():
    broken = payload()
    broken["questions"]["team"]["criteria"] = {"only": "one"}
    with client() as api:
        response = api.post(
            "/v1/systemone", json=broken, headers={"Authorization": "Bearer test-key"}
        )
    assert response.status_code == 422
    assert "criteria" in response.json()["error"]["message"]
