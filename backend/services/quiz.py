from __future__ import annotations

import asyncio
import json
from typing import Any, List

from google import genai
from google.genai import types

from .context import ContextPackage


class QuizService:
    """Generates quiz questions with recency bias from a context package."""

    def __init__(self, *, model: str = "gemini-1.5-pro") -> None:
        self.client = genai.Client()
        self.model = model
        self.schema = types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "question": types.Schema(type=types.Type.STRING),
                    "options": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="Multiple choice options",
                    ),
                    "answer_index": types.Schema(
                        type=types.Type.INTEGER,
                        description="0-based index of the correct option",
                    ),
                    "rationale": types.Schema(
                        type=types.Type.STRING,
                        description="Brief justification for the correct answer",
                    ),
                },
                required=["question", "options", "answer_index"],
            ),
        )

    async def generate_questions(
        self, context: ContextPackage, *, question_count: int = 3
    ) -> List[dict[str, Any]]:
        if not context.has_content:
            raise ValueError("No context available to generate questions.")

        prompt = self._build_prompt(context, question_count)
        raw = await asyncio.to_thread(self._generate_blocking, prompt)
        return self._parse_json(raw)

    def _build_prompt(self, context: ContextPackage, question_count: int) -> str:
        recent_block = context.render_recent_block()
        summary_block = context.render_summary_block()
        return (
            "You are an assistant for teachers. Based on the lecture transcripts below, "
            "write {count} multiple-choice questions. Weight recent discussion more heavily.".format(
                count=question_count
            )
            + "\n\nRecent detailed transcript (highest priority):\n"
            + recent_block
            + "\n\nGlobal summaries (reference for context):\n"
            + summary_block
            + "\n\nOutput strictly matches the JSON schema you were provided."
        )

    def _generate_blocking(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self.schema,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            raise RuntimeError("Quiz generation returned empty response")
        return raw

    @staticmethod
    def _parse_json(raw: str) -> List[dict[str, Any]]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise RuntimeError("Model returned malformed JSON") from exc

        if not isinstance(payload, list):
            raise RuntimeError("Quiz response must be a list")
        return payload
