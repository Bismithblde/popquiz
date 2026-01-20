import pytest
import asyncio
from ..services.audio_processor import AudioProcessor

@pytest.mark.asyncio
async def test_audio_accumulation():
    """
    Tests that the AudioProcessor accumulates small chunks and only
    triggers 'transcribe' once the THRESHOLD is reached.
    """
    # 1. Setup
    queue = asyncio.Queue()
    processor = AudioProcessor(queue)
    
    # We create a small chunk (10,000 bytes)
    # Our threshold is 96,000 bytes, so 10 chunks should trigger it
    small_chunk = b"\x00" * 10000 

    # 2. Start the processor in the background
    # we use a task so we can cancel it later
    worker_task = asyncio.create_task(processor.run_forever())

    # 3. Feed the queue
    for _ in range(9):
        await queue.put(small_chunk)
    
    # Allow a tiny bit of time for the loop to process
    await asyncio.sleep(0.1)
    
    # ASSERT: The buffer should have 90,000 bytes and NOT be empty yet
    assert len(processor.buffer) == 90000

    # 4. Send the 10th chunk to cross the 96,000 threshold
    await queue.put(small_chunk)
    await asyncio.sleep(0.1)

    # ASSERT: The buffer should have been cleared after processing
    assert len(processor.buffer) == 0
    
    # Cleanup
    worker_task.cancel()

@pytest.mark.asyncio
async def test_processor_resilience():
    queue = asyncio.Queue()
    processor = AudioProcessor(queue)
    
    # Force the transcribe method to crash
    async def broken_transcribe(data):
        raise ValueError("AI Service Offline!")
    
    processor.transcribe = broken_transcribe
    
    worker_task = asyncio.create_task(processor.run_forever())
    
    # Send enough data to trigger the 'broken' transcription
    await queue.put(b"\x00" * 100000)
    await asyncio.sleep(0.1)
    
    # If the loop is still alive, we should be able to send more data
    assert worker_task.done() is False 
    
    worker_task.cancel()