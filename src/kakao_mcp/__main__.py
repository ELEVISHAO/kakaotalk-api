"""Allow running as: python -m kakao_mcp"""
import sys

if len(sys.argv) > 1 and sys.argv[1] in ("--gui", "--panel"):
    from kakao_mcp.panel import main
    main()
else:
    from kakao_mcp.server import main
    main()
