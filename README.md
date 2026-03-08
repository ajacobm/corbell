<div align="center">
  <h1>🏗️ Corbell</h1>
  <p><strong>Multi-repo architecture graph, AI-powered spec generation, and architecture review — for backend teams that ship to production.</strong></p>
  <p>
    <a href="https://pypi.org/project/corbell/"><img src="https://img.shields.io/pypi/v/corbell" alt="PyPI"/></a>
    <a href="https://pypi.org/project/corbell/"><img src="https://img.shields.io/pypi/pyversions/corbell" alt="Python"/></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"/></a>
  </p>
</div>

---

## What problem does this solve?

You're a staff engineer or architect at a company where features touch 5–10 repositories.<br/>
Every quarter your team re-litigates the same architectural decisions: "should we use Kafka or SQS?", "why do we have three different auth patterns?", "who owns the rate-limiting layer?"

The decisions live in Confluence pages nobody reads, Slack messages nobody can find, and the memories of engineers who've since left.

When a new engineer joins—or even when you return to a service you haven't touched in 6 months—you're starting from scratch.

**Corbell gives your team a knowledge graph of your architecture** built from the actual code in your repos, your existing design docs, and your team's past technical decisions. When you need to write a new design document, Corbell uses that knowledge as context to generate a precise, opinionated technical spec—one that respects your team's established patterns instead of inventing new ones.

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
                 [spec review] → Checks claims against graph → .review.md
                 [spec approve] → status: approved
                 [spec decompose] → parallel task tracks YAML
                 [export linear] → Linear issues created
```

No servers. No cloud setup. Runs entirely from your laptop against local repos.

---

## Installation

```bash
pip install corbell

# With LLM support (recommended — pick one):
pip install "corbell[anthropic]"    # Claude (recommended)
pip install "corbell[openai]"       # GPT-4o

# With export integrations:
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

Edit `corbell/workspace.yaml` to add your repos:

```yaml
# corbell/workspace.yaml
workspace:
  name: my-platform

services:
  - id: payments-service
    repo: ../payments-service
    language: python

  - id: auth-service
    repo: ../auth-service
    language: python

  - id: notifications-service
    repo: ../notifications-service
    language: python

llm:
  provider: anthropic   # or: openai, ollama
  model: claude-sonnet-4-5-20250929
  api_key: ${ANTHROPIC_API_KEY}
```

### 2. Build the knowledge graph

```bash
# Scan all repos — builds service + dependency graph
corbell graph build

# Index code chunks for semantic retrieval
corbell embeddings build

# Scan your existing design docs (ADRs, RFCs, specs)
corbell docs scan
corbell docs learn
```

### 3. Generate a design document (no --service needed!)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

corbell spec new \
  --feature "Payment Retry with Exponential Backoff" \
  --prd-file docs/payment-retry-prd.md
```

Corbell **automatically discovers** which services are relevant using embedding similarity search on the PRD — no `--service` flag needed.

You can also provide the PRD inline:

```bash
corbell spec new \
  --feature "Rate Limiting by Customer Tier" \
  --prd "We need to enforce per-customer rate limits across all API calls.
         Tier 1: 100 req/min. Tier 2: 1000 req/min."
```

**Token usage is displayed after every LLM command:**

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Step                    ┃ Model                    ┃ Input  ┃ Output  ┃ Total  ┃ Est. Cost   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━┩
│ search_query_generation │ claude-sonnet-4-5        │    487 │     124 │    611 │ $0.00311    │
│ spec_generation         │ claude-sonnet-4-5        │  5,243 │   3,812 │  9,055 │ $0.07292    │
├─────────────────────────┼──────────────────────────┼────────┼─────────┼────────┼─────────────┤
│ TOTAL                   │ 2 call(s)                │  5,730 │   3,936 │  9,666 │ $0.07603    │
└─────────────────────────┴──────────────────────────┴────────┴─────────┴────────┴─────────────┘
```

### 4. Generate a design doc for your existing codebase

No PRD? Just want to document what you already have?

```bash
corbell spec new --existing
# → specs/existing-codebase-design.md
```

Generates a 4-6 page design doc covering: overview, architecture diagram, key entry points, representative flows, and a code map — using only the scanned repos.

### 5. Feed existing design docs as context

Point Corbell at your team's existing design docs (Confluence exports, markdown RFCs, ADRs) to extract patterns and inject them as context when generating new specs:

```bash
corbell spec new \
  --feature "Auth Token Refresh" \
  --prd-file prd.md \
  --design-doc docs/auth-design-2023.md \
  --design-doc docs/session-management-rfc.md
```

Corbell extracts design decisions and patterns from those docs (using LLM or regex), and injects them into the LLM prompt so the new spec follows your team's established approach.

### 6. Document your architecture constraints

Every spec has a `## Reliability and Risk Constraints` section. This is where your team documents infrastructure, scaling, and security constraints that **all future designs must respect**:

```markdown
## Reliability and Risk Constraints

<!-- CORBELL_CONSTRAINTS_START -->
- **Cloud provider**: Only Azure — no AWS services permitted in any new feature
- **Latency SLO**: All synchronous API calls must have p99 < 200ms
- **Security**: All PII must be encrypted at rest (AES-256) and in transit (TLS 1.2+)
- **Scaling**: Horizontal scaling only; no vertical scaling. Max 1000 DB connections/node.
- **Redundancy**: Must survive single AZ failure — always deploy 2+ replicas per AZ
- **Rate limiting**: All calls to external APIs must be rate-limited (circuit breaker pattern)
<!-- CORBELL_CONSTRAINTS_END -->
```

`corbell spec review` checks whether the proposed design violates any documented constraint.

### 7. Review, approve, decompose

```bash
# Review the spec against the graph — writes .review.md
corbell spec review specs/payment-retry.md

# Approve
corbell spec approve specs/payment-retry.md

# Generate parallel task tracks
corbell spec decompose specs/payment-retry.md
# → specs/payment-retry.tasks.yaml

# Push to Linear
export CORBELL_LINEAR_API_KEY="lin_api_..."
corbell export linear specs/payment-retry.tasks.yaml
```

---

## CLI Reference

```
corbell --help

Usage: corbell [OPTIONS] COMMAND [ARGS]...

  graph       Service dependency graph commands
    build       Scan repos, build service + dependency graph
    services    List all discovered services
    deps        Show dependencies of a service
    methods     List methods (with --methods flag at build time)
    callpath    Find call paths between methods

  embeddings  Code embedding index commands
    build       Index code chunks for semantic search
    query       Search the code index with a text query

  docs        Design doc scanning and pattern learning
    scan        Find candidate design docs (ADRs, RFCs) in repos
    learn       Extract decisions and patterns from confirmed docs
    patterns    Show learned patterns

  spec        Design spec lifecycle
    new         Generate a design doc — services auto-discovered from PRD
                  --feature NAME      Feature name (prompts if omitted)
                  --prd TEXT          PRD text inline
                  --prd-file PATH     PRD from a file (recommended)
                  --design-doc PATH   Existing design doc for pattern context (repeatable)
                  --existing          Generate codebase doc without PRD
                  --no-llm            Template mode only
    lint        Validate spec structure — CI-safe (--ci exits with code 1)
    review      Review spec vs graph → .review.md sidecar
    approve     Mark spec approved
    decompose   Break approved spec into parallel task YAML
    context     Preview auto-discovered services + code context for a PRD

    mcp        Model Context Protocol (MCP) server integration

  export      Export to external tools
    notion      Export spec to Notion
    linear      Create Linear issues from .tasks.yaml

  init        Initialize a workspace (creates corbell/workspace.yaml)
```

## MCP – Model Context Protocol

The `mcp` command runs the Model Context Protocol server, enabling Corbell to provide context‑aware LLM completions.

```bash
# Start the MCP server (default host localhost, port 8000)
corbell mcp serve

# Start on a custom port
corbell mcp serve --port 9000
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

| Provider    | Models                                           | Key env var         |
|-------------|--------------------------------------------------|---------------------|
| `anthropic` | `claude-sonnet-4-5`, `claude-haiku-4-5`, `claude-3-5-haiku-*` | `ANTHROPIC_API_KEY` |
| `openai`    | `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`          | `OPENAI_API_KEY`    |
| `ollama`    | `llama3`, `mistral`, any local model             | (no key required)   |
| `aws`       | `us.anthropic.claude-sonnet-4-20250514-v1:0`     | `BEDROCK_API_KEY` (long-term key from Bedrock console) or IAM credentials |
| `azure`     | `gpt-4o`, any Azure deployment                   | `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` |
| `gcp`       | `claude-sonnet-4-5@20250514`                     | `gcloud auth application-default login` or `GOOGLE_APPLICATION_CREDENTIALS` |

**Template mode**: If no key is configured, `spec new` generates a structured skeleton with graph and code context filled in, leaving prose sections for you to complete.

---

## Token usage tracking

Every LLM call is tracked automatically. After each command, Corbell shows:
- Per-step breakdown (search query generation, spec generation, review, decompose)
- Input and output token counts
- Estimated cost in USD (using current provider pricing)
- Session total

This works for Anthropic and OpenAI. Ollama is always free (local model).

---

## Architecture

Corbell is intentionally lean and runs entirely locally:

- **Graph store**: SQLite (default). Optional: Neo4j for large multi-repo topologies.
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local, no API key). Optional: ChromaDB backend.
- **LLM**: None required for graph/embedding commands. Claude/GPT-4o/Ollama for spec generation.

```
corbell/
  core/
    workspace.py       # Pydantic config loader
    llm_client.py      # OpenAI / Anthropic / Ollama — with token tracking
    prd_processor.py   # PRD → search queries → auto service discovery
    token_tracker.py   # Per-call token + cost tracking, rich summary table
    graph/             # Service graph: schema, SQLite store, builder, method graph
    embeddings/        # Code chunk extraction, sentence-transformers, SQLite store
    docs/              # Design doc scanner, pattern learner, JSON store
    spec/              # Schema (Pydantic), linter, generator, reviewer, decomposer
    export/            # Notion blocks API, Linear GraphQL API
  cli/
    commands/          # Typer CLI: graph, embeddings, docs, spec, export
```

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
git clone https://github.com/your-org/corbell
cd Corbell
pip install -e ".[dev]"

# Run tests
pytest tests/ -q --cov=corbell --cov-report=term-missing

# Check help
corbell --help
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
