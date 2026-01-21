from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import DefaultDict, Dict

from .database import LectureRepository, TranscriptRecord
from .summarization import SummaryScheduler
from .transcription import TranscriptionService


BYTES_PER_SAMPLE = 2  # 16-bit audio


@dataclass(slots=True)
class AudioChunk:
    session_id: str
    payload: bytes
    received_at: float = field(default_factory=lambda: time.time())


@dataclass(slots=True)
class SessionBuffer:
    data: bytearray = field(default_factory=bytearray)
    started_at: float = field(default_factory=lambda: time.time())


class AudioProcessor:
    """Processes queued audio chunks and orchestrates transcription + storage."""

    def __init__(
        self,
        queue: asyncio.Queue,
        *,
        transcription_service: TranscriptionService,
        repository: LectureRepository,
        summary_scheduler: SummaryScheduler,
        sample_rate_hz: int = 16_000,
        target_window_seconds: int = 60,
    ) -> None:
        self.queue = queue
        self.transcription_service = transcription_service
        self.repository = repository
        self.summary_scheduler = summary_scheduler
        self.sample_rate_hz = sample_rate_hz
        self.bytes_per_second = sample_rate_hz * BYTES_PER_SAMPLE
        self.threshold_bytes = self.bytes_per_second * target_window_seconds
        self.buffers: Dict[str, SessionBuffer] = {}
        self.transcript_history: DefaultDict[str, list[TranscriptRecord]] = defaultdict(list)

    async def run_forever(self) -> None:
        print("Audio Processor Worker Started!")
        while True:
            chunk: AudioChunk = await self.queue.get()
            try:
                await self._handle_chunk(chunk)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"❌ Critical Worker Error for {chunk.session_id}: {exc}")
            finally:
                self.queue.task_done()

    async def force_flush(self, session_id: str) -> None:
        buffer = self.buffers.get(session_id)
        if not buffer or not buffer.data:
            return
        await self._flush_buffer(session_id, buffer)

    async def _handle_chunk(self, chunk: AudioChunk) -> None:
        buffer = self.buffers.setdefault(chunk.session_id, SessionBuffer())
        if not buffer.data:
            buffer.started_at = chunk.received_at
        buffer.data.extend(chunk.payload)

        if len(buffer.data) >= self.threshold_bytes:
            await self._flush_buffer(chunk.session_id, buffer, end_time=chunk.received_at)

    async def _flush_buffer(
        self, session_id: str, buffer: SessionBuffer, *, end_time: float | None = None
    ) -> None:
        if not buffer.data:
            return

        start_time = buffer.started_at
        final_time = end_time or time.time()
        audio_bytes = bytes(buffer.data)
        buffer.data.clear()
        buffer.started_at = final_time

        try:
            transcript_text = await self.transcription_service.transcribe(audio_bytes)
        except Exception as exc:
            print(f"⚠️ Transcription failed for {session_id}: {exc}")
            return

        record = await self.repository.insert_transcript(
            session_id=session_id,
            start_time=start_time,
            end_time=final_time,
            text=transcript_text,
        )
        self.transcript_history[session_id].append(record)
        await self.summary_scheduler.consider_transcript(record)