"""Tests for the audio processor."""
import asyncio
import time
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ..services.audio_processor import AudioProcessor, AudioChunk, SessionBuffer
from ..services.database import LectureRepository
from ..services.summarization import SummarizationService, SummaryScheduler
from ..services.transcription import TranscriptionService


@pytest.fixture
async def repo():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        repository = LectureRepository(db_path=db_path)
        await repository.initialize()
        yield repository


@pytest.fixture
async def processor(repo):
    """Create an audio processor with mocked services."""
    queue = asyncio.Queue()
    transcription_service = AsyncMock(spec=TranscriptionService)
    summarization_service = SummarizationService()
    summary_scheduler = SummaryScheduler(repo, summarization_service)

    processor = AudioProcessor(
        queue,
        transcription_service=transcription_service,
        repository=repo,
        summary_scheduler=summary_scheduler,
        sample_rate_hz=16_000,
        target_window_seconds=1,  # 1 second for testing (32KB threshold)
    )
    return processor


class TestAudioProcessor:
    @pytest.mark.asyncio
    async def test_buffer_accumulation(self, processor):
        """Test that audio chunks accumulate in the buffer."""
        chunk1 = b"\x00" * 10_000
        chunk2 = b"\x00" * 10_000

        processor.buffers["room1"] = processor.buffers.get("room1") or SessionBuffer()
        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk1))

        assert len(processor.buffers["room1"].data) == 10_000

        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk2))

        assert len(processor.buffers["room1"].data) == 20_000

    @pytest.mark.asyncio
    async def test_buffer_flush_on_threshold(self, processor):
        """Test that buffer flushes when threshold is reached."""
        # 1 second at 16kHz 16-bit = 32KB
        threshold_bytes = processor.threshold_bytes

        chunk = b"\x00" * threshold_bytes

        processor.transcription_service.transcribe = AsyncMock(
            return_value="Transcribed audio"
        )

        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk))

        # Buffer should be flushed
        assert len(processor.buffers["room1"].data) == 0

        # Transcript should be stored
        processor.transcription_service.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_flush(self, processor):
        """Test force flushing a partial buffer."""
        chunk = b"\x00" * 10_000

        processor.buffers["room1"] = SessionBuffer()
        processor.buffers["room1"].data.extend(chunk)

        processor.transcription_service.transcribe = AsyncMock(
            return_value="Forced flush"
        )

        await processor.force_flush("room1")

        assert len(processor.buffers["room1"].data) == 0
        processor.transcription_service.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcription_failure_handling(self, processor):
        """Test that transcription failures don't crash the processor."""
        chunk = b"\x00" * processor.threshold_bytes

        processor.transcription_service.transcribe = AsyncMock(
            side_effect=Exception("API Error")
        )

        # Should not raise
        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk))

        # Buffer should still be cleared even if transcription fails
        assert len(processor.buffers["room1"].data) == 0

    @pytest.mark.asyncio
    async def test_multi_session_isolation(self, processor):
        """Test that different sessions maintain separate buffers."""
        chunk = b"\x00" * 10_000

        processor.buffers["room1"] = SessionBuffer()
        processor.buffers["room2"] = SessionBuffer()

        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk))
        await processor._handle_chunk(AudioChunk(session_id="room2", payload=chunk))

        assert len(processor.buffers["room1"].data) == 10_000
        assert len(processor.buffers["room2"].data) == 10_000

    @pytest.mark.asyncio
    async def test_transcript_history(self, processor):
        """Test that transcripts are stored in history."""
        chunk = b"\x00" * processor.threshold_bytes

        processor.transcription_service.transcribe = AsyncMock(
            return_value="Test transcript"
        )

        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk))

        assert len(processor.transcript_history["room1"]) == 1
        assert processor.transcript_history["room1"][0].text == "Test transcript"

    @pytest.mark.asyncio
    async def test_run_forever_integration(self, processor):
        """Test the main run_forever loop."""
        processor.transcription_service.transcribe = AsyncMock(
            return_value="Transcribed"
        )

        # Start the worker
        worker = asyncio.create_task(processor.run_forever())

        # Give it time to start
        await asyncio.sleep(0.1)

        # Queue a chunk
        chunk = b"\x00" * processor.threshold_bytes
        await processor.queue.put(AudioChunk(session_id="room1", payload=chunk))

        # Give it time to process
        await asyncio.sleep(0.2)

        # Verify processing happened
        processor.transcription_service.transcribe.assert_called_once()

        # Cleanup
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_timestamp_tracking(self, processor):
        """Test that start and end times are tracked accurately."""
        processor.transcription_service.transcribe = AsyncMock(
            return_value="Text"
        )

        chunk = b"\x00" * processor.threshold_bytes
        before = time.time()

        await processor._handle_chunk(AudioChunk(session_id="room1", payload=chunk))

        after = time.time()

        record = processor.transcript_history["room1"][0]
        assert before <= record.start_time <= after
        assert before <= record.end_time <= after
        assert record.end_time >= record.start_time
