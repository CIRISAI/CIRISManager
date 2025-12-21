"""
Output formatting utilities for the CIRIS CLI tool.

This module provides consistent output formatting across all CLI commands,
supporting table, JSON, and YAML formats.
"""

from typing import Any, List, Dict, Optional
import json
import yaml
from tabulate import tabulate  # type: ignore[import-untyped]


class OutputFormatterImpl:
    """Implementation of OutputFormatter protocol."""

    def format_table(self, data: List[Dict[str, Any]], columns: Optional[List[str]] = None) -> str:
        """
        Format data as a table using tabulate.

        Args:
            data: List of dictionaries to format
            columns: Optional list of column names to include (defaults to all keys)

        Returns:
            Formatted table string
        """
        if not data:
            return "No data available."

        # Handle empty list
        if len(data) == 0:
            return "No data available."

        # If columns not specified, use all keys from first item
        if columns is None:
            # Get all unique keys across all dictionaries
            all_keys: set[str] = set()
            for item in data:
                if isinstance(item, dict):
                    all_keys.update(item.keys())
            columns = sorted(all_keys)

        # Build table data - only include specified columns
        table_data = []
        for item in data:
            if not isinstance(item, dict):
                # Handle non-dict items by converting to dict
                item = {"value": item}

            row = []
            for col in columns:
                value = item.get(col)
                # Handle None values
                if value is None:
                    row.append("")
                # Handle nested objects
                elif isinstance(value, (dict, list)):
                    row.append(json.dumps(value))
                # Handle booleans
                elif isinstance(value, bool):
                    row.append("Yes" if value else "No")
                else:
                    row.append(str(value))
            table_data.append(row)

        # Format as table with headers
        result: str = tabulate(table_data, headers=columns, tablefmt="simple")
        return result

    def format_json(self, data: Any) -> str:
        """
        Format data as JSON.

        Args:
            data: Data to format (can be dict, list, or any JSON-serializable type)

        Returns:
            Formatted JSON string
        """
        if data is None:
            return "{}"

        try:
            return json.dumps(data, indent=2, default=str)
        except (TypeError, ValueError) as e:
            # Fallback for non-serializable objects
            return json.dumps({"error": f"Failed to serialize data: {e}"}, indent=2)

    def format_yaml(self, data: Any) -> str:
        """
        Format data as YAML.

        Args:
            data: Data to format (can be dict, list, or any YAML-serializable type)

        Returns:
            Formatted YAML string
        """
        if data is None:
            return "{}"

        try:
            return yaml.safe_dump(
                data, default_flow_style=False, sort_keys=False, allow_unicode=True
            )
        except yaml.YAMLError as e:
            # Fallback for non-serializable objects
            return yaml.safe_dump(
                {"error": f"Failed to serialize data: {e}"},
                default_flow_style=False,
            )

    def format_output(self, data: Any, format: str, columns: Optional[List[str]] = None) -> str:
        """
        Format output based on format string.

        Args:
            data: Data to format
            format: Output format ('table', 'json', or 'yaml')
            columns: Optional list of columns for table format

        Returns:
            Formatted output string

        Raises:
            ValueError: If format is not recognized
        """
        format = format.lower()

        if format == "json":
            return self.format_json(data)
        elif format == "yaml":
            return self.format_yaml(data)
        elif format == "table":
            # Convert single dict to list for table formatting
            if isinstance(data, dict) and not any(
                isinstance(v, (list, dict)) for v in data.values()
            ):
                # Simple dict - convert to key-value list
                data = [{"key": k, "value": v} for k, v in data.items()]
                if columns is None:
                    columns = ["key", "value"]
            elif isinstance(data, dict):
                # Complex dict - format as JSON instead
                return self.format_json(data)
            elif not isinstance(data, list):
                # Other non-list types
                data = [{"value": data}]

            return self.format_table(data, columns)
        else:
            raise ValueError(f"Unknown format: {format}. Use 'table', 'json', or 'yaml'.")


# Create default instance for easy importing
formatter = OutputFormatterImpl()
