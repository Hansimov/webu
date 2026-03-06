import threading

from types import SimpleNamespace

from webu.google_docker.helptext import (
    HINTS_DOC_PATH,
    SETUP_DOC_PATH,
    USAGE_DOC_PATH,
    render_hints_markdown,
    render_setup_markdown,
    render_usage_markdown,
)
from webu.google_api.profile_bootstrap import create_encrypted_profile_archive, restore_encrypted_profile_archive
from webu.runtime_settings import GoogleDockerSettings, HfSpaceSettings, assert_public_text_safe
from webu.runtime_settings.schema import CONFIGS_DOC_PATH, render_configs_markdown, validate_config_payload

from webu.google_docker.cli import (
    _resolve_default_space_name,
    build_parser,
    cmd_config_init,
    cmd_docker_check,
    cmd_hf_sync_all,
    cmd_hf_search,
    cmd_hf_check,
    cmd_hf_doctor,
    cmd_hf_super_squash,
    cmd_hf_sync,
    prepare_local_docker_build_context,
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

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18200, "owner/demo")
    assert (bundle_root / "Dockerfile").exists()
    assert (bundle_root / "README.md").exists()
    pyproject_text = (bundle_root / "pyproject.toml").read_text(encoding="utf-8")
    requirements_text = (bundle_root / "requirements.txt").read_text(encoding="utf-8")
    assert "Hansimov" not in pyproject_text
    assert "github.com/Hansimov" not in pyproject_text
    assert requirements_text == ""
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

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18200, "owner/demo")
    pyproject_text = (bundle_root / "pyproject.toml").read_text(encoding="utf-8")
    requirements_text = (bundle_root / "requirements.txt").read_text(encoding="utf-8")

    assert 'dependencies = [' in pyproject_text
    assert '"requests"' in pyproject_text
    assert requirements_text == "requests\nfastapi\n"
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

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18200, "owner/demo")
    archive_path = bundle_root / "bootstrap" / "google_api_profile.bin"
    assert archive_path.exists()
    assert not (bundle_root / "bootstrap" / "google_api_profile").exists()

    restored_dir = tmp_path / "restored"
    restore_encrypted_profile_archive(archive_path, restored_dir, "bootstrap-secret")
    assert (restored_dir / "google_cookies.json").exists()


def test_prepare_space_bundle_falls_back_to_tracked_profile_asset(tmp_path, monkeypatch):
    source_root = tmp_path / "repo"
    tracked_source_dir = tmp_path / "tracked-profile"
    tracked_archive_path = tmp_path / "tracked" / "google_api_profile.bin"
    missing_profile_dir = tmp_path / "missing-profile"
    (source_root / "src" / "webu" / "google_api").mkdir(parents=True)
    for package_name in ["google_docker", "captcha", "fastapis", "runtime_settings"]:
        (source_root / "src" / "webu" / package_name).mkdir(parents=True)
        (source_root / "src" / "webu" / package_name / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "google_api" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "pyproject.toml").write_text("[project]\nname='webu'\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    tracked_source_dir.mkdir(parents=True)
    (tracked_source_dir / "google_cookies.json").write_text("[]\n", encoding="utf-8")
    create_encrypted_profile_archive(tracked_source_dir, tracked_archive_path, "webu")

    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_settings",
        lambda runtime_env=None, service_type=None: SimpleNamespace(profile_dir=missing_profile_dir),
    )
    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_service_profile",
        lambda runtime_env=None, service_type=None, host=None, port=None: {
            "url": "https://example.invalid",
            "type": "hf-space",
            "api_token": "bootstrap-secret",
        },
    )
    monkeypatch.setattr("webu.google_docker.cli.TRACKED_PROFILE_ARCHIVE_PATH", tracked_archive_path)

    bundle_root = prepare_space_bundle(source_root, tmp_path / "out", 18200, "owner/demo")
    archive_path = bundle_root / "bootstrap" / "google_api_profile.bin"
    restored_dir = tmp_path / "restored-from-tracked"
    restore_encrypted_profile_archive(archive_path, restored_dir, "bootstrap-secret")
    assert (restored_dir / "google_cookies.json").exists()


def test_prepare_local_docker_build_context_includes_shared_bootstrap(tmp_path, monkeypatch):
    source_root = tmp_path / "repo"
    tracked_source_dir = tmp_path / "tracked-profile"
    tracked_archive_path = tmp_path / "tracked" / "google_api_profile.bin"
    missing_profile_dir = tmp_path / "missing-profile"
    (source_root / "src" / "webu" / "google_api").mkdir(parents=True)
    for package_name in ["google_docker", "captcha", "fastapis", "runtime_settings"]:
        (source_root / "src" / "webu" / package_name).mkdir(parents=True)
        (source_root / "src" / "webu" / package_name / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "src" / "webu" / "google_api" / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "pyproject.toml").write_text("[project]\nname='webu'\n", encoding="utf-8")
    (source_root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    tracked_source_dir.mkdir(parents=True)
    (tracked_source_dir / "google_cookies.json").write_text("[]\n", encoding="utf-8")
    create_encrypted_profile_archive(tracked_source_dir, tracked_archive_path, "webu")

    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_google_api_settings",
        lambda runtime_env=None, service_type=None: SimpleNamespace(profile_dir=missing_profile_dir),
    )
    monkeypatch.setattr("webu.google_docker.cli.TRACKED_PROFILE_ARCHIVE_PATH", tracked_archive_path)

    bundle_root = prepare_local_docker_build_context(source_root, tmp_path / "out")
    archive_path = bundle_root / "bootstrap" / "google_api_profile.bin"
    restored_dir = tmp_path / "restored-local-docker"
    restore_encrypted_profile_archive(archive_path, restored_dir, "webu")
    assert (bundle_root / "Dockerfile").exists()
    assert (bundle_root / "requirements.txt").read_text(encoding="utf-8") == ""
    assert (bundle_root / "src" / "webu" / "google_api").exists()
    assert (restored_dir / "google_cookies.json").exists()


def test_cli_parser_supports_hf_sync():
    parser = build_parser()
    args = parser.parse_args(["hf-sync", "--space", "owner/demo"])
    assert args.space == "owner/demo"
    assert not hasattr(args, "repo_id")


def test_cli_parser_supports_default_hf_space_resolution():
    parser = build_parser()
    args = parser.parse_args(["hf-status"])
    assert args.space == ""


def test_cli_parser_supports_hf_search():
    parser = build_parser()
    args = parser.parse_args(["hf-search", "OpenAI news", "--num", "5"])
    assert args.query == "OpenAI news"
    assert args.num == 5


def test_cli_parser_supports_hf_check_and_docker_up():
    parser = build_parser()
    hf_args = parser.parse_args(["hf-check", "--check-auth"])
    docker_args = parser.parse_args(["docker-up", "--skip-build"])
    assert hf_args.check_auth is True
    assert docker_args.skip_build is True


def test_cli_parser_supports_hf_doctor_and_config_commands():
    parser = build_parser()
    doctor_args = parser.parse_args(["hf-doctor", "--check-auth", "--lines", "50"])
    schema_args = parser.parse_args(["config-schema", "google_api"])
    check_args = parser.parse_args(["config-check", "--name", "google_api"])
    init_args = parser.parse_args(["config-init", "--name", "google_api", "--force"])
    assert doctor_args.lines == 50
    assert schema_args.name == "google_api"
    assert check_args.name == "google_api"
    assert init_args.force is True


def test_cli_parser_supports_hub_and_multi_space_commands():
    parser = build_parser()
    hub_args = parser.parse_args(["hub-search", "OpenAI news", "--port", "18100"])
    hub_docker_args = parser.parse_args(["hub-docker-up", "--mount-configs", "--replace"])
    create_space_args = parser.parse_args(["hf-create-space", "--space", "owner/space2", "--exist-ok"])
    sync_all_args = parser.parse_args(["hf-sync-all", "--restart", "--max-workers", "4"])
    assert hub_args.port == 18100
    assert hub_docker_args.mount_configs is True
    assert hub_docker_args.replace is True
    assert create_space_args.space == "owner/space2"
    assert sync_all_args.restart is True
    assert sync_all_args.max_workers == 4


def test_root_help_contains_quick_start_examples():
    parser = build_parser()
    help_text = parser.format_help()
    assert "Quick Start:" in help_text
    assert "ggdk hub-check" in help_text


def test_subcommand_help_contains_examples():
    parser = build_parser()
    subparser_action = next(action for action in parser._actions if getattr(action, "choices", None))
    help_text = subparser_action.choices["hf-check"].format_help()
    assert "Examples:" in help_text
    assert "ggdk hf-check --check-auth" in help_text


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
            port=18200,
            image_name="webu/google-api:dev",
            container_name="webu-google-api",
            admin_token="",
            service_log_path=tmp_path / "service.log",
            app_port=18200,
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
        port=18200,
        message="",
        restart=False,
        factory=False,
        admin_token="",
    )

    cmd_hf_sync(args)

    assert recorded["upload_folder"]["delete_patterns"] == "*"


def test_cmd_hf_sync_all_runs_in_parallel(monkeypatch, tmp_path, capsys):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "hf_spaces.json").write_text(
        '[{"space": "owner/space1", "hf_token": "hf_demo", "enabled": true}, {"space": "owner/space2", "hf_token": "hf_demo", "enabled": true}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    thread_ids = set()
    gate = threading.Barrier(2)

    def _fake_sync(sync_args):
        thread_ids.add(threading.get_ident())
        gate.wait(timeout=2)
        return None

    monkeypatch.setattr("webu.google_docker.cli.cmd_hf_sync", _fake_sync)
    monkeypatch.setattr("webu.google_docker.cli._refresh_tracked_profile_asset", lambda preferred_spaces=None: {"action": "unchanged"})

    cmd_hf_sync_all(SimpleNamespace(port=18200, message="", restart=False, factory=False, admin_token="", max_workers=2))
    output = capsys.readouterr().out
    assert '"synced": true' in output
    assert len(thread_ids) == 2


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
    monkeypatch.setattr(
        "webu.google_docker.cli.resolve_hf_space_settings",
        lambda space_name: SimpleNamespace(space_host="https://space2-host.example"),
    )
    monkeypatch.setattr("webu.google_docker.cli.requests.get", _fake_get)

    cmd_hf_search(
        SimpleNamespace(
            query="OpenAI news",
            space="owner/space2",
            num=3,
            lang="en",
            api_token="",
            no_auth=False,
            timeout=60,
        )
    )
    output = capsys.readouterr().out

    assert recorded["url"] == "https://space2-host.example/search"
    assert recorded["params"] == {"q": "OpenAI news", "num": 3, "lang": "en"}
    assert recorded["headers"] == {"X-Api-Token": "search-token"}
    assert '"success": true' in output.lower()


def test_cmd_hf_check_renders_combined_status(monkeypatch, capsys):
    class _Runtime:
        stage = "RUNNING"
        hardware = "cpu-basic"
        requested_hardware = "cpu-basic"

    class _Api:
        def get_space_runtime(self, repo_id):
            return _Runtime()

    class _Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._payload

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/health"):
            return _Response(200, {"status": "ok"})
        if url.endswith("/admin/runtime"):
            return _Response(200, {"service_type": "hf-space"})
        if url.endswith("/search"):
            return _Response(401, {"detail": "Invalid api token"})
        raise AssertionError(url)

    monkeypatch.setattr(
        "webu.google_docker.cli._resolve_hf_api",
        lambda space_name: (_Api(), SimpleNamespace(space_host="https://space-host.example", hf_token="hf_xxx")),
    )
    monkeypatch.setattr("webu.google_docker.cli._resolve_default_space_name", lambda explicit=None: "owner/demo")
    monkeypatch.setattr("webu.google_docker.cli._resolve_hf_service_url", lambda space_name=None: "https://space-host.example")
    monkeypatch.setattr("webu.google_docker.cli._resolve_admin_token", lambda explicit=None: "admin-token")
    monkeypatch.setattr("webu.google_docker.cli.requests.get", _fake_get)

    cmd_hf_check(SimpleNamespace(space="", admin_token="", timeout=30, query="OpenAI news", check_auth=True))
    output = capsys.readouterr().out
    assert '"repo_id": "owner/demo"' in output
    assert '"anonymous_search_status": 401' in output


def test_cmd_hf_doctor_includes_bootstrap_and_commit_details(monkeypatch, capsys):
    class _Runtime:
        stage = "RUNNING"
        hardware = "cpu-basic"
        requested_hardware = "cpu-basic"

    class _Api:
        def get_space_runtime(self, repo_id):
            return _Runtime()

        def list_repo_files(self, repo_id, repo_type):
            return ["README.md", "bootstrap/google_api_profile.bin"]

        def list_repo_commits(self, repo_id, repo_type):
            return [1, 2, 3]

    class _Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._payload

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/health"):
            return _Response(200, {"status": "ok"})
        if url.endswith("/admin/runtime"):
            return _Response(200, {"service_type": "hf-space"})
        if url.endswith("/admin/logs"):
            return _Response(200, {"content": "recent logs"})
        if url.endswith("/search"):
            return _Response(401, {"detail": "Invalid api token"})
        raise AssertionError(url)

    monkeypatch.setattr(
        "webu.google_docker.cli._resolve_hf_api",
        lambda space_name: (_Api(), SimpleNamespace(space_host="https://space-host.example", hf_token="hf_xxx")),
    )
    monkeypatch.setattr("webu.google_docker.cli._resolve_default_space_name", lambda explicit=None: "owner/demo")
    monkeypatch.setattr("webu.google_docker.cli._resolve_hf_service_url", lambda space_name=None: "https://space-host.example")
    monkeypatch.setattr("webu.google_docker.cli._resolve_admin_token", lambda explicit=None: "admin-token")
    monkeypatch.setattr("webu.google_docker.cli.requests.get", _fake_get)

    cmd_hf_doctor(SimpleNamespace(space="", admin_token="", timeout=30, query="OpenAI news", check_auth=True, lines=80))
    output = capsys.readouterr().out
    assert '"bootstrap_files": [' in output
    assert '"commit_count": 3' in output
    assert 'recent logs' in output


def test_cmd_docker_check_renders_local_status(monkeypatch, capsys):
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_get(url, headers=None, timeout=None):
        if url.endswith("/health"):
            return _Response({"status": "ok"})
        if url.endswith("/admin/runtime"):
            return _Response({"service_type": "docker"})
        raise AssertionError(url)

    monkeypatch.setattr("webu.google_docker.cli._container_running", lambda name: True)
    monkeypatch.setattr("webu.google_docker.cli._resolve_admin_token", lambda explicit=None: "admin-token")
    monkeypatch.setattr("webu.google_docker.cli.requests.get", _fake_get)

    cmd_docker_check(SimpleNamespace(name="", port=18200, admin_token="", timeout=15))
    output = capsys.readouterr().out
    assert '"running": true' in output.lower()
    assert '"service_url": "http://127.0.0.1:18200"' in output


def test_cmd_docker_check_reports_direct_process_hint(monkeypatch, capsys):
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    monkeypatch.setattr("webu.google_docker.cli._container_running", lambda name: False)
    monkeypatch.setattr("webu.google_docker.cli._resolve_admin_token", lambda explicit=None: "admin-token")
    monkeypatch.setattr("webu.google_docker.cli._detect_port_listener", lambda port: "LISTEN 0 128 127.0.0.1:18200 users:(('python',pid=1234,fd=8))")
    monkeypatch.setattr(
        "webu.google_docker.cli.requests.get",
        lambda url, headers=None, timeout=None: _Response({"status": "ok"}),
    )

    cmd_docker_check(SimpleNamespace(name="", port=18200, admin_token="", timeout=15))
    output = capsys.readouterr().out
    assert '"runtime_error": "docker container is not running"' in output
    assert 'python' in output


def test_usage_doc_matches_shared_help_source():
    assert USAGE_DOC_PATH.read_text(encoding="utf-8") == render_usage_markdown()
    assert_public_text_safe(render_usage_markdown())


def test_setup_doc_matches_shared_help_source():
    assert SETUP_DOC_PATH.read_text(encoding="utf-8") == render_setup_markdown()
    assert_public_text_safe(render_setup_markdown())


def test_hints_doc_matches_shared_help_source():
    assert HINTS_DOC_PATH.read_text(encoding="utf-8") == render_hints_markdown()
    assert_public_text_safe(render_hints_markdown())


def test_configs_doc_matches_schema_source():
    assert CONFIGS_DOC_PATH.read_text(encoding="utf-8") == render_configs_markdown()
    assert_public_text_safe(render_configs_markdown())


def test_config_schema_validator_reports_errors():
    errors = validate_config_payload("google_api", {"host": "0.0.0.0", "port": "18200", "services": []})
    assert any("expected integer" in error for error in errors)


def test_cmd_config_init_writes_missing_templates(monkeypatch, tmp_path, capsys):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    cmd_config_init(SimpleNamespace(name="google_api", force=False))
    output = capsys.readouterr().out

    assert '"action": "written"' in output
    assert (config_dir / "google_api.json").exists()


def test_cmd_config_init_skips_existing_without_force(monkeypatch, tmp_path, capsys):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "google_api.json"
    config_path.write_text('{"custom": true}\n', encoding="utf-8")
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    cmd_config_init(SimpleNamespace(name="google_api", force=False))
    output = capsys.readouterr().out

    assert '"action": "skipped"' in output
    assert config_path.read_text(encoding="utf-8") == '{"custom": true}\n'