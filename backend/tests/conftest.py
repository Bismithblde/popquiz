"""Pytest configuration and shared fixtures for all tests."""
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(scope="session", autouse=True)
def mock_google_api_key():
    """Mock Google API key and Gemini client for all tests."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Mock response"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-api-key-mock"}):
        with patch("google.genai.Client", return_value=mock_client):
            yield


@pytest.fixture
def mock_genai_client():
    """Provide a mock Gemini client for services."""
    client_instance = MagicMock()
    response = MagicMock()
    response.text = "Mock response"
    client_instance.models.generate_content.return_value = response
    return client_instance


@pytest.fixture
def mock_transcription_response():
    """Mock transcription response from Gemini."""
    response = MagicMock()
    response.text = "This is a transcribed text from the audio."
    return response


@pytest.fixture
def mock_summarization_response():
    """Mock summarization response from Gemini."""
    response = MagicMock()
    response.text = "• Key concept 1\n• Key concept 2\n• Key concept 3"
    return response


@pytest.fixture
def mock_quiz_response():
    """Mock quiz generation response from Gemini."""
    response = MagicMock()
    response.text = """[
        {
            "question": "What is the capital of France?",
            "options": ["London", "Paris", "Berlin", "Madrid"],
            "answer_index": 1,
            "rationale": "Paris is the capital of France."
        }
    ]"""
    return response
