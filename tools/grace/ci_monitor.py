"""
CI/CD monitoring for CIRISManager.
"""

import json
import subprocess
from datetime import datetime


class CIMonitor:
    """Monitor CI/CD status for CIRISManager."""

    def __init__(self):
        """Initialize CI monitor."""
        self.repo = "CIRISAI/CIRISManager"

    def check_current_ci(self) -> str:
        """Check CI status for current branch."""
        message = []

        # Get current branch
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                message.append(f"Branch: {branch}")
            else:
                branch = "unknown"
        except Exception:
            branch = "unknown"

        # Check CI runs for this branch
        try:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    self.repo,
                    "--branch",
                    branch,
                    "--limit",
                    "1",
                    "--json",
                    "status,conclusion,headSha,workflowName,createdAt",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                runs = json.loads(result.stdout)
                if runs:
                    run = runs[0]
                    status = run.get("status")
                    conclusion = run.get("conclusion")
                    workflow = run.get("workflowName", "Unknown")
                    created = run.get("createdAt", "")
                    sha = run.get("headSha", "")[:7]

                    # Format time
                    if created:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        age = datetime.now(created_dt.tzinfo) - created_dt
                        if age.days > 0:
                            age_str = f"{age.days}d ago"
                        elif age.seconds > 3600:
                            age_str = f"{age.seconds // 3600}h ago"
                        else:
                            age_str = f"{age.seconds // 60}m ago"
                    else:
                        age_str = "unknown"

                    if conclusion:
                        if conclusion == "success":
                            message.append(f"✅ {workflow}: SUCCESS ({age_str})")
                        elif conclusion == "failure":
                            message.append(f"❌ {workflow}: FAILED ({age_str})")
                        else:
                            message.append(f"⚠️  {workflow}: {conclusion.upper()} ({age_str})")
                    elif status:
                        if status == "in_progress":
                            message.append(f"🔄 {workflow}: RUNNING ({age_str})")
                        elif status == "queued":
                            message.append(f"⏳ {workflow}: QUEUED")
                        else:
                            message.append(f"📝 {workflow}: {status.upper()}")

                    message.append(f"   Commit: {sha}")
                else:
                    message.append("No CI runs for this branch")
        except Exception as e:
            message.append(f"Error checking CI: {e}")

        return "\n".join(message)

    def check_prs(self) -> str:
        """Check open PRs and their status."""
        message = []

        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    self.repo,
                    "--json",
                    "number,title,state,isDraft,mergeable,checks",
                    "--limit",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                prs = json.loads(result.stdout)

                if not prs:
                    message.append("No open PRs")
                else:
                    for pr in prs:
                        number = pr.get("number")
                        title = pr.get("title", "")[:50]
                        is_draft = pr.get("isDraft", False)
                        mergeable = pr.get("mergeable", "UNKNOWN")
                        checks = pr.get("checks", [])

                        # Determine status
                        if is_draft:
                            status = "📝 DRAFT"
                        elif mergeable == "CONFLICTING":
                            status = "🚨 CONFLICT"
                        elif checks:
                            # Check CI status
                            failed = any(c.get("conclusion") == "FAILURE" for c in checks)
                            pending = any(c.get("status") == "IN_PROGRESS" for c in checks)

                            if failed:
                                status = "❌ CI FAILED"
                            elif pending:
                                status = "🔄 CI RUNNING"
                            else:
                                status = "✅ READY"
                        else:
                            status = "⏸️  NO CHECKS"

                        message.append(f"#{number}: {status} - {title}")

        except Exception as e:
            message.append(f"Error checking PRs: {e}")

        return "\n".join(message) if message else "No PRs found"

    def check_builds(self) -> str:
        """Check recent build status."""
        message = []

        try:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    self.repo,
                    "--workflow",
                    "ci.yml",
                    "--limit",
                    "5",
                    "--json",
                    "status,conclusion,headBranch,createdAt",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                runs = json.loads(result.stdout)

                if not runs:
                    message.append("No recent builds")
                else:
                    for run in runs:
                        branch = run.get("headBranch", "unknown")[:20]
                        conclusion = run.get("conclusion")
                        status = run.get("status")
                        created = run.get("createdAt", "")

                        # Format time
                        if created:
                            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            age = datetime.now(created_dt.tzinfo) - created_dt
                            if age.days > 0:
                                age_str = f"{age.days}d"
                            elif age.seconds > 3600:
                                age_str = f"{age.seconds // 3600}h"
                            else:
                                age_str = f"{age.seconds // 60}m"
                        else:
                            age_str = "?"

                        if conclusion:
                            if conclusion == "success":
                                emoji = "✅"
                            elif conclusion == "failure":
                                emoji = "❌"
                            else:
                                emoji = "⚠️"
                            message.append(f"{emoji} {branch} ({age_str} ago)")
                        elif status:
                            if status == "in_progress":
                                emoji = "🔄"
                            else:
                                emoji = "⏳"
                            message.append(f"{emoji} {branch} ({status})")

        except Exception as e:
            message.append(f"Error checking builds: {e}")

        return "\n".join(message) if message else "No builds found"

    def analyze_failure(self) -> str:
        """Analyze the most recent CI failure."""
        message = []

        try:
            # Get most recent failed run
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    self.repo,
                    "--status",
                    "failure",
                    "--limit",
                    "1",
                    "--json",
                    "databaseId,headBranch,conclusion",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                runs = json.loads(result.stdout)
                if runs:
                    run = runs[0]
                    run_id = run.get("databaseId")
                    branch = run.get("headBranch", "unknown")

                    message.append(f"Analyzing failure on {branch}...")

                    # Get run details
                    result = subprocess.run(
                        [
                            "gh",
                            "run",
                            "view",
                            str(run_id),
                            "--repo",
                            self.repo,
                            "--json",
                            "jobs",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                        jobs = data.get("jobs", [])

                        failed_jobs = [j for j in jobs if j.get("conclusion") == "failure"]

                        if failed_jobs:
                            message.append("\nFailed jobs:")
                            for job in failed_jobs:
                                name = job.get("name", "unknown")
                                message.append(f"  ❌ {name}")

                                # Get step details
                                steps = job.get("steps", [])
                                failed_steps = [
                                    s for s in steps if s.get("conclusion") == "failure"
                                ]

                                if failed_steps:
                                    for step in failed_steps:
                                        step_name = step.get("name", "unknown")
                                        message.append(f"     Failed at: {step_name}")

                        # Common fixes
                        message.append("\n💡 Common fixes:")
                        message.append("  • Lint issues: grace fix")
                        message.append("  • Type errors: mypy ciris_manager/")
                        message.append("  • Test failures: pytest -xvs")
                        message.append("  • Check logs: gh run view " + str(run_id))

                else:
                    message.append("No recent failures to analyze")

        except Exception as e:
            message.append(f"Error analyzing failure: {e}")

        return "\n".join(message)
