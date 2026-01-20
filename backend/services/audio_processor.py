import asyncio

class AudioProcessor:
    """
    Processes audio chunks from an async queue and manages the accumulation buffer.
    """
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self.buffer = bytearray()
        # Threshold: ~3 seconds of 16kHz 16-bit audio
        self.THRESHOLD = 96000 
        
        # ADDED: Store the results of the transcriptions
        self.transcript_history = []

    async def run_forever(self):
        print("Audio Processor Worker Started!")
        while True:
            chunk = await self.queue.get()
            try:
                # 1. Accumulate audio
                self.buffer.extend(chunk)

                # 2. Check threshold
                if len(self.buffer) >= self.THRESHOLD:
                    audio_to_send = bytes(self.buffer)
                    self.buffer.clear()
                    
                    # 3. DANGEROUS ZONE: Wrap AI call in its own try/except
                    # This prevents the whole 'while' loop from crashing if the API is down
                    try:
                        await self.transcribe(audio_to_send)
                    except Exception as e:
                        print(f"⚠️ Transcription failed: {e}")
                        # Optionally: You could put the audio back in a retry queue here
            
            except Exception as e:
                print(f"❌ Critical Worker Error: {e}")
            
            finally:
                # Always mark the task as done so the queue doesn't bloat
                self.queue.task_done()

    async def transcribe(self, full_audio: bytes):
        """
        Integration point for Gemini / Whisper.
        """
        # Placeholder for actual AI API call
        await asyncio.sleep(0.5) 
        
        # MOCK RESULT: In reality, this comes from the AI
        mock_text = f"Teacher said something at {len(full_audio)} bytes."
        
        self.transcript_history.append(mock_text)
        print(f"--- AI TRANSCRIBED: {mock_text} ---")