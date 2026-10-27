"""Authorized, isolated evaluation execution for a deliberately small action allowlist."""

import subprocess
import time
from dataclasses import dataclass

from acil.config import get_settings

ACTION_COMMANDS = {
    "CHECK_DEPENDENCIES": "test -f pyproject.toml && uv --version",
    "PREPARE_ENVIRONMENT": "uv sync --locked --no-install-project",
    "RUN_TESTS": "uv run --no-sync pytest -q",
}


@dataclass(frozen=True)
class RunnerResult:
    observed_actions: list[str]
    outcome: str
    evidence: dict


class DockerEvaluationRunner:
    """Runs fixed action templates in a prebuilt image with no network or host mounts.

    This is an authorization boundary: image selection is server configuration, never
    request payload or LLM output. Images must contain the repository and `uv`.
    """

    def __init__(self, image: str, timeout_seconds: int, executor=subprocess.run):
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.executor = executor

    @classmethod
    def from_settings(cls) -> "DockerEvaluationRunner":
        settings = get_settings()
        if not settings.evaluation_runner_enabled:
            raise RuntimeError("ACIL evaluation runner is disabled by configuration")
        if not settings.evaluation_docker_image:
            raise RuntimeError("ACIL_EVALUATION_DOCKER_IMAGE is required for isolated evaluation")
        return cls(settings.evaluation_docker_image, settings.evaluation_timeout_seconds)

    def run(self, actions: list[str]) -> RunnerResult:
        unsupported = [action for action in actions if action not in ACTION_COMMANDS]
        if unsupported:
            raise ValueError(f"Unsupported evaluation actions: {', '.join(unsupported)}")
        if not actions:
            raise ValueError("At least one evaluation action is required")

        script_lines = ["set -eu"]
        for action in actions:
            script_lines.extend(
                [
                    f"echo '@@ACIL_START:{action}'",
                    ACTION_COMMANDS[action],
                    f"echo '@@ACIL_DONE:{action}'",
                ]
            )
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--user",
            "65532:65532",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=512m",
            "--workdir",
            "/workspace",
            "--env",
            "UV_PROJECT_ENVIRONMENT=/tmp/venv",
            "--env",
            "UV_CACHE_DIR=/tmp/uv-cache",
            self.image,
            "sh",
            "-lc",
            "\n".join(script_lines),
        ]
        started = time.monotonic()
        try:
            completed = self.executor(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            stdout = completed.stdout or ""
            done_actions = [
                action for action in actions if f"@@ACIL_DONE:{action}" in stdout
            ]
            outcome = "success" if completed.returncode == 0 else "failure"
            error_category = None if outcome == "success" else "isolated_evaluation_failed"
        except subprocess.TimeoutExpired:
            done_actions = []
            outcome = "failure"
            error_category = "isolated_evaluation_timeout"
        except FileNotFoundError:
            done_actions = []
            outcome = "failure"
            error_category = "docker_unavailable"
        duration_ms = int((time.monotonic() - started) * 1_000)
        # Never persist container stdout/stderr: tests may print secrets or source contents.
        return RunnerResult(
            observed_actions=done_actions,
            outcome=outcome,
            evidence={
                "runner": "docker_isolated",
                "image": self.image,
                "network": "disabled",
                "host_mounts": "none",
                "requested_actions": actions,
                "completed_actions": done_actions,
                "duration_ms": duration_ms,
                "error_category": error_category,
                "output_persisted": False,
            },
        )
