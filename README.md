# ActionDash

Realtime GitHub Actions dashboard — monitor CI/CD workflows across all your repos in one place.

![Version](https://img.shields.io/badge/version-2026.02-blue)
![Deploy](https://github.com/ZechCodes/ActionDash/actions/workflows/deploy.yaml/badge.svg)
![Tests](https://github.com/ZechCodes/ActionDash/actions/workflows/test.yaml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- Real-time webhook-driven workflow run and job tracking
- Per-repo monitoring with automatic GitHub webhook management
- Daily success/failure charts with 60-day history
- Step-level progress summaries for in-progress runs
- SSE-based live dashboard updates
- GitHub OAuth login
- Multi-user support with per-user repo monitoring

## Tech Stack

- **Backend:** Python 3.13, Litestar, SQLAlchemy (async), Skrift CMS
- **Database:** PostgreSQL 17
- **Cache/PubSub:** Redis
- **Deployment:** Docker, Kubernetes (DigitalOcean)

## Self-Hosting

### Prerequisites

- Python 3.13+
- PostgreSQL 17+
- Redis
- GitHub OAuth App

### Quick Start with Docker Compose

1. Clone the repository:

   ```bash
   git clone https://github.com/ZechCodes/ActionDash.git
   cd ActionDash
   ```

2. Start the services:

   ```bash
   podman compose up
   ```

   This starts PostgreSQL, runs database migrations, and launches the app on `http://localhost:8080`.

### GitHub OAuth App Setup

1. Go to **GitHub Settings > Developer Settings > OAuth Apps > New OAuth App**
2. Set the **Authorization callback URL** to `http://localhost:8080/auth/github/callback`
3. Note the **Client ID** and **Client Secret**

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) | Yes |
| `SECRET_KEY` | Session encryption key | Yes |
| `AUTH_REDIRECT_BASE_URL` | Base URL for OAuth callbacks | Yes |
| `GITHUB_CLIENT_ID` | GitHub OAuth app client ID | Yes |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth app client secret | Yes |
| `GITHUB_WEBHOOK_SECRET` | Shared secret for webhook HMAC verification | Recommended |
| `REDIS_URL` | Redis connection string | Yes |

### Database Migrations

```bash
uv run python -m actiondash.initdb
```

### Kubernetes Deployment

The `k8s/` directory contains production manifests managed with [Kustomize](https://kustomize.io/) (built into `kubectl`).

1. **Set your namespace** in `k8s/kustomization.yaml`
2. **Edit placeholder values** — search for `CHANGEME` in:
   - `k8s/configmap.yaml` — domain and cookie settings
   - `k8s/ingress.yaml` — hostname, ingress class, and cluster-issuer
   - `k8s/deploy-actiondash.yaml`, `k8s/deploy-step-worker.yaml`, `k8s/init-db-job.yaml` — Redis URL
3. **Create secrets** — copy `k8s/secrets.template.yaml` to `k8s/secrets.yaml`, fill in base64-encoded values, and apply:
   ```bash
   kubectl apply -f k8s/secrets.yaml
   ```
4. **Deploy**:
   ```bash
   kubectl apply -k k8s/
   ```

## Local Development

```bash
# Install dependencies
uv sync --group dev

# Start PostgreSQL
podman compose up -d db

# Run database migrations
uv run python -m actiondash.initdb

# Run the app
uv run python -m actiondash

# Run tests
uv run pytest -v
```

## License

MIT
