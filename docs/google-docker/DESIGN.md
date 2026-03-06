# DESIGN

## Goals

`google_docker` wraps `webu.google_api` so the same service can run in three modes:

1. Local source-driven debugging.
2. Local Docker runtime that can still reach host-only proxy ports.
3. Remote Hugging Face Docker Space deployment.

## Architecture

The runtime split is centralized in `webu.runtime_settings`.

Important rules:

1. Secrets are injected at runtime, never baked into the image.
2. HF uploads use a minimal bundle, not the full repo.
3. HF bundle writes a sanitized `pyproject.toml` without author metadata or repo URLs.
4. Local proxy addresses live only in `configs/proxies.json`.
5. Remote server and HF Space do not rely on local proxy config.

## Runtime Model

`local`
Used for direct source execution on the workstation. Local proxy config can be read from `configs/proxies.json`.

`docker`
Used for local container runs. If `configs/` is mounted, local proxies are read and rewritten from `127.0.0.1` to `host.docker.internal` or `127.0.0.1` depending on network mode.

`hf-space`
Used for the deployed Space. Proxy mode defaults to disabled. The landing page is intentionally generic and does not advertise API functionality.

## HF Deployment Design

The CLI prepares a reduced upload bundle containing only:

1. `captcha`
2. `fastapis`
3. `google_api`
4. `google_docker`
5. `runtime_settings`

The sync flow also deletes stale remote files with `delete_patterns="*"` so unrelated or previously leaked files do not remain in the Space repo.

## Admin Surface

`/admin/runtime`
Runtime summary and effective environment.

`/admin/config`
Effective service config without exposing the token value.

`/admin/logs`
Service log tail.

All `/admin/*` routes are protected by `WEBU_ADMIN_TOKEN`.