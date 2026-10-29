"""CLI 端到端测试：命令存在性、JSON 输出、退出码、错误处理。"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harscope.cli import EXIT_ERROR, EXIT_OK, EXIT_VIOLATION, build_parser, main  # noqa: E402

from har_fixture import sample_json  # noqa: E402


class CliTestCase(unittest.TestCase):
    """提供一份样本 HAR 文件。"""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile("w", suffix=".har", delete=False,
                                                encoding="utf-8")
        self._tmp.write(sample_json())
        self._tmp.close()
        self.sample = self._tmp.name

    def tearDown(self) -> None:
        os.unlink(self.sample)

    def run_cli(self, *args: str) -> tuple[int, str]:
        """执行 CLI 并返回 ``(退出码, 标准输出)``。"""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(list(args))
        return code, buffer.getvalue()


class TestBasics(CliTestCase):
    """基础行为。"""

    def test_version_flag(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as ctx:
                build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("harscope", buffer.getvalue())

    def test_no_command_prints_help(self) -> None:
        code, output = self.run_cli()
        self.assertEqual(code, EXIT_OK)

    def test_all_commands_available(self) -> None:
        parser = build_parser()
        sub_actions = [
            action for action in parser._subparsers._group_actions[0].choices.items()
        ]
        names = {name for name, _sub in sub_actions}
        self.assertTrue({
            "summary", "waterfall", "domains", "mime", "slow", "largest",
            "status", "pages", "dupes", "security", "export", "report",
            "ci", "record", "doctor",
        }.issubset(names))

    def test_missing_file_returns_error(self) -> None:
        code, _output = self.run_cli("summary", "/nope/nothing.har")
        self.assertEqual(code, EXIT_ERROR)

    def test_no_color_flag(self) -> None:
        code, output = self.run_cli("--no-color", "summary", self.sample)
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("\033[", output)


class TestSummaryCommands(CliTestCase):
    """只读命令的输出。"""

    def test_summary_text(self) -> None:
        code, output = self.run_cli("--no-color", "summary", self.sample)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("会话总览", output)
        self.assertIn("状态码分布", output)

    def test_summary_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "summary", self.sample)
        payload = json.loads(output)
        self.assertEqual(payload["requests"], 14)

    def test_domains_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "domains", self.sample)
        self.assertIn("domains", json.loads(output))

    def test_status_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "status", self.sample)
        payload = json.loads(output)
        self.assertEqual(sum(payload["classes"].values()), 14)

    def test_pages_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "pages", self.sample)
        self.assertEqual(len(json.loads(output)["pages"]), 1)

    def test_dupes_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "dupes", self.sample)
        self.assertEqual(len(json.loads(output)["duplicates"]), 1)

    def test_slow_by_wait(self) -> None:
        code, _ = self.run_cli("--no-color", "slow", self.sample, "--by", "wait", "--top", "3")
        self.assertEqual(code, EXIT_OK)


class TestGlobalFlagsAfterSubcommand(CliTestCase):
    """通用开关放在子命令之后也必须生效。"""

    def test_json_after_subcommand(self) -> None:
        for command in ("summary", "domains", "status", "pages", "dupes", "security"):
            with self.subTest(command=command):
                code, output = self.run_cli("--no-color", command, self.sample, "--json")
                self.assertEqual(code, EXIT_OK)
                json.loads(output)

    def test_json_before_subcommand(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "summary", self.sample)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(output)["requests"], 14)

    def test_no_color_after_subcommand(self) -> None:
        code, output = self.run_cli("summary", self.sample, "--no-color")
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("\x1b[", output)


class TestExports(CliTestCase):
    """导出命令落盘。"""

    def test_export_json_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.json")
            code, _ = self.run_cli("--no-color", "export", self.sample,
                                   "--format", "json", "-o", target)
            self.assertEqual(code, EXIT_OK)
            self.assertTrue(os.path.getsize(target) > 100)
            csv_target = os.path.join(tmp, "out.csv")
            code, _ = self.run_cli("--no-color", "export", self.sample,
                                   "--format", "csv", "-o", csv_target)
            self.assertEqual(code, EXIT_OK)

    def test_report_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.html")
            code, _ = self.run_cli("--no-color", "report", self.sample, "-o", target)
            self.assertEqual(code, EXIT_OK)
            with open(target, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("<svg", content)

    def test_export_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.json")
            self.run_cli("--no-color", "export", self.sample, "-o", target)
            code, _ = self.run_cli("--no-color", "export", self.sample, "-o", target)
            self.assertEqual(code, EXIT_ERROR)
            code, _ = self.run_cli("--no-color", "export", self.sample,
                                   "-o", target, "--force")
            self.assertEqual(code, EXIT_OK)


class TestCiGate(CliTestCase):
    """CI 门禁退出码。"""

    def test_pass_with_loose_thresholds(self) -> None:
        code, output = self.run_cli(
            "--no-color", "ci", self.sample,
            "--max-requests", "100", "--max-transfer-kb", "100000",
        )
        self.assertEqual(code, EXIT_OK)
        self.assertIn("✅", output)

    def test_fail_with_tight_threshold(self) -> None:
        code, output = self.run_cli(
            "--no-color", "ci", self.sample, "--max-requests", "1",
        )
        self.assertEqual(code, EXIT_VIOLATION)
        self.assertIn("❌", output)

    def test_ci_json_payload(self) -> None:
        code, output = self.run_cli(
            "--no-color", "--json", "ci", self.sample, "--max-requests", "1000",
        )
        payload = json.loads(output)
        self.assertTrue(payload["passed"])

    def test_ci_without_thresholds_passes(self) -> None:
        code, _ = self.run_cli("--no-color", "ci", self.sample)
        self.assertEqual(code, EXIT_OK)

    def test_require_https_fails_on_sample(self) -> None:
        code, _ = self.run_cli("--no-color", "ci", self.sample, "--require-https")
        self.assertEqual(code, EXIT_VIOLATION)


class TestSecurityCommand(CliTestCase):
    """安全命令与 fail-on 阈值。"""

    def test_security_text(self) -> None:
        code, output = self.run_cli("--no-color", "security", self.sample)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("综合评分", output)

    def test_fail_on_high(self) -> None:
        code, _ = self.run_cli("--no-color", "security", self.sample, "--fail-on", "high")
        self.assertEqual(code, EXIT_VIOLATION)

    def test_fail_on_none_passes(self) -> None:
        code, _ = self.run_cli("--no-color", "security", self.sample, "--fail-on", "none")
        self.assertEqual(code, EXIT_OK)


class TestDoctor(CliTestCase):
    """自检命令。"""

    def test_doctor_runs(self) -> None:
        code, output = self.run_cli("--no-color", "doctor")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("环境自检", output)

    def test_doctor_json(self) -> None:
        code, output = self.run_cli("--no-color", "--json", "doctor")
        self.assertIn("python", json.loads(output))


class TestSubprocessEntry(unittest.TestCase):
    """以子进程方式验证 ``python -m harscope`` 可用。"""

    def test_module_invocation(self) -> None:
        import os
        import tempfile

        from har_fixture import sample_json

        with tempfile.NamedTemporaryFile("w", suffix=".har", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(sample_json())
            path = handle.name
        try:
            env = dict(os.environ, PYTHONPATH=SRC, NO_COLOR="1")
            result = subprocess.run(
                [sys.executable, "-m", "harscope", "summary", path],
                capture_output=True, text=True, env=env, cwd=ROOT, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("会话总览", result.stdout)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
