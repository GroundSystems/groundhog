"""Executable black-box histories for Groundhog contract checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable

from verify.backend import BackendOptions

from .history import HistoryRecorder, OperationRecord
from .linearizability import CheckResult, CheckStatus, check_history
from .transport import GroundhogProcess


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    history_path: Path
    check: CheckResult

    def require_linearizable(self) -> None:
        if self.check.status != CheckStatus.LINEARIZABLE:
            raise AssertionError(
                f"scenario {self.name!r} is {self.check.status.value}: {self.check.reason}"
            )


def event_batch(
    batch_id: str,
    record_key: str,
    *,
    source: str = "verify",
    stream: str = "records",
    payload: Any | None = None,
    expected_frontier: str | None | object = ...,
) -> dict[str, Any]:
    batch: dict[str, Any] = {
        "v": 1,
        "batch_id": batch_id,
        "source": source,
        "events": [
            {
                "stream": stream,
                "record_key": record_key,
                "kind": "upserted",
                "payload": payload if payload is not None else {"id": record_key},
            }
        ],
    }
    if expected_frontier is not ...:
        batch["stream_precondition"] = {
            "stream": stream,
            "expected_frontier": expected_frontier,
        }
    return batch


def _response_body(operation: OperationRecord) -> dict[str, Any]:
    if operation.response is None:
        raise AssertionError(f"{operation.operation_id} has no HTTP response")
    value = operation.response.json_body()
    if not isinstance(value, dict):
        raise AssertionError(f"{operation.operation_id} response is not an object")
    return value


def _record_result(name: str, recorder: HistoryRecorder) -> ScenarioResult:
    history = recorder.history()
    return ScenarioResult(name, recorder.path, check_history(history))


def _with_process(
    binary: str | Path,
    output_dir: Path,
    seed: int,
    name: str,
    run: Callable[[GroundhogProcess, HistoryRecorder], None],
    backend: BackendOptions,
) -> ScenarioResult:
    recorder = HistoryRecorder(output_dir / f"{name}.json", seed)
    with GroundhogProcess(binary, backend=backend) as process:
        run(process, recorder)
    result = _record_result(name, recorder)
    result.require_linearizable()
    return result


def run_append_scenarios(
    binary: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 1,
    backend: BackendOptions | None = None,
) -> tuple[ScenarioResult, ...]:
    """Run retry, conflict, precondition, and concurrent append scenarios."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or BackendOptions()

    def retry(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        batch = event_batch("retry", "retry")
        first = recorder.request(
            process.client,
            client_id="retry-client",
            operation_id="retry-commit",
            method="POST",
            target="/v1/events",
            json_body=batch,
        )
        second = recorder.request(
            process.client,
            client_id="retry-client",
            operation_id="retry-duplicate",
            method="POST",
            target="/v1/events",
            json_body=batch,
        )
        if _response_body(first).get("status") != "committed":
            raise AssertionError("first retry scenario append did not commit")
        if _response_body(second).get("status") != "duplicate":
            raise AssertionError("exact retry did not return duplicate")

    def conflict(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        original = event_batch("conflict", "conflict", payload={"revision": 1})
        changed = event_batch("conflict", "conflict", payload={"revision": 2})
        recorder.request(
            process.client,
            client_id="conflict-client",
            operation_id="conflict-commit",
            method="POST",
            target="/v1/events",
            json_body=original,
        )
        rejected = recorder.request(
            process.client,
            client_id="conflict-client",
            operation_id="conflict-reject",
            method="POST",
            target="/v1/events",
            json_body=changed,
        )
        if rejected.response is None or rejected.response.status != 409:
            raise AssertionError("changed batch identity did not conflict")

    def precondition(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        seed_batch = event_batch("precondition-seed", "seed", expected_frontier=None)
        seeded = recorder.request(
            process.client,
            client_id="precondition-client",
            operation_id="precondition-seed",
            method="POST",
            target="/v1/events",
            json_body=seed_batch,
        )
        frontier = _response_body(seeded)["last_event_id"]
        candidate = event_batch("precondition-candidate", "candidate", expected_frontier=None)
        stale = recorder.request(
            process.client,
            client_id="precondition-client",
            operation_id="precondition-stale",
            method="POST",
            target="/v1/events",
            json_body=candidate,
        )
        if stale.response is None or stale.response.status != 409:
            raise AssertionError("stale stream precondition did not conflict")
        candidate["stream_precondition"]["expected_frontier"] = frontier
        committed = recorder.request(
            process.client,
            client_id="precondition-client",
            operation_id="precondition-commit",
            method="POST",
            target="/v1/events",
            json_body=candidate,
        )
        duplicate = recorder.request(
            process.client,
            client_id="precondition-client",
            operation_id="precondition-duplicate",
            method="POST",
            target="/v1/events",
            json_body=candidate,
        )
        if _response_body(committed).get("status") != "committed":
            raise AssertionError("corrected stream precondition did not commit")
        if _response_body(duplicate).get("status") != "duplicate":
            raise AssertionError("idempotency did not precede the stale precondition")

    def concurrent(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        barrier = threading.Barrier(2)

        def append(index: int) -> OperationRecord:
            barrier.wait(timeout=5)
            return recorder.request(
                process.client,
                client_id=f"concurrent-client-{index}",
                operation_id=f"concurrent-{index}",
                method="POST",
                target="/v1/events",
                json_body=event_batch(
                    f"concurrent-{index}",
                    f"concurrent-{index}",
                    expected_frontier=None,
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            operations = tuple(pool.map(append, (1, 2)))
        statuses = sorted(
            operation.response.status if operation.response is not None else -1
            for operation in operations
        )
        if statuses != [200, 409]:
            raise AssertionError(f"concurrent preconditions returned {statuses!r}")

    def atomic_batch(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        batch = event_batch(
            "atomic-three",
            "atomic-0",
            source="atomic-source",
            stream="atomic-stream",
        )
        batch["events"] = [
            {
                "stream": "atomic-stream",
                "record_key": f"atomic-{index}",
                "kind": "upserted",
                "payload": {"index": index},
            }
            for index in range(3)
        ]
        committed = recorder.request(
            process.client,
            client_id="atomic-client",
            operation_id="atomic-commit",
            method="POST",
            target="/v1/events",
            json_body=batch,
        )
        if _response_body(committed).get("events") != 3:
            raise AssertionError("multi-event append receipt has the wrong count")
        replayed = recorder.request(
            process.client,
            client_id="atomic-client",
            operation_id="atomic-replay",
            method="GET",
            target="/v1/events?source=atomic-source&stream=atomic-stream&limit=10",
        )
        visible = _response_body(replayed).get("events", [])
        keys = [event.get("record_key") for event in visible]
        if keys != ["atomic-0", "atomic-1", "atomic-2"]:
            raise AssertionError(f"multi-event replay visibility is {keys!r}")

    cases = (
        ("append-retry", retry),
        ("append-conflict", conflict),
        ("append-precondition", precondition),
        ("append-concurrent", concurrent),
        ("append-atomic-batch", atomic_batch),
    )
    return tuple(
        _with_process(binary, destination, seed + index, name, scenario, selected_backend)
        for index, (name, scenario) in enumerate(cases)
    )


def run_retirement_race_scenarios(
    binary: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 100,
    iterations: int = 8,
    backend: BackendOptions | None = None,
) -> tuple[ScenarioResult, ...]:
    """Race one new append against retirement of the same source."""

    if iterations < 1:
        raise ValueError("iterations must be positive")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or BackendOptions()

    def make_race(iteration: int) -> Callable[[GroundhogProcess, HistoryRecorder], None]:
        def race(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
            source = f"retiring-{iteration}"
            seeded = recorder.request(
                process.client,
                client_id="setup-client",
                operation_id="retirement-seed",
                method="POST",
                target="/v1/events",
                json_body=event_batch("seed", "seed", source=source),
            )
            seed_frontier = _response_body(seeded)["last_event_id"]
            barrier = threading.Barrier(2)

            def append() -> OperationRecord:
                barrier.wait(timeout=5)
                return recorder.request(
                    process.client,
                    client_id="append-client",
                    operation_id="retirement-racing-append",
                    method="POST",
                    target="/v1/events",
                    json_body=event_batch("racing", "racing", source=source),
                )

            def retire() -> OperationRecord:
                barrier.wait(timeout=5)
                return recorder.request(
                    process.client,
                    client_id="retirement-client",
                    operation_id="retirement-racing-retire",
                    method="POST",
                    target="/v1/sources/retire",
                    json_body={"v": 1, "source": source},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                append_future = pool.submit(append)
                retire_future = pool.submit(retire)
                appended = append_future.result()
                retired = retire_future.result()
            if retired.response is None or retired.response.status != 200:
                raise AssertionError("retirement race did not return a retirement receipt")
            retirement_body = _response_body(retired)
            if appended.response is None:
                raise AssertionError("racing append lacks a response")
            if appended.response.status == 200:
                append_frontier = _response_body(appended)["last_event_id"]
                if retirement_body.get("final_frontier") != append_frontier:
                    raise AssertionError("retirement did not include the winning append")
            elif appended.response.status == 409:
                if retirement_body.get("final_frontier") != seed_frontier:
                    raise AssertionError("retirement frontier changed after append refusal")
            else:
                raise AssertionError(
                    f"racing append returned status {appended.response.status}"
                )

        return race

    return tuple(
        _with_process(
            binary,
            destination,
            seed + iteration,
            f"retirement-race-{iteration}",
            make_race(iteration),
            selected_backend,
        )
        for iteration in range(iterations)
    )


def run_replay_scenarios(
    binary: str | Path,
    output_dir: str | Path,
    *,
    seed: int = 200,
    backend: BackendOptions | None = None,
) -> tuple[ScenarioResult, ...]:
    """Check replay visibility and anchored stream pagination."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or BackendOptions()

    def replay_visibility(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        committed = recorder.request(
            process.client,
            client_id="replay-client",
            operation_id="replay-append",
            method="POST",
            target="/v1/events",
            json_body=event_batch(
                "visible",
                "visible",
                source="visible-source",
                stream="visible-stream",
            ),
        )
        frontier = _response_body(committed)["last_event_id"]
        replayed = recorder.request(
            process.client,
            client_id="replay-client",
            operation_id="replay-visible",
            method="GET",
            target="/v1/events?source=visible-source&stream=visible-stream&limit=10",
        )
        replay_body = _response_body(replayed)
        if [event.get("event_id") for event in replay_body.get("events", [])] != [frontier]:
            raise AssertionError("finite replay did not expose the committed event")
        resumed = recorder.request(
            process.client,
            client_id="replay-client",
            operation_id="replay-resume",
            method="GET",
            target=f"/v1/events?after={frontier}&limit=10",
        )
        if _response_body(resumed).get("events") != []:
            raise AssertionError("replay after the frontier returned an event")

    def anchored_streams(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        for stream in ("a", "c", "d"):
            recorder.request(
                process.client,
                client_id="streams-client",
                operation_id=f"streams-initial-{stream}",
                method="POST",
                target="/v1/events",
                json_body=event_batch(
                    f"streams-initial-{stream}",
                    stream,
                    source="anchor",
                    stream=stream,
                ),
            )
        first = recorder.request(
            process.client,
            client_id="streams-client",
            operation_id="streams-first-page",
            method="GET",
            target="/v1/streams?source=anchor&limit=1",
        )
        first_body = _response_body(first)
        through = first_body["snapshot_through_event_id"]
        after = first_body["next_after"]
        if after != "anchor/a":
            raise AssertionError(f"first stream cursor is {after!r}")
        recorder.request(
            process.client,
            client_id="streams-client",
            operation_id="streams-later-b",
            method="POST",
            target="/v1/events",
            json_body=event_batch(
                "streams-later-b", "b", source="anchor", stream="b"
            ),
        )
        anchored = recorder.request(
            process.client,
            client_id="streams-client",
            operation_id="streams-anchored-page",
            method="GET",
            target=f"/v1/streams?source=anchor&limit=10&after=anchor%2Fa&through={through}",
        )
        anchored_names = [row["stream"] for row in _response_body(anchored)["streams"]]
        if anchored_names != ["c", "d"]:
            raise AssertionError(f"anchored stream page is {anchored_names!r}")
        fresh = recorder.request(
            process.client,
            client_id="streams-client",
            operation_id="streams-fresh-page",
            method="GET",
            target="/v1/streams?source=anchor&limit=10",
        )
        fresh_names = [row["stream"] for row in _response_body(fresh)["streams"]]
        if fresh_names != ["a", "b", "c", "d"]:
            raise AssertionError(f"fresh stream page is {fresh_names!r}")

    cases = (
        ("replay-visibility", replay_visibility),
        ("streams-anchored-pagination", anchored_streams),
    )
    return tuple(
        _with_process(binary, destination, seed + index, name, scenario, selected_backend)
        for index, (name, scenario) in enumerate(cases)
    )


def run_s3_local_state_loss_scenario(
    binary: str | Path,
    output_dir: str | Path,
    *,
    seed: int,
    backend: BackendOptions,
) -> ScenarioResult:
    """Verify an acknowledged batch after deleting every local deployment file."""
    if backend.name != "s3":
        raise ValueError("local-state-loss scenario requires the S3 backend")

    def local_state_loss(process: GroundhogProcess, recorder: HistoryRecorder) -> None:
        batch = event_batch("local-state-loss", "durable")
        committed = recorder.request(
            process.client,
            client_id="local-state-loss",
            operation_id="local-state-loss-commit",
            method="POST",
            target="/v1/events",
            json_body=batch,
        )
        if _response_body(committed).get("status") != "committed":
            raise AssertionError("local-state-loss batch did not commit")
        process.reset_local_state()
        duplicate = recorder.request(
            process.client,
            client_id="local-state-loss",
            operation_id="local-state-loss-duplicate",
            method="POST",
            target="/v1/events",
            json_body=batch,
        )
        if _response_body(duplicate).get("status") != "duplicate":
            raise AssertionError("reattached deployment did not return the durable receipt")
        replay = recorder.request(
            process.client,
            client_id="local-state-loss",
            operation_id="local-state-loss-replay",
            method="GET",
            target="/v1/events?source=verify",
        )
        events = _response_body(replay).get("events")
        if not isinstance(events, list) or len(events) != 1:
            raise AssertionError("reattached deployment did not replay the durable event")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    return _with_process(
        binary,
        destination,
        seed,
        "s3-local-state-loss",
        local_state_loss,
        backend,
    )
