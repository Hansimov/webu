from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse

SWAGGER_CUSTOM_CSS = """
/* Hide curl command */
.curl-command {
    display: none !important;
}
/* Hide /openapi.json link under title */
.info .link {
    display: none !important;
}
/* Hide OAS3.1 badge */
.version-stamp {
    display: none !important;
}
/* Hide 422 Validation Error responses */
tr.response[data-code="422"] {
    display: none !important;
}
"""


def setup_swagger_ui(app: FastAPI):
    """
    Setup custom Swagger UI for FastAPI app.
    Hides Curl command and static Responses documentation,
    but keeps live Server response visible.
    """
    title = app.title or "FastAPI"

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def swagger_ui():
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <style>{SWAGGER_CUSTOM_CSS}</style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        SwaggerUIBundle({{
            url: "/openapi.json",
            dom_id: "#swagger-ui",
            defaultModelsExpandDepth: -1,
        }});
    </script>
</body>
</html>
"""


def setup_root_landing_page(app: FastAPI, title: str, message: str):
    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def landing_page():
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <meta name=\"robots\" content=\"noindex,nofollow\">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #f4f5f7;
            color: #4b5563;
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
        }}
        main {{
            width: min(520px, calc(100vw - 40px));
            padding: 28px 32px;
            border: 1px solid #dde1e6;
            border-radius: 12px;
            background: #ffffff;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }}
        h1 {{
            margin: 0 0 10px;
            font-size: 18px;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #111827;
        }}
        p {{
            margin: 0;
            font-size: 14px;
            line-height: 1.6;
            color: #6b7280;
        }}
    </style>
</head>
<body>
    <main>
        <h1>{title}</h1>
        <p>{message}</p>
    </main>
</body>
</html>
"""


def setup_root_redirect_page(app: FastAPI, target_path: str):
    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url=target_path, status_code=307)
