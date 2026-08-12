"""Tests for D-FT-09 deploy PR helper.

Verifies:
- Branch name auto-generated
- gh command construction
- dry_run mode skips subprocess
- Live mode invokes subprocess (with injected runner)
- PR URL parsing from stdout
- Failure path: subprocess fails -> ok=False with error message
- assert_d_ft_09_safe_to_run rejects "/" and missing opt-in env
"""

from __future__ import annotations


import pytest

from app.ft_strategy.deploy_pr import (
    DeployPRRequest,
    _build_gh_command,
    _generate_branch_name,
    assert_d_ft_09_safe_to_run,
    build_deploy_pr_body,
    create_deploy_pr,
)


def _request(**kwargs):
    defaults = {
        "strategy_id": "strat-1",
        "strategy_name": "My RSI v2",
        "version": 3,
        "title": "Deploy My RSI v2 v3",
        "body": "Body content here",
        "base_branch": "main",
        "branch_name": None,
        "repo_dir": ".",
        "dry_run": True,
    }
    defaults.update(kwargs)
    return DeployPRRequest(**defaults)


# ---------------------------------------------------------------------------
# Branch name generation
# ---------------------------------------------------------------------------


class TestBranchName:
    def test_auto_generated_slug(self):
        req = _request(strategy_name="My RSI v2", version=3)
        assert _generate_branch_name(req) == "ft-strategy-deploy-my-rsi-v2-v3"

    def test_special_chars_replaced_with_hyphen(self):
        req = _request(strategy_name="Foo/Bar Baz!", version=1)
        branch = _generate_branch_name(req)
        assert "/" not in branch
        assert "!" not in branch

    def test_long_name_truncated(self):
        req = _request(strategy_name="a" * 200, version=1)
        branch = _generate_branch_name(req)
        assert len(branch) <= 80

    def test_explicit_branch_name_returned(self):
        req = _request(branch_name="custom/deploy-stuff")
        assert _generate_branch_name(req) == "custom/deploy-stuff"


# ---------------------------------------------------------------------------
# gh command construction
# ---------------------------------------------------------------------------


class TestBuildGhCommand:
    def test_command_includes_required_flags(self):
        req = _request(title="My T", body="My B", base_branch="main")
        branch = _generate_branch_name(req)
        cmd = _build_gh_command(req, branch)
        # cmd is a list, not a tuple
        assert isinstance(cmd, list)
        assert cmd[0] == "gh"
        assert cmd[1] == "pr"
        assert cmd[2] == "create"
        assert "--base" in cmd and "main" in cmd
        assert "--title" in cmd and "My T" in cmd
        assert "--body" in cmd and "My B" in cmd
        assert "--fill" in cmd

    def test_branch_in_head_flag(self):
        req = _request()
        cmd = _build_gh_command(req, "test-branch")
        assert "--head" in cmd
        assert cmd[cmd.index("--head") + 1] == "test-branch"

    def test_custom_base_branch(self):
        req = _request(base_branch="release/1.0")
        cmd = _build_gh_command(req, "x")
        assert cmd[cmd.index("--base") + 1] == "release/1.0"


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


class TestDryRunMode:
    def test_dry_run_does_not_shell_out(self):
        req = _request(dry_run=True)
        runner_calls = []

        def fake_runner(cmd, cwd):
            runner_calls.append((cmd, cwd))
            return 0, "", ""

        result = create_deploy_pr(req, subprocess_runner=fake_runner)
        assert runner_calls == [], "dry-run must not invoke the runner"
        assert result.ok
        assert result.branch_name
        assert result.pr_url and result.pr_url.startswith("http")

    def test_dry_run_branch_set(self):
        req = _request(dry_run=True)
        result = create_deploy_pr(req)
        assert result.branch_name
        assert result.branch_name.startswith("ft-strategy-deploy-")

    def test_dry_run_command_recorded(self):
        req = _request(dry_run=True)
        result = create_deploy_pr(req)
        assert result.command
        assert result.command[0] == "gh"


# ---------------------------------------------------------------------------
# Live mode (with injected runner)
# ---------------------------------------------------------------------------


class TestLiveMode:
    def test_successful_subprocess_returns_pr_url(self):
        def fake_runner(cmd, cwd):
            return 0, "https://github.com/owner/repo/pull/42\n", ""

        req = _request(dry_run=False, body="body")
        result = create_deploy_pr(req, subprocess_runner=fake_runner)
        assert result.ok
        assert result.pr_url == "https://github.com/owner/repo/pull/42"
        assert result.error is None

    def test_failed_subprocess_returns_error(self):
        def fake_runner(cmd, cwd):
            return 1, "", "fatal: not a git repo"

        req = _request(dry_run=False)
        result = create_deploy_pr(req, subprocess_runner=fake_runner)
        assert not result.ok
        assert "fatal" in result.error

    def test_pr_url_parsed_from_long_stdout(self):
        def fake_runner(cmd, cwd):
            return 0, "Opening PR...\nCreated PR!\nhttps://github.com/x/y/pull/7\n", ""

        req = _request(dry_run=False)
        result = create_deploy_pr(req, subprocess_runner=fake_runner)
        assert result.ok
        assert result.pr_url == "https://github.com/x/y/pull/7"

    def test_no_url_line_yields_none(self):
        def fake_runner(cmd, cwd):
            return 0, "no url here", ""

        req = _request(dry_run=False)
        result = create_deploy_pr(req, subprocess_runner=fake_runner)
        assert result.ok
        assert result.pr_url is None


# ---------------------------------------------------------------------------
# PR body builder
# ---------------------------------------------------------------------------


class TestBuildPRBody:
    def test_includes_metrics(self):
        body = build_deploy_pr_body(
            strategy_id="strat-1",
            version=3,
            gate_summary="8/8 ✅",
            baseline_drawdown=0.156,
            candidate_drawdown=0.05,
            candidate_sharpe=1.5,
            candidate_calmar=2.0,
            candidate_profit_pct=0.20,
        )
        assert "strat-1" in body
        assert "8/8 ✅" in body
        assert "1.5000" in body
        assert "Calmar" in body
        assert "Profit" in body

    def test_includes_report_when_provided(self):
        body = build_deploy_pr_body(
            strategy_id="x",
            version=1,
            gate_summary="8/8 ✅",
            baseline_drawdown=0.10,
            candidate_drawdown=0.05,
            candidate_sharpe=1.0,
            candidate_calmar=1.5,
            candidate_profit_pct=0.10,
            report_url="https://example.com/durable-facts",
        )
        assert "https://example.com/durable-facts" in body

    def test_skips_report_section_when_no_url(self):
        body = build_deploy_pr_body(
            strategy_id="x",
            version=1,
            gate_summary="8/8 ✅",
            baseline_drawdown=0.10,
            candidate_drawdown=0.05,
            candidate_sharpe=1.0,
            candidate_calmar=1.5,
            candidate_profit_pct=0.10,
            report_url=None,
        )
        assert "### Report" not in body

    def test_includes_deploy_checklist(self):
        body = build_deploy_pr_body(
            strategy_id="x",
            version=1,
            gate_summary="8/8",
            baseline_drawdown=0.10,
            candidate_drawdown=0.05,
            candidate_sharpe=1.0,
            candidate_calmar=1.5,
            candidate_profit_pct=0.10,
        )
        assert "SIGHUP" in body
        assert "tuning snapshot SHA" in body


# ---------------------------------------------------------------------------
# Defensive path
# ---------------------------------------------------------------------------


class TestDefensive:
    def test_non_request_returns_failure(self):
        result = create_deploy_pr({"not": "a request"})  # type: ignore[arg-type]
        assert not result.ok

    def test_assert_safe_to_run_blocks_repo_dir_root(self, monkeypatch):
        monkeypatch.delenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY", raising=False)
        with pytest.raises(RuntimeError, match="repo_dir"):
            assert_d_ft_09_safe_to_run(dry_run=False, repo_dir="/")

    def test_assert_safe_to_run_blocks_live_without_opt_in(self, monkeypatch):
        monkeypatch.delenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY", raising=False)
        with pytest.raises(RuntimeError, match="FT_STRATEGY_ALLOW_LIVE_DEPLOY"):
            assert_d_ft_09_safe_to_run(dry_run=False, repo_dir=".")

    def test_assert_safe_to_run_allows_dry_run_in_repo(self):
        # Dry-run is always safe (as long as repo_dir != /)
        assert_d_ft_09_safe_to_run(dry_run=True, repo_dir=".")

    def test_assert_safe_to_run_blocks_slash_even_in_dry_run(self):
        # Defense in depth: "/" is blocked regardless of mode
        with pytest.raises(RuntimeError, match="repo_dir"):
            assert_d_ft_09_safe_to_run(dry_run=True, repo_dir="/")

    def test_assert_safe_to_run_allows_live_with_opt_in(self, monkeypatch):
        monkeypatch.setenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY", "1")
        assert_d_ft_09_safe_to_run(dry_run=False, repo_dir=".")


# ---------------------------------------------------------------------------
# Dataclass frozen
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_request_frozen(self):
        r = _request()
        with pytest.raises(Exception):
            r.dry_run = False  # type: ignore[misc]

    def test_result_frozen(self):
        r = create_deploy_pr(_request())
        with pytest.raises(Exception):
            r.ok = False  # type: ignore[misc]


class TestLiveModeSubprocess:
    def test_live_mode_subprocess_runner_invoked(self):
        """Verify the live-mode path actually invokes the runner with cwd."""
        captured = []
        def runner(cmd, cwd):
            captured.append((cmd, cwd))
            return 0, "https://github.com/x/y/pull/9", ""
        req = _request(dry_run=False, repo_dir="/tmp/repo")
        create_deploy_pr(req, subprocess_runner=runner)
        assert len(captured) == 1
        assert captured[0][1] == "/tmp/repo"
        assert captured[0][0][0] == "gh"
    def test_live_mode_default_runner_success(self, monkeypatch):
        """When no subprocess_runner is passed, the default runner is used.
        Patch _run_subprocess to a stub that returns OK.
        """
        import app.ft_strategy.deploy_pr as mod
        monkeypatch.setattr(mod, "_run_subprocess",
                            lambda cmd, cwd: (0, "https://github.com/x/y/pull/8\n", ""))
        monkeypatch.setenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY", "1")
        req = _request(dry_run=False)
        result = create_deploy_pr(req)
        assert result.ok
        assert result.pr_url == "https://github.com/x/y/pull/8"
    def test_live_mode_default_runner_failure(self, monkeypatch):
        """Default runner returning non-zero exit yields ok=False."""
        import app.ft_strategy.deploy_pr as mod
        monkeypatch.setattr(mod, "_run_subprocess",
                            lambda cmd, cwd: (1, "", "fatal error"))
        monkeypatch.setenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY", "1")
        req = _request(dry_run=False)
        result = create_deploy_pr(req)
        assert not result.ok
        assert "fatal error" in result.error
    def test_subprocess_runner_called_with_branch_in_head(self):
        captured = []
        def runner(cmd, cwd):
            captured.append(cmd)
            return 0, "https://github.com/x/y/pull/9", ""
        req = _request(dry_run=False, branch_name="custom-branch")
        create_deploy_pr(req, subprocess_runner=runner)
        assert captured[0][captured[0].index("--head") + 1] == "custom-branch"

class TestToDict:
    def test_to_dict_shape_happy(self):
        r = create_deploy_pr(_request())
        d = r.to_dict()
        assert d['ok'] is True
        assert d['branch_name'].startswith('ft-strategy-deploy-')
        assert isinstance(d['command'], list)
    def test_to_dict_shape_failure(self):
        result = create_deploy_pr({'not': 'a request'})
        d = result.to_dict()
        assert d['ok'] is False
        assert d['branch_name'] is None
        assert d['error'] is not None
