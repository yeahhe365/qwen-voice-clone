#!/usr/bin/env python3
"""
Qwen Voice Clone - CLI Tool
Uses the internal API of omni.qwen.ai to clone voices.

Flow:
1. Get STS token (OSS credentials)
2. Upload audio file to Ali OSS
3. Call /voice/clone_stream (SSE) to create voice clone

Usage:
    # Get token from browser localStorage.token and cookies from DevTools
    export QWEN_TOKEN="eyJ..."
    export QWEN_COOKIES="acw_tc=...; cna=...; aui=...; ..."
    python3 qwen_voice_clone.py <audio_file>
"""

import json
import sys
import os
import datetime
import requests

BASE_URL = "https://omni.qwen.ai"
API_PREFIX = "/api/v2/omni"

QWEN_TOKEN = os.environ.get("QWEN_TOKEN", "")
COOKIES_STR = os.environ.get("QWEN_COOKIES", "")


def get_cookies():
    cookies = {}
    if COOKIES_STR:
        for item in COOKIES_STR.split("; "):
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k] = v
    if QWEN_TOKEN:
        cookies["token"] = QWEN_TOKEN
    return cookies


def get_user_id():
    import base64
    token = get_cookies().get("token", "")
    parts = token.split(".")
    if len(parts) >= 2:
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("id")
    return None


def base_headers():
    """Headers that match the browser's axios interceptor (cf function)."""
    return {
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "referer": f"{BASE_URL}/voice-clone",
        "origin": BASE_URL,
        "source": "web",
        "version": "0.0.5",
        "timezone": datetime.datetime.now().astimezone().strftime("%a %b %d %Y %H:%M:%S GMT%z (%Z)"),
    }


# ---- Step 1: Get STS Token ----
def get_sts_token(filename, filesize, filetype="audio"):
    url = f"{BASE_URL}{API_PREFIX}/files/getstsToken"
    headers = {**base_headers(), "content-type": "application/json", "accept": "application/json, text/plain, */*"}
    r = requests.post(url, json={"filename": filename, "filesize": filesize, "filetype": filetype},
                      headers=headers, cookies=get_cookies())
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise Exception(f"getstsToken failed: {data}")
    return data["data"]


# ---- Step 2: Upload to Ali OSS ----
def upload_to_oss(file_path, sts_data):
    import oss2
    auth = oss2.StsAuth(
        sts_data["access_key_id"],
        sts_data["access_key_secret"],
        sts_data["security_token"],
    )
    bucket = oss2.Bucket(auth, sts_data["endpoint"], sts_data["bucketname"], connect_timeout=120)
    file_size = os.path.getsize(file_path)
    object_key = sts_data["file_path"]
    print(f"  Uploading {file_size} bytes to OSS: {object_key}")
    with open(file_path, "rb") as f:
        bucket.put_object(object_key, f)
    print(f"  Upload complete.")
    # Use the signed file_url from STS — includes auth signature
    return sts_data["file_id"], sts_data["file_url"]


# ---- Step 3: Clone voice (SSE stream) ----
def clone_voice(voice_url, voice_sample_text, model="qwen3.5-omni-flash"):
    user_id = get_user_id()
    url = f"{BASE_URL}{API_PREFIX}/voice/clone_stream?user_id={user_id}"
    headers = {**base_headers(), "accept": "text/event-stream", "content-type": "application/json"}

    payload = {
        "upload_type": "upload",
        "voice_sample_text": voice_sample_text,
        "voice_url": voice_url,
        "model": model,
    }

    print(f"  Clone request to: {url}")
    result = {}
    r = requests.post(url, json=payload, headers=headers, cookies=get_cookies(), stream=True)
    r.raise_for_status()

    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        print(f"  {line}")
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                if chunk.get("choices"):
                    for choice in chunk["choices"]:
                        audio = choice.get("delta", {}).get("audio", {})
                        if audio.get("url"):
                            result["audio_url"] = audio["url"]
                        if choice.get("delta", {}).get("status") == "finished":
                            result["finished"] = True
                if chunk.get("error"):
                    result["error"] = chunk["error"].get("details", chunk["error"].get("code", "Unknown"))
                if chunk.get("voice_id"):
                    result["voice_id"] = chunk["voice_id"]
                result.setdefault("all_chunks", []).append(chunk)
            except json.JSONDecodeError:
                pass

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Qwen Voice Clone CLI")
    parser.add_argument("audio_file", help="Path to audio file (10-60 seconds, mp3/wav/...)")
    parser.add_argument("--text", default="This is a sample text. You can edit it manually or generate it using AI.",
                        help="Preview text for voice clone")
    parser.add_argument("--model", default="qwen3.5-omni-flash",
                        choices=["qwen3.5-omni-flash", "qwen3.5-omni-plus"])
    args = parser.parse_args()

    if not QWEN_TOKEN:
        print("Error: Set QWEN_TOKEN environment variable.")
        print("  export QWEN_TOKEN='eyJhbGci...'  # from localStorage.token in browser")
        sys.exit(1)

    audio_path = os.path.abspath(args.audio_file)
    if not os.path.exists(audio_path):
        print(f"Error: File not found: {audio_path}")
        sys.exit(1)

    filename = os.path.basename(audio_path)
    filesize = os.path.getsize(audio_path)

    print(f"[1/3] Getting STS token for: {filename} ({filesize} bytes)")
    sts = get_sts_token(filename, filesize)
    print(f"  Bucket: {sts['bucketname']}, Region: {sts['region']}")

    print(f"\n[2/3] Uploading to Ali OSS...")
    file_id, voice_url = upload_to_oss(audio_path, sts)

    print(f"\n[3/3] Cloning voice...")
    result = clone_voice(voice_url=voice_url, voice_sample_text=args.text, model=args.model)

    print(f"\n{'='*60}")
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
        sys.exit(1)
    elif result.get("audio_url"):
        print(f"  SUCCESS!")
        print(f"  Audio URL: {result['audio_url']}")
    else:
        print(f"  Result: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
