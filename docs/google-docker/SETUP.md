# SETUP

## Local Files

Expected local config files:

1. `configs/hf_spaces.json`
2. `configs/llms.json`
3. `configs/captcha.json`
4. `configs/proxies.json`
5. `configs/google_docker.json`

## proxies.json

Example structure:

```json
{
	"google_api": {
		"proxies": [
			{"url": "http://127.0.0.1:11111", "name": "proxy-11111"},
			{"url": "http://127.0.0.1:11119", "name": "proxy-11119"}
		]
	},
	"gemini": {"default_proxy": "http://127.0.0.1:11119"},
	"proxy_api": {"fetch_proxy": "http://127.0.0.1:11119"},
	"searches": {"chrome_proxy": "http://127.0.0.1:11111"}
}
```

If this file is absent on a remote server or inside HF Space, those runtimes naturally operate without local proxies.

## Long-Term Admin Token

Local persistent token now lives in `configs/google_docker.json`.

To rotate it later:

```bash
openssl rand -hex 24
```

Then update `configs/google_docker.json` and resync the Space.

## Local Docker Build

```bash
ggdk docker-build --image webu/google-api:dev
```

## Local Docker Run

```bash
ggdk docker-run --bind-source --mount-configs --replace
```

## HF Space Bootstrap

Current Space target:

```text
1krog/space1
```

Create or update it with:

```bash
ggdk hf-sync --space 1krog/space1
```

If you need a rebuild request after sync:

```bash
ggdk hf-sync --space 1krog/space1 --restart --factory
```
