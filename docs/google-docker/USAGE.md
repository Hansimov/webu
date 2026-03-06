# USAGE

## Inspect Effective Config

```bash
ggdk print-config
```

## Run Service Directly

```bash
python -m webu.google_docker serve --host 0.0.0.0 --port 18000
```

## Local Docker Workflow

Build:

```bash
ggdk docker-build --image webu/google-api:dev
```

Run with mounted configs and live source:

```bash
ggdk docker-run --bind-source --mount-configs --replace
```

Tail logs:

```bash
ggdk docker-logs --follow
```

Stop container:

```bash
ggdk docker-stop
```

## HF Space Workflow

Sync current code:

```bash
ggdk hf-sync --space 1krog/space1
```

Sync and request factory rebuild:

```bash
ggdk hf-sync --space 1krog/space1 --restart --factory
```

Check runtime:

```bash
ggdk hf-status --space 1krog/space1
```

Read remote logs:

```bash
ggdk hf-logs --space 1krog/space1 --admin-token "$(jq -r '.admin_token' configs/google_docker.json)"
```

Squash Space history:

```bash
ggdk hf-super-squash --space 1krog/space1
```

## Live Endpoint Checks

Health:

```bash
curl -L https://1krog-space1.hf.space/health
```

Hidden landing page:

```bash
curl -L https://1krog-space1.hf.space/
```

Admin runtime:

```bash
curl -L -H "X-Admin-Token: $(jq -r '.admin_token' configs/google_docker.json)" https://1krog-space1.hf.space/admin/runtime
```

Search:

```bash
curl -L 'https://1krog-space1.hf.space/search?q=test&num=3'
```
