# Qwen Voice Clone

通义千问语音克隆工具 — 从 [omni.qwen.ai/voice-clone](https://omni.qwen.ai/voice-clone) 逆向的语音克隆接口。

提供 **WebUI** 和 **CLI** 两种使用方式。

上传一段音频（10-60 秒），即可生成用该声音朗读任意文本的语音。

## 工作原理

1. **获取 STS Token** — `POST /api/v2/omni/files/getstsToken`，获取阿里云 OSS 临时上传凭证
2. **上传音频** — 通过 `oss2` SDK 上传到阿里云 OSS
3. **语音克隆** — `POST /api/v2/omni/voice/clone_stream`，SSE 流式返回克隆音频 URL

## 前置条件

- Python 3.8+
- 安装依赖：`pip install requests oss2`
- 从浏览器获取认证信息（见下方）

## 获取认证信息

1. 打开 [omni.qwen.ai/voice-clone](https://omni.qwen.ai/voice-clone) 并登录
2. 打开浏览器 DevTools（F12）
3. **获取 Token**: `Application → Local Storage → token` 的值
4. **获取 Cookie**: `Application → Cookies → omni.qwen.ai` 的所有 cookie（可复制任意一条后拼接成 `key=value; key=value` 格式）

## 使用方法

```bash
export QWEN_TOKEN="eyJhbGciOiJIUzI1NiIs..."
export QWEN_COOKIES="acw_tc=...; cna=...; aui=...; ..."

python3 qwen_voice_clone.py /path/to/audio.mp3
```

自定义文本和模型：

```bash
python3 qwen_voice_clone.py sample.mp3 \
  --text "你好，我是你的AI助手，今天天气不错。" \
  --model qwen3.5-omni-plus
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `audio_file` | 音频文件路径（10-60 秒，mp3/wav） | 必填 |
| `--text` | 克隆声音朗读的文本 | `This is a sample text...` |
| `--model` | 模型选择 | `qwen3.5-omni-flash` |

可选模型：`qwen3.5-omni-flash`、`qwen3.5-omni-plus`

## WebUI 模式

图形界面，无需配置环境变量：

```bash
pip install fastapi uvicorn python-multipart jinja2 oss2 requests
python3 webui.py
```

打开 http://localhost:8008

在网页中填入 Token 和 Cookies、上传音频、输入文本即可克隆。

## 输出

成功后克隆音频保存为 WAV 文件，URL 会打印在终端。

## 注意事项

- 认证信息（token/cookie）有过期时间，过期后需要重新从浏览器获取
- `token` cookie 是 HttpOnly 的，无法通过 `document.cookie` 读取，需从 `localStorage.token` 获取
- 请求头必须包含 `source: web`、`version: 0.0.5`、`timezone`，否则服务端返回 `Verification failed`

## License

MIT
