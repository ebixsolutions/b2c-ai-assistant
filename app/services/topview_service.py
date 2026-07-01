"""TopView API service — HTTP client wrapping TopView REST endpoints.

Ports TopviewService.php (shopify-api) to Python.
All public functions return {"code": 0|int, "msg": str, "data": dict|None}.
"""
import os
import logging
import tempfile

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("b2c.topview")

TOPVIEW_BASE = "https://api.topview.ai"


def _get_headers():
    return {
        "Authorization": f"Bearer {os.getenv('TOPVIEW_API_KEY', '')}",
        "Topview-Uid": os.getenv("TOPVIEW_UID", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, endpoint: str, data: dict | None = None):
    url = TOPVIEW_BASE + endpoint
    headers = _get_headers()
    data = data or {}

    try:
        if method.upper() == "POST":
            resp = requests.post(url, json=data, headers=headers, timeout=60, verify=False)
        else:
            resp = requests.get(url, params=data, headers=headers, timeout=60, verify=False)
    except requests.RequestException as exc:
        logger.error("TopView [%s] %s connection error: %s", method, endpoint, exc)
        return {"code": 500, "msg": f"Connection error: {exc}", "data": None}

    logger.info("TopView [%s] %s HTTP:%d", method, endpoint, resp.status_code)

    if resp.status_code != 200:
        try:
            result = resp.json()
            msg = result.get("message") or result.get("msg") or f"TopView API error (HTTP {resp.status_code})"
        except Exception:
            msg = f"TopView API error (HTTP {resp.status_code})"
        return {"code": resp.status_code, "msg": msg, "data": None}

    try:
        result = resp.json()
    except Exception:
        return {"code": 500, "msg": "Invalid JSON response from TopView", "data": None}

    return {"code": 0, "msg": "success", "data": result}


# POST /v1/common_task/omni_reference/task/submit
def omni_reference_submit(params: dict):
    return _request("POST", "/v1/common_task/omni_reference/task/submit", params)


# GET /v1/common_task/omni_reference/task/query?taskId=
def omni_reference_query(task_id: str):
    return _request("GET", "/v1/common_task/omni_reference/task/query", {"taskId": task_id})


# GET /v1/upload/credential?format={ext}
# Response: result.fileId, result.uploadUrl (pre-signed S3 PUT URL)
def get_upload_credential(fmt: str):
    return _request("GET", "/v1/upload/credential", {"format": fmt.lower()})


def upload_binary_to_s3(upload_url: str, binary_data: bytes) -> bool:
    """Write binary to a temp file then stream it to S3."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as f:
            f.write(binary_data)
            tmp_path = f.name
        return upload_file_to_s3(upload_url, tmp_path, len(binary_data))
    except Exception as exc:
        logger.error("upload_binary_to_s3 error: %s", exc)
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def upload_file_to_s3(upload_url: str, file_path: str, file_size: int | None = None) -> bool:
    """Stream a local file to S3 via PUT — preferred for large files."""
    try:
        if file_size is None:
            file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as fh:
            resp = requests.put(
                upload_url,
                data=fh,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(file_size),
                },
                timeout=300,
                verify=False,
            )
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.error("upload_file_to_s3 error: %s", exc)
        return False


# POST /v1/common_task/image_edit/task/submit
def image_edit_submit(params: dict):
    return _request("POST", "/v1/common_task/image_edit/task/submit", params)


# GET /v1/common_task/image_edit/task/query?taskId=
def image_edit_query(task_id: str):
    return _request("GET", "/v1/common_task/image_edit/task/query", {"taskId": task_id})
