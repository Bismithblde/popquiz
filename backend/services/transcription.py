from __future__ import annotations

import asyncio
from typing import Optional

from google import genai
from google.genai import types


MAX_INLINE_BYTES = 20 * 1024 * 1024  # 20 MB limit for inline audio payloads


class TranscriptionService:
	"""Wraps Gemini audio understanding for batch transcription."""

	DEFAULT_PROMPT = (
		"Generate an accurate transcript of the classroom discussion. "
		"Preserve speaker intent, terminology, numbers, and named entities."
	)

	def __init__(
		self,
		*,
		model: str = "gemini-1.5-flash",
		mime_type: str = "audio/wav",
		client: Optional[genai.Client] = None,
	) -> None:
		self._client = client
		self.model = model
		self.mime_type = mime_type

	@property
	def client(self) -> genai.Client:
		"""Lazily initialize the Gemini client."""
		if self._client is None:
			self._client = genai.Client()
		return self._client

	async def transcribe(self, audio_bytes: bytes, prompt: Optional[str] = None) -> str:
		if not audio_bytes:
			raise ValueError("Audio payload is empty")
		if len(audio_bytes) > MAX_INLINE_BYTES:
			raise ValueError(
				"Audio payload exceeds the 20 MB inline limit. Upload the file via the Files API instead."
			)

		prompt_text = prompt or self.DEFAULT_PROMPT
		contents = [
			prompt_text,
			types.Part.from_bytes(data=audio_bytes, mime_type=self.mime_type),
		]
		return await asyncio.to_thread(self._transcribe_blocking, contents)

	def _transcribe_blocking(self, contents: list[types.Part | str]) -> str:
		response = self.client.models.generate_content(
			model=self.model,
			contents=contents,
			config=types.GenerateContentConfig(response_mime_type="text/plain"),
		)
		text = (response.text or "").strip()
		if not text:
			raise RuntimeError("Gemini did not return any transcript text")
		return text

