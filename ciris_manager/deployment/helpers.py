"""
Utility functions for deployment operations.

Pure functions for formatting, risk assessment, and version handling.
"""

from typing import Any, Dict, Optional


def format_changelog_for_agent(changelog: str) -> str:
    """
    Format Keep a Changelog format for agent notifications.

    Prioritizes changes by importance:
    1. Security (highest priority)
    2. Deprecated/Removed (breaking changes)
    3. Added/Changed (features)
    4. Fixed (bug fixes)

    Args:
        changelog: Raw changelog text from CI/CD

    Returns:
        Formatted changelog string for agent notification, or empty string if not structured
    """
    if not changelog or not changelog.strip():
        return ""

    lines = changelog.strip().split("\n")

    # Categories in priority order
    categories: Dict[str, Dict[str, Any]] = {
        "Security": {"prefix": "🔒", "items": [], "priority": 1},
        "Deprecated": {"prefix": "⚠️", "items": [], "priority": 2},
        "Removed": {"prefix": "💔", "items": [], "priority": 2},
        "Added": {"prefix": "✨", "items": [], "priority": 3},
        "Changed": {"prefix": "🔄", "items": [], "priority": 3},
        "Fixed": {"prefix": "🐛", "items": [], "priority": 4},
    }

    current_category = None
    found_categories = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if this line is a category header
        for category in categories.keys():
            if line.lower().startswith(category.lower() + ":") or line == category:
                current_category = category
                found_categories = True
                break
        else:
            # This is a changelog item
            if current_category and line.startswith(("-", "•", "*")):
                # Remove bullet and clean up
                item = line.lstrip("-•* ").strip()
                if item:
                    categories[current_category]["items"].append(item)
            elif current_category and line and not line.startswith("#"):
                # No bullet but has content and not a markdown header
                categories[current_category]["items"].append(line)

    if not found_categories:
        # Not a structured Keep a Changelog format
        return ""

    # Build the formatted output
    formatted_parts = []

    # Sort categories by priority and include only those with items
    sorted_categories = sorted(
        [(cat, data) for cat, data in categories.items() if data["items"]],
        key=lambda x: int(x[1]["priority"]),
    )

    if not sorted_categories:
        return ""

    # Limit to most important changes for conciseness
    max_items_per_category = 3
    max_total_items = 8
    total_items = 0

    for category, data in sorted_categories:
        if total_items >= max_total_items:
            break

        items_list = data["items"]
        assert isinstance(items_list, list), "Expected items to be a list"
        items_to_show = items_list[:max_items_per_category]
        remaining_items = len(items_list) - len(items_to_show)

        category_items = []
        for item in items_to_show:
            if total_items >= max_total_items:
                break
            category_items.append(f"  • {item}")
            total_items += 1

        if category_items:
            category_header = f"{data['prefix']} {category}"
            if remaining_items > 0:
                category_header += f" (+{remaining_items} more)"

            formatted_parts.append(f"\n{category_header}:")
            formatted_parts.extend(category_items)

    if formatted_parts:
        return "".join(formatted_parts)
    else:
        return ""


def get_risk_indicator(risk_level: Optional[str]) -> str:
    """
    Get risk indicator emoji and text for agent notifications.

    Args:
        risk_level: Risk level from UpdateNotification

    Returns:
        Risk indicator string with emoji and text
    """
    if not risk_level:
        return ""

    risk_indicators = {
        "high": "🚨 HIGH RISK ",
        "medium": "⚠️ MEDIUM RISK ",
        "low": "✅ LOW RISK ",
        "critical": "🔥 CRITICAL ",
    }

    return risk_indicators.get(risk_level.lower(), "")


def build_version_reason(version: Optional[str]) -> str:
    """
    Build version-aware reason string for deployments.

    Args:
        version: Version string from UpdateNotification

    Returns:
        Formatted reason string
    """
    if not version:
        return "Runtime: CD update requested"

    # Enhanced version detection for Keep a Changelog format
    if version.startswith(("v", "V")):
        # Standard semantic version (v1.2.3, v2.0.0-beta.1)
        return f"Runtime: CD update to version {version}"
    elif version.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0.")):
        # Semantic version without 'v' prefix (1.2.3, 2.0.0-beta.1)
        return f"Runtime: CD update to version v{version}"
    elif len(version) >= 7 and all(c in "0123456789abcdef" for c in version[:7]):
        # Looks like a commit SHA
        return f"Runtime: CD update to commit {version[:7]}"
    elif version.lower() in ("latest", "main", "master", "develop", "dev"):
        # Branch or tag names
        return f"Runtime: CD update to {version}"
    else:
        # Unknown format - use as-is but add context
        return f"Runtime: CD update to {version}"
