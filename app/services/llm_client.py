from functools import lru_cache
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from app.core.config import get_settings


class LlmAnswer(BaseModel):
    message: str
    refusal: bool
    action: Literal["NONE", "CHANGE_CONDITIONS", "VIEW_PRODUCT_LIST"]


class LlmClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)
        self._model = settings.llm_model

    def ask(self, system_prompt: str, history: list[dict[str, str]], message: str) -> LlmAnswer:
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message},
        ]
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=messages,
            response_format=LlmAnswer,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("LLM returned no parsed response")
        return parsed


@lru_cache
def get_llm_client() -> LlmClient:
    return LlmClient()
