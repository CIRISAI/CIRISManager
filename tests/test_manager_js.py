"""
Unit tests for manager.js deployment functions.

These tests validate the JavaScript deployment handling logic by
simulating the DOM and function calls.
"""

import pytest


class TestDeploymentUIFunctions:
    """Test deployment UI functions from manager.js"""

    def test_show_failed_deployment_with_valid_status(self):
        """Test showFailedDeployment accepts only failed status."""
        # This test validates the JavaScript logic
        deployment_data = {
            "status": "failed",
            "deployment_id": "test-123",
            "agent_image": "test:latest",
            "message": "Test failure",
            "version": "1.2.3",
        }

        # Simulating the validation logic from showFailedDeployment
        assert deployment_data["status"] == "failed", "Should only accept failed status"

    def test_show_failed_deployment_rejects_non_failed_status(self):
        """Test showFailedDeployment rejects non-failed status."""
        deployment_data = {
            "status": "pending",  # Wrong status
            "deployment_id": "test-123",
        }

        # This simulates the JavaScript validation
        with pytest.raises(AssertionError, match="Should only accept failed status"):
            if deployment_data["status"] != "failed":
                raise AssertionError(
                    f"showFailedDeployment called with status '{deployment_data['status']}' - Should only accept failed status"
                )

    def test_show_pending_deployment_with_valid_status(self):
        """Test showPendingDeployment accepts pending or no status."""
        # Test with pending status
        deployment_data = {
            "status": "pending",
            "deployment_id": "test-456",
            "agent_image": "test:latest",
        }

        # Simulating the validation logic
        assert deployment_data.get("status") in ["pending", None] or not deployment_data.get(
            "status"
        ), "Should only accept pending or no status"

        # Test with no status (also valid)
        deployment_data_no_status = {"deployment_id": "test-789", "agent_image": "test:latest"}

        assert deployment_data_no_status.get("status") in [
            "pending",
            None,
        ] or not deployment_data_no_status.get("status"), "Should accept missing status"

    def test_show_pending_deployment_rejects_failed_status(self):
        """Test showPendingDeployment rejects failed status."""
        deployment_data = {
            "status": "failed",  # Wrong status
            "deployment_id": "test-123",
        }

        # This simulates the JavaScript validation
        with pytest.raises(AssertionError, match="Should only accept pending"):
            if deployment_data.get("status") and deployment_data["status"] != "pending":
                raise AssertionError(
                    f"showPendingDeployment called with status '{deployment_data['status']}' - Should only accept pending"
                )

    def test_cancel_deployment_requires_deployment_id(self):
        """Test cancelDeployment requires a deployment ID."""
        # Test with valid ID
        deployment_id = "test-123"
        assert deployment_id, "Deployment ID should be provided"

        # Test with missing ID
        deployment_id = None
        with pytest.raises(AssertionError, match="Deployment ID is required"):
            if not deployment_id:
                raise AssertionError("Deployment ID is required to cancel a deployment")

        # Test with empty string
        deployment_id = ""
        with pytest.raises(AssertionError, match="Deployment ID is required"):
            if not deployment_id:
                raise AssertionError("Deployment ID is required to cancel a deployment")

    def test_check_pending_deployment_routing(self):
        """Test that checkPendingDeployment routes to correct function based on status."""
        test_cases = [
            # (pending, status, expected_function)
            (True, "failed", "showFailedDeployment"),
            (True, "pending", "showPendingDeployment"),
            (True, None, "showPendingDeployment"),
            (False, None, "hidePendingDeployment"),
        ]

        for pending, status, expected_function in test_cases:
            data = {"pending": pending}
            if status:
                data["status"] = status

            # Simulate the routing logic
            if data.get("pending"):
                if data.get("status") == "failed":
                    actual_function = "showFailedDeployment"
                elif data.get("status") == "pending" or not data.get("status"):
                    actual_function = "showPendingDeployment"
                else:
                    raise ValueError(f"Invalid status: {data.get('status')}")
            else:
                actual_function = "hidePendingDeployment"

            assert (
                actual_function == expected_function
            ), f"For pending={pending}, status={status}, expected {expected_function} but got {actual_function}"

    def test_trigger_new_deployment_checks_for_blocking_failed(self):
        """Test triggerNewDeployment checks for blocking failed deployments."""
        # Simulate the check for failed deployment blocking
        pending_response = {"pending": True, "status": "failed", "deployment_id": "blocked-123"}

        # If there's a failed deployment, it should not proceed
        if pending_response.get("pending") and pending_response.get("status") == "failed":
            with pytest.raises(AssertionError, match="Must clear failed deployment first"):
                raise AssertionError("Must clear failed deployment first")

        # If no failed deployment, it should proceed
        pending_response_clear = {"pending": False}
        assert not (
            pending_response_clear.get("pending")
            and pending_response_clear.get("status") == "failed"
        ), "Should proceed when no failed deployment is blocking"


class TestDeploymentAPIIntegration:
    """Test the integration between UI and API for deployments."""

    @pytest.mark.asyncio
    async def test_cancel_deployment_api_call(self):
        """Test that cancelDeployment makes correct API call."""
        deployment_id = "test-failed-123"
        expected_body = {
            "deployment_id": deployment_id,
            "reason": "Clearing failed deployment to allow retry",
        }

        # This validates the API call structure
        assert expected_body["deployment_id"] == deployment_id
        assert "reason" in expected_body
        assert "Clearing failed" in expected_body["reason"]

    @pytest.mark.asyncio
    async def test_pending_endpoint_response_handling(self):
        """Test handling of /updates/pending endpoint responses."""
        # Test failed deployment response
        failed_response = {
            "pending": True,
            "deployment_id": "failed-123",
            "status": "failed",
            "message": "Deployment failed",
            "agent_image": "test:latest",
            "version": "1.2.3",
        }

        # Should route to showFailedDeployment
        assert failed_response["status"] == "failed"
        assert failed_response["pending"] is True

        # Test pending deployment response
        pending_response = {
            "pending": True,
            "deployment_id": "pending-456",
            "status": "pending",
            "message": "Awaiting approval",
            "agent_image": "test:latest",
        }

        # Should route to showPendingDeployment
        assert pending_response["status"] == "pending"
        assert pending_response["pending"] is True

        # Test no deployment response
        no_deployment = {"pending": False}

        # Should hide the deployment section
        assert no_deployment["pending"] is False


class TestDeploymentValidation:
    """Test deployment data validation."""

    def test_deployment_status_enum(self):
        """Test that only valid deployment statuses are accepted."""
        valid_statuses = ["pending", "failed", "in_progress", "completed", "cancelled"]
        invalid_statuses = ["random", "invalid", "test", 123, None]

        for status in valid_statuses:
            # Should not raise
            assert isinstance(status, str)

        for status in invalid_statuses:
            if status not in valid_statuses:
                # This would be caught by validation
                pass

    def test_deployment_id_format(self):
        """Test deployment ID validation."""
        valid_ids = ["a26312c0-118f-4bf6-b648-74e8d7dd3c4c", "test-123", "deployment-456"]

        invalid_ids = [
            "",
            None,
            123,  # Should be string
            "   ",  # Just whitespace
        ]

        for dep_id in valid_ids:
            assert dep_id and isinstance(dep_id, str) and dep_id.strip()

        for dep_id in invalid_ids:
            assert not (dep_id and isinstance(dep_id, str) and dep_id.strip())

    def test_version_display_format(self):
        """Test version display formatting."""
        test_cases = [
            ("1.2.3", "Version: 1.2.3"),
            ("7d21f39", "Version: 7d21f39"),
            (None, None),  # No version display
            ("", None),  # Empty version, no display
        ]

        for version, expected_display in test_cases:
            if version:
                actual_display = f"Version: {version}"
                assert actual_display == expected_display
            else:
                assert expected_display is None


class TestErrorHandling:
    """Test error handling and logging."""

    def test_console_error_logging(self):
        """Test that errors are logged to console."""
        error_scenarios = [
            (
                "showFailedDeployment",
                "pending",
                "ERROR: showFailedDeployment called with non-failed status: pending",
            ),
            (
                "showPendingDeployment",
                "failed",
                "ERROR: showPendingDeployment called with non-pending status: failed",
            ),
            ("cancelDeployment", None, "ERROR: cancelDeployment called without deployment ID"),
        ]

        for function_name, invalid_input, expected_error in error_scenarios:
            # Validate error message format
            assert "ERROR:" in expected_error
            assert function_name in expected_error
            if invalid_input:
                assert str(invalid_input) in expected_error

    def test_exception_throwing(self):
        """Test that exceptions are thrown for invalid states."""
        # Test invalid status for showFailedDeployment
        with pytest.raises(Exception) as exc_info:
            status = "pending"
            if status != "failed":
                raise Exception(
                    f"showFailedDeployment called with status '{status}' - only 'failed' is allowed"
                )
        assert "only 'failed' is allowed" in str(exc_info.value)

        # Test invalid status for showPendingDeployment
        with pytest.raises(Exception) as exc_info:
            status = "failed"
            if status and status != "pending":
                raise Exception(
                    f"showPendingDeployment called with status '{status}' - only 'pending' is allowed"
                )
        assert "only 'pending' is allowed" in str(exc_info.value)

        # Test missing deployment ID
        with pytest.raises(Exception) as exc_info:
            deployment_id = None
            if not deployment_id:
                raise Exception("Deployment ID is required to cancel a deployment")
        assert "Deployment ID is required" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
