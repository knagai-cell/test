"""認証ユーティリティ（HMAC-SHA256ベースのトークン）"""
import hashlib
import hmac
import json
import base64
import os
import time

SECRET_KEY = os.environ.get("SECRET_KEY", "sales-report-secret-key-change-in-production")
TOKEN_EXPIRY_SECONDS = 86400  # 24時間


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _sign(message: str) -> str:
    return _b64encode(
        hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    )


def create_token(user_id: int, email: str, role: str, name: str) -> str:
    """トークンを生成"""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "name": name,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }
    payload_b64 = _b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    signature = _sign(payload_b64)
    return f"{payload_b64}.{signature}"


def verify_token(token: str) -> dict | None:
    """トークンを検証してペイロードを返す"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None

        payload_b64, signature = parts
        expected_sig = _sign(payload_b64)

        if not hmac.compare_digest(signature, expected_sig):
            return None

        payload = json.loads(_b64decode(payload_b64))

        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


def get_current_user(handler) -> dict | None:
    """リクエストからユーザー情報を取得"""
    cookie_header = handler.headers.get("Cookie", "")
    token = None
    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("token="):
            token = cookie[6:]
            break

    if not token:
        return None

    return verify_token(token)
