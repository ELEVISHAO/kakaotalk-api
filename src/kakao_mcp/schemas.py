"""HTTP API request/response models and error codes."""
from pydantic import BaseModel, Field


class ErrorCode:
    KAKAOTALK_NOT_RUNNING = "KAKAOTALK_NOT_RUNNING"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    ROOM_MISMATCH = "ROOM_MISMATCH"
    EDIT_CONTROL_NOT_FOUND = "EDIT_CONTROL_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_PATH_NOT_ALLOWED = "FILE_PATH_NOT_ALLOWED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_SEND_FAILED = "FILE_SEND_FAILED"
    IMAGE_SEND_FAILED = "IMAGE_SEND_FAILED"
    MESSAGE_SEND_FAILED = "MESSAGE_SEND_FAILED"
    INVALID_API_KEY = "INVALID_API_KEY"
    IP_NOT_ALLOWED = "IP_NOT_ALLOWED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_JOB_ID = "INVALID_JOB_ID"
    AUTOMATION_BUSY = "AUTOMATION_BUSY"
    JOB_EXEC_TIMEOUT = "JOB_EXEC_TIMEOUT"
    MONITOR_DISABLED = "MONITOR_DISABLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RoomOpenRequest(BaseModel):
    room_name: str


class SendMessageRequest(BaseModel):
    room_name: str
    message: str


class SendImageRequest(BaseModel):
    room_name: str
    image_path: str


class SendFileRequest(BaseModel):
    room_name: str
    file_path: str


class SendFilesRequest(BaseModel):
    room_name: str
    file_paths: list[str]


class SendMaterialsRequest(BaseModel):
    room_name: str
    job_id: str
    message: str = ""
    files: list[str] = Field(default_factory=list)
