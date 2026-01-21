"""Integration tests for the entire quiz pipeline."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ..main import app, repository, audio_processor


@pytest.fixture(autouse=True)
async def clean_repository():
    """Ensure the shared repository is initialized and empty for each test."""
    await repository.initialize()
    conn = await repository._connect()
    try:
        await conn.execute("DELETE FROM transcripts")
        await conn.execute("DELETE FROM summaries")
        await conn.commit()
    finally:
        await conn.close()


class TestAudioIngestEndpoint:
    def test_ingest_audio_success(self):
        """Test audio ingestion endpoint."""
        client = TestClient(app)

        audio_data = b"\x00" * 10_000

        response = client.post(
            "/rooms/math101/audio",
            files={"file": ("audio.wav", audio_data, "audio/wav")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["bytes"] == 10_000

    def test_ingest_audio_empty_file(self):
        """Test that empty audio files are rejected."""
        client = TestClient(app)

        response = client.post(
            "/rooms/math101/audio",
            files={"file": ("audio.wav", b"", "audio/wav")},
        )

        assert response.status_code == 400

    def test_ingest_audio_multiple_rooms(self):
        """Test audio ingestion across multiple rooms."""
        client = TestClient(app)

        audio_data = b"\x00" * 1_000

        response1 = client.post(
            "/rooms/room1/audio",
            files={"file": ("audio.wav", audio_data, "audio/wav")},
        )
        response2 = client.post(
            "/rooms/room2/audio",
            files={"file": ("audio.wav", audio_data, "audio/wav")},
        )

        assert response1.status_code == 200
        assert response2.status_code == 200


class TestQuizTriggerEndpoint:
    @pytest.mark.asyncio
    async def test_quiz_trigger_no_transcripts(self):
        """Test quiz trigger when no transcripts exist."""
        client = TestClient(app)

        with patch("backend.main.audio_processor.force_flush", new_callable=AsyncMock):
            response = client.post(
                "/rooms/room1/quiz",
                json={"question_count": 3, "recent_minutes": 10},
            )

            assert response.status_code == 400
            assert "No transcripts" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_quiz_trigger_with_context(self):
        """Test quiz trigger with available transcripts."""
        client = TestClient(app)
        await repository.insert_transcript(
            session_id="room1",
            start_time=0.0,
            end_time=10.0,
            text="The Earth revolves around the Sun.",
        )

        with patch("backend.main.audio_processor.force_flush", new_callable=AsyncMock):
            with patch("backend.main.context_builder.build") as mock_build:
                mock_context = MagicMock()
                mock_context.has_content = True
                mock_build.return_value = mock_context

                with patch("backend.main.quiz_service.generate_questions") as mock_gen:
                    mock_gen.return_value = [
                        {
                            "question": "What does Earth revolve around?",
                            "options": ["Sun", "Moon", "Mars", "Venus"],
                            "answer_index": 0,
                        }
                    ]

                    response = client.post(
                        "/rooms/room1/quiz",
                        json={"question_count": 1, "recent_minutes": 10},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert "questions" in data
                    assert len(data["questions"]) == 1

    def test_quiz_trigger_invalid_params(self):
        """Test quiz trigger with invalid parameters."""
        client = TestClient(app)

        # question_count too high
        response = client.post(
            "/rooms/room1/quiz",
            json={"question_count": 20, "recent_minutes": 10},
        )
        assert response.status_code == 422  # Validation error

        # recent_minutes too high
        response = client.post(
            "/rooms/room1/quiz",
            json={"question_count": 3, "recent_minutes": 100},
        )
        assert response.status_code == 422


class TestHealthCheck:
    def test_health_check(self):
        """Test health check endpoint."""
        client = TestClient(app)

        response = client.get("/health_check")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"


class TestWebSocketBroadcasting:
    def test_quiz_broadcast_to_websockets(self):
        """Test that quiz results are broadcast to connected clients."""
        client = TestClient(app)

        with client.websocket_connect("/ws/room1") as ws1:
            with client.websocket_connect("/ws/room1") as ws2:
                with patch("backend.main.audio_processor.force_flush", new_callable=AsyncMock):
                    with patch("backend.main.context_builder.build") as mock_build:
                        mock_context = MagicMock()
                        mock_context.has_content = True
                        mock_build.return_value = mock_context

                        with patch("backend.main.quiz_service.generate_questions") as mock_gen:
                            mock_gen.return_value = [
                                {
                                    "question": "Test?",
                                    "options": ["A", "B", "C", "D"],
                                    "answer_index": 0,
                                }
                            ]

                            # Trigger quiz
                            response = client.post(
                                "/rooms/room1/quiz",
                                json={"question_count": 1, "recent_minutes": 10},
                            )

                            assert response.status_code == 200

                            # Both clients should receive the broadcast
                            data1 = ws1.receive_json()
                            data2 = ws2.receive_json()

                            assert data1["type"] == "quiz"
                            assert data2["type"] == "quiz"
                            assert len(data1["questions"]) == 1


class TestEndToEndFlow:
    @pytest.mark.asyncio
    async def test_complete_pipeline(self):
        """Test the complete flow: ingest -> transcribe -> summarize -> quiz."""
        client = TestClient(app)

        # 1. Ingest audio
        audio_data = b"\x00" * 32_000  # ~1 second at 16kHz
        response = client.post(
            "/rooms/integration_test/audio",
            files={"file": ("audio.wav", audio_data, "audio/wav")},
        )
        assert response.status_code == 200

        # 2. Wait for processing
        await asyncio.sleep(0.2)

        # 3. Trigger quiz (with mocked transcription)
        with patch("backend.main.audio_processor.force_flush", new_callable=AsyncMock):
            with patch("backend.main.context_builder.build") as mock_build:
                mock_context = MagicMock()
                mock_context.has_content = True
                mock_build.return_value = mock_context

                with patch("backend.main.quiz_service.generate_questions") as mock_gen:
                    mock_gen.return_value = [
                        {
                            "question": "Sample question?",
                            "options": ["A", "B", "C", "D"],
                            "answer_index": 0,
                        }
                    ]

                    response = client.post(
                        "/rooms/integration_test/quiz",
                        json={"question_count": 1, "recent_minutes": 10},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert len(data["questions"]) == 1
