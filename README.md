# Claude Code + Langfuse: Session Observability Template

> Forked from [doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template) by [doneyli](https://github.com/doneyli). Read the original blog post: [I Built My Own Observability for Claude Code](https://doneyli.substack.com/p/i-built-my-own-observability-for).

Self-hosted Langfuse for capturing every Claude Code conversation — prompts, responses, tool calls, and session grouping. Optionally export traces to **Grafana Cloud** (Tempo) via OTLP and container logs to **Grafana Cloud** (Loki) via Alloy.

This template provides a complete, production-ready setup for observing your Claude Code sessions. Everything runs locally in Docker, with automatic session tracking and incremental state management. Traces can be sent to Langfuse, Grafana Cloud, or both simultaneously.

## Prerequisites

- Docker and Docker Compose
- Python 3.11 or higher
- Claude Code CLI (desktop or terminal)
- 4-6GB available RAM
- 2-5GB available disk space

## After a Restart

Once setup is complete, the only thing you need to do after rebooting your machine is start Docker and the containers:

1. **Start the Docker daemon**
   ```bash
   open -a Docker
   ```

2. **Start the containers**
   ```bash
   cd personal-llm-o11y
   docker compose up -d

   # If using Grafana Cloud log collection:
   docker compose --profile logs up -d
   ```

Wait 30-60 seconds for all services to initialize. The hook, env vars, and credentials persist across restarts — no reconfiguration needed.

If you're only using Grafana Cloud (not local Langfuse), you can skip this step entirely since there are no local services to start.

## Quick Start

Follow these steps to get Langfuse observability running in under 5 minutes:

1. **Clone the repository**
   ```bash
   git clone git@github.com:stevendungan/personal-llm-o11y.git
   cd personal-llm-o11y
   ```

   **Optional: Verify prerequisites**
   ```bash
   ./scripts/validate-setup.sh
   ```

2. **Generate credentials**
   ```bash
   cp .env.example .env
   ./scripts/generate-env.sh
   ```
   This will generate secure random credentials and prompt for your email/name.

3. **Start Langfuse**
   ```bash
   docker compose up -d
   ```
   Wait 30-60 seconds for all services to initialize.

4. **Install the hook**
   ```bash
   ./scripts/install-hook.sh
   ```
   This installs the Python package and configures Claude Code to send traces to Langfuse.

5. **Verify the setup**
   - Open http://localhost:3050 in your browser
   - Log in with the credentials from your `.env` file
   - Start a Claude Code conversation
   - Watch traces appear in Langfuse in real-time

   **Optional: Run full validation**
   ```bash
   ./scripts/validate-setup.sh --post
   ```

## What Gets Captured

| Item | Description |
|------|-------------|
| User prompts | Full text of every user message |
| Assistant responses | Complete assistant replies, including reasoning |
| Tool calls | Name, input parameters, and output for every tool invocation |
| Session grouping | All turns in a Claude Code session grouped together |
| Model info | Model name and version used for each response |
| Timing | Duration of each turn and tool call |
| Project context | Project name extracted from workspace path |

## Analyze Your Traces

Once you have traces flowing, run the built-in analyzer to find patterns in how Claude Code uses tools, how session length affects productivity, and whether your prompting habits pay off.

**Quick start (self-hosted, ClickHouse direct):**
```bash
./scripts/analyze-traces.sh
```

**SDK / REST API (works with Cloud too):**
```bash
pip install langfuse
export LANGFUSE_PUBLIC_KEY=$(docker exec langfuse-web printenv LANGFUSE_INIT_PROJECT_PUBLIC_KEY)
export LANGFUSE_SECRET_KEY=$(docker exec langfuse-web printenv LANGFUSE_INIT_PROJECT_SECRET_KEY)
python3 scripts/analyze-traces-sdk.py
```

Both scripts produce five analyses: tool usage distribution, session turn distribution, productivity by session length, and read-before-edit patterns. Add `--json` for machine-readable output or `--tag <project>` to filter by project.

See [docs/trace-analysis.md](docs/trace-analysis.md) for the full methodology, ClickHouse schema reference, and a query cookbook for writing your own analytics.

## How It Works

The Langfuse hook runs as a Claude Code **Stop hook** — it executes after each assistant response completes.

**Architecture:**

```
┌─────────────┐
│ Claude Code │
│  (Desktop)  │
└──────┬──────┘
       │
       │ Writes transcript after each turn
       ▼
┌─────────────────────┐
│ transcript.jsonl    │
│ ~/.claude/projects/ │
└──────┬──────────────┘
       │
       │ Stop hook triggers
       ▼
┌──────────────────────┐
│ langfuse_hook.py     │
│ - Parses transcript  │
│ - Tracks state       │
│ - Groups by session  │
│ - Multi-backend      │
└──────┬──────┬────────┘
       │      │
       │      │ OTLP/HTTP (optional)
       │      ▼
       │  ┌──────────────────────┐
       │  │ Grafana Cloud        │
       │  │ (Tempo via OTLP)     │
       │  └──────────────────────┘
       │
       │ HTTP POST
       ▼
┌──────────────────┐     ┌──────────────────────┐
│ Langfuse API     │     │ Grafana Alloy        │
│ (localhost:3050) │     │ (Docker sidecar)     │
└──────┬───────────┘     └──────┬───────────────┘
       │                        │ Container logs
       ▼                        ▼
┌──────────────────────────┐  ┌──────────────────────┐
│ PostgreSQL + ClickHouse  │  │ Grafana Cloud        │
│ (traces, analytics)      │  │ (Loki via OTLP)      │
└──────────────────────────┘  └──────────────────────┘
```

**Key Features:**

- **Incremental state tracking**: Only processes new messages since last run
- **Session grouping**: All turns in a conversation are linked by session ID
- **Tool call tracking**: Each tool invocation is captured as a span with input/output
- **Grafana Cloud traces**: Optionally send traces to Grafana Cloud Tempo via OTLP
- **Grafana Cloud logs**: Optionally ship Docker container logs to Grafana Cloud Loki via Alloy
- **Dual-backend support**: Send to Langfuse, Grafana Cloud, or both — each backend is independently fenced
- **Graceful failure**: Errors are logged but don't interrupt Claude Code
- **Opt-in by default**: Only runs when `TRACE_TO_LANGFUSE=true` and/or `TRACE_TO_GRAFANA=true`

## Configuration

### Global vs Per-Project

The installation script sets up **global tracing** by default (all Claude Code sessions are captured).

To opt out for a specific project:

1. Create `.claude/settings.local.json` in your project root
2. Add the opt-out configuration:
   ```json
   {
     "env": {
       "TRACE_TO_LANGFUSE": "false"
     }
   }
   ```

See `settings-examples/project-opt-out.json` for a complete example.

### Environment Variables

All configuration is managed through environment variables in `~/.claude/settings.json`:

**Langfuse (local):**

- `TRACE_TO_LANGFUSE`: Enable/disable Langfuse tracing (`true` or `false`)
- `LANGFUSE_PUBLIC_KEY`: Project public key (auto-generated)
- `LANGFUSE_SECRET_KEY`: Project secret key (auto-generated)
- `LANGFUSE_HOST`: Langfuse URL (default: `http://localhost:3050`)
- `CC_LANGFUSE_DEBUG`: Enable debug logging (`true` or `false`)

**Grafana Cloud (optional):**

- `TRACE_TO_GRAFANA`: Enable/disable Grafana Cloud export (`true` or `false`)
- `GRAFANA_OTLP_ENDPOINT`: OTLP gateway URL (e.g. `https://otlp-gateway-prod-us-central-0.grafana.net/otlp`)
- `GRAFANA_INSTANCE_ID`: Numeric instance ID (used as basic auth username)
- `GRAFANA_WRITE_TOKEN`: API token with `traces:write` scope
- `GRAFANA_READ_TOKEN`: API token with `traces:read` scope (for querying Tempo)

**Grafana Cloud Logs (optional, Docker Compose only):**

- `GRAFANA_OTLP_ENDPOINT`: OTLP gateway URL (e.g. `https://otlp-gateway-prod-us-east-0.grafana.net/otlp`)
- `GRAFANA_OTLP_INSTANCE_ID`: OTLP instance ID (used as basic auth username)
- `GRAFANA_OTLP_TOKEN`: API token with `logs:write` scope

Both trace backends can be enabled simultaneously. Each is independently health-checked and fenced — if one is unavailable, the other continues working.

### Grafana Cloud Setup

To export traces to Grafana Cloud (Tempo) in addition to or instead of local Langfuse:

1. **Get your OTLP credentials** from the Grafana Cloud portal:
   - Log in at [grafana.com](https://grafana.com) and navigate to your stack
   - Go to **Connections > OpenTelemetry** (or the Tempo section)
   - Copy the **OTLP endpoint** and **Instance ID**
   - Generate an **API token** with `traces:write` scope (write policy)
   - Optionally generate an **API token** with `traces:read` scope (read policy) for querying traces

2. **Add the env vars** to `~/.claude/settings.json`:
   ```json
   {
     "env": {
       "TRACE_TO_GRAFANA": "true",
       "GRAFANA_OTLP_ENDPOINT": "https://otlp-gateway-prod-us-central-0.grafana.net/otlp",
       "GRAFANA_INSTANCE_ID": "123456",
       "GRAFANA_WRITE_TOKEN": "glc_eyJ...",
       "GRAFANA_READ_TOKEN": "glc_eyJ..."
     }
   }
   ```

3. **Install Python dependencies** (included automatically if you ran `install-hook.sh`):
   ```bash
   ~/.claude/hooks/venv/bin/pip install -r requirements.txt
   ```

4. **Verify traces** in Grafana Cloud:
   - Open your Grafana Cloud instance
   - Go to **Drilldown > Traces** in the main menu
   - The default filter attribute is `resource.service.name` — select **`claude-code-hook`**
   - Use the Rate, Errors, and Duration (RED) metric tabs for an overview
   - Drill into individual traces to see the span tree: root span "Turn N" with children "Claude Response" and "Tool: X"

### Grafana Cloud Logs Setup

To ship Docker container logs (Langfuse, PostgreSQL, ClickHouse, Redis, MinIO) to Grafana Cloud Loki:

1. **Get your OTLP credentials** from the Grafana Cloud portal:
   - Log in at [grafana.com](https://grafana.com) and navigate to your stack
   - Go to **Connections > OpenTelemetry**
   - Copy the **OTLP endpoint** and **Instance ID**
   - Generate an **API token** with `logs:write` scope (can reuse your traces token if it has both scopes)

2. **Add the env vars** to your `.env` file:
   ```
   GRAFANA_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-0.grafana.net/otlp
   GRAFANA_OTLP_INSTANCE_ID=123456
   GRAFANA_OTLP_TOKEN=glc_eyJ...
   ```

3. **Start services with the `logs` profile**:
   ```bash
   docker compose --profile logs up -d
   ```
   This starts all the normal services plus a [Grafana Alloy](https://grafana.com/docs/alloy/) sidecar that collects container logs and ships them to Loki.

4. **Verify logs** in Grafana Cloud:
   - Open your Grafana Cloud instance
   - Go to **Drilldown > Logs** in the main menu
   - Search for the **`personal-llm-o11y`** service in the service list
   - Click **Show logs** to view entries, then use **(+) Add label** to filter by `container` (e.g. `langfuse-web-1`)

If you're already running, restart with the profile:
```bash
docker compose --profile logs up -d
```

### Customization

**Change the Langfuse port:**
Edit `docker-compose.yml` and update the `langfuse-web` port mapping:
```yaml
ports:
  - 3051:3000  # Change 3050 to 3051
```

Also update `LANGFUSE_HOST` in your `.env.example` and regenerate credentials.

**Add custom tags:**
Edit `hooks/langfuse_hook.py` and modify the `tags` list in the `create_trace()` function:
```python
tags = ["claude-code", "my-custom-tag"]
```

**Adjust log retention:**
By default, logs are kept indefinitely. To clean up old logs:
```bash
# Clear hook logs older than 7 days
find ~/.claude/state -name "langfuse_hook.log" -mtime +7 -delete
```

## Operations

### Common Commands

**View logs:**
```bash
# Langfuse web logs
docker compose logs -f langfuse-web

# All services
docker compose logs -f

# Hook execution logs
tail -f ~/.claude/state/langfuse_hook.log
```

**Restart services:**
```bash
docker compose restart
```

**Stop services:**
```bash
docker compose down
```

**Stop and remove all data:**
```bash
docker compose down -v
```

**Update Langfuse to latest version:**
```bash
docker compose pull
docker compose up -d
```

**Check service health:**
```bash
docker compose ps
```

**Access the database directly:**
```bash
# PostgreSQL
docker compose exec postgres psql -U postgres

# ClickHouse
docker compose exec clickhouse clickhouse-client
```

### Debugging

**Enable debug logging:**
Edit `~/.claude/settings.json` and add:
```json
{
  "env": {
    "CC_LANGFUSE_DEBUG": "true"
  }
}
```

Then check `~/.claude/state/langfuse_hook.log` for detailed execution logs.

**Verify the hook is running:**
```bash
# Check if hook is registered
cat ~/.claude/settings.json | grep -A 5 "Stop"

# Check hook logs
tail -20 ~/.claude/state/langfuse_hook.log
```

**Test the hook manually:**
```bash
TRACE_TO_LANGFUSE=true \
LANGFUSE_PUBLIC_KEY=pk-lf-local-claude-code \
LANGFUSE_SECRET_KEY=your-secret-key \
LANGFUSE_HOST=http://localhost:3050 \
python3 ~/.claude/hooks/langfuse_hook.py
```

## Troubleshooting

### Docker not running

**Symptom:** `docker compose up -d` fails with connection error

**Solution:**
```bash
# macOS
open -a Docker

# Linux
sudo systemctl start docker
```

### Python version too old

**Symptom:** `install-hook.sh` reports Python 3.11+ required

**Solution:**
```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo apt install python3.12

# Or use pyenv
pyenv install 3.12
pyenv global 3.12
```

### Port already in use

**Symptom:** Docker fails to start because port 3050 is in use

**Solution:**
```bash
# Find what's using the port
lsof -i :3050

# Either stop that service, or change the Langfuse port in docker-compose.yml
```

### Traces not appearing

**Symptom:** Langfuse UI shows no traces after conversations

**Check:**
1. Is `TRACE_TO_LANGFUSE=true` in `~/.claude/settings.json`?
2. Are the API keys correct?
3. Check hook logs: `tail -f ~/.claude/state/langfuse_hook.log`
4. Verify Docker services are running: `docker compose ps`
5. Test Langfuse API: `curl http://localhost:3050/api/public/health`

### Hook runs slowly

**Symptom:** Hook execution takes >3 minutes (warning in logs)

**Solution:**
- Large transcripts can slow processing
- Consider archiving old sessions: move `.jsonl` files from `~/.claude/projects/*/` to a backup location
- Check Docker resource limits (increase CPU/memory allocation)

### Database disk space

**Symptom:** Services crash due to disk space

**Solution:**
```bash
# Check volume sizes
docker system df -v

# Remove old traces (via Langfuse UI or API)
# Or reset everything:
docker compose down -v
docker compose up -d
```

## Resource Usage

**Typical usage:**
- **RAM:** 4-6GB total (PostgreSQL: 500MB, ClickHouse: 2GB, Redis: 100MB, MinIO: 200MB, Langfuse: 1-2GB)
- **Disk:** 2-5GB (depends on trace volume and retention)
- **CPU:** Minimal (spikes during trace ingestion)

**Scaling considerations:**
- For heavy usage (>1000 traces/day), consider increasing PostgreSQL and ClickHouse memory limits
- ClickHouse benefits from SSD storage for analytics queries
- Redis is used for caching and can be scaled vertically if needed

## Architecture Details

### Services

- **langfuse-web**: Main web UI and API (port 3050)
- **langfuse-worker**: Background job processor (handles async tasks)
- **postgres**: Primary data store (traces, users, projects)
- **clickhouse**: Analytics database (aggregations, dashboards)
- **redis**: Cache and job queue
- **minio**: S3-compatible object storage (media uploads, exports)
- **alloy** *(optional, `--profile logs`)*: Collects Docker container logs and ships to Grafana Cloud Loki

### Data Flow

1. Claude Code writes each message to `~/.claude/projects/<project>/<session>.jsonl`
2. After assistant response, Stop hook triggers
3. Hook reads new messages since last execution (tracked in state file)
4. Hook groups messages into turns (user → assistant → tools → assistant)
5. Each turn is dispatched to all enabled backends:
   - **Langfuse**: Creates traces with nested spans via the Langfuse SDK
   - **Grafana Cloud**: Creates OTEL spans exported via OTLP/HTTP to Tempo
6. If no backends are reachable, traces are queued locally and drained on the next successful connection

### Security

- All Docker services run on `localhost` (not exposed to network)
- Credentials are generated randomly on first setup
- `.env` file is git-ignored (never commit credentials)
- Langfuse is fully self-hosted with no external telemetry
- Grafana Cloud export (if enabled) sends traces to your Grafana Cloud instance over HTTPS with Basic auth — no data is sent externally unless you explicitly enable `TRACE_TO_GRAFANA=true`

## Customization Ideas

**Add user ID tracking:**
Edit the hook to include your name or machine ID in metadata:
```python
metadata={
    "user": os.environ.get("USER"),
    "hostname": os.uname().nodename,
    "source": "claude-code",
}
```

**Filter sensitive content:**
Add a sanitization function to scrub API keys or passwords before sending:
```python
def sanitize(text: str) -> str:
    # Remove common secret patterns
    text = re.sub(r'sk-[a-zA-Z0-9]{32,}', 'SK-REDACTED', text)
    text = re.sub(r'Bearer [a-zA-Z0-9._-]+', 'Bearer REDACTED', text)
    return text
```

**Add cost tracking:**
Estimate token usage based on text length and add to metadata:
```python
import tiktoken

def estimate_tokens(text: str, model: str = "claude") -> int:
    # Rough estimate: ~4 chars per token
    return len(text) // 4

metadata={
    "estimated_tokens": estimate_tokens(user_text + final_output),
}
```

## Roadmap

| Priority | Item |
|----------|------|
| **High** | Clean sensitive data before writing to Tempo/Loki |
| Medium | Send telemetry through Alloy collector instead of direct OTLP export |
| Medium | Create metrics from traces |
| Medium | Track dollar cost of Claude Code calls |

### LLM O11y Roadmap Discovery

Things we want to be able to see and analyze with this observability setup:

- See duration from when input is entered to when output returns
- See subactivity and trace spans and/or logs
- Analyze what % of tokens goes to what tasks
- Analyze what % of spend goes to what tasks
- Analyze expensive calls
- Analyze repeated asks that can be made into skills or subagents
- Analyze where context can be reduced

## Disclaimer

This is a **personal project** and is not affiliated with, sponsored by, or endorsed by ClickHouse, Inc., Anthropic, or any other organization.

This software is provided "as-is" without warranty of any kind. Use at your own risk. The author makes no guarantees about reliability, security, or fitness for any particular purpose.

**No support commitment.** While issues and PRs are welcome, there is no guarantee of response time or resolution. This is a side project maintained in spare time.

By using this template, you accept full responsibility for:
- Securing your deployment
- Backing up your data
- Reviewing the code for your specific security requirements
- Any costs, damages, or issues arising from its use

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly (especially the hook script)
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Credits

- [doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template) - Original project by [doneyli](https://github.com/doneyli)
- [Langfuse](https://langfuse.com/) - Open-source LLM observability
- [Grafana Cloud](https://grafana.com/products/cloud/) - Observability platform (Tempo for traces, Loki for logs)
- [Grafana Alloy](https://grafana.com/docs/alloy/) - OpenTelemetry-native observability collector
- [OpenTelemetry](https://opentelemetry.io/) - Vendor-neutral observability framework
- [Anthropic Claude](https://claude.ai/) - AI assistant platform

---

**Happy tracing!** If you find this useful, consider starring the repository.
