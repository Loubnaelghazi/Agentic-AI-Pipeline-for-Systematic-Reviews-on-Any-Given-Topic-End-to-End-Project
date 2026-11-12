# Folio · Agentic literature review

A local FastAPI + React workspace for preliminary scientific literature reviews.
LangGraph coordinates discovery, screening, full-text acquisition, Ollama-based
extraction, human review, source-linked reporting, and quality checks.

## Run with Docker

Requirements: Docker Engine/Desktop with Compose, and an existing Ollama server
with `qwen3.5:4b` and `qwen3-embedding:0.6b` available (or the models
configured in `.env`). Models are not downloaded or
started by Compose.

```bash
docker compose up -d
docker compose ps
```

Run this from the project root. Compose builds missing images automatically and
starts both services in the background. The frontend waits for the backend health
check. No separate frontend or backend startup commands are needed.

After changing application code, rebuild the images with:

```bash
docker compose up -d --build
```

- **Dashboard:** http://localhost:3000
- **API and documentation:** http://localhost:8000/docs
- **API health:** http://localhost:8000/api/health

There are exactly two services. The frontend uses Node's HTTP server to serve
compiled React assets. The browser connects directly to FastAPI; there is no
reverse proxy, Nginx, Vite development server, or server-side API forwarding.
Both services run as non-root users and have health checks. FastAPI runs one
worker because workflow execution and mutation locks are process-local.

```bash
docker compose logs -f backend frontend
docker compose stop
docker compose down
```

Review data is bind-mounted from **`./data` to `/data`**. Existing PDFs, Chroma
indexes, checkpoints, decisions and reports remain available across container
rebuilds and restarts. Data and `.env` are excluded from build contexts/images.
Keep a backup of `data/` before external/manual changes to research records.

### Configuration

Use [.env.example](.env.example) as a reference for your existing `.env`.
Environment variables take precedence over local dotenv values.

| Variable | Purpose |
| --- | --- |
| `OLLAMA_MODEL` | Local generation model; defaults to `qwen3.5:4b` |
| `EMBEDDING_MODEL` | Defaults to `qwen3-embedding:0.6b` |
| `OLLAMA_BASE_URL` | Ollama URL for local Python execution |
| `DOCKER_OLLAMA_BASE_URL` | Container-to-Ollama URL; defaults to `http://host.docker.internal:11434` |
| `API_BASE_URL` | Browser-visible API origin; defaults to `http://localhost:8000` |
| `CORS_ORIGINS` | Comma-separated allowed dashboard origins |
| `DATA_DIR` | Local Python data directory; Compose sets `/data` |
| `LOCAL_UID`, `LOCAL_GID` | Backend image user IDs; default `1000` for bind-mount ownership |

`API_BASE_URL` is read by the frontend server at startup and exposed through
`/config.js`; changing it does not require rebuilding React. Use an address the
**browser** can resolve, not the Docker service name `backend`. Default CORS
origins allow localhost/127.0.0.1 on ports 3000 and 5173. Adjust both settings
if you change browser origins.

Containers cannot reach the host's `127.0.0.1`. Ollama must listen on a Docker-
reachable interface. If needed, configure `OLLAMA_HOST=0.0.0.0:11434` before
starting your existing Ollama server, or set `DOCKER_OLLAMA_BASE_URL` to its
reachable address. On WSL, verify which host/WSL interface Ollama serves.
Compose adds `host.docker.internal:host-gateway` for Linux compatibility.

If your host user is not UID/GID 1000, set `LOCAL_UID` and `LOCAL_GID` before
building so the backend can write your existing `data/` directory. No startup
script recursively changes ownership of your research data.

This remains a local single-user application without authentication or
multi-instance coordination. Published ports bind to loopback by default.
Do not run a CLI writer against a review currently running/editing in the UI.

## Local development

Python 3.12+, uv, Node 20.19+ and npm are required.

```bash
uv sync --frozen
uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Development also calls FastAPI directly through
CORS. The development API origin is set in `frontend/public/config.js`.
For a local production frontend, run `npm run build` then `npm start`; its API
origin is configurable with `API_BASE_URL`.

## CLI and human review

```bash
uv run python main.py --topic "Your research question"
uv run python main.py --review-id REVIEW_ID
uv run python human_review.py REVIEW_ID
uv run python human_review.py REVIEW_ID --item ITEM_ID
```

The workflow pauses for protocol approval, uncertain screening adjudication,
full-text eligibility, evidence approval, and study appraisal. Reporting then
requires checklist assessment and scientific QA. See the methodology section
below for the extended workflow.

Record your own assessment through the dashboard or CLI:

```bash
uv run python human_review.py REVIEW_ID --item eligibility:W123 --decision include --reviewer "Your name" --reason "Documented eligibility rationale"
uv run python human_review.py REVIEW_ID --item evidence:HASH --decision approve --kind methodology --reviewer "Your name" --reason "Checked source, attribution and category"
```

Screening/eligibility accept `include` or `exclude`; evidence accepts `approve`
or `reject`. Corrections append to the audit history. Approvals are tied to
content fingerprints; stale views and changed sources require reassessment.
Unavailable full texts are acquisition failures, not scientific exclusions.

Individual stages use one CLI, replacing the former duplicate
`download_pdfs.py`, `extract_papers.py`, `generate_report.py`, `review_report.py`:

```bash
uv run python -m workflow.cli download REVIEW_ID
uv run python -m workflow.cli extraction REVIEW_ID
uv run python -m workflow.cli synthesis REVIEW_ID
uv run python -m workflow.cli quality REVIEW_ID
```

These enforce review prerequisites. Prefer `main.py --review-id` to keep graph
checkpoints synchronized. In a container, use e.g.
`docker compose exec backend python human_review.py REVIEW_ID`.

## Evidence and persistence

Each workspace is under `data/reviews/REVIEW_ID/`. `outputs/` contains raw and
approved evidence, acquisition outcomes, decision history, the Markdown report,
QA results, counts and status. `workflow_state.json` stores completed stages.
Prior scientific outputs are copied into `outputs/history/` on invalidation.
Run logs live in `outputs/runs/`.

Qwen selects numbered source sentences; Python copies them exactly. Quotations
are matched to source passages and original PDF pages. Bibliography filtering
and sentence selection are heuristic; source matching does not establish
scientific truth, attribution, or correct categorization. Human approval remains
required. Reports contain only approved quotations from eligible studies.
Missing evidence is distinguished from author-reported study limitations.

`outputs/review_status.json` indicates whether report exports are current.
Historical files remain available while review is pending. Protocol approval
and simulated dual screening are implemented; independent human dual review
and final scientific validation remain researcher responsibilities. QA does
not automatically establish correctness or PRISMA compliance.

Decision changes invalidate dependent stages while retaining usable acquisition
and extraction results. Other model-setting changes do not automatically
invalidate checkpoints. Unavailable PDFs are not retried automatically. A server
restart marks orphaned jobs interrupted; resume their saved checkpoints.

## Code structure and checks

```text
api/                 HTTP routes and background workflow execution
agents/              Search, screening, extraction, reporting and QA
workflow/            Typed graph, nodes and consolidated stage CLI
storage/             Review workspaces, decisions and atomic persistence
rag/                 Indexing, retrieval and PDF provenance
tools/               OpenAlex and open-access PDF acquisition
frontend/src/        React application, components and typed API client
frontend/server.mjs  Static serving and runtime browser configuration
config.py            Shared paths and model configuration
tests/               Mocked API, workflow and evidence regression tests
```

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format --check .
cd frontend
npm test
npm run build
```

Runtime images install locked production dependencies only. The backend does
not install unused Streamlit, sentence-transformers, Torch/CUDA or the LangChain
umbrella package; embeddings and generation use Ollama. Frontend runtime images
contain only the compiled site and the dependency-free static server.

The original cleanup passed its Python and Node static-server tests, as do Ruff, TypeScript and the production frontend build. Both Docker
images were built and both services passed health checks. Container smoke
checks verified direct CORS/API access, runtime frontend configuration, PDF/data
persistence, non-root users, Ollama connectivity, and background execution
returning to the existing human-review gate. Research decisions were not
approved automatically.

## Protocol-driven methodology

New and existing reviews now pause for an approved protocol before the extended
workflow runs. Open the protocol validation card in your conversation, create a template or
request a local planner suggestion, edit the criteria and settings, save a
revision, and explicitly approve it. Suggestions never approve themselves.

The protocol defines concept/synonym groups, optional MeSH terms, sources,
publication dates, record caps, extraction fields, appraisal domains and a
synthesis plan. OpenAlex, PubMed and arXiv are supported. `OPENALEX_API_KEY` is
optional when required by the provider's current access policy; no paid
full-text endpoint is used. Network failures and search truncation are reported.

For an existing workspace, select **Reuse existing search records** only if you
intend to retain legacy search coverage. Screening is then reconsidered under
the approved protocol. Otherwise the workflow runs fresh multi-source searches.
Old data is preserved and prior exports are archived. Missing provenance stays
unknown and is flagged by QA.

Title/abstract screening uses two blinded prompt roles of the same local model,
with criterion IDs and disagreement handling. Partial reviewer responses are
saved for resume. Full-text recommendations are advisory; the human eligibility
decision remains required. Extraction uses dense + sparse rank fusion and
source-exact context windows. Candidate characteristic values remain suggestions
until a human confirms them.

After evidence review, open **Study appraisal**. Confirm the structured study
characteristics and domain judgements, using exact source quotations for
substantive assertions. Empty values mean not reported/confirmed. The default
rubric is project-defined, not a validated clinical instrument implementation;
choose and document a suitable instrument for your study designs. Optional
study IDs link multiple reports from a single underlying study.

Generated artifacts now include:

- `search_strategy.json`, `search_log.json`, `retrieved_records.json`, `duplicates.json`
- `screening_progress.json`, `eligibility_proposals.json`, `execution_trace.json`
- `appraisals.json`, `appraisal_proposals.json`, `evidence_table.csv`
- `evidence_map.csv`, `evidence_map.svg`, `prisma_flow.json`, `prisma_flow.svg`
- `literature_review.md`, `literature_review.docx`, `references.bib`
- `prisma_checklist.json` and `meta_analysis_template.csv`

The manuscript groups confirmed study characteristics and source-linked findings
across reports. It does not manufacture pooled effects or conclusions from quote
counts. Open **PRISMA checklist** to assess reporting items against the official
guidance, with manuscript locations and applicability rationales. Checklist
assessments are bound to the report's fingerprint. Resume after changes to rerun
QA; final status is `completed_preliminary` or `completed_with_issues`, neither
of which is an automatic scientific or PRISMA certification.

Protocol CLI equivalents:

```bash
uv run python -m methodology.protocol draft REVIEW_ID
uv run python -m methodology.protocol show REVIEW_ID
uv run python -m methodology.protocol save REVIEW_ID --file edited-protocol.json --reviewer "Your name"
uv run python -m methodology.protocol approve REVIEW_ID --fingerprint CURRENT_FINGERPRINT --reviewer "Your name" --reason "Criteria and methods reviewed"
```

## Evaluation and optional quantitative preparation

Export a sample without overwriting existing human labels:

```bash
uv run python -m evaluation.prepare REVIEW_ID ./evaluation-sample
# A human must complete labels.json. Record timings for the same task scope.
uv run python -m evaluation.benchmark ./evaluation-sample/labels.json ./evaluation-sample/predictions.json ./evaluation-sample/results.json
```

Unlabelled samples are rejected. Missing ratings and timings produce unknown
metrics, not invented zeroes or accuracy claims. Agreement is between simulated
model roles. Software regression tests are separate from scientific benchmarks.

The meta-analysis CSV is a preparation template, not an analysis result. Only
use suitable comparable estimates with independent study IDs, an appropriate
common effect scale, positive standard errors and explicit human verification:

```bash
uv run python -m evaluation.meta_analysis verified-estimates.csv --reviewer "Your name" --comparability-reason "Documented assessment of comparability and independence" --output pooled-result.json
```

The optional tool performs fixed-effect inverse-variance pooling only; it cannot
determine clinical comparability or select an appropriate effect measure for you.
No pooling is performed automatically by the review graph.

Academic report and demonstration materials will be prepared separately.

The current phase appears as an assistant message with processing status, elapsed
time and per-paper counts where available. Stage counts are not a time estimate;
local model calls can vary substantially in duration. Use **Pause to review** to
request a safe pause after the current operation. Saved items remain visible while
running; decision forms unlock once the worker has paused. Resume reuses saved work,
although an interrupted stage may repeat unfinished operations. Protocol changes can
invalidate earlier results as usual. The Activity tab provides the live run log.

Review decisions use a compact reading pane with independently scrolling paper
content and queue. **Save & next** advances the queue; **Skip for now** leaves the
item undecided. Notes are optional for routine screening, inclusion and evidence
decisions. Full-text exclusions still require a reason; protocol criteria are
available as one-click reason shortcuts. Protocol approval notes are optional.
Appraisal uses a step-by-step form: blank study characteristics and notes for
unclear judgements are allowed, while substantive judgements still require reasons
and verified source quotations. AI extraction proposals are opt-in. The checklist
advances to the next outstanding item after saving; reported items need a manuscript
location, while missing/not-applicable items need an explanation.

### Guided review assistant

The app opens on a new-conversation screen. Existing reviews reopen as chat threads.
It presents one phase at a time: protocol, search, screening, full-text eligibility,
evidence, appraisal and report. Review cards keep the source and decision controls
close together. Saved decisions and confirmations can be expanded in the conversation;
the details drawer provides specialist tools for deeper inspection.

The backend stops after each processing phase. Finish any required item-level
reviews, then choose **Confirm & continue** to start the next phase. Confirming a
phase does not approve individual papers or evidence. Confirmation tokens prevent
stale or repeated approvals. New protocol revisions invalidate old confirmations.
The final draft requires **Confirm & finish**. Automated checks remain advisory.

The visible **Thinking Off / On** control applies to new AI calls for this review.
Thinking defaults to Off until explicitly enabled. Existing explicit On/level choices
are retained; older model-default settings now resolve to Off. Options are discovered
from the installed model through Ollama's `/api/show`; models supporting on/off offer
both choices, while models with named levels expose those levels. Unsupported or
unreachable models do not show a working toggle. Thinking may increase processing
time. Existing completed results are retained when this preference changes.
Thinking traces are not shown in the review conversation.

For CLI execution, use `python main.py --review-id REVIEW_ID --thinking off`
(or `on`, `default`, or a supported named level). Confirm workflow phases through
the dashboard. See [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking)
for the model-specific API behavior.

### Chat-first interface

The dashboard shell has been replaced with a chatbot layout. Start a conversation
by typing a research question on the home screen, or reopen an existing review
from the left sidebar. Ask follow-up questions in the message composer. Replies
come from the configured local Ollama model, and messages persist with the review.
Study findings in chat use currently human-approved evidence; chat answers remain
advisory and must be checked against the sources.

The assistant's next action appears as a validation card in the thread. Expand it
to review the protocol, individual papers, evidence, appraisal or draft. Required
decisions still block continuation. Only the explicit validation buttons advance
the workflow; typing an approval request in chat does not approve anything.
Review files, logs and specialist tools are available in the details drawer.
Thinking controls remain above the conversation. Chat is disabled while a workflow
phase runs; pause the worker first if you want to ask a question mid-phase.


### Original PDF reader

Use **Papers & PDFs** above the chat to browse downloaded research papers.
**Read original PDF** opens an in-app reader with page navigation, zoom and a
responsive page view. Pages are rendered directly from the saved PDF, preserving
its columns, figures, tables and layout. **Browser PDF view** uses the browser’s
native reader, and **Download PDF** returns the unchanged original file.
The same reader is available inside eligibility, evidence and appraisal cards.
PDFs become available during full-text acquisition after screening validation;
inaccessible sources remain labelled unavailable. The chat toolbar and PDF reader
wrap on smaller screens, with a full-screen reader on mobile.

### Configure a run before the prompt

The opening chat screen fits the viewport. Click **Settings** (the sliders icon
inside the prompt box) to open the run settings panel; on mobile it opens as a
bottom sheet. This exposes installed local chat models, Thinking Off/On, run mode,
response temperature, record limits per query and search sources before sending
a research question. Close with **Done**, Escape or a click outside the panel.
The moon/sun button in the top bar switches between light and dark mode across the
workspace. Your choice is remembered in this browser; initially it follows your
system preference. On short screens, secondary welcome text and suggestions give
way to the prompt box. Settings and long conversations scroll within their own
panels. No model downloads are performed. Embedding and
cloud model entries are excluded from the local chat model chooser.
Settings are saved with the new review and passed to workflow worker processes;
search sources and caps populate the protocol proposal. Changing Thinking later
keeps the review's model, mode and other settings.

Choose **Guided** to validate intermediate phases, or **Automated draft** to run
planning, search, screening, acquisition, extraction, appraisal notes and an
extractive draft without intermediate human decisions. Automated mode starts on
submission and stops at a final **Accept final result / Reject final result** card.
It retains source quotations and machine proposals as artifacts, and labels them
unvalidated. It does not fabricate protocol approvals, individual inclusion
approvals, evidence approvals, validated bias scores or PRISMA compliance.
Final acceptance concerns the overall preliminary draft only. Final decisions are
bound to the report, source files and machine artifacts; changed results require
a new review decision after regeneration. Model/mode/search changes after processing
starts require a new conversation, preserving the original run's provenance.


## Publication years and automatic PRISMA reporting

Before sending a new question, open **Settings → Search and response parameters**.
The publication start/end years are optional. Both blank means no date restriction;
a single bound is also supported. Selected years include January 1 through
December 31. OpenAlex/PubMed apply publication dates; arXiv applies submission dates.
The selected range is saved in the protocol and cannot be silently changed after
processing starts. To change an existing search period, create a new conversation.

Automatic drafts now export `prisma_flow.json`, a branched `prisma_flow.svg`,
`full_text_decisions.csv`, `evidence_table.csv`, `references.bib`, and a
`prisma_checklist.json` tied to **automatic_review.md**. The manuscript and DOCX
include a reporting appendix with the actual protocol, search logs, date range,
counts, limitations and references supporting the synthesis. Machine decisions,
uncertain provisional reports, unavailable reports and extraction gaps remain
separate. Independent study counts remain unknown without confirmed study IDs.

Open **Read draft and quality notes** to view the diagram, or **Review PRISMA
checklist** to record human reporting assessments. Suggested locations are aids,
not verified checklist answers. Generation and final draft acceptance do not
certify PRISMA compliance or scientific accuracy.

Existing unchanged automatic drafts can be upgraded using the local API
`POST /api/reviews/REVIEW_ID/reporting`, or by resuming a legacy draft. This adds
reporting without rerunning retrieval or model calls, archives prior exports,
and requires a new final decision when the manuscript changes.

## Recovery from local inference failures

Local inference uses bounded retries for transient connection errors and timeouts.
`OLLAMA_REQUEST_TIMEOUT` defaults to 300 seconds and `OLLAMA_RETRY_ATTEMPTS` to 2.
Optional passage reranking has a shorter deadline; when it cannot complete, hybrid
fusion results remain available and the retrieval trace records the fallback.

Failed or empty extractions are persisted but do not complete the extraction
stage. **Retry failed extractions / Resume** keeps searches, screening, downloads,
indexes and successful records, then regenerates dependent appraisal/report files.
An incomplete legacy result cannot be accepted as a finished draft. Sleep/network
outages still require Docker and Ollama to become reachable before retry succeeds.

## Scientific support checks

Automatic eligibility and evidence selections undergo a separate attribution and
semantic support audit. Potential exclusions are challenged against their logical
opposites; inconsistent or incomplete answers remain uncertain. Uncertain studies
are shown separately and do not support the automatic comparative interpretation.
PDF table cells retain original decimals, headers and page geometry, with numerical
rows exported to `numerical_results.csv`. Guided mode requires explicit approval
of the corresponding row quotation before using those numerical results.

Resume historical automatic drafts to apply the current scientific
checks; prior outputs are archived and existing downloads are reused. These
model-based checks do not certify scientific correctness.


### Ollama installed inside Debian/WSL

If Ollama runs in WSL, routing through the Windows localhost relay can interrupt
long requests. This installation uses a systemd override that binds Ollama only
to the current private WSL `eth0` address, not to all interfaces. The helper is
`scripts/ollama_wsl_private.py`, installed as `/usr/local/libexec/ollama-wsl-private`.

Start the project after a WSL restart with:

```bash
./scripts/start-local.sh
```

The script refreshes `OLLAMA_HOST_ADDRESS` and the local `OLLAMA_BASE_URL` in
`.env`, then starts Compose. The backend keeps using `host.docker.internal`,
which is mapped directly to the private WSL address. Ordinary setups without
this service override retain Docker's default host gateway. If Docker Desktop
restores an empty WSL bind mount, the script recreates the backend container;
review files are kept in `data/`.

The service override is `/etc/systemd/system/ollama.service.d/10-docker-access.conf`.
It does not change the Ollama models or weights. An NVIDIA/WSL GPU failure is
separate: inference can fall back to CPU and take substantially longer.


Report presentation includes selection cards, readable evidence tables and a colored PRISMA flow with separate pending/include branches. Word exports contain native tables, styled headings and the embedded diagram. SVG/PNG downloads and raw JSON audit files remain available separately. Completed automatic drafts can receive presentation updates through the reporting endpoint without new searches or inference.


The automatic manuscript opens with a structured abstract, introduction, methods, results, discussion, limitations, conclusion and references. Detailed source evidence, appraisal questions and search logs follow as appendices. Unresolved eligibility remains explicit; article structure alone does not establish a completed systematic review.

### Scientific writing in both run modes

The shared writing agent now drafts the introduction, results, discussion,
conclusion and abstract from eligible source-linked evidence. Methods and
selection counts come from execution records. Each paragraph receives citation,
numerical-value and model-based support checks, with one bounded repair attempt.
Rejected prose stays in the audit artifact and does not enter the manuscript.
Guided runs use human-approved evidence; automatic runs retain explicit machine
proposal status. Provisional reports remain separate from primary conclusions.

The report screen shows five section checks and provides a Word manuscript.
Resume reuses verified sections when source and decision fingerprints match.
Incomplete automatic writing blocks final acceptance.
`outputs/scientific_manuscript.json` records paragraph evidence, critic verdicts,
rejected drafts and checkpoints; it is a technical audit export.


### Local model audit and controlled upgrade

All generation
roles share the configured context budget. `EMBEDDING_NUM_GPU=0` reserves scarce
VRAM for generation. `OLLAMA_AUDIT_REASONING=true` enables careful reasoning for disputed eligibility
when supported, independently of the drafting/search Thinking control.
Uncertain eligibility uses criterion-specific context and
source sentence IDs, followed by a separate semantic check. These checks do
not certify scientific correctness.

The candidate model is activated only after measured diagnostic and GPU checks;
`data/model_audits/upgrade_status.json` distinguishes downloading, benchmarking,
adoption and review completion. An explicit
`POST /api/reviews/REVIEW_ID/generation-model` with `{"model":"INSTALLED_MODEL"}`
archives old outputs and invalidates model-dependent proposals while preserving
PDFs, source-checked extraction and actual human decisions. The operation is
blocked while that review is running. Ordinary settings updates remain guarded.
