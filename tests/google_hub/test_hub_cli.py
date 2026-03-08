import subprocess
import sys

from webu.google_hub.cli import build_parser


def test_hub_cli_parser_supports_core_commands():
    parser = build_parser()
    benchmark_args = parser.parse_args(
        ["benchmark", "--requests", "20", "--concurrency", "5"]
    )
    search_args = parser.parse_args(["search", "OpenAI news", "--num", "3"])
    check_args = parser.parse_args(["check", "--port", "18100"])
    start_args = parser.parse_args(["start"])

    assert benchmark_args.requests == 20
    assert benchmark_args.concurrency == 5
    assert benchmark_args.timeout == 60
    assert search_args.query == "OpenAI news"
    assert search_args.num == 3
    assert search_args.timeout == 60
    assert check_args.port == 18100
    assert start_args.exclude_nodes == "local-google-api"
    assert start_args.request_timeout == 60


def test_hub_cli_help_lists_benchmark_and_backends():
    result = subprocess.run(
        [sys.executable, "-m", "webu.google_hub", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    output = result.stdout.lower()
    assert "gghb" in output
    assert "benchmark" in output
    assert "backends" in output
