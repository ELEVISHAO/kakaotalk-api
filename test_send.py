# -*- coding: utf-8 -*-
"""KakaoTalk Agent 测试脚本 (UTF-8 安全)"""
import json
import sys
import requests

HOST = "127.0.0.1"
PORT = "8765"
API_KEY = "test-key-123"
BASE = f"http://{HOST}:{PORT}"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def send_message(room_name, message):
    r = requests.post(f"{BASE}/send/message", headers=HEADERS,
                      json={"room_name": room_name, "message": message}, timeout=15)
    print(f"[发文字] {room_name} -> status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


def send_file(room_name, file_path):
    r = requests.post(f"{BASE}/send/file", headers=HEADERS,
                      json={"room_name": room_name, "file_path": file_path}, timeout=60)
    print(f"[发文件] {room_name} -> status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


def send_materials(room_name, job_id, message, files):
    r = requests.post(f"{BASE}/send/materials", headers=HEADERS,
                      json={"room_name": room_name, "job_id": job_id,
                            "message": message, "files": files}, timeout=60)
    print(f"[文字+文件] {room_name} -> status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


def list_rooms():
    r = requests.get(f"{BASE}/rooms", headers=HEADERS, timeout=15)
    print(f"[聊天室列表] status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python test_send.py rooms                   # 列出聊天室")
        print("  python test_send.py msg <聊天室名> <内容>    # 发文字")
        print("  python test_send.py file <聊天室名> <路径>   # 发文件")
        print("  python test_send.py mat <聊天室名> <job> <文字> <文件1,文件2>")
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "rooms":
            list_rooms()
        elif cmd == "msg":
            send_message(sys.argv[2], sys.argv[3])
        elif cmd == "file":
            send_file(sys.argv[2], sys.argv[3])
        elif cmd == "mat":
            files = sys.argv[5].split(",") if len(sys.argv) > 5 else []
            send_materials(sys.argv[2], sys.argv[3], sys.argv[4], files)
        else:
            print("未知命令")
    except IndexError:
        print("参数不足")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"请求失败: {e}")
        sys.exit(1)
