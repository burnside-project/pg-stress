# Releases & CI/CD

pg-stress uses a fully automated continuous delivery pipeline.
Every push to `main` that passes CI gates produces a release candidate
with multi-arch Docker images published to GHCR.

## Pipeline

```
Push to main
    │
    ▼
CI Gates (parallel)
├── Lint Go          go vet + go build
├── Lint Python      ruff (load-generator-orm, dashboard, truth-service)
├── Test             pytest (truth-service)
├── Compose          docker compose config --quiet
└── Shell            shellcheck
    │
    ▼  all pass
Resolve RC Version
    reads VERSION file → 1.0.0
    finds existing RCs → v1.0.0-rc1, v1.0.0-rc2
    next → v1.0.0-rc3
    │
    ▼
Build & Push (parallel, multi-arch: linux/amd64 + linux/arm64)
├── load-generator      → ghcr.io/.../load-generator:v1.0.0-rc3
├── load-generator-orm  → ghcr.io/.../load-generator-orm:v1.0.0-rc3
├── pgbench-runner      → ghcr.io/.../pgbench-runner:v1.0.0-rc3
├── dashboard           → ghcr.io/.../dashboard:v1.0.0-rc3
└── truth-service       → ghcr.io/.../truth-service:v1.0.0-rc3
    │
    ▼
Publish RC Release
    → GitHub prerelease with auto-generated notes
    → Tag: v1.0.0-rc3
```

## Versioning

pg-stress follows [Semantic Versioning](https://semver.org/):

```
v<major>.<minor>.<patch>[-rc<N>]
```

| Component | When to bump |
|-----------|-------------|
| **major** | Breaking changes to CLI, config, or compose structure |
| **minor** | New services, new load patterns, new features |
| **patch** | Bug fixes, performance improvements |

The target version lives in the `VERSION` file at the repo root.
RC numbers auto-increment per version.

## Workflow Files

| File | Trigger | Purpose |
|------|---------|---------|
| `ci-cd.yml` | PR (CI only) + push to `main` (CI + build + release) | Single pipeline for validation and delivery |
| `release.yml` | Manual dispatch | Promote RC to stable release |

On pull requests, `ci-cd.yml` runs CI gates and a build check.
On push to `main`, it runs the same CI gates, then builds multi-arch images,
publishes an RC release, and commits updated release info back to `RELEASES.md` and `README.md`.

## Docker Images

All images are published to GitHub Container Registry (GHCR) as multi-arch
manifests supporting `linux/amd64` and `linux/arm64`.

### Pull by version

```bash
docker pull ghcr.io/dataalgebra-engineering/pg-stress/load-generator:v1.0.0-rc11
docker pull ghcr.io/dataalgebra-engineering/pg-stress/dashboard:v1.0.0-rc11
```

### Pull latest RC

```bash
for svc in load-generator load-generator-orm pgbench-runner dashboard truth-service; do
  docker pull ghcr.io/dataalgebra-engineering/pg-stress/${svc}:rc-latest
done
```

### Pull latest stable

```bash
for svc in load-generator load-generator-orm pgbench-runner dashboard truth-service; do
  docker pull ghcr.io/dataalgebra-engineering/pg-stress/${svc}:latest
done
```

### Image tags

| Tag | Meaning |
|-----|---------|
| `v1.0.0-rc3` | Specific release candidate |
| `rc-latest` | Most recent RC from any version |
| `v1.0.0` | Stable release |
| `latest` | Most recent stable release |

## How to Cut a Release

### Automatic (every push to main)

Just push to `main`. If CI passes, a new RC is created automatically.

```bash
git push origin main
# → v1.0.0-rc4 created, images pushed to GHCR, GitHub release published
```

### Promote RC to stable

Once an RC is validated in staging:

```bash
gh workflow run release.yml \
  --repo dataalgebra-engineering/pg-stress \
  -f version=v1.0.0
```

This rebuilds all images, tags them with the stable version + `:latest`,
and creates a non-prerelease GitHub release.

### Start a new version

Bump the `VERSION` file and push:

```bash
echo "1.1.0" > VERSION
git commit -am "chore: bump version to 1.1.0"
git push origin main
# → v1.1.0-rc1 created automatically
```

### Skip RC creation

Pushes that only change docs (`*.md`, `docs/**`, `LICENSE`, `.gitignore`)
do not trigger the CD pipeline.

## Auto-Updated Files

The pipeline automatically commits updates to these files after each release:

| File | What gets updated |
|------|------------------|
| `RELEASES.md` | Full release history table, latest version links, install commands |
| `README.md` | Docker pull version in the install section |

These commits use `[skip ci]` to avoid retriggering the pipeline.

## Release Notes

Release notes are auto-generated from:

1. **Git log** — commits since the previous tag
2. **CHANGELOG.md** — `[Unreleased]` section (if present)
3. **Docker image table** — pull commands for every service
4. **Testing instructions** — how to deploy and validate the RC
5. **Promotion command** — one-liner to promote to stable

## CI Gates

All gates must pass before an RC is created. Any failure blocks the release.

| Gate | What it checks |
|------|---------------|
| **Lint Go** | `go vet` + `go build` on `load-generator/` |
| **Lint Python** | `ruff` on load-generator-orm, dashboard, truth-service |
| **Test Truth** | `pytest` on truth-service unit tests |
| **Compose Validate** | Both compose files parse correctly |
| **Lint Shell** | `shellcheck` on scripts |
