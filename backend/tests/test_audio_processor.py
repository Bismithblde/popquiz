import asyncio
import itertools
from unittest.mock import AsyncMock, MagicMock

import pytest

from ..services.audio_processor import AudioChunk, AudioProcessor
from ..services.database import TranscriptRecord


@pytest.fixture()
def processor_setup():
    queue = asyncio.Queue()

    transcription_service = MagicMock()
    transcription_service.transcribe = AsyncMock(return_value="transcript")

    transcript_id = itertools.count(1)

    async def fake_insert(**kwargs):
        return TranscriptRecord(
            id=next(transcript_id),
            session_id=kwargs["session_id"],
            start_time=kwargs["start_time"],
            end_time=kwargs["end_time"],
            text=kwargs["text"],
            created_at=kwargs["end_time"],
        )

    repository = MagicMock()
    repository.insert_transcript = AsyncMock(side_effect=fake_insert)

    summary_scheduler = MagicMock()
    summary_scheduler.consider_transcript = AsyncMock()

    processor = AudioProcessor(
        queue,
        transcription_service=transcription_service,
        repository=repository,
        summary_scheduler=summary_scheduler,
        target_window_seconds=1,
    )

    return {
        "processor": processor,
        "transcription_service": transcription_service,
        "repository": repository,
        "summary_scheduler": summary_scheduler,
    }


@pytest.mark.asyncio
async def test_audio_accumulation_triggers_flush(processor_setup):
    processor = processor_setup["processor"]
    chunk_size = processor.threshold_bytes // 2

    await processor._handle_chunk(AudioChunk("room1", b"\x00" * chunk_size))
    assert len(processor.buffers["room1"].data) == chunk_size

    await processor._handle_chunk(AudioChunk("room1", b"\x00" * chunk_size))

    assert len(processor.buffers["room1"].data) == 0
    processor_setup["transcription_service"].transcribe.assert_awaited_once()
    processor_setup["repository"].insert_transcript.assert_awaited_once()
    processor_setup["summary_scheduler"].consider_transcript.assert_awaited_once()


@pytest.mark.asyncio
async def test_processor_resilience_on_transcription_failure(processor_setup):
    processor = processor_setup["processor"]
    processor_setup["transcription_service"].transcribe.side_effect = RuntimeError("offline")

    await processor._handle_chunk(AudioChunk("room2", b"\x00" * processor.threshold_bytes))

    assert len(processor.buffers["room2"].data) == 0
    processor_setup["repository"].insert_transcript.assert_not_awaited()
    processor_setup["summary_scheduler"].consider_transcript.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_flush_drains_partial_buffer(processor_setup):
    processor = processor_setup["processor"]

    await processor._handle_chunk(AudioChunk("room3", b"\x00" * (processor.threshold_bytes // 4)))
    assert len(processor.buffers["room3"].data) > 0

    await processor.force_flush("room3")

    assert len(processor.buffers["room3"].data) == 0
    processor_setup["transcription_service"].transcribe.assert_awaited_once()