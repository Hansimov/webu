# HINTS

## Environment Notes

Local workstation:

1. `configs/proxies.json` is the only place where local proxy addresses should live.
2. `google_api`, `gemini`, `proxy_api`, and `searches` now read from that file instead of code literals.

Local Docker:

1. Use `--mount-configs` if you expect the container to see local proxy config.
2. On Linux, host-only proxies bound to `127.0.0.1` still require host networking when proxy mode is enabled.

Remote server:

1. Do not ship `configs/proxies.json` unless that host really owns local proxies.
2. Prefer `WEBU_GOOGLE_PROXY_MODE=disabled`.

HF Space:

1. The root page is intentionally generic and should not be used as a service indicator.
2. Secrets are managed through HF Space secrets, not repo files.
3. If rebuild control endpoints are flaky, `hf-sync` can still update repo contents without restart.

## Debug Commands

List current Space repo files:

```bash
python - <<'PY'
from huggingface_hub import HfApi
from webu.runtime_settings import resolve_hf_space_settings
settings = resolve_hf_space_settings('1krog/space1')
api = HfApi(token=settings.hf_token)
for name in sorted(api.list_repo_files(repo_id='1krog/space1', repo_type='space')):
	print(name)
PY
```

Check commit count after squash:

```bash
python - <<'PY'
from huggingface_hub import HfApi
from webu.runtime_settings import resolve_hf_space_settings
settings = resolve_hf_space_settings('1krog/space1')
api = HfApi(token=settings.hf_token)
print(len(api.list_repo_commits(repo_id='1krog/space1', repo_type='space')))
PY
```

## Common Failure Modes

`PAUSED`
The Space has not been woken or rebuilt yet.

`APP_STARTING`
The image built successfully and is still booting.

`503` on restart endpoint
Control plane issue. Try syncing without restart first, then re-check the Space host.
