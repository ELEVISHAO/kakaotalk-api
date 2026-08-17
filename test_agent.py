"""Test KakaoTalk Agent locally."""
import os
import sys

# Set environment variables for local testing
os.environ["KAKAO_AGENT_API_KEY"] = "test-key-123"
os.environ["KAKAO_AGENT_HOST"] = "127.0.0.1"
os.environ["KAKAO_AGENT_PORT"] = "8765"

# Run the agent
from kakao_mcp.api import main

if __name__ == "__main__":
    print("Starting KakaoTalk Agent...")
    print(f"API Key: test-key-123")
    print(f"Host: 127.0.0.1")
    print(f"Port: 8765")
    main()
