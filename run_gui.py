import sys
import traceback

try:
    from kakao_mcp.panel import main
    main()
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    traceback.print_exc()
    input("Press Enter to exit...")
