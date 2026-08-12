"""D-FT-09 — gh CLI wrapper for creating the deploy PR.

Phase 5 of the FT-STRATEGY-UI plan: the `/api/ft-strategies/:id/deploy`
endpoint detects a passed multi-objective gate and then this module
constructs the PR via the `gh` CLI.

Designed for parity with the existing `scripts/freqtrade/start_with_creds.sh`
pattern (Keychain credentials, chmod 600 config, no secrets in the file).

The actual `gh` invocation is wrapped in a thin function
(`create_deploy_pr`) so tests can swap it for a fake. The PR title and
body follow the Loop #10 PR template: tuning snapshot SHA + report hash +
salt_version.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployPRRequest:
    """Inputs for the deploy PR helper."""

    strategy_id: str
    strategy_name: str
    version: int
    title: str
    body: str
    base_branch: str = "main"
    branch_name: Optional[str] = None  # auto-generated if None
    repo_dir: str = "."
    dry_run: bool = True  # default true — Phase 5 ships without writing to main


@dataclass(frozen=True)
class DeployPRResult:
    ok: bool
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    error: Optional[str] = None
    command: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "branch_name": self.branch_name,
            "pr_url": self.pr_url,
            "error": self.error,
            "command": list(self.command),
        }


# Subprocess timeout: PR operations should be near-instant; allow 60s
# for `gh pr create` network round-trips.
_SUBPROCESS_TIMEOUT = 60


def _generate_branch_name(req: DeployPRRequest) -> str:
    if req.branch_name:
        return req.branch_name
    # e.g. ft-strategy-deploy-rsi-v2-v3
    clean = "".join(c if c.isalnum() else "-" for c in req.strategy_name.lower()).strip("-")
    return f"ft-strategy-deploy-{clean}-v{req.version}"[:80]


def _build_gh_command(req: DeployPRRequest, branch: str) -> list[str]:
    """Construct the `gh pr create` command.

    ``gh pr create --base main --head <branch> --title <t> --body <b> --fill``.
    """
    cmd = [
        "gh", "pr", "create",
        "--base", req.base_branch,
        "--head", branch,
        "--title", req.title,
        "--body", req.body,
        "--fill",  # auto-fill defaults (don't prompt for missing fields)
    ]
    return cmd


def _run_subprocess(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a subprocess, return (exit_code, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {_SUBPROCESS_TIMEOUT}s: {e}"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"


def create_deploy_pr(
    req: DeployPRRequest,
    *,
    subprocess_runner=None,
) -> DeployPRResult:
    """Create the deploy PR. Tests inject ``subprocess_runner``.

    Flow:
    1. Generate branch name (or use provided).
    2. Construct `gh pr create` command.
    3. Run via subprocess_runner (or default _run_subprocess).
    4. On success: parse pr_url from stdout (last URL line).

    Dry-run semantics: when ``dry_run=True`` we return a result that
    *would have* succeeded without actually shelling out — Phase 5 ships
    in this mode so no real PR is created during integration testing.
    """
    if not isinstance(req, DeployPRRequest):
        return DeployPRResult(ok=False, error=f"req must be DeployPRRequest; got {type(req).__name__}")

    branch = _generate_branch_name(req)
    cmd = _build_gh_command(req, branch)

    if req.dry_run:
        # Don't shell out; return a synthetic result.
        return DeployPRResult(
            ok=True,
            branch_name=branch,
            pr_url=f"https://example.invalid/{branch}",
            command=tuple(cmd),
        )

    runner = subprocess_runner or _run_subprocess
    code, stdout, stderr = runner(cmd, cwd=req.repo_dir)
    if code != 0:
        return DeployPRResult(
            ok=False,
            branch_name=branch,
            error=f"gh pr create failed (exit={code}): {stderr.strip()[:200]}",
            command=tuple(cmd),
        )

    # `gh pr create --fill` prints the new PR URL on stdout, e.g.
    #   https://github.com/owner/repo/pull/123
    pr_url: Optional[str] = None
    for line in stdout.strip().splitlines():
        line = line.strip()
        if line.startswith("http"):
            pr_url = line
            break

    return DeployPRResult(
        ok=True,
        branch_name=branch,
        pr_url=pr_url,
        command=tuple(cmd),
    )


def build_deploy_pr_body(
    *,
    strategy_id: str,
    version: int,
    gate_summary: str,
    baseline_drawdown: float,
    candidate_drawdown: float,
    candidate_sharpe: float,
    candidate_calmar: float,
    candidate_profit_pct: float,
    report_url: Optional[str] = None,
) -> str:
    """Build the PR body markdown per Loop #10 outerloop template."""
    lines = [
        f"## FT Strategy deploy — strategy `{strategy_id}` v{version}",
        "",
        "### Multi-objective gate (auto-checked)",
        gate_summary,
        "",
        "### Metrics",
        f"- Sharpe: `{candidate_sharpe:.4f}`",
        f"- Calmar: `{candidate_calmar:.4f}`",
        f"- Profit %: `{candidate_profit_pct*100:.2f}%`",
        f"- Max DD: `{candidate_drawdown*100:.2f}%` (baseline `{baseline_drawdown*100:.2f}%`, "
        f"allowed `{2*baseline_drawdown*100:.2f}%`)",
    ]
    if report_url:
        lines += ["", f"### Report", f"Final-report artifact: {report_url}"]
    lines += [
        "",
        "### Deploy checklist (human)",
        "- [ ] Confirm tuning snapshot SHA matches HISTORY.jsonl",
        "- [ ] Confirm salt_version present in tuning.py (if applicable)",
        "- [ ] Confirm [ftstrategy-shadow-01] durable-fact exists",
        "- [ ] After merge: SIGHUP gunicorn workers to reload tuning",
        "- [ ] Watch 7-day shadow metrics for anomalies",
        "",
        "_Auto-generated by Loop #13 (FT Strategy UI Loop). Do not edit manually._",
    ]
    return "\n".join(lines)


def assert_d_ft_09_safe_to_run(dry_run: bool, repo_dir: str) -> None:
    """Sanity check before invoking the real `gh pr create`.

    Two guards, ordered so the most likely failure is reported first:
      1. ``repo_dir != "/"`` — guard against accidental fork-bomb. Applies
         regardless of dry_run (defense in depth).
      2. If ``dry_run=False``: require ``FT_STRATEGY_ALLOW_LIVE_DEPLOY=1``.
         Without this env opt-in, refuse to call ``gh pr create``.
    """
    # Guard 1: refuse "/" repo_dir for both modes.
    if repo_dir == "/":
        raise RuntimeError("repo_dir must not be /")
    # Guard 2: live mode requires explicit opt-in.
    if not dry_run:
        if os.getenv("FT_STRATEGY_ALLOW_LIVE_DEPLOY") != "1":
            raise RuntimeError(
                "Live deploy requires FT_STRATEGY_ALLOW_LIVE_DEPLOY=1 "
                "(Phase 5 ships in dry_run=True)"
            )
