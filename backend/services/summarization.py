from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from typing import Dict, List, Sequence

from google import genai
from google.genai import types

from .database import LectureRepository, TranscriptRecord


class SummarizationService:
    """Generates low-token summaries that preserve technical vocabulary."""

    def __init__(self, *, model: str = "gemini-1.5-flash") -> None:
        """Initialize the summarization service with a Gemini model.

        Args:
            model: The Gemini model to use for summarization.
        """
        self._client = None
        self.model = model

    @property
    def client(self) -> genai.Client:
        """Lazily initialize the Gemini client."""
        if self._client is None:
            self._client = genai.Client()
        return self._client

    async def summarize(self, transcripts: Sequence[TranscriptRecord]) -> str:
        """Summarize a sequence of transcript records into concise bullet points.

        Args:
            transcripts: A sequence of TranscriptRecord objects to summarize.

        Returns:
            A string containing the summarized bullet points.

        Raises:
            ValueError: If no transcripts are provided.
        """
        if not transcripts:
            raise ValueError("summarize() requires at least one transcript")

        contents = self._build_prompt(transcripts)
        return await asyncio.to_thread(self._summarize_blocking, contents)

    def _build_prompt(self, transcripts: Sequence[TranscriptRecord]) -> List[types.Part | str]:
        """Build the prompt and content for the summarization request.

        Args:
            transcripts: A sequence of TranscriptRecord objects.

        Returns:
            A list of parts for the Gemini API request.
        """
        prompt = (
            "Summarize the classroom discussion into concise bullet points. Focus on keeping every proper noun, "
            "numerical value, formula, technical term, main idea of each part of the discussion. Use as many bullets "
            "points as needed, but optimize for word efficiency, meaning using just enough words to capture every "
            "important idea of the discussion."
        )

        joined = "\n".join(
            self._format_segment(idx + 1, record) for idx, record in enumerate(transcripts)
        )
        return [prompt, joined]

    @staticmethod
    def _format_segment(index: int, record: TranscriptRecord) -> str:
        """Format a transcript record into a timestamped segment string.

        Args:
            index: The index of the segment.
            record: The TranscriptRecord to format.

        Returns:
            A formatted string with timestamp and text.
        """
        duration = record.end_time - record.start_time
        minutes = math.floor(record.start_time / 60)
        seconds = int(record.start_time % 60)
        timestamp = f"{minutes:02d}:{seconds:02d} (+{duration:.1f}s)"
        return f"[{index} @ {timestamp}] {record.text.strip()}"

    def _summarize_blocking(self, contents: List[types.Part | str]) -> str:
        """Perform the blocking summarization call to Gemini.

        Args:
            contents: The content parts for the API request.

        Returns:
            The summarized text response.
        """
        config = types.GenerateContentConfig(response_mime_type="text/plain")
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return (response.text or "").strip()


class SummaryScheduler:
    """Creates rolling summaries every N minutes per session."""

    def __init__(
        self,
        repository: LectureRepository,
        summarizer: SummarizationService,
        *,
        window_seconds: int = 300,
        min_chunks: int = 5,
    ) -> None:
        """Initialize the summary scheduler.

        Args:
            repository: The database repository for transcripts and summaries.
            summarizer: The service to generate summaries.
            window_seconds: The time window in seconds for grouping transcripts.
            min_chunks: The minimum number of transcript chunks required to trigger a summary.
        """
        self.repository = repository
        self.summarizer = summarizer
        self.window_seconds = window_seconds
        self.min_chunks = min_chunks
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_summary_ts: Dict[str, float] = {}

    async def consider_transcript(self, record: TranscriptRecord) -> None:
        """Consider a new transcript record for potential summarization.

        Checks if enough time has passed and sufficient chunks are available,
        then triggers a summary if conditions are met.

        Args:
            record: The new TranscriptRecord to consider.
        """
        session_id = record.session_id
        last_run = self._last_summary_ts.get(session_id)
        if last_run is not None and record.end_time - last_run < self.window_seconds:
            return

        lock = self._locks[session_id]
        async with lock:
            # Re-check after acquiring lock to avoid duplicate work
            last_run = self._last_summary_ts.get(session_id)
            if last_run is not None and record.end_time - last_run < self.window_seconds:
                return

            window_start = record.end_time - self.window_seconds
            transcripts = await self.repository.fetch_transcripts_in_window(
                session_id=session_id,
                start_time=window_start,
                end_time=record.end_time,
            )
            if len(transcripts) < self.min_chunks:
                return

            summary_text = await self.summarizer.summarize(transcripts)
            await self.repository.insert_summary(
                session_id=session_id,
                start_time=transcripts[0].start_time,
                end_time=transcripts[-1].end_time,
                summary_text=summary_text,
            )
            self._last_summary_ts[session_id] = record.end_time