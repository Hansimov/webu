from types import SimpleNamespace

from webu.runtime_settings import GoogleDockerSettings, HfSpaceSettings

from webu.google_docker.cli import build_parser, cmd_hf_super_squash, cmd_hf_sync, prepare_space_bundle


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


def test_cli_parser_supports_hf_sync():
    parser = build_parser()
    args = parser.parse_args(["hf-sync", "--space", "owner/demo"])
    assert args.space == "owner/demo"


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