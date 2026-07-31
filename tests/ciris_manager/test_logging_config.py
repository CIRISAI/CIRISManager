"""Tests for centralized logging configuration.

Two order-dependence bugs found on 2026-07-30 live here:

1. `setup_logging` called `root_logger.handlers.clear()`, removing handlers it
   did not own (an embedder's, or pytest's).
2. `HumanReadableFormatter` permanently rewrote `record.levelname` to add ANSI
   colour. Because a LogRecord is shared across every handler, that corrupted
   the level for the file handlers and the log shipper, and broke any
   `record.levelname == "WARNING"` comparison downstream - but only once a
   colour-enabled console handler happened to be installed, which made it look
   like a flaky test rather than the production log-corruption bug it is.
"""

import logging

from ciris_manager.logging_config import HumanReadableFormatter, setup_logging


class _ForeignHandler(logging.Handler):
    """Stands in for a handler owned by an embedder (pytest's caplog, etc.)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _isolated_root():
    """Snapshot root logger state; returns (root, restore).

    setup_logging() mutates process-global logging state, so every test here
    must put it back or it becomes the polluter it is testing for.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    def _restore():
        root.handlers[:] = original_handlers
        root.setLevel(original_level)

    return root, _restore


def test_setup_logging_preserves_foreign_handlers(tmp_path):
    """A handler we did not install must survive setup_logging()."""
    root, restore = _isolated_root()
    foreign = _ForeignHandler()
    root.addHandler(foreign)
    try:
        setup_logging(log_dir=str(tmp_path / "logs"))
        assert foreign in root.handlers, "setup_logging removed a handler it does not own"
    finally:
        root.removeHandler(foreign)
        restore()


def test_setup_logging_is_idempotent_for_its_own_handlers(tmp_path):
    """Repeat calls must not stack duplicate handlers.

    This is the behaviour the original `handlers.clear()` was protecting; the
    selective removal has to keep it.
    """
    root, restore = _isolated_root()
    try:
        setup_logging(log_dir=str(tmp_path / "logs"))
        after_first = len([h for h in root.handlers if getattr(h, "_ciris_managed", False)])

        setup_logging(log_dir=str(tmp_path / "logs"))
        after_second = len([h for h in root.handlers if getattr(h, "_ciris_managed", False)])

        assert after_first > 0, "setup_logging installed no handlers"
        assert after_second == after_first, "repeat setup_logging duplicated handlers"
    finally:
        restore()


def test_caplog_still_captures_after_setup_logging(tmp_path, caplog):
    """The concrete regression: caplog must keep working afterwards.

    Directly reproduces the failure of
    test_deployment_tokens::test_env_file_sync_failure_warns_once, which saw an
    empty caplog whenever it happened to run after something called
    setup_logging().
    """
    root, restore = _isolated_root()
    try:
        setup_logging(log_dir=str(tmp_path / "logs"))
        with caplog.at_level(logging.WARNING):
            logging.getLogger("ciris_manager.deployment_tokens").warning("canary message")
        assert any("canary message" in r.message for r in caplog.records)
    finally:
        restore()


def _record(level=logging.WARNING, msg="hello"):
    return logging.LogRecord(
        name="ciris_manager.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_colour_formatter_does_not_mutate_the_record():
    """Colouring must not leak into the shared LogRecord.

    A record is handed to every handler on the logger. If the console formatter
    rewrites `levelname` in place, the rotating file handlers - which set
    use_colors=False specifically to avoid escape codes - write ANSI garbage
    into manager.log, and so does the CIRISLens shipper.
    """
    record = _record()
    coloured = HumanReadableFormatter(use_colors=True)

    out = coloured.format(record)

    assert "\033[33m" in out, "colour was not applied to the console output"
    assert record.levelname == "WARNING", "formatter corrupted the shared record"


def test_plain_formatter_sees_clean_level_after_colour_formatter():
    """The exact production handler ordering: console first, then file.

    setup_logging adds the colour console handler before the file handlers, so
    this is the order a real record is formatted in.
    """
    record = _record()
    HumanReadableFormatter(use_colors=True).format(record)
    plain = HumanReadableFormatter(use_colors=False).format(record)

    assert "\033[" not in plain, f"ANSI escape leaked into file output: {plain!r}"
    assert "WARNING" in plain


def test_levelname_comparison_survives_formatting():
    """Consumers compare levelname to a bare string; that must keep working."""
    record = _record()
    HumanReadableFormatter(use_colors=True).format(record)
    assert record.levelname == "WARNING"
