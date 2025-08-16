"""
Grace main implementation for CIRISManager.
"""

import json
import subprocess
from pathlib import Path

from .ci_monitor import CIMonitor


class Grace:
    """Grace - CIRISManager development companion."""

    def __init__(self):
        """Initialize Grace."""
        self.project_root = Path(__file__).parent.parent.parent
        self.ci_monitor = CIMonitor()

    def status(self) -> str:
        """Show current project status."""
        message = ["=== CIRISManager Status ===\n"]

        # Check production
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "https://agents.ciris.ai/manager/v1/status",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                code = result.stdout.strip()
                if code == "200":
                    message.append("✅ Production: UP")
                else:
                    message.append(f"⚠️  Production: HTTP {code}")
            else:
                message.append("❌ Production: DOWN")
        except Exception:
            message.append("❌ Production: UNREACHABLE")

        # Check CI status
        try:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    "CIRISAI/CIRISManager",
                    "--limit",
                    "1",
                    "--json",
                    "status,conclusion",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                runs = json.loads(result.stdout)
                if runs:
                    run = runs[0]
                    conclusion = run.get("conclusion", "")
                    status = run.get("status", "")
                    if conclusion:
                        if conclusion == "success":
                            message.append("✅ CI/CD: PASSING")
                        else:
                            message.append(f"❌ CI/CD: {conclusion.upper()}")
                    elif status:
                        message.append(f"🔄 CI/CD: {status.upper()}")
                else:
                    message.append("⏸️  CI/CD: NO RECENT RUNS")
        except Exception:
            message.append("❌ CI/CD: ERROR")

        # Check SonarCloud quality gate
        quality_status = self._check_sonar_quick()
        if quality_status:
            message.append(quality_status)

        # Git status
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            if result.returncode == 0:
                if result.stdout.strip():
                    changes = len(result.stdout.strip().split("\n"))
                    message.append(f"📝 Git: {changes} uncommitted changes")
                else:
                    message.append("✅ Git: Clean working tree")
        except Exception:
            pass

        return "\n".join(message)

    def quality(self) -> str:
        """Check SonarCloud quality gate status."""
        message = ["=== SonarCloud Quality Report ===\n"]

        # Get token
        token_file = Path.home() / ".sonartoken"
        if not token_file.exists():
            message.append("❌ No SonarCloud token found")
            message.append("Create ~/.sonartoken with your token")
            return "\n".join(message)

        token = token_file.read_text().strip()

        # Check quality gate
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-u",
                    f"{token}:",
                    "https://sonarcloud.io/api/qualitygates/project_status?projectKey=CIRISAI_CIRISManager",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                project_status = data.get("projectStatus", {})
                status = project_status.get("status", "UNKNOWN")

                if status == "OK":
                    message.append("✅ Quality Gate: PASSING")
                elif status == "ERROR":
                    message.append("❌ Quality Gate: FAILING")
                else:
                    message.append(f"⚠️  Quality Gate: {status}")

                # Show failing conditions
                conditions = project_status.get("conditions", [])
                failures = [c for c in conditions if c.get("status") == "ERROR"]

                if failures:
                    message.append("\nFailing conditions:")
                    for condition in failures:
                        metric = condition.get("metricKey", "unknown")
                        actual = condition.get("actualValue", "?")
                        threshold = condition.get("errorThreshold", "?")

                        # Format metric name
                        metric_display = metric.replace("_", " ").replace("new ", "").title()
                        message.append(f"  • {metric_display}: {actual} (needs {threshold})")

                # Get detailed metrics
                result = subprocess.run(
                    [
                        "curl",
                        "-s",
                        "-u",
                        f"{token}:",
                        "https://sonarcloud.io/api/measures/component?component=CIRISAI_CIRISManager&metricKeys=bugs,vulnerabilities,code_smells,coverage,security_hotspots",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    measures = data.get("component", {}).get("measures", [])

                    message.append("\nCode Quality Metrics:")
                    for measure in measures:
                        metric = measure.get("metric")
                        value = measure.get("value", "0")

                        if metric == "bugs":
                            emoji = "🐛" if int(value) > 0 else "✅"
                            message.append(f"  {emoji} Bugs: {value}")
                        elif metric == "vulnerabilities":
                            emoji = "🔓" if int(value) > 0 else "✅"
                            message.append(f"  {emoji} Vulnerabilities: {value}")
                        elif metric == "code_smells":
                            emoji = "🔧" if int(value) > 50 else "✅"
                            message.append(f"  {emoji} Code Smells: {value}")
                        elif metric == "security_hotspots":
                            emoji = "🔥" if int(value) > 10 else "✅"
                            message.append(f"  {emoji} Security Hotspots: {value}")

                message.append("\n📊 View full report:")
                message.append("   https://sonarcloud.io/project/overview?id=CIRISAI_CIRISManager")

        except Exception as e:
            message.append(f"❌ Error checking SonarCloud: {e}")

        return "\n".join(message)

    def _check_sonar_quick(self) -> str:
        """Quick SonarCloud check for status display."""
        token_file = Path.home() / ".sonartoken"
        if not token_file.exists():
            return "⏸️  SonarCloud: NO TOKEN"

        token = token_file.read_text().strip()

        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-u",
                    f"{token}:",
                    "https://sonarcloud.io/api/qualitygates/project_status?projectKey=CIRISAI_CIRISManager",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                status = data.get("projectStatus", {}).get("status", "UNKNOWN")

                if status == "OK":
                    return "✅ SonarCloud: PASSING"
                elif status == "ERROR":
                    conditions = data.get("projectStatus", {}).get("conditions", [])
                    failures = len([c for c in conditions if c.get("status") == "ERROR"])
                    return f"❌ SonarCloud: {failures} failures"
                else:
                    return f"⚠️  SonarCloud: {status}"
        except Exception:
            return "❌ SonarCloud: ERROR"

    def ci(self, subcommand: str = None) -> str:
        """Check CI/CD status and provide guidance."""
        message = []

        if subcommand == "prs":
            # Show all PRs with their status
            message.append("=== Open PRs ===")
            message.append(self.ci_monitor.check_prs())

        elif subcommand == "builds":
            # Show recent builds
            message.append("=== Recent Builds ===")
            message.append(self.ci_monitor.check_builds())

        elif subcommand == "analyze":
            # Analyze CI failure
            message.append("=== CI Failure Analysis ===")
            message.append(self.ci_monitor.analyze_failure())

        else:
            # Default: current branch CI
            message.append("=== Current Branch CI ===")
            message.append(self.ci_monitor.check_current_ci())

            # PR status summary
            message.append("\n=== PR Status ===")
            pr_status = self.ci_monitor.check_prs()

            # Only show first 3 PRs in default view
            lines = pr_status.split("\n")[:3]
            message.extend(lines)
            if len(pr_status.split("\n")) > 3:
                message.append("... (use 'grace ci prs' for all)")

        return "\n".join(message)

    def precommit(self, autofix: bool = False) -> str:
        """Run pre-commit checks."""
        message = ["=== Pre-commit Checks ===\n"]

        # Run pre-commit
        cmd = ["pre-commit", "run", "--all-files"]
        if autofix:
            message.append("Running with auto-fix enabled...\n")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=60,
            )

            if result.returncode == 0:
                message.append("✅ All checks passed!")
            else:
                # Parse output for specific issues
                output = result.stdout + result.stderr

                if "ruff" in output and "fixed" in output:
                    message.append("✨ Ruff fixed formatting issues")

                if "mypy" in output and "error:" in output:
                    # Count mypy errors
                    error_count = output.count("error:")
                    message.append(f"❌ MyPy: {error_count} type errors")
                    message.append("   Run 'mypy ciris_manager/' for details")

                if "Failed" in output:
                    message.append("❌ Some checks failed")
                    if not autofix:
                        message.append("   Try 'grace fix' to auto-fix issues")

        except subprocess.TimeoutExpired:
            message.append("⏱️  Pre-commit timed out (>60s)")
        except Exception as e:
            message.append(f"❌ Error running pre-commit: {e}")

        return "\n".join(message)

    def fix(self) -> str:
        """Auto-fix pre-commit issues."""
        return self.precommit(autofix=True)

    def deploy_status(self) -> str:
        """Check deployment status."""
        message = ["=== Deployment Status ===\n"]

        try:
            # Check latest deployment
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "https://agents.ciris.ai/manager/v1/updates/status",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)

                # Current deployment
                current = data.get("current_deployment")
                if current:
                    message.append(f"🚀 Active: {current}")
                else:
                    message.append("✅ No active deployment")

                # Recent deployments
                deployments = data.get("deployments", [])
                if deployments:
                    message.append("\nRecent deployments:")
                    for dep in deployments[:3]:
                        dep_id = dep.get("deployment_id", "unknown")[:8]
                        status = dep.get("status", "unknown")
                        agents = dep.get("agents_total", 0)

                        if status == "completed":
                            emoji = "✅"
                        elif status == "failed":
                            emoji = "❌"
                        else:
                            emoji = "🔄"

                        message.append(f"  {emoji} {dep_id}: {status} ({agents} agents)")

        except Exception as e:
            message.append(f"❌ Error checking deployments: {e}")

        return "\n".join(message)

    def test(self) -> str:
        """Run tests with coverage."""
        message = ["=== Running Tests ===\n"]

        try:
            result = subprocess.run(
                ["pytest", "--cov=ciris_manager", "--cov-report=term-missing", "-v"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=120,
            )

            output = result.stdout + result.stderr

            # Parse test results
            if "passed" in output:
                import re

                # Extract test counts
                match = re.search(r"(\d+) passed", output)
                if match:
                    passed = match.group(1)
                    message.append(f"✅ Tests: {passed} passed")

            if "failed" in output:
                import re

                match = re.search(r"(\d+) failed", output)
                if match:
                    failed = match.group(1)
                    message.append(f"❌ Tests: {failed} failed")

            # Extract coverage
            if "TOTAL" in output:
                for line in output.split("\n"):
                    if "TOTAL" in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            coverage = parts[-1]
                            message.append(f"📊 Coverage: {coverage}")
                            break

            if result.returncode != 0:
                message.append("\n❌ Tests failed")
                message.append("Run 'pytest -v' for details")
            else:
                message.append("\n✅ All tests passed!")

        except subprocess.TimeoutExpired:
            message.append("⏱️  Tests timed out (>120s)")
        except Exception as e:
            message.append(f"❌ Error running tests: {e}")

        return "\n".join(message)
