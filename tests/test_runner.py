from types import SimpleNamespace

from acil.runner import DockerEvaluationRunner


def test_runner_uses_hardened_docker_command_and_records_only_safe_evidence():
    captured = {}

    def fake_executor(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout="@@ACIL_START:CHECK_DEPENDENCIES\n@@ACIL_DONE:CHECK_DEPENDENCIES\n"
            "@@ACIL_START:RUN_TESTS\n@@ACIL_DONE:RUN_TESTS\nsecret output",
        )

    result = DockerEvaluationRunner("registry/acil-target:1", 30, fake_executor).run(
        ["CHECK_DEPENDENCIES", "RUN_TESTS"]
    )
    assert result.outcome == "success"
    assert result.observed_actions == ["CHECK_DEPENDENCIES", "RUN_TESTS"]
    assert result.evidence["output_persisted"] is False
    assert "--network" in captured["command"]
    assert captured["command"][captured["command"].index("--network") + 1] == "none"
    assert "--read-only" in captured["command"]
    assert "secret output" not in str(result.evidence)


def test_runner_rejects_actions_outside_the_allowlist():
    runner = DockerEvaluationRunner("registry/acil-target:1", 30)
    try:
        runner.run(["RUN_ARBITRARY_COMMAND"])
    except ValueError as exc:
        assert "Unsupported evaluation actions" in str(exc)
    else:
        raise AssertionError("Expected allowlist rejection")
