from fastapi import FastAPI
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
