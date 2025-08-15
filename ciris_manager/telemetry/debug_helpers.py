"""
Debug helpers for telemetry system - FAIL FAST AND LOUD.

This module provides aggressive logging and validation to make issues immediately obvious.
"""

import logging
from typing import Any
from ciris_manager.telemetry.schemas import AgentOperationalMetrics, TelemetrySnapshot

logger = logging.getLogger(__name__)


def validate_agent_metrics(metrics: AgentOperationalMetrics, source: str) -> None:
    """
    Validate agent metrics and SCREAM if something is wrong.

    Args:
        metrics: The metrics to validate
        source: Where these metrics came from (for debugging)
    """
    logger.info(f"[{source}] Agent metrics for {metrics.agent_name} (ID: {metrics.agent_id}):")
    logger.info(f"  ✓ cost_cents_24h: {metrics.cost_cents_24h} cents")
    logger.info(f"  ✓ carbon_24h_grams: {metrics.carbon_24h_grams} grams")
    logger.info(f"  ✓ message_count_24h: {metrics.message_count_24h}")
    logger.info(f"  ✓ api_healthy: {metrics.api_healthy}")
    logger.info(f"  ✓ cognitive_state: {metrics.cognitive_state}")

    # FAIL LOUD if we have inconsistent data
    if metrics.api_healthy and metrics.cost_cents_24h == 0:
        logger.warning(f"⚠️ SUSPICIOUS: {metrics.agent_name} is healthy but has 0 cost!")

    if metrics.api_healthy and metrics.uptime_seconds > 3600 and metrics.cost_cents_24h == 0:
        logger.error(
            f"❌ PROBLEM: {metrics.agent_name} has been up for {metrics.uptime_seconds}s but 0 cost!"
        )


def validate_snapshot(snapshot: TelemetrySnapshot, source: str) -> None:
    """
    Validate a telemetry snapshot and SCREAM about issues.

    Args:
        snapshot: The snapshot to validate
        source: Where this snapshot came from
    """
    logger.info(f"[{source}] Validating snapshot {snapshot.snapshot_id}:")
    logger.info(f"  📊 Contains {len(snapshot.agents)} agents")

    total_cost = 0
    total_messages = 0

    for agent in snapshot.agents:
        logger.info(f"    Agent '{agent.agent_name}':")
        logger.info(f"      - cost: {agent.cost_cents_24h} cents")
        logger.info(f"      - messages: {agent.message_count_24h}")
        logger.info(f"      - carbon: {agent.carbon_24h_grams} grams")

        total_cost += agent.cost_cents_24h
        total_messages += agent.message_count_24h

        # SCREAM if something looks wrong
        if agent.api_healthy and agent.cost_cents_24h == 0:
            logger.warning(f"    ⚠️ SUSPICIOUS: {agent.agent_name} healthy but 0 cost!")

    logger.info(f"  📈 Snapshot totals: cost={total_cost} cents, messages={total_messages}")

    if len(snapshot.agents) > 0 and total_cost == 0:
        logger.error(f"❌ PROBLEM: {len(snapshot.agents)} agents but ZERO total cost!")
        logger.error("   This should NEVER happen if agents are running!")


def trace_value(value: Any, name: str, location: str) -> Any:
    """
    Trace a value through the system and SCREAM if it changes unexpectedly.

    Args:
        value: The value to trace
        name: Name of the value
        location: Where we are in the code

    Returns:
        The value (for chaining)
    """
    if isinstance(value, (int, float)):
        if value == 0:
            logger.warning(f"🔍 [{location}] {name} = {value} (ZERO!)")
        else:
            logger.info(f"🔍 [{location}] {name} = {value}")
    else:
        logger.info(f"🔍 [{location}] {name} = {value}")

    return value


def validate_auth_response(response: Any, agent_id: str, endpoint: str) -> None:
    """
    Validate API response and SCREAM about auth issues.

    Args:
        response: The HTTP response
        agent_id: Which agent we called
        endpoint: Which endpoint we called
    """
    logger.info(f"📡 API call to {agent_id} {endpoint}:")
    logger.info(f"   Status: {response.status_code}")

    if response.status_code == 401:
        logger.error(f"❌ AUTH FAILED for {agent_id}! Check service tokens!")
        logger.error(f"   Response: {response.text[:200]}")
        raise ValueError(f"Authentication failed for {agent_id}")

    if response.status_code == 403:
        logger.error(f"❌ FORBIDDEN for {agent_id}! Check permissions!")
        raise ValueError(f"Forbidden access to {agent_id}")

    if response.status_code != 200:
        logger.warning(f"⚠️ Non-200 status from {agent_id}: {response.status_code}")
        logger.warning(f"   Response: {response.text[:200]}")


def assert_metrics_flow(
    raw_value: float,
    parsed_value: float,
    stored_value: float,
    aggregated_value: float,
    field_name: str,
) -> None:
    """
    Assert that metrics flow correctly through the system.

    Args:
        raw_value: Value from API response
        parsed_value: Value after parsing
        stored_value: Value in data structure
        aggregated_value: Value after aggregation
        field_name: Name of the field
    """
    logger.info(f"🔄 Metrics flow for {field_name}:")
    logger.info(f"   1. Raw from API: {raw_value}")
    logger.info(f"   2. After parsing: {parsed_value}")
    logger.info(f"   3. In data structure: {stored_value}")
    logger.info(f"   4. After aggregation: {aggregated_value}")

    if raw_value != parsed_value:
        logger.error(f"❌ VALUE CHANGED during parsing! {raw_value} → {parsed_value}")
        raise ValueError(f"Parsing corrupted {field_name}")

    if parsed_value != stored_value:
        logger.error(f"❌ VALUE CHANGED during storage! {parsed_value} → {stored_value}")
        raise ValueError(f"Storage corrupted {field_name}")

    if stored_value > 0 and aggregated_value == 0:
        logger.error(f"❌ VALUE LOST during aggregation! {stored_value} → {aggregated_value}")
        raise ValueError(f"Aggregation lost {field_name}")
