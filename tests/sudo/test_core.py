import signal
import subprocess

from webu.sudo.core import _merge_input, build_command, signal_process


def test_build_command_uses_sudopass(monkeypatch):
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    monkeypatch.setenv("SUDOPASS", "secret")

    prepared = build_command(["echo", "hello"], preserve_env={"PATH": "/usr/bin"})

    assert prepared.argv[:4] == ["sudo", "-S", "env", "PATH=/usr/bin"]
    assert prepared.argv[-2:] == ["echo", "hello"]
    assert prepared.stdin_data == b"secret\n"


def test_signal_process_falls_back_to_sudo(monkeypatch):
    recorded = {}

    def fake_kill(target, sig):
        raise PermissionError()

    def fake_run(command, **kwargs):
        recorded["command"] = command

        class _Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Result()

    monkeypatch.setattr("os.kill", fake_kill)
    monkeypatch.setattr("webu.sudo.core.run", fake_run)

    signal_process(1234, signal.SIGTERM, process_group=True)

    assert recorded["command"] == ["kill", f"-{signal.SIGTERM}", "--", "-1234"]


def test_merge_input_decodes_sudo_password_for_text_mode() -> None:
    merged = _merge_input(b"secret\n", None, text_mode=True)

    assert merged == "secret\n"


def test_run_supports_text_mode_with_sudopass(monkeypatch):
    recorded = {}

    def fake_subprocess_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded["input"] = kwargs.get("input")

        class _Result(subprocess.CompletedProcess):
            def __init__(self):
                super().__init__(args=argv, returncode=0, stdout="", stderr="")

        return _Result()

    monkeypatch.setattr("os.geteuid", lambda: 1000)
    monkeypatch.setenv("SUDOPASS", "secret")
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    from webu.sudo.core import run

    run(["echo", "hello"], text=True, capture_output=True)

    assert recorded["argv"][:2] == ["sudo", "-S"]
    assert recorded["input"] == "secret\n"
