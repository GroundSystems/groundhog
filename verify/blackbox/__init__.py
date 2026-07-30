"""Black-box verification tools for the Groundhog HTTP API."""

from .transport import GroundhogProcess, HttpResponse, TransportError, UnixHttpClient
from .history import History, HistoryRecorder, OperationRecord
from .linearizability import CheckResult, CheckStatus, check_history
from .model import ModelViolation, SequentialModel
from .scenarios import (
    ScenarioResult,
    event_batch,
    run_append_scenarios,
    run_replay_scenarios,
    run_retirement_race_scenarios,
)

__all__ = [
    "CheckResult",
    "CheckStatus",
    "GroundhogProcess",
    "History",
    "HistoryRecorder",
    "HttpResponse",
    "ModelViolation",
    "OperationRecord",
    "ScenarioResult",
    "SequentialModel",
    "TransportError",
    "UnixHttpClient",
    "check_history",
    "event_batch",
    "run_append_scenarios",
    "run_replay_scenarios",
    "run_retirement_race_scenarios",
]
