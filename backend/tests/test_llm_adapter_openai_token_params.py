from services.llm_adapter import OpenAIAdapter


def test_openai_gpt5_uses_max_completion_tokens():
    adapter = OpenAIAdapter(api_key="test-key")

    assert adapter._build_token_limit_kwargs(model="gpt-5", max_tokens=1234) == {
        "max_completion_tokens": 1234
    }


def test_openai_legacy_models_use_max_tokens():
    adapter = OpenAIAdapter(api_key="test-key")

    assert adapter._build_token_limit_kwargs(model="gpt-4o-mini", max_tokens=4321) == {
        "max_tokens": 4321
    }
