# Genesys Voice QA Agent

A real-time call quality monitoring agent that connects to **Genesys Cloud** via the **Notifications API WebSocket**, streams live transcripts, and uses an **LLM** (Azure OpenAI or a swappable in-house AI gateway) to detect **headset issues** and **background noise** — firing alerts the moment problems are detected during a call.

---

## How it works

```
Genesys Call
    │
    ▼
Native Voice Transcription (built-in, no extra streaming fee)
    │
    ▼
Notifications API WebSocket  ←── your service connects here
    │  topic: v2.conversations.{id}.transcription
    ▼
GenesysNotificationsListener
    ├── buffers utterances per conversation
    ├── every N utterances → LLM quality analysis
    ├── on call disconnect  → final analysis
    └── problem detected    → NotificationSink (stdout / webhook)
```

**Cost:** The Notifications API is included in all Genesys Cloud CX licenses — no per-minute AudioHook or Transcription Connector fees.

---

## Project structure

```
src/genesys_voice_qa/
  __main__.py                   CLI entry point
  genesys_auth.py               OAuth2 client-credentials + token refresh
  genesys_listener.py           WebSocket listener, utterance buffer, analysis trigger
  analyzer.py                   LLM-based quality analysis (headset / background noise)
  models.py                     Pydantic models (CallQualityAnalysis, QualityIssue)
  notifications.py              NotificationSink — logging or webhook
  bootstrap.py                  Env-driven LLM client factory
  genesys.py                    Genesys context helpers
  llm/
    completion_client.py        Abstract CompletionClient (swap without touching analyzers)
    azure_openai_completion.py  Azure OpenAI implementation
    in_house_gateway_completion.py  In-house AI gateway stub — replace this file to migrate
```

---

## Prerequisites

### Genesys Cloud

1. **Enable Native Voice Transcription**
   `Admin → Telephony → Voice Transcription` — enable for your queues/flows.

2. **Create an OAuth Client**
   `Admin → OAuth → Add Client`
   - Grant type: **Client Credentials**
   - Scopes: `notifications`, `conversations:readonly`
   - Copy the **Client ID** and **Client Secret**.

3. **Enable transcription in Architect flows**
   Open your call flows and ensure transcription is turned on in the flow settings.

### Python

- Python 3.10+
- Dependencies are managed via `pyproject.toml`

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/udaygreddy/genesys-voice-qa-agent.git
cd genesys-voice-qa-agent

# 2. Create a virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Configure environment variables
cp .env.example .env
# Edit .env with your credentials (see Configuration below)
```

---

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```dotenv
# Genesys Cloud
GENESYS_REGION=us-east-1          # see genesys_auth.py for all supported regions
GENESYS_CLIENT_ID=...
GENESYS_CLIENT_SECRET=...

# LLM backend: "azure" (default) or "gateway"
LLM_BACKEND=azure

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# In-house gateway (set LLM_BACKEND=gateway to use)
# AI_GATEWAY_BASE_URL=https://your-ai-gateway.internal
# AI_GATEWAY_API_KEY=...
# AI_GATEWAY_MODEL=gpt-4o

# Notifications — leave blank to log to stdout
NOTIFICATION_WEBHOOK_URL=

# Tuning
ANALYSIS_UTTERANCE_WINDOW=20      # trigger LLM analysis every N utterances mid-call
LOG_LEVEL=INFO
```

### Supported Genesys regions

| `GENESYS_REGION` | Domain |
|---|---|
| `us-east-1` | mypurecloud.com |
| `us-west-2` | usw2.pure.cloud |
| `eu-west-1` | mypurecloud.ie |
| `eu-west-2` | euw2.pure.cloud |
| `ap-southeast-2` | mypurecloud.com.au |
| `ap-northeast-1` | mypurecloud.jp |
| `ca-central-1` | cac1.pure.cloud |

---

## Running

```bash
# Activate venv (if not already active)
source .venv/bin/activate

# Run
genesys-voice-qa

# or
python -m genesys_voice_qa
```

The agent connects to Genesys, subscribes to all live conversation transcription topics, and runs indefinitely — reconnecting automatically on WebSocket drops.

---

## Debugging (VS Code)

Open the project in VS Code. Two debug configurations are provided in `.vscode/launch.json`:

| Configuration | Description |
|---|---|
| **Genesys Voice QA Agent** | Default — Azure OpenAI backend, `LOG_LEVEL=DEBUG` |
| **Genesys Voice QA Agent (gateway backend)** | Same but with `LLM_BACKEND=gateway` |

Press **F5** to start. Breakpoints in any source file work normally. The `.env` file is loaded automatically.

---

## Swapping the LLM backend

The `CompletionClient` abstract class decouples all analyzers from any specific LLM provider.

| To use | Set `LLM_BACKEND=` | Reads from |
|---|---|---|
| Azure OpenAI | `azure` (default) | `AZURE_OPENAI_*` vars |
| In-house gateway | `gateway` | `AI_GATEWAY_*` vars |

To migrate to your internal AI gateway:
1. Set `LLM_BACKEND=gateway` and `AI_GATEWAY_BASE_URL=...` in `.env`.
2. If the gateway payload differs from the OpenAI `/v1/chat/completions` shape, edit `src/genesys_voice_qa/llm/in_house_gateway_completion.py` — that is the **only file** you need to touch.

---

## Notifications

| Sink | When | Config |
|---|---|---|
| `LoggingNotificationSink` | Default (no webhook set) | Prints to stdout |
| `WebhookNotificationSink` | `NOTIFICATION_WEBHOOK_URL` is set | HTTP POST JSON payload |

The webhook payload shape:
```json
{
  "title": "Call quality issue: <conversationId>",
  "body": "- [high] headset: Agent audio cutting out repeatedly\n  · 'Can you hear me now?'",
  "metadata": {
    "conversation_id": "...",
    "confidence": 0.92,
    "issues": [
      {
        "category": "headset",
        "severity": "high",
        "summary": "Agent audio cutting out repeatedly",
        "evidence": ["Can you hear me now?", "You're breaking up"]
      }
    ]
  }
}
```

Point `NOTIFICATION_WEBHOOK_URL` at a Teams incoming webhook, Slack webhook, or your own API endpoint.

---

## License

MIT
