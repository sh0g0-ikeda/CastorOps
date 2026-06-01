# CastorOps

CastorOps is a Gemini-driven DevOps AI agent prototype for making GCP application design, deployment, and operations easier to understand.

The current repository contains the local demo-mode backend implementation used for the hackathon flow. It runs entirely in memory and exercises the core workflow without requiring live GCP credentials.

## Current Scope

Implemented:

- Project creation and phase transitions.
- Requirement follow-up question generation.
- Demo image-artifact capture for visual requirement notes.
- Requirement, design, architecture, and security agent workflow orchestration.
- Approval gates for requirements, design, and architecture.
- Architecture proposal validation, editable node updates, chat-based re-proposal, confirmed node deletion, node addition, edge editing, and impact preview.
- Target FastAPI app package generation with custom fields, environment variable documentation, generated tests, and demo AI review.
- Demo GitHub delivery adapter for repository read, branch creation, push, and Draft PR payloads.
- Terraform preview generation for the COULD-level IaC path.
- Apply failure guidance with rollback candidate suggestions.
- Deterministic Cloud Build apply plan rendering.
- Local Cloud Build deployment simulation.
- Ops dashboard eight-section aggregation and local UI rendering.
- Timeline events with expandable rationale and SSE event encoding helpers.
- Dependency-free local demo HTTP server and static UI for design docs, target app files, GUI architecture edits, approval modals, and apply locks.
- Container runtime for Cloud Run.
- Cloud Build pipeline for testing, building, pushing, and deploying CastorOps.
- GitHub Actions CI for compile, unit tests, and secret pattern smoke checks.

Not implemented in this repository yet:

- Persistent Firestore / Cloud Storage adapters.
- Live Vertex AI / Gemini provider adapter.
- Live Cloud Build / Cloud Run architecture-apply adapter.
- Authentication for production usage. The hackathon demo uses a single demo identity.

## Design Document

The main design document is:

- [castor_ops_design_docs_v21.md](castor_ops_design_docs_v21.md)

The design document is the source of truth for the intended hackathon product scope, architecture, and later production direction.

## Requirements

- Python 3.11 or newer.
- No third-party Python package is required for the current local demo and test suite.

## Local Validation

Run the unit tests:

```powershell
python -m unittest discover -s tests -v
```

Compile all Python modules:

```powershell
python -m compileall app tests scripts
```

Run the local end-to-end demo:

```powershell
python scripts\run_full_demo.py --idea "support desk app" --target-project-id demo-gcp-project
```

Run only the requirement workflow demo:

```powershell
python scripts\run_requirement_demo.py --idea "support desk app"
```

Serve the local browser demo:

```powershell
python scripts\serve_demo.py --host 127.0.0.1 --port 8080 --target-project-id demo-gcp-project
```

Then open:

```text
http://127.0.0.1:8080
```

Run the same server in a container:

```powershell
docker build -t castorops:local .
docker run --rm -p 8080:8080 -e PORT=8080 -e HOST=0.0.0.0 castorops:local
```

Deploy CastorOps itself through Cloud Build:

```powershell
.\scripts\deploy_self.ps1 -ProjectId "your-gcp-project" -Region "asia-northeast1" -Service "castorops" -TargetProjectId "demo-gcp-project"
```

The deployment command requires a configured `gcloud` CLI, an active billing account, and the required Google Cloud APIs enabled for the target project.

## Configuration And Secrets

The local demo does not require secrets.

For a Cloud Run demo deployment:

- `PORT` is provided by Cloud Run.
- `HOST` defaults to `0.0.0.0` in the container.
- `TARGET_PROJECT_ID` controls the target GCP project id shown in generated plans.

Do not commit `.env`, service account keys, API keys, OAuth secrets, or downloaded credentials. Use Cloud Run environment variables and Secret Manager for real credentials when live adapters are introduced.

## Repository Layout

```text
app/
  agents/          Agent runtime, schemas, role-specific agents, and tool guard.
  api/             Application facade and API response envelope.
  approvals/       Approval gate models, repository, and service.
  architectures/   Architecture spec models, validation, and versioning.
  auth/            Demo identity boundary.
  codegen/         Target app package generation.
  core/            Shared error types.
  deployments/     Local deployment adapter and deployment records.
  documents/       Versioned document storage.
  ops/             Ops dashboard aggregation.
  projects/        Project model, repository, and phase service.
  security/        Security finding model and service.
  streaming/       SSE encoding helpers.
  timeline/        User-facing timeline events.
  tools/           Guarded tool execution runtime.
  web/             Dependency-free local demo HTTP server and static UI.
  workflows/       Requirement, design, planning, security, apply, and demo workflows.
scripts/
  deploy_self.ps1
  run_full_demo.py
  run_requirement_demo.py
  serve_demo.py
tests/
  unittest-based behavior tests.
```

## License And Notices

- [LICENSE](LICENSE)
- [NOTICE](NOTICE)

## Git Remote

The canonical GitHub repository is:

```text
https://github.com/sh0g0-ikeda/CastorOps
```
