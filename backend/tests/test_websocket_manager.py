import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ..services.audio_processor import app, rooms

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_rooms():
    """Clear rooms before and after each test"""
    rooms.clear()
    yield
    rooms.clear()

def test_websocket_broadcast():
    """
    Test that a message sent by one client is broadcasted to all 
    clients in the same room.
    """
    # Create two clients connecting to the SAME room
    with client.websocket_connect("/ws/math101") as ws1:
        with client.websocket_connect("/ws/math101") as ws2:
            # Client 1 sends a message
            ws1.send_text("Hello Class!")
            
            # Both clients should receive the broadcasted message
            data1 = ws1.receive_json()
            data2 = ws2.receive_json()
            
            assert data1["message"] == "Room math101 says: Hello Class!"
            assert data2["message"] == "Room math101 says: Hello Class!"

def test_room_isolation():
    """
    Test that messages in Room A do not leak into Room B.
    """
    with client.websocket_connect("/ws/room_a") as ws_a:
        with client.websocket_connect("/ws/room_b") as ws_b:
            ws_a.send_text("Secret message")
            
            # Room A gets the message
            data_a = ws_a.receive_json()
            assert "Secret message" in data_a["message"]
            
            # Room B should NOT receive messages from Room A
            # Using pytest.raises to ensure no message arrives
            with pytest.raises(Exception):
                ws_b.receive_json(timeout=0.1)

def test_single_client_receives_own_message():
    """
    Test that a single client receives its own broadcasted message.
    """
    with client.websocket_connect("/ws/solo_room") as ws:
        ws.send_text("Talking to myself")
        data = ws.receive_json()
        assert data["message"] == "Room solo_room says: Talking to myself"

def test_multiple_messages_in_sequence():
    """
    Test that multiple messages are broadcasted correctly in order.
    """
    with client.websocket_connect("/ws/chat") as ws1:
        with client.websocket_connect("/ws/chat") as ws2:
            messages = ["First", "Second", "Third"]
            
            for msg in messages:
                ws1.send_text(msg)
                data1 = ws1.receive_json()
                data2 = ws2.receive_json()
                
                assert data1["message"] == f"Room chat says: {msg}"
                assert data2["message"] == f"Room chat says: {msg}"

def test_client_disconnect_cleans_up():
    """
    Test that disconnecting a client removes it from the room.
    """
    with client.websocket_connect("/ws/temp_room") as ws1:
        ws2 = client.websocket_connect("/ws/temp_room")
        ws2.__enter__()
        
        # Send message while both connected
        ws1.send_text("Both here")
        ws1.receive_json()
        ws2.receive_json()
        
        # Disconnect ws2
        ws2.__exit__(None, None, None)
        
        # Send another message - only ws1 should receive
        ws1.send_text("Only me now")
        data = ws1.receive_json()
        assert data["message"] == "Room temp_room says: Only me now"

def test_empty_message():
    """
    Test handling of empty messages.
    """
    with client.websocket_connect("/ws/empty_test") as ws:
        ws.send_text("")
        data = ws.receive_json()
        assert data["message"] == "Room empty_test says: "

def test_special_characters_in_message():
    """
    Test that special characters are handled correctly.
    """
    with client.websocket_connect("/ws/special") as ws:
        special_msg = "Test: @#$%^&*(){}[]|\\<>?/~`"
        ws.send_text(special_msg)
        data = ws.receive_json()
        assert special_msg in data["message"]

def test_unicode_and_emoji_messages():
    """
    Test that unicode and emoji characters work.
    """
    with client.websocket_connect("/ws/unicode") as ws:
        unicode_msg = "Hello 世界 🌍 café ñoño"
        ws.send_text(unicode_msg)
        data = ws.receive_json()
        assert unicode_msg in data["message"]

def test_very_long_message():
    """
    Test handling of very long messages.
    """
    with client.websocket_connect("/ws/longmsg") as ws:
        long_msg = "A" * 10000
        ws.send_text(long_msg)
        data = ws.receive_json()
        assert long_msg in data["message"]

def test_room_with_special_characters():
    """
    Test that room IDs with special characters work.
    """
    room_id = "room-123_test"
    with client.websocket_connect(f"/ws/{room_id}") as ws:
        ws.send_text("Testing special room ID")
        data = ws.receive_json()
        assert f"Room {room_id} says:" in data["message"]

def test_concurrent_rooms():
    """
    Test multiple rooms operating simultaneously without interference.
    """
    with client.websocket_connect("/ws/room1") as ws1_a, \
         client.websocket_connect("/ws/room1") as ws1_b, \
         client.websocket_connect("/ws/room2") as ws2_a, \
         client.websocket_connect("/ws/room2") as ws2_b:
        
        # Send to room1
        ws1_a.send_text("Message for room1")
        r1_a = ws1_a.receive_json()
        r1_b = ws1_b.receive_json()
        
        # Send to room2
        ws2_a.send_text("Message for room2")
        r2_a = ws2_a.receive_json()
        r2_b = ws2_b.receive_json()
        
        assert "room1" in r1_a["message"]
        assert "room1" in r1_b["message"]
        assert "room2" in r2_a["message"]
        assert "room2" in r2_b["message"]