from __future__ import annotations

import logging
from PySide6.QtCore import QObject, Signal


class QtLogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """
    Logging handler that forwards formatted log records to a Qt signal.
    """
    def __init__(self, emitter: QtLogEmitter):
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._emitter.message.emit(msg)