# Technology decisions

Master prompt section 22: "Do not blindly select technologies ... choose based on actual
requirements ... avoid unnecessary complexity." Status 2026-10-08 (autolab 0.8.x).

## The actual requirements

| # | Requirement | Source |
|---|---|---|
| T1 | Runs on one Windows 10 PC, operated by one person, with no servers to administer | the lab today |
| T2 | Every record immutable, versioned and tamper-evident; full provenance | s.14, s.23 (7-9) |
| T3 | Bit-for-bit reproducible experiments from a commit + frozen protocol | s.9, s.23 (5, 18) |
| T4 | Agents are external CLIs/APIs (Claude, Codex, Gemini, OpenAI); the lab orchestrates, it does not train frontier models | s.4, s.17 |
| T5 | Survives crashes, PC sleep and multi-hour agent calls; resumable from state on disk | D35, D47 |
| T6 | Observability without operating a monitoring stack | s.20 |
| T7 | Scales later to GPU, containers, robots -- not needed yet | s.9, s.24 phases 7-8 |

T1 and T5 dominate: every service added (a database server, a broker, a cluster) is something
that can be down when an unattended run needs it.

## Decisions

| Technology area | Options considered | Decision | Why | Revisit when |
|---|---|---|---|---|
| Language | Python, TypeScript | **Python 3.13** (standard library + jsonschema + PyYAML) | the research and ML ecosystem; agents write Python experiments; one language for controller and experiments | a large front-end application is needed |
| Web UI | React/TypeScript SPA, server-rendered, dependency-free ES module | **dependency-free ES module + stdlib `ThreadingHTTPServer`** | no build step or npm supply chain; strict CSP; loopback only; works offline | multi-user or remote access is required |
| API framework | FastAPI, Flask, stdlib | **stdlib `http.server`** | ~20 JSON endpoints on loopback; FastAPI adds a server process and dependencies for no current need | the API is exposed beyond the machine or needs auth/OpenAPI clients |
| Records / provenance store | PostgreSQL, SQLite, event store | **SQLite (WAL) with append-only, hash-chained records** | a file, no server (T1); SQL triggers forbid UPDATE/DELETE; transactional; read-only opening for cross-lab knowledge | concurrent writers from several machines |
| Knowledge graph | Neo4j/graph DB, RDF store, derived in-process graph | **graph derived in Python from the ledgers on demand** | cannot drift from the source of truth (T2); thousands of nodes, not millions; no server | > ~10^5 nodes or graph queries become a bottleneck |
| Object / artifact storage | S3/MinIO, filesystem | **content-addressed filesystem store (sha256, read-only files)** | integrity checked on read; no service; trivially backed up | artifacts outgrow one disk or must be shared between machines |
| Cache / coordination | Redis | **none** | state lives in the ledger; one controller process per lab | several controllers must coordinate on one lab |
| Events / messaging | Kafka, RabbitMQ, NATS, ledger events | **ledger events (hash-chained) + Server-Sent Events to the dashboard** | events are already durable and ordered in the ledger; agents are dispatched by the controller, not by subscriptions | agents must react to events asynchronously across processes or machines |
| Manifest format | YAML (PyYAML), TOML (stdlib), JSON (stdlib) | **YAML via PyYAML 6** (D61) | s.16 requires `project.yaml`; hand-writing a YAML parser would be fragile; PyYAML is small, mature, `safe_load` only | - |
| Containers | Docker, none | **none yet** (trials run as subprocesses with resource accounting and a pinned interpreter + lock check) | Docker Desktop on this PC is an extra moving part; reproducibility is enforced by commit + lock + seeds | experiments need system libraries, GPUs or stronger isolation (planned: containerised trial runner) |
| Cluster / distributed | Kubernetes, Ray, none | **none** | one machine | multi-GPU or multi-machine experiments |
| Experiment tracking | MLflow, Weights & Biases, ledger | **the lab's own run/result records** | pre-registration, freeze hashes, decision rules and provenance are first-class here and absent in MLflow | model training at scale needs model registries and artifact lineage MLflow provides |
| Source control / CI | GitHub (+ Actions), local git | **local git worktrees per agent; private GitHub backup (D38)** | branches never deleted; controlled merges with provenance trailers | CI: adding GitHub Actions for the test suite is a cheap next step |
| Robotics middleware | ROS 2, custom | **custom contracts now (robolab), ROS 2 adapter before Gate 7** | ROS 2 on Windows is heavy; simulation-only gates do not need it; the MHS/contract layer keeps the brain middleware-agnostic | hardware integration (Gate 7) |
| Simulation | MuJoCo, Isaac Sim, Gazebo, own NumPy simulators | **own deterministic NumPy simulators (Puck2D, Car2D)** | exact determinism and ground-truth isolation for the research questions of Gates 1-4 | contact-rich or 3D bodies (humanoid, manipulation) |
| Vector search | FAISS, pgvector, Chroma, none | **none; lexical BM25 in the knowledge plane** | the record count is small; lexical retrieval is deterministic and explainable | retrieval misses paraphrases often enough to matter (ROADMAP phase 6) |
| Observability | OpenTelemetry + Prometheus/Grafana, built-in | **built-in: ledger, task records, trial resource metering, dashboard** | no stack to operate (T6) | tokens/cost/GPU metrics or multi-machine traces are needed |
| Workflow orchestration | Temporal, Airflow, Prefect, state machines | **explicit state machines in the controller (research, engineering, programme)** | every transition is validated and recorded; resumable from the database; the orchestration *is* the research method | many concurrent long-running workflows across machines |

## Principles applied

* Prefer a file over a server, and a standard-library module over a dependency (T1, T5).
* Derive views (graph, dashboard, exports) from the ledger instead of keeping second copies (T2).
* Add a technology only when a named requirement needs it; each "Revisit when" is that trigger.

## Known costs of these choices

* No multi-user access, no remote dashboard, no horizontal scaling.
* Experiment isolation is weaker than containers: trials see the controller's environment
  (SECURITY_ARCHITECTURE.md).
* No CI service yet: the suite runs locally (about 25 minutes).
