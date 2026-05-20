import io
import json
import os
import datetime
import base64
import requests
import oss2
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Qwen Voice Clone WebUI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_URL = "https://omni.qwen.ai"
API_PREFIX = "/api/v2/omni"

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")
CREDS_PATH = os.path.join(os.path.expanduser("~"), ".qwen-voice-creds.json")


def load_creds():
    try:
        with open(CREDS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def build_headers(token, cookies_str, extra=None):
    h = {
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "referer": f"{BASE_URL}/voice-clone",
        "origin": BASE_URL,
        "source": "web",
        "version": "0.0.5",
        "timezone": datetime.datetime.now().astimezone().strftime("%a %b %d %Y %H:%M:%S GMT%z (%Z)"),
    }
    if extra:
        h.update(extra)
    return h

def parse_cookies(cookies_str):
    c = {}
    for item in cookies_str.split("; "):
        if "=" in item:
            k, v = item.split("=", 1)
            c[k] = v
    if "token" not in c:
        # token is HttpOnly, must be explicitly injected from input
        pass
    return c

def get_user_id(token):
    parts = token.split(".")
    if len(parts) >= 2:
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("id")

@app.get("/", response_class=HTMLResponse)
async def index():
    html = open(TEMPLATE_PATH).read()
    token = os.environ.get("QWEN_TOKEN") or load_creds().get("token", "")
    cookies = os.environ.get("QWEN_COOKIES") or load_creds().get("cookies", "")
    html = html.replace("{{ default_token }}", token)
    html = html.replace("{{ default_cookies }}", cookies)
    return HTMLResponse(html)


@app.post("/api/creds")
async def save_creds(body: dict):
    with open(CREDS_PATH, "w") as f:
        json.dump(body, f)
    return {"ok": True}

@app.post("/api/clone")
async def clone(
    file: UploadFile,
    token: str = Form(...),
    cookies: str = Form(""),
    text: str = Form("This is a sample text. You can edit it manually or generate it using AI."),
    model: str = Form("qwen3.5-omni-flash"),
):
    # Build cookie dict
    cookie_dict = parse_cookies(cookies)
    cookie_dict["token"] = token

    # Read file
    file_bytes = await file.read()
    filesize = len(file_bytes)
    filename = file.filename or "audio.mp3"

    # 1. STS
    sts_resp = requests.post(
        f"{BASE_URL}{API_PREFIX}/files/getstsToken",
        json={"filename": filename, "filesize": filesize, "filetype": "audio"},
        headers={**build_headers(token, cookies), "content-type": "application/json", "accept": "application/json"},
        cookies=cookie_dict,
    )
    if not sts_resp.ok:
        raise HTTPException(400, f"STS failed: {sts_resp.text[:200]}")
    sts = sts_resp.json().get("data")
    if not sts:
        raise HTTPException(400, f"STS failed: {sts_resp.json()}")

    # 2. Upload to OSS
    auth = oss2.StsAuth(sts["access_key_id"], sts["access_key_secret"], sts["security_token"])
    bucket = oss2.Bucket(auth, sts["endpoint"], sts["bucketname"], connect_timeout=120)
    bucket.put_object(sts["file_path"], file_bytes)

    # 3. Clone
    user_id = get_user_id(token)
    clone_headers = build_headers(token, cookies, {"accept": "text/event-stream", "content-type": "application/json"})
    r = requests.post(
        f"{BASE_URL}{API_PREFIX}/voice/clone_stream?user_id={user_id}",
        json={"upload_type": "upload", "voice_sample_text": text, "voice_url": sts["file_url"], "model": model},
        headers=clone_headers,
        cookies=cookie_dict,
        stream=True,
    )
    if not r.ok:
        raise HTTPException(400, f"Clone failed: {r.text[:200]}")

    audio_url = None
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            if chunk.get("choices"):
                for choice in chunk["choices"]:
                    audio = choice.get("delta", {}).get("audio", {})
                    if audio.get("url"):
                        audio_url = audio["url"]
            if chunk.get("error"):
                return JSONResponse({"error": chunk["error"].get("details", "Unknown error")}, status=400)
        except json.JSONDecodeError:
            pass

    if audio_url:
        save_creds({"token": token, "cookies": cookies})
        return {"audio_url": audio_url}
    return JSONResponse({"error": "No audio URL in response"}, status=500)


if __name__ == "__main__":
    uvicorn.run("webui:app", host="0.0.0.0", port=8008, reload=True)
