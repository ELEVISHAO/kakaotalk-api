"""Central configuration for KakaoTalk MCP Server."""
import os
import unicodedata
from dataclasses import dataclass

# KakaoTalk window class names
KAKAO_MAIN_WINDOW_CLASS = "EVA_Window_Dblclk"
KAKAO_MAIN_WINDOW_TITLE = "카카오톡"
KAKAO_CHAT_WINDOW_CLASS = "EVA_Window_Dblclk"
KAKAO_LIST_CONTROL_CLASS = "EVA_VH_ListControl_Dblclk"
KAKAO_EDIT_CLASS = "RICHEDIT50W"

# Win32 message constants
WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_ESCAPE = 0x1B
VK_A = 0x41
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002

# KakaoTalk data paths
KAKAO_LOCAL_DATA = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Kakao", "KakaoTalk"
)
KAKAO_USERS_DIR = os.path.join(KAKAO_LOCAL_DATA, "users")

# Image cache subdirectories to monitor
IMAGE_CACHE_SUBDIRS = [
    "chat_data/cli_http_v2",
    "chat_data/cli/thumbnail",
    "chat_data/oci_v2",
    "chat_data/mci_v2",
]

# Timeouts and intervals
CLIPBOARD_MAX_RETRIES = 5
CLIPBOARD_RETRY_INTERVAL_SEC = 0.1
KEY_COMBO_WAIT_SEC = 0.15  # Was 0.3 — Ctrl+A/C combo wait

# Window and focus timing
WINDOW_ACTIVATE_WAIT_SEC = 0.15  # Was 0.2 — after bring_window_to_front
EDIT_CLICK_WAIT_SEC = 0.08  # Was 0.1 — after clicking edit control
CLIPBOARD_PASTE_WAIT_SEC = 0.03  # Was 0.05 — after clipboard set, before Ctrl+V
AFTER_PASTE_WAIT_SEC = 0.05  # Was 0.1 — after Ctrl+V, before Enter

# Search and open room timing
SEARCH_ACTIVATE_WAIT_SEC = 0.3  # Was 0.5 — after Ctrl+F
SEARCH_CHAR_INTERVAL_SEC = 0.02  # Per-character typing delay
SEARCH_RESULTS_WAIT_SEC = 0.8  # Was 1.5 — wait for search results
SEARCH_OPEN_WAIT_SEC = 0.5  # Was 1.0 — after Enter to open room

# Image sending
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
IMAGE_CONFIRM_WAIT_SEC = 0.5  # Was 1.0 — dialog render wait
IMAGE_BETWEEN_SEND_WAIT_SEC = 1.0  # Was 1.5 — between multiple images
IMAGE_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after bring_window_to_front for image
IMAGE_SET_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after SetFocus on edit
IMAGE_DIALOG_POLL_INTERVAL_SEC = 0.15  # Was 0.2 — dialog poll interval
IMAGE_AFTER_CONFIRM_WAIT_SEC = 0.3  # Was 0.5 — after Enter on dialog

# Mention timing
MENTION_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after bring to front
MENTION_CLICK_WAIT_SEC = 0.15  # Was 0.2 — after clicking edit
MENTION_AT_WAIT_SEC = 0.5  # Was 0.8 — after typing @
MENTION_NAME_WAIT_SEC = 0.6  # Was 1.0 — after typing name
MENTION_SELECT_WAIT_SEC = 0.3  # Was 0.5 — after Enter to select
MENTION_PASTE_WAIT_SEC = 0.2  # Was 0.3 — after Ctrl+V
MENTION_SEND_WAIT_SEC = 0.3  # Was 0.5 — after final Enter

# Default output directory for downloaded images
DEFAULT_IMAGE_OUTPUT_DIR = os.path.join(
    os.environ.get("USERPROFILE", ""),
    "Documents", "KakaoMCP_Images"
)


# ---------------------------------------------------------------------------
# HTTP Agent settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentSettings:
    api_key: str
    host: str
    port: int
    allow_ips: list[str]
    allowed_file_root: str
    max_file_size_mb: int
    job_wait_timeout_sec: float
    job_exec_timeout_sec: float
    log_message_body: bool


def _parse_allow_ips(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _is_loopback_host(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def load_agent_settings() -> AgentSettings:
    api_key = os.environ.get("KAKAO_AGENT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("KAKAO_AGENT_API_KEY is required to start kakaotalk-api")
    host = os.environ.get("KAKAO_AGENT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("KAKAO_AGENT_PORT", "8765"))
    allow_ips = _parse_allow_ips(os.environ.get("KAKAO_AGENT_ALLOW_IPS"))
    if not _is_loopback_host(host) and not allow_ips:
        raise RuntimeError("KAKAO_AGENT_ALLOW_IPS is required when host is not loopback")
    wait = (
        os.environ.get("KAKAO_JOB_WAIT_TIMEOUT_SEC")
        or os.environ.get("KAKAO_JOB_TIMEOUT_SEC")
        or "60"
    )
    return AgentSettings(
        api_key=api_key,
        host=host,
        port=port,
        allow_ips=allow_ips,
        allowed_file_root=os.environ.get("KAKAO_ALLOWED_FILE_ROOT", r"C:\KakaoAgent\jobs"),
        max_file_size_mb=int(os.environ.get("KAKAO_MAX_FILE_SIZE_MB", "100")),
        job_wait_timeout_sec=float(wait),
        job_exec_timeout_sec=float(os.environ.get("KAKAO_JOB_EXEC_TIMEOUT_SEC", "300")),
        log_message_body=os.environ.get("KAKAO_LOG_MESSAGE_BODY", "").strip()
        in ("1", "true", "TRUE"),
    )


def normalize_room_title(value: str) -> str:
    return unicodedata.normalize("NFC", value)
