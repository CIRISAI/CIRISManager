"""
Deployment management commands for CIRIS CLI.

This module provides commands for managing deployments including
status checking, cancellation, and deployment history.
"""

import json
import sys
from argparse import Namespace
from datetime import datetime

import httpx

from ciris_manager_sdk import APIError, AuthenticationError
from ciris_manager_client.protocols import (
    CommandContext,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_AUTH_ERROR,
    EXIT_API_ERROR,
    EXIT_NOT_FOUND,
)


class DeploymentCommands:
    """Deployment management commands."""

    @staticmethod
    def status(ctx: CommandContext, args: Namespace) -> int:
        """
        Get deployment status.

        Args:
            ctx: Command context
            args: Parsed arguments (deployment_id optional)

        Returns:
            Exit code
        """
        try:
            deployment_id = getattr(args, "deployment_id", None)

            if deployment_id:
                # Specific deployment requested
                if not ctx.quiet:
                    print(f"Fetching status for deployment {deployment_id}...")
                status = ctx.client.get_deployment_status(deployment_id)
                if not status:
                    print(f"Deployment {deployment_id} not found", file=sys.stderr)
                    return EXIT_NOT_FOUND
                return DeploymentCommands._print_deployment_status(ctx, status)
            else:
                # Show all pending deployments
                if not ctx.quiet:
                    print("Fetching deployment status...")

                pending = ctx.client.get_pending_deployments()

                # Format output
                if ctx.output_format == "json":
                    import json

                    print(json.dumps(pending, indent=2))
                    return EXIT_SUCCESS
                elif ctx.output_format == "yaml":
                    import yaml

                    print(yaml.dump(pending, default_flow_style=False))
                    return EXIT_SUCCESS

                # Table format
                deployments = pending.get("deployments", [])
                total = pending.get("total_pending", 0)
                latest_tag = pending.get("latest_tag", {})

                if total == 0:
                    print("\n=== Deployment Status ===")
                    print("No pending deployments")
                    if latest_tag.get("local_image_id"):
                        print(f"\nCurrent 'latest' image: {latest_tag['local_image_id']}")
                    return EXIT_SUCCESS

                print(f"\n=== Pending Deployments ({total}) ===\n")

                for dep in deployments:
                    print(f"Deployment ID: {dep.get('deployment_id', 'N/A')}")
                    print(f"  Version: {dep.get('version', 'N/A')}")
                    print(f"  Status: {dep.get('status', 'N/A')}")
                    print(f"  Strategy: {dep.get('strategy', 'N/A')}")
                    print(f"  Staged At: {dep.get('staged_at', 'N/A')}")
                    print(f"  Affected Agents: {dep.get('affected_agents', 0)}")
                    print(f"  Message: {dep.get('message', 'N/A')}")
                    if dep.get("commit_sha"):
                        print(f"  Commit: {dep['commit_sha'][:8]}")
                    print()

                if latest_tag.get("local_image_id"):
                    print(f"Current 'latest' image: {latest_tag['local_image_id']}")

                return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error fetching deployment status: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def _print_deployment_status(ctx: CommandContext, status: dict) -> int:
        """Print a single deployment status."""
        if ctx.output_format == "json":
            import json

            print(json.dumps(status, indent=2))
        elif ctx.output_format == "yaml":
            import yaml

            print(yaml.dump(status, default_flow_style=False))
        else:
            print("\n=== Deployment Status ===")
            print(f"Deployment ID: {status.get('deployment_id', 'N/A')}")
            print(f"Status: {status.get('status', 'N/A')}")
            print(f"Strategy: {status.get('strategy', 'N/A')}")
            print(f"Message: {status.get('message', 'N/A')}")
            print("\nProgress:")
            print(f"  Total Agents: {status.get('agents_total', 0)}")
            print(f"  Updated: {status.get('agents_updated', 0)}")
            print(f"  Failed: {status.get('agents_failed', 0)}")
            print(f"  Pending: {status.get('agents_pending', 0)}")

            if status.get("current_phase"):
                print(f"\nCurrent Phase: {status['current_phase']}")

            if status.get("staged_at"):
                print(f"\nStaged At: {status['staged_at']}")
            if status.get("updated_at"):
                print(f"Updated At: {status['updated_at']}")

        return EXIT_SUCCESS

    @staticmethod
    def cancel(ctx: CommandContext, args: Namespace) -> int:
        """
        Cancel/reject a deployment.

        For pending deployments, uses reject endpoint.
        For stuck deployments, uses cancel endpoint.

        Args:
            ctx: Command context
            args: Parsed arguments (deployment_id, reason)

        Returns:
            Exit code
        """
        try:
            deployment_id = args.deployment_id
            reason = getattr(args, "reason", "Cancelled via CLI")

            if not ctx.quiet:
                print(f"Cancelling deployment {deployment_id}...")

            # Try reject first (for pending deployments)
            try:
                result = ctx.client.reject_deployment(deployment_id, reason)
                action = "rejected"
            except APIError as e:
                if e.status_code == 404:
                    # Not a pending deployment, try cancel (for stuck deployments)
                    result = ctx.client.cancel_deployment(deployment_id, reason)
                    action = "cancelled"
                else:
                    raise

            if not ctx.quiet:
                print(f"✓ Deployment {deployment_id} {action} successfully")
                print(f"  Reason: {reason}")
                if result.get("message"):
                    print(f"  Message: {result['message']}")

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Deployment {args.deployment_id} not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error cancelling deployment: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def start(ctx: CommandContext, args: Namespace) -> int:
        """
        Start/launch a pending deployment.

        Args:
            ctx: Command context
            args: Parsed arguments (deployment_id)

        Returns:
            Exit code
        """
        try:
            deployment_id = args.deployment_id

            if not ctx.quiet:
                print(f"Starting deployment {deployment_id}...")

            result = ctx.client.start_deployment(deployment_id)

            if not ctx.quiet:
                print(f"✓ Deployment {deployment_id} started successfully")
                if result.get("message"):
                    print(f"  Message: {result['message']}")

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Deployment {args.deployment_id} not found or not pending", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error starting deployment: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def watch(ctx: CommandContext, args: Namespace) -> int:
        """
        Watch deployment events in real-time via SSE stream.

        Streams deployment events as they happen and exits when
        deployment completes, fails, or is cancelled.

        Args:
            ctx: Command context
            args: Parsed arguments (deployment_id)

        Returns:
            Exit code (0 for success/completed, non-zero for failures)
        """
        deployment_id = args.deployment_id

        if not ctx.quiet:
            print(f"Watching deployment {deployment_id}...")
            print("=" * 60)
            print()

        # Build the SSE stream URL
        base_url = ctx.client.base_url.rstrip("/")
        stream_url = f"{base_url}/updates/events/{deployment_id}/stream"

        # Get auth headers from the client
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        if hasattr(ctx.client, "_get_headers"):
            headers.update(ctx.client._get_headers())
        elif hasattr(ctx.client, "token") and ctx.client.token:
            headers["Authorization"] = f"Bearer {ctx.client.token}"

        try:
            with httpx.stream(
                "GET",
                stream_url,
                headers=headers,
                timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0),
            ) as response:
                if response.status_code == 401:
                    print("Authentication error: Invalid or expired token", file=sys.stderr)
                    return EXIT_AUTH_ERROR
                elif response.status_code == 404:
                    print(f"Deployment {deployment_id} not found", file=sys.stderr)
                    return EXIT_NOT_FOUND
                elif response.status_code != 200:
                    print(f"Error: HTTP {response.status_code}", file=sys.stderr)
                    return EXIT_API_ERROR

                # Track last status for change detection
                last_status = None
                error_occurred = False

                for line in response.iter_lines():
                    if not line:
                        continue

                    # SSE format: "data: {json}"
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "unknown")

                        if event_type == "error":
                            print(f"\n❌ ERROR: {event.get('message', 'Unknown error')}")
                            error_occurred = True
                            return EXIT_ERROR

                        elif event_type == "status":
                            # Only print status if it changed
                            status = event.get("status")
                            if status != last_status:
                                last_status = status
                                updated = event.get("agents_updated", 0)
                                failed = event.get("agents_failed", 0)
                                total = event.get("agents_total", 0)
                                phase = event.get("canary_phase", "")

                                status_line = f"[{status.upper()}]"
                                if phase:
                                    status_line += f" Phase: {phase}"
                                status_line += f" | Progress: {updated}/{total}"
                                if failed > 0:
                                    status_line += f" (❌ {failed} failed)"

                                print(f"\n📊 {status_line}")

                        elif event_type == "close":
                            status = event.get("status", "unknown")
                            message = event.get("message", "")
                            print(f"\n{'=' * 60}")

                            if status == "completed":
                                print("✅ Deployment completed successfully")
                                return EXIT_SUCCESS
                            elif status == "failed":
                                print(f"❌ Deployment failed: {message}")
                                return EXIT_ERROR
                            elif status in ("cancelled", "rejected"):
                                print(f"⚠️  Deployment {status}: {message}")
                                return EXIT_ERROR
                            elif status == "rolled_back":
                                print(f"↩️  Deployment rolled back: {message}")
                                return EXIT_ERROR
                            else:
                                print(f"Deployment ended: {status}")
                                return EXIT_SUCCESS

                        else:
                            # Regular event - print it
                            timestamp = event.get("timestamp", "")
                            if timestamp:
                                try:
                                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                                    timestamp = dt.strftime("%H:%M:%S")
                                except (ValueError, AttributeError):
                                    timestamp = timestamp[:19]

                            message = event.get("message", "")
                            details = event.get("details", {})

                            # Format based on event type
                            if event_type == "agent_updated":
                                agent = details.get("agent_id", "unknown")
                                print(f"  [{timestamp}] ✓ Agent updated: {agent}")
                            elif event_type == "agent_failed":
                                agent = details.get("agent_id", "unknown")
                                error = details.get("error", "unknown error")
                                print(f"  [{timestamp}] ❌ Agent failed: {agent} - {error}")
                                error_occurred = True
                            elif event_type == "phase_started":
                                phase = details.get("phase", "unknown")
                                print(f"\n  [{timestamp}] 🚀 Starting phase: {phase}")
                            elif event_type == "phase_completed":
                                phase = details.get("phase", "unknown")
                                print(f"  [{timestamp}] ✅ Phase completed: {phase}")
                            elif event_type == "rollback_initiated":
                                print(f"  [{timestamp}] ↩️  Rollback initiated: {message}")
                            else:
                                print(f"  [{timestamp}] {event_type}: {message}")

                # Stream ended without close event
                if error_occurred:
                    return EXIT_ERROR
                return EXIT_SUCCESS

        except httpx.ConnectError as e:
            print(f"Connection error: {e}", file=sys.stderr)
            return EXIT_ERROR
        except httpx.TimeoutException as e:
            print(f"Connection timeout: {e}", file=sys.stderr)
            return EXIT_ERROR
        except KeyboardInterrupt:
            print("\n\nWatch cancelled by user")
            return EXIT_SUCCESS
        except Exception as e:
            print(f"Error watching deployment: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR
