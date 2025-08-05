"""
Centralized logging configuration for CIRISManager.

Implements file-based logging with rotation, multiple log streams,
and structured logging for better observability.
"""
# mypy: ignore-errors

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import json
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON for better parsing."""
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "agent_id"):
            log_obj["agent_id"] = record.agent_id
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for console and file logs."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = False):
        """Initialize formatter with optional color support."""
        self.use_colors = use_colors
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        """Format with optional colors for console output."""
        if self.use_colors and record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    log_dir: str = "/var/log/ciris-manager",
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    use_json: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 10,
) -> None:
    """
    Configure comprehensive logging for CIRISManager.

    Args:
        log_dir: Directory for log files
        console_level: Console logging level
        file_level: File logging level
        use_json: Use JSON formatting for files
        max_bytes: Max size per log file before rotation
        backup_count: Number of backup files to keep
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    (log_path / "archive").mkdir(exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with color
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, console_level))
    console_handler.setFormatter(HumanReadableFormatter(use_colors=True))
    root_logger.addHandler(console_handler)

    # Formatter for files
    file_formatter = StructuredFormatter() if use_json else HumanReadableFormatter()

    # Main application log
    main_handler = logging.handlers.RotatingFileHandler(
        log_path / "manager.log", maxBytes=max_bytes, backupCount=backup_count
    )
    main_handler.setLevel(getattr(logging, file_level))
    main_handler.setFormatter(file_formatter)
    root_logger.addHandler(main_handler)

    # Error-only log for monitoring
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / "error.log", maxBytes=max_bytes, backupCount=backup_count
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)

    # Nginx updates log
    nginx_logger = logging.getLogger("ciris_manager.nginx")
    nginx_handler = logging.handlers.RotatingFileHandler(
        log_path / "nginx-updates.log", maxBytes=max_bytes, backupCount=backup_count
    )
    nginx_handler.setFormatter(file_formatter)
    nginx_logger.addHandler(nginx_handler)
    nginx_logger.setLevel(logging.DEBUG)
    nginx_logger.propagate = False  # Don't duplicate to root logger

    # Agent lifecycle log
    agent_logger = logging.getLogger("ciris_manager.agent_lifecycle")
    agent_handler = logging.handlers.RotatingFileHandler(
        log_path / "agent-lifecycle.log", maxBytes=max_bytes, backupCount=backup_count
    )
    agent_handler.setFormatter(file_formatter)
    agent_logger.addHandler(agent_handler)
    agent_logger.setLevel(logging.DEBUG)
    agent_logger.propagate = False

    # API access log
    api_logger = logging.getLogger("ciris_manager.api")
    api_handler = logging.handlers.RotatingFileHandler(
        log_path / "api-access.log", maxBytes=max_bytes, backupCount=backup_count
    )
    api_handler.setFormatter(file_formatter)
    api_logger.addHandler(api_handler)
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False

    # Set third-party loggers to WARNING to reduce noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("docker").setLevel(logging.WARNING)

    # Log startup
    root_logger.info(
        f"Logging initialized - Console: {console_level}, File: {file_level}, "
        f"Directory: {log_dir}, JSON: {use_json}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (e.g., "ciris_manager.nginx")

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding contextual information to logs."""

    def __init__(self, logger: logging.Logger, **kwargs):
        """
        Initialize log context.

        Args:
            logger: Logger to add context to
            **kwargs: Context fields to add to all logs
        """
        self.logger = logger
        self.context = kwargs
        self.old_factory = None

    def __enter__(self):
        """Enter context and inject fields."""
        old_factory = logging.getLogRecordFactory()
        self.old_factory = old_factory

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and restore factory."""
        if self.old_factory:
            logging.setLogRecordFactory(self.old_factory)


# Convenience function for agent operations
def log_agent_operation(
    operation: str, agent_id: str, details: Optional[Dict[str, Any]] = None, level: str = "INFO"
) -> None:
    """
    Log an agent lifecycle operation.

    Args:
        operation: Operation type (create, delete, start, stop, etc.)
        agent_id: Agent identifier
        details: Additional operation details
        level: Log level (INFO, WARNING, ERROR)
    """
    logger = logging.getLogger("ciris_manager.agent_lifecycle")

    message = f"Agent operation: {operation}"
    extra = {"agent_id": agent_id}

    if details:
        extra.update(details)
        message += f" - {json.dumps(details)}"

    log_method = getattr(logger, level.lower())
    log_method(message, extra=extra)


# Convenience function for nginx operations
def log_nginx_operation(
    operation: str,
    success: bool,
    details: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """
    Log an nginx configuration operation.

    Args:
        operation: Operation type (update, reload, validate, etc.)
        success: Whether operation succeeded
        details: Additional operation details
        error: Error message if failed
    """
    logger = logging.getLogger("ciris_manager.nginx")

    level = "INFO" if success else "ERROR"
    message = f"Nginx {operation}: {'SUCCESS' if success else 'FAILED'}"

    if error:
        message += f" - {error}"
    if details:
        message += f" - {json.dumps(details)}"

    log_method = getattr(logger, level.lower())
    log_method(message)
