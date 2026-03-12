<div align="center">
  <img src="assets/logo.png" width="300" alt="Corbell Logo" />
  <h1>Corbell</h1>
  <p><strong>Multi-repo architecture graph, AI-powered spec generation, and architecture review — for backend teams that ship to production.</strong></p>
  <p>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"/></a>
    <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"/></a>
  </p>
</div>

---

## What problem does this solve?

You're a staff engineer or architect at a company where features touch 5–10 repositories.<br/>
Every quarter your team re-litigates the same architectural decisions: "should we use Kafka or SQS?", "why do we have three different auth patterns?", "who owns the rate-limiting layer?"

The decisions live in Confluence pages nobody reads, Slack messages nobody can find, and the memories of engineers who've since left.

When a new engineer joins—or even when you return to a service you haven't touched in 6 months—you're starting from scratch.

**Corbell gives your team a living knowledge graph of your architecture** — built from the actual code in your repos and your team's past design docs. When you need a new spec, Corbell generates one that respects your established patterns instead of inventing new ones. When you push to Linear, each task carries the exact method signatures, call paths, and cross-service impacts an AI coding agent needs to work autonomously.

---

## How it works

```
Your repos → [graph:build] → Service graph (SQLite)
Your docs  → [docs:scan]   → Design pattern extraction
              ↓
  [spec new --feature "Payment Retry" --prd-file prd.md]
                 →  Generates 3-4 PRD-driven code search queries (LLM or regex)
                 →  Auto-discovers relevant services via embedding similarity
                 →  Injects graph topology + real code snippets
                 →  Applies your team's established design patterns
                 →  Calls Claude / GPT-4o to write the full design doc
                 →  Displays token usage and estimated cost
                 →  specs/payment-retry.md ✓
              ↓
  [spec review]    → Checks claims against graph → .review.md
  [spec decompose] → Parallel task tracks YAML
  [export linear]  → Linear issues with full method/service context
```

No servers. No cloud setup. Runs entirely from your laptop against local repos.

---

## Installation

```bash
pip install corbell

# With LLM support (pick one):
pip install "corbell[anthropic]"    # Claude (recommended)
pip install "corbell[openai]"       # GPT-4o

# With exports:
pip install "corbell[notion,linear]"

# Everything:
pip install "corbell[anthropic,openai,notion,linear]"
```

**Requirements**: Python ≥ 3.11

---

## Quick start (5 minutes)

### 1. Initialize a workspace

```bash
cd ~/my-platform   # wherever your repos live
corbell init
```

Edit `corbell-data/workspace.yaml`:

```yaml
workspace:
  name: my-platform

services:
  - id: payments-service
    repo: ../payments-service
    language: python        # python | javascript | typescript | go | java

  - id: auth-service
    repo: ../auth-service
    language: go

llm:
  provider: anthropic   # or: openai, ollama
  model: claude-sonnet-4-5-20250929
  api_key: ${ANTHROPIC_API_KEY}
```

### 2. Build the knowledge graph

```bash
corbell graph build --methods    # service + dependency graph + call graph, typed signatures, flows
corbell embeddings build         # code chunk index for semantic search
corbell docs scan && corbell docs learn   # extract patterns from existing RFCs/ADRs
```

### 3. Generate a design document

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

# From a PRD file — services are auto-discovered, no --service flag needed
corbell spec new \
  --feature "Payment Retry with Exponential Backoff" \
  --prd-file docs/payment-retry-prd.md

# Spec with full call graph context (bypasses keyword filters for structural map)
corbell spec new --feature "Auth Flow" --prd-file prd.md --full-graph

# Inline PRD
corbell spec new --feature "Rate Limiting" --prd "Tier 1: 100 req/min..."

# Document your existing codebase with no PRD at all
corbell spec new --existing

# Add existing design docs as context (ADRs, Confluence exports, RFCs)
corbell spec new --feature "Auth Token Refresh" --prd-file prd.md \
  --design-doc docs/auth-design-2023.md
```

Token usage and estimated cost are shown after every LLM call. Template mode (no LLM key) generates a structured skeleton with graph context filled in.

### 4. Document architecture constraints

Add a constraints block to any spec and all future specs will respect it:

```markdown
<!-- CORBELL_CONSTRAINTS_START -->
- **Cloud provider**: Only Azure — no AWS services permitted
- **Latency SLO**: p99 < 200ms for all synchronous API calls
- **Security**: All PII encrypted at rest (AES-256) and in transit (TLS 1.2+)
<!-- CORBELL_CONSTRAINTS_END -->
```

`corbell spec review` checks proposed designs against these constraints. The `corbell ui serve` graph browser also surfaces them in a persistent bar at the bottom.

### 5. Review, approve, decompose, export

```bash
corbell spec review specs/payment-retry.md     # → .review.md sidecar
corbell spec approve specs/payment-retry.md

corbell spec decompose specs/payment-retry.md  # → .tasks.yaml

export CORBELL_LINEAR_API_KEY="lin_api_..."
corbell export linear specs/payment-retry.tasks.yaml
```

---

## Architecture graph browser

```bash
corbell ui serve          # opens http://localhost:7433 · Ctrl+C to stop
corbell ui serve --port 8080 --no-browser
```

An interactive local graph view — no cloud, no sign-in, reads from your existing SQLite store:

- **Force-directed graph** — services (sized by method count), data stores, queues, execution flows. Zoom, pan, drag.
- **Detail panel** — click any service to see: language, dependencies, HTTP callers, typed method signatures, execution flows (e.g. `LoginFlow`), git change coupling pairs with strength %.
- **Constraints bar** — all `CORBELL_CONSTRAINTS_START` blocks from your spec files shown as persistent amber pills at the bottom. Click to expand.
- **Sidebar** — filterable service list, stores, queues, flows with search.

---

## CLI Reference

```
graph       Service dependency graph
  build       --methods for call graph + typed signatures + git coupling + flows
  services    List discovered services
  deps        Show service dependencies
  callpath    Find call paths between methods

embeddings  Code embedding index
  build       Index code chunks
  query       Semantic search

docs        Design doc patterns
  scan / learn / patterns

spec        Design spec lifecycle
  new         --feature --prd-file --prd --design-doc --existing --no-llm
  lint        Validate structure (--ci exits 1)
  review      Check spec vs graph → .review.md
  approve / decompose / context

export      notion | linear

ui          Architecture graph browser
  serve       --port (default 7433) --no-browser

mcp         Model Context Protocol server
  serve       stdio transport for Claude Desktop / Cursor

init        Create workspace.yaml
```

## MCP – Model Context Protocol

Corbell exposes its architecture graph, code embeddings, and spec tools via MCP, so external AI platforms (Cursor, Claude Desktop, Antigravity) can query your codebase context directly.

### Available Tools

| Tool | Description |
|---|---|
| `graph_query` | Query service dependencies, methods, and call paths |
| `get_architecture_context` | Auto-discover relevant services for a feature description |
| `code_search` | Semantic search across the code embedding index |
| `list_services` | List all services in the workspace graph |

### Usage

```bash
# Default: stdio transport (for IDE integrations)
corbell mcp serve

# SSE transport (for web-based MCP clients / MCP Inspector)
corbell mcp serve --transport sse --port 8000
```

### IDE Configuration

**Cursor** (`~/.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "corbell": {
      "command": "corbell",
      "args": ["mcp", "serve"]
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "corbell": {
      "command": "corbell",
      "args": ["mcp", "serve"]
    }
  }
}
```

If your IDE overrides the working directory, set the `CORBELL_WORKSPACE` environment variable:

```bash
env CORBELL_WORKSPACE=/path/to/my-platform corbell mcp serve
```


---

## Auto service discovery

When you run `corbell spec new`, Corbell discovers which services are relevant to your PRD **automatically** — without you having to specify `--service`:

1. Generates 3-4 natural-language code search queries from your PRD (using LLM or regex fallback)
2. Encodes them with the same `sentence-transformers/all-MiniLM-L6-v2` model used for indexing
3. Runs similarity search against all indexed code chunks
4. Ranks services by how many of their chunks appear in the top results
5. Selects the top-scoring services and builds context from them

Preview what would be discovered without generating a spec:

```bash
corbell spec context "Add exponential backoff retry to payment processing"
```

---

## LLM providers

| Provider | Models | Key env var |
|---|---|---|
| `anthropic` | `claude-sonnet-4-5`, `claude-haiku-4-5` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo` | `OPENAI_API_KEY` |
| `ollama` | `llama3`, `mistral`, any local model | (none) |
| `aws` | `us.anthropic.claude-sonnet-4-*` | `BEDROCK_API_KEY` or IAM |
| `azure` | `gpt-4o`, any deployment | `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` |
| `gcp` | `claude-sonnet-4-5@20250514` | `GOOGLE_APPLICATION_CREDENTIALS` |

---

## Architecture

Corbell runs entirely locally, no cloud required:

- **Graph store**: SQLite (default). Optional: Neo4j for large multi-repo topologies.
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local). Storage backend is pluggable via `storage.embeddings.backend` in `workspace.yaml`.
- **UI**: Python stdlib `http.server` + D3.js via CDN. Zero extra dependencies.
- **LLM**: Not required for graph/embedding/UI commands. Claude/GPT-4o/Ollama for spec generation.

### What `graph build --methods` extracts

| Signal | Languages | Result |
|---|---|---|
| Typed method signatures | Python, TS, Go, Java | `MethodNode.typed_signature` |
| Call edges | All 5 | `method_call` edges |
| DB/queue/HTTP dependencies | All 5 | `DataStoreNode`, `QueueNode`, `http_call` |
| Git change coupling | Any git repo | `git_coupling` edges with strength score |
| Execution flow traces | All 5 | `FlowNode` + `flow_step` edges |

---

## CI integration

```yaml
# .github/workflows/spec-lint.yml
- name: Lint architecture specs
  run: |
    pip install corbell
    corbell spec lint specs/my-feature.md --ci
```

---

## Development

```bash
git clone https://github.com/your-org/corbell && cd Corbell
pip install -e ".[dev]"
pytest tests/ -q
corbell --help
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
