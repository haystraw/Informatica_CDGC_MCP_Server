# Official IDMC MCP Server

A proxy MCP server that wraps the official Informatica-hosted MCP services, handling authentication and session management. Includes a companion AI Assistant web UI.

## Architecture

```
Claude / MCP Client
        │
        │  X-IDMC-Token (encrypted)
        ▼
o-idmc-mcp-server  (Cloud Run, port 8000)
  ├── Decrypts token → pod / username / password
  ├── Authenticates with Informatica → session ID + pod_location
  ├── Caches session (SESSION_TIMEOUT_MINUTES)
  └── Proxies calls to official Informatica MCP servers via SSE
        │
        ▼
  Informatica-hosted MCP servers
  (address verification, CDGC search, customer ID, data provisioning, job management)

o-idmc-ai-assistant  (Cloud Run, port 8080)
  └── Web chat UI → calls o-idmc-mcp-server
```

## Services Proxied

| Service | Upstream Path |
|---------|--------------|
| Address Verification | `/mcp-servers/public/dqverifyaddress` |
| CDGC Metadata Search | `/mcp-servers/public/cdgcsearchmetadata` |
| Customer Identification | `/mcp-servers/public/searchcustomer` |
| Data Provisioning | `/mcp-servers/public/dataprovisioning` |
| Job Management | `/mcp-servers/public/jobmanagement` |

---

## Prerequisites

### 1. Install the Google Cloud CLI

**Windows:**
Download and run the installer from:
https://cloud.google.com/sdk/docs/install#windows

Or via PowerShell (winget):
```powershell
winget install Google.CloudSDK
```

**macOS:**
```bash
brew install --cask google-cloud-sdk
```

**Linux:**
```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

### 2. Authenticate with GCP

```bash
gcloud auth login
```

This opens a browser to complete Google sign-in. Use the account that has access to the target GCP project.

Set the active project:
```bash
gcloud config set project gcp-informatica-sales-sc-emea
```

Verify:
```bash
gcloud config list
```

---

## Configuration

### 1. Copy the example env files

```bash
cp .env.example .env
cp ai-assistant/.env.example ai-assistant/.env   # if it exists
```

Edit `.env` and fill in all required values:

| Variable | Description |
|----------|-------------|
| `ENCRYPTION_KEY` | Fernet key — generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ENROLL_PASSWORD` | Password to access the `/enroll` UI |
| `SESSION_TIMEOUT_MINUTES` | Minutes before re-authentication (default: 20) |
| `MCP_URL_PREFIX_MAP` | JSON map of pod → URL prefix overrides (e.g. `{"dmp-us": "a2e-preview-c360"}`) |
| `MCP_URL_PREFIX_DEFAULT` | Prefix for any pod not in the map (default: `a2e-prod`) |
| `MCP_SERVER_URL` | URL of the deployed MCP server (used by the AI assistant) |
| `ANTHROPIC_API_KEY` | Claude API key (Anthropic or Azure AI Foundry) |
| `ANTHROPIC_BASE_URL` | Azure AI Foundry endpoint (omit for direct Anthropic API) |
| `CLAUDE_MODEL` | Claude model ID (default: `claude-opus-4-6`) |
| `GEMINI_API_KEY` | Google Gemini API key (fallback if Claude is unavailable) |
| `GEMINI_MODEL` | Gemini model ID (default: `gemini-2.5-flash`) |

### 2. Create the deploy env files

These are flattened versions of `.env` used by `gcloud run deploy --env-vars-file`.

**mcp-server.env** — MCP server variables only:
```
ENCRYPTION_KEY=...
ENROLL_PASSWORD=...
SESSION_TIMEOUT_MINUTES=20
MCP_URL_PREFIX_MAP={"dmp-us": "a2e-preview-c360"}
MCP_URL_PREFIX_DEFAULT=a2e-prod
ADDRESS_VERIFICATION_URL=https://{url_prefix}-{pod_location}-mcp.{pod}.informaticacloud.com/mcp-servers/public/dqverifyaddress
CDGC_METADATA_SEARCH_URL=https://{url_prefix}-{pod_location}-mcp.{pod}.informaticacloud.com/mcp-servers/public/cdgcsearchmetadata
CUSTOMER_IDENTIFICATION_URL=https://{url_prefix}-{pod_location}-mcp.{pod}.informaticacloud.com/mcp-servers/public/searchcustomer
DATA_PROVISIONING_URL=https://{url_prefix}-{pod_location}-mcp.{pod}.informaticacloud.com/mcp-servers/public/dataprovisioning
JOB_MANAGEMENT_URL=https://{url_prefix}-{pod_location}-mcp.{pod}.informaticacloud.com/mcp-servers/public/jobmanagement
```

**ai-assistant.env** — AI assistant variables only:
```
ENCRYPTION_KEY=...
MCP_SERVER_URL=https://o-idmc-mcp-server-<project-number>.us-central1.run.app
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=...
CLAUDE_MODEL=claude-opus-4-6
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

> **Note:** `mcp-server.env` and `ai-assistant.env` are gitignored. Never commit them.

---

## Deployment

### Deploy the MCP Server

Run from the `official_idmc_mcp_server/` directory:

```bash
gcloud run deploy o-idmc-mcp-server \
  --source . \
  --region us-central1 \
  --project gcp-informatica-sales-sc-emea \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --env-vars-file mcp-server.env
```

Note the deployed URL — it will be:
`https://o-idmc-mcp-server-668103879510.us-central1.run.app`

Update `MCP_SERVER_URL` in `ai-assistant.env` with this URL before deploying the assistant.

### Deploy the AI Assistant

Run from the `official_idmc_mcp_server/ai-assistant/` directory:

```bash
gcloud run deploy o-idmc-ai-assistant \
  --source . \
  --region us-central1 \
  --project gcp-informatica-sales-sc-emea \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --env-vars-file ../ai-assistant.env
```

---

## Enrollment (Getting a Token)

1. Navigate to the MCP server's enroll page:
   `https://o-idmc-mcp-server-668103879510.us-central1.run.app/enroll`

2. Enter the `ENROLL_PASSWORD` from your `.env`

3. Fill in your Informatica credentials:
   - **Pod** — prefix from your IDMC login URL: `https://<pod>.informaticacloud.com`
   - **Username** — your IDMC username
   - **Password** — your IDMC password

4. Check/uncheck the services you want this token to have access to

5. Click **Generate Token** and copy the token

---

## Using the Token

### Claude Code / Claude Desktop

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "idmc-official": {
      "type": "http",
      "url": "https://o-idmc-mcp-server-668103879510.us-central1.run.app/mcp",
      "headers": {
        "X-IDMC-Token": "<your-token>"
      }
    }
  }
}
```

### AI Assistant Web UI

Navigate to:
`https://o-idmc-ai-assistant-668103879510.us-central1.run.app`

Paste your token at the login prompt. Click **Enroll here** to generate one if needed.

### Any other MCP client

- **URL:** `https://o-idmc-mcp-server-668103879510.us-central1.run.app/mcp`
- **Header:** `X-IDMC-Token: <your-token>`  
  or `Authorization: Bearer <your-token>`

---

## Local Development

Install dependencies:
```bash
pip install -r requirements.txt
```

Add `pod`, `username`, and `password` to `.env`, then run:
```bash
# MCP server (port 8000)
uvicorn app:app --port 8000 --reload

# AI assistant (port 8080) — in a separate terminal
cd ai-assistant
MCP_SERVER_URL=http://localhost:8000 uvicorn app:app --port 8080 --reload
```
