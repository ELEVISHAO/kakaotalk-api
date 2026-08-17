@echo off
echo Starting KakaoTalk Agent...

:: Set environment variables
set KAKAO_AGENT_API_KEY=test-key-123
set KAKAO_AGENT_HOST=127.0.0.1
set KAKAO_AGENT_PORT=8765

:: Run Python script directly
python test_agent.py

pause
