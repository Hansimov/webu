from types import SimpleNamespace

from webu.google_api.profile_bootstrap import restore_encrypted_profile_archive
from webu.runtime_settings import GoogleDockerSettings, HfSpaceSettings

from webu.google_docker.cli import (
    _resolve_default_space_name,
    build_parser,
    cmd_hf_search,
    cmd_hf_super_squash,
    cmd_hf_sync,
    prepare_space_bundle,
)


def test_prepare_space_bundle_excludes_configs(tmp_path):
    source_root = tmp_path / "repo"
    (source_root / "src" / "webu").mkdir(parents=True)
    for package_name in ["google_api", "google_docker", "captcha", "fastapis", "runtime_settings", "gemini", "warp_api", "ipv6"]:
        (source_root / "src" / "webu" / package_name).mkdir(parents=True)
    (source_root / "configs").mkdir()
    (source_root / "data").mkdir()
    (source_root / "pyproject.toml").write_text("[project]\nname='webu'\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (source_root / "src" / "webu" / "__init__.py").write_text("from .gemini import x\n", encoding="utf-8")
    (source_root / "src" / "webu" / "google_api" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "google_docker" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "captcha" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "captcha" / "imgs").mkdir(parents=True)
    (source_root / "src" / "webu" / "captcha" / "imgs" / "verify.jpg").write_text("img\n", encoding="utf-8")
    (source_root / "src" / "webu" / "fastapis" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "runtime_settings" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "gemini" / "secret.py").write_text("secret\n", encoding="utf-8")
    (source_root / "src" / "webu" / "warp_api" / "server.py").write_text("warp\n", encoding="utf-8")
    (source_root / "src" / "webu" / "ipv6" / "ipv6_global_addrs.json").write_text("[]\n", encoding="utf-8")
    (source_root / "configs" / "captcha.json").write_text("{}", encoding="utf-8")

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18000, "owner/demo")
    assert (bundle_root / "Dockerfile").exists()
    assert (bundle_root / "README.md").exists()
    pyproject_text = (bundle_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "Hansimov" not in pyproject_text
    assert "github.com/Hansimov" not in pyproject_text
    assert not (bundle_root / "configs").exists()
    assert not (bundle_root / "src" / "webu" / "gemini").exists()
    assert not (bundle_root / "src" / "webu" / "warp_api").exists()
    assert not (bundle_root / "src" / "webu" / "ipv6").exists()
    assert not (bundle_root / "src" / "webu" / "captcha" / "imgs").exists()
    assert (bundle_root / "src" / "webu" / "google_api").exists()
    assert (bundle_root / "src" / "webu" / "__init__.py").read_text(encoding="utf-8") == "__all__ = []\n"


def test_prepare_space_bundle_preserves_dependencies_and_scripts(tmp_path):
    source_root = tmp_path / "repo"
    (source_root / "src" / "webu" / "google_api").mkdir(parents=True)
    for package_name in ["google_docker", "captcha", "fastapis", "runtime_settings"]:
        (source_root / "src" / "webu" / package_name).mkdir(parents=True)
        (source_root / "src" / "webu" / package_name / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "google_api" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "pyproject.toml").write_text(
        """
[project]
name = \"webu\"
version = \"0.1.0\"
authors = [{ name = \"Hansimov\" }]
dependencies = [\"requests\", \"fastapi\"]

[project.urls]
Homepage = \"https://github.com/Hansimov/webu\"

[project.scripts]
ggdk = \"webu.google_docker.cli:main\"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18000, "owner/demo")
    pyproject_text = (bundle_root / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dependencies = [' in pyproject_text
    assert '"requests"' in pyproject_text
    assert '[project.scripts]' in pyproject_text
    assert 'ggdk = "webu.google_docker.cli:main"' in pyproject_text
    assert 'authors' not in pyproject_text
    assert 'project.urls' not in pyproject_text


def test_prepare_space_bundle_includes_encrypted_profile_bootstrap(tmp_path, monkeypatch):
    source_root = tmp_path / "repo"
    profile_dir = tmp_path / "profile"
    (source_root / "src" / "webu" / "google_api").mkdir(parents=True)
    for package_name in ["google_docker", "captcha", "fastapis", "runtime_settings"]:
        (source_root / "src" / "webu" / package_name).mkdir(parents=True)
        (source_root / "src" / "webu" / package_name / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "google_api" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "pyproject.toml").write_text("[project]\nname='webu'\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    profile_dir.mkdir(parents=True)
    (profile_dir / "google_cookies.json").write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_settings",
        lambda runtime_env=None, service_type=None: SimpleNamespace(profile_dir=profile_dir),
    )
    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_service_profile",
        lambda runtime_env=None, service_type=None, host=None, port=None: {
            "url": "https://example.invalid",
            "type": "hf-space",
            "api_token": "bootstrap-secret",
        },
    )

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18000, "owner/demo")
    archive_path = bundle_root / "bootstrap" / "google_api_profile.bin"
    assert archive_path.exists()
    assert not (bundle_root / "bootstrap" / "google_api_profile").exists()

    restored_dir = tmp_path / "restored"
    restore_encrypted_profile_archive(archive_path, restored_dir, "bootstrap-secret")
    assert (restored_dir / "google_cookies.json").exists()


def test_cli_parser_supports_hf_sync():
    parser = build_parser()
    args = parser.parse_args(["hf-sync", "--space", "owner/demo"])
    assert args.space == "owner/demo"


def test_cli_parser_supports_default_hf_space_resolution():
    parser = build_parser()
    args = parser.parse_args(["hf-status"])
    assert args.space == ""


def test_cli_parser_supports_hf_search():
    parser = build_parser()
    args = parser.parse_args(["hf-search", "OpenAI news", "--num", "5"])
    assert args.query == "OpenAI news"
    assert args.num == 5


def test_cli_parser_supports_factory_restart_during_sync():
    parser = build_parser()
    args = parser.parse_args(["hf-sync", "--space", "owner/demo", "--restart", "--factory"])
    assert args.restart is True
    assert args.factory is True


def test_cli_parser_supports_hf_super_squash():
    parser = build_parser()
    args = parser.parse_args(["hf-super-squash", "--space", "owner/demo", "--branch", "main"])
    assert args.space == "owner/demo"
    assert args.branch == "main"


def test_cmd_hf_super_squash_uses_space_repo_type(monkeypatch):
    recorded = {}

    class _FakeApi:
        def super_squash_history(self, repo_id, repo_type, branch):
            recorded["repo_id"] = repo_id
            recorded["repo_type"] = repo_type
            recorded["branch"] = branch

    monkeypatch.setattr(
        "webu.google_docker.cli._resolve_hf_api",
        lambda space_name: (_FakeApi(), SimpleNamespace(hf_token="hf_xxx")),
    )

    cmd_hf_super_squash(SimpleNamespace(space="owner/demo", branch="main"))

    assert recorded == {
        "repo_id": "owner/demo",
        "repo_type": "space",
        "branch": "main",
    }


def test_cmd_hf_sync_deletes_stale_remote_files(monkeypatch, tmp_path):
    recorded = {}

    class _FakeApi:
        def create_repo(self, **kwargs):
            recorded["create_repo"] = kwargs

        def upload_folder(self, **kwargs):
            recorded["upload_folder"] = kwargs

        def add_space_variable(self, **kwargs):
            recorded.setdefault("variables", []).append(kwargs)

        def add_space_secret(self, **kwargs):
            recorded.setdefault("secrets", []).append(kwargs)

    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()

    monkeypatch.setattr(
        "webu.google_docker.cli._resolve_hf_api",
        lambda space_name: (
            _FakeApi(),
            HfSpaceSettings(repo_id=space_name, hf_token="hf_xxx", space_host="https://example.hf.space"),
        ),
    )
    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_docker_settings",
        lambda: GoogleDockerSettings(
            host="0.0.0.0",
            port=18000,
            image_name="webu/google-api:dev",
            container_name="webu-google-api",
            admin_token="",
            service_log_path=tmp_path / "service.log",
            app_port=18000,
            runtime_env="local",
            project_root=tmp_path,
            config_dir=tmp_path / "configs",
        ),
    )
    monkeypatch.setattr(
        "webu.google_docker.cli.get_workspace_paths",
        lambda: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(
        "webu.google_docker.cli.prepare_space_bundle",
        lambda source_root, output_root, app_port, repo_id: bundle_root,
    )
    monkeypatch.setattr("webu.google_docker.cli._sync_space_runtime_config", lambda api, space_name, admin_token: None)

    args = SimpleNamespace(
        space="owner/demo",
        repo_id="",
        port=18000,
        message="",
        restart=False,
        factory=False,
        admin_token="",
    )

    cmd_hf_sync(args)

    assert recorded["upload_folder"]["delete_patterns"] == "*"


def test_resolve_default_space_name_reads_first_configured_space(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "hf_spaces.json").write_text(
        '[{"space": "owner/demo", "hf_token": "hf_xxx"}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    assert _resolve_default_space_name("") == "owner/demo"


def test_cmd_hf_search_uses_resolved_url_and_token(monkeypatch, capsys):
    recorded = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "query": "OpenAI news"}

    def _fake_get(url, params=None, headers=None, timeout=None):
        recorded["url"] = url
        recorded["params"] = params
        recorded["headers"] = headers
        recorded["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_service_profile",
        lambda runtime_env=None, service_type=None, host=None, port=None: {
            "url": "https://space-host.example",
            "type": "hf-space",
            "api_token": "search-token",
        },
    )
    monkeypatch.setattr("webu.google_docker.cli.requests.get", _fake_get)

    cmd_hf_search(
        SimpleNamespace(
            query="OpenAI news",
            num=3,
            lang="en",
            api_token="",
            no_auth=False,
            timeout=60,
        )
    )
    output = capsys.readouterr().out

    assert recorded["url"] == "https://space-host.example/search"
    assert recorded["params"] == {"q": "OpenAI news", "num": 3, "lang": "en"}
    assert recorded["headers"] == {"X-Api-Token": "search-token"}
    assert '"success": true' in output.lower()