# flatten-tests Automation — Developer Guide

A system that automatically flattens `describe` blocks in test files into `test` blocks
via the Devin API whenever a matching file is pushed to the repository.

---

## Architecture

```
Developer
    │
    │  git push (master branch)
    ▼
┌─────────────────────────────────────────────────────────┐
│                   GitHub Actions                        │
│                                                         │
│  ┌──────────────────────────┐                           │
│  │  Job 1: detect-and-notify│                           │
│  │                          │                           │
│  │  1. git diff HEAD~1 HEAD │                           │
│  │  2. match targets in     │                           │
│  │     flatten-tests.json   │                           │
│  │  3. grep for describe()  │                           │
│  │  4. Slack notification ──┼──────────────────────────┼──▶ Slack
│  └────────────┬─────────────┘     (blue, files listed) │
│               │ matched_files                           │
│               ▼                                         │
│  ┌──────────────────────────┐                           │
│  │  Job 2: launch-devin     │                           │
│  │                          │                           │
│  │  flatten_tests/main.py   │                           │
│  │    │                     │                           │
│  │    ├─ launch session ────┼──────────────────────────┼──▶ Devin API
│  │    │                     │                           │      │
│  │    ├─ poll (30s interval)│◀─────────────────────────┼──────┘
│  │    │   until:            │   session status /        │
│  │    │   • PR created      │   pull_requests           │
│  │    │   • exit / error    │                           │
│  │    │   • timeout (15min) │                           │
│  │    │                     │                           │
│  │    └─ Slack notification ┼──────────────────────────┼──▶ Slack
│  └──────────────────────────┘  (green / yellow / red)  │
└─────────────────────────────────────────────────────────┘
                                          │
                              Devin works autonomously
                                          │
                              1. Clone repository
                              2. Flatten describe() → test()
                              3. Run npm test
                              4. Open Pull Request ([skip ci])
```

---

## Prerequisites

| Tool | Check |
|------|-------|
| Git | `git --version` |
| Docker | `docker --version` |
| Docker Compose (optional) | `docker compose version` |

---

## 1. Clone the Repository

```bash
git clone https://github.com/tishib2/superset.git
cd superset
```

---

## 2. Build the Docker Image

All commands below are run from the **repository root**.

```bash
docker build \
  -f docker/flatten-tests/Dockerfile \
  -t flatten-tests \
  .
```

---

## 3. Run Unit Tests

Unit tests run entirely inside the container with no external dependencies (HTTP is mocked).

```bash
docker run --rm flatten-tests \
  uv run pytest tests/ -v --ignore=tests/test_integration.py
```

Expected: **40 passed**

| File | Module | Tests |
|------|--------|-------|
| `test_detector.py` | `detector.py` — file detection logic | 14 |
| `test_devin_client.py` | `devin_client.py` — API client | 9 |
| `test_slack_client.py` | `slack_client.py` — Slack notifications | 17 |

---

## 4. Run Integration Tests

Integration tests exercise the full `main()` flow with real filesystem access
and mocked HTTP calls.

```bash
docker run --rm flatten-tests \
  uv run pytest tests/test_integration.py -v
```

Expected: **14 passed**

| Class | Description | Tests |
|-------|-------------|-------|
| `TestDetectorFilesystemIntegration` | `detect_files` against real temp files | 6 |
| `TestLoadFlattenConfigIntegration` | Loading `flatten-tests.json` from disk | 2 |
| `TestMainIntegration` | Full `main()` flow: PR created, errors, DRY_RUN, timeout | 6 |

---

## 5. Run All Tests

```bash
docker run --rm flatten-tests \
  uv run pytest -v
```

Expected: **54 passed**

---

## 6. DRY_RUN — Verify Without Calling Devin or Slack

Runs the full pipeline logic without making any real HTTP requests.

```bash
docker run --rm \
  -e DEVIN_API_KEY="cog_dummy" \
  -e DEVIN_ORG_ID="org-dummy" \
  -e SLACK_WEBHOOK_URL="https://hooks.slack.com/dummy" \
  -e TARGET_FILES="superset-frontend/src/visualizations/TimeTable/utils/sortUtils/sortUtils.test.ts" \
  -e GITHUB_ACTOR="your-name" \
  -e GITHUB_REPOSITORY="tishib2/superset" \
  -e GITHUB_SHA="abc123" \
  -e GITHUB_RUN_ID="local-001" \
  -e SKIP_LAUNCH_NOTIFICATION="1" \
  -e DRY_RUN="1" \
  flatten-tests
```

Expected output:

```
[flatten-tests] Using provided TARGET_FILES.
[flatten-tests] Files with describe blocks detected:
[flatten-tests]   - superset-frontend/src/.../sortUtils.test.ts
[flatten-tests] [DRY RUN] Would launch Devin session with prompt:
...
[flatten-tests] [DRY RUN] Would send completion Slack notification: ...
```

---

## 7. Full E2E Run Against Real APIs

### 7-1. Create a `.env` file

```bash
cp docker/flatten-tests/.env.example docker/flatten-tests/.env
# Edit .env with your actual credentials
```

```dotenv
DEVIN_API_KEY=cog_xxxxxxxxxxxx
DEVIN_ORG_ID=org-xxxxxxxxxxxx
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
GITHUB_ACTOR=your-github-username
GITHUB_REPOSITORY=tishib2/superset
GITHUB_SHA=abc123
GITHUB_RUN_ID=local-001
TARGET_FILES=superset-frontend/src/visualizations/TimeTable/utils/sortUtils/sortUtils.test.ts
SKIP_LAUNCH_NOTIFICATION=1
```

### 7-2. Run

```bash
docker run --rm \
  --env-file docker/flatten-tests/.env \
  flatten-tests
```

---

## 8. Trigger via GitHub Actions (E2E on CI)

Push a change to any file under a path listed in `.devin/flatten-tests.json` `targets`
on the `master` branch. The workflow fires automatically.

```bash
# Example: bump the trigger comment in the target test file
sed -i 's/demo v[0-9]*/demo vNEXT/' \
  superset-frontend/src/visualizations/TimeTable/utils/sortUtils/sortUtils.test.ts

git add superset-frontend/src/visualizations/TimeTable/utils/sortUtils/sortUtils.test.ts
git commit -m "test: trigger flatten-tests workflow"
git push origin master
```

Monitor at: `https://github.com/tishib2/superset/actions`

---

## 9. GitHub Secrets Required

Set the following in `Settings > Secrets and variables > Actions`:

| Secret | Description |
|--------|-------------|
| `DEVIN_API_KEY` | Devin API key (starts with `cog_`) |
| `DEVIN_ORG_ID` | Devin Organization ID (starts with `org-`) |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

---

## 10. Configuration

### `.devin/flatten-tests.json`

```json
{
  "targets": [
    "superset-frontend/src/visualizations/TimeTable"
  ],
  "test_command": "cd superset-frontend && npm run test -- --testPathPattern",
  "pr_branch_prefix": "auto/flatten-tests"
}
```

| Field | Description |
|-------|-------------|
| `targets` | Directories to watch (relative to repo root) |
| `test_command` | Command Devin runs after flattening to verify tests pass |
| `pr_branch_prefix` | Branch name prefix for the created PR |

---

## 11. Repository Layout

```
.devin/
├── README.md                    # This file
├── SESSION_NOTES.md             # Design decisions and notes
└── flatten-tests.json           # Watch targets and command config

.github/workflows/
└── flatten-tests.yml            # GitHub Actions workflow (2-job structure)

docker/flatten-tests/
├── Dockerfile                   # Docker image definition
├── flatten_tests/               # Python package
│   ├── models.py                # pydantic models (Config, API response types)
│   ├── detector.py              # describe block detection
│   ├── devin_client.py          # Devin API client (launch, poll, terminate)
│   ├── slack_client.py          # Slack notifications
│   └── main.py                  # Entrypoint
├── tests/
│   ├── test_detector.py         # Unit tests
│   ├── test_devin_client.py     # Unit tests
│   ├── test_slack_client.py     # Unit tests
│   └── test_integration.py      # Integration tests
├── pyproject.toml               # uv project config and dependencies
└── uv.lock                      # Locked dependency versions
```

---

## 12. Slack Notification Colors

| Situation | Color |
|-----------|-------|
| describe blocks detected (start) | Blue `#0088cc` |
| Session completed, PR created | Green `#36a64f` |
| Session timed out | Yellow `#e8a838` |
| Session failed or workflow error | Red `#e01e5a` |
