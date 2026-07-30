from __future__ import annotations

import copy
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from verify.conformance.validate import ContractError, load_document, validate_document

ROOT = Path(__file__).resolve().parents[3]
DOCUMENT = load_document(ROOT / "openapi.yaml")


class ValidatorTests(unittest.TestCase):
    def assert_rejected(
        self, mutation: Callable[[dict[str, Any]], None], text: str
    ) -> None:
        document = copy.deepcopy(DOCUMENT)
        mutation(document)
        with self.assertRaisesRegex(ContractError, text):
            validate_document(document)

    def test_canonical_document_passes(self) -> None:
        validate_document(copy.deepcopy(DOCUMENT))

    def test_structure_is_checked(self) -> None:
        self.assert_rejected(lambda document: document.update(openapi="3.1.0"), "3.2.0")

    def test_local_references_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["schemas"]["Event"]["properties"].update(
                event_id={"$ref": "#/components/schemas/Missing"}
            ),
            "unresolved local reference",
        )

    def test_operation_ids_are_unique(self) -> None:
        self.assert_rejected(
            lambda document: document["paths"]["/v1/streams"]["get"].update(
                operationId="replayEvents"
            ),
            "operationId",
        )

    def test_json_examples_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["AppendSuccess"]["content"][
                "application/json"
            ]["examples"]["committed"]["value"].update(status="unknown"),
            "example is invalid",
        )

    def test_ndjson_lines_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["ReplaySuccess"]["content"][
                "application/x-ndjson"
            ]["examples"]["snapshotAndCaughtUp"].update(value='{"type":"unknown"}\n'),
            "NDJSON line",
        )

    def test_stable_errors_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["schemas"]["ErrorCode"][
                "x-http-status"
            ].update(overloaded=503),
            "stable status map",
        )

    def test_query_parameters_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["paths"]["/v1/events"]["get"].update(
                parameters=[{"$ref": "#/components/parameters/NoQuery"}]
            ),
            "ReplayQuery",
        )

    def test_requests_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["paths"]["/v1/events"]["post"].pop("requestBody"),
            "require a request body",
        )

    def test_responses_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["paths"]["/v1/streams"]["get"]["responses"]["200"].update(
                **{"$ref": "#/components/responses/HeadJsonSuccess"}
            ),
            "has no content map",
        )

    def test_statuses_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["paths"]["/v1/events"]["post"]["responses"].pop("503"),
            "response statuses",
        )

    def test_media_types_are_checked(self) -> None:
        def mutate(document: dict[str, Any]) -> None:
            content = document["components"]["responses"]["StreamsSuccess"]["content"]
            content["text/json"] = content.pop("application/json")

        self.assert_rejected(mutate, "media types")

    def test_headers_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["Overloaded"]["headers"].pop(
                "Retry-After"
            ),
            "Retry-After",
        )

    def test_duplicate_yaml_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.yaml"
            path.write_text("openapi: 3.2.0\nopenapi: 3.1.0\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate YAML key"):
                load_document(path)

    def test_authentication_is_deployment_conditional(self) -> None:
        self.assert_rejected(
            lambda document: document.update(security=[{"bearerAuth": []}, {}]),
            "authentication rule",
        )

    def test_replay_limits_are_configuration_dependent(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["schemas"]["ReplayQuery"][
                "properties"
            ]["limit"].update(maximum=100000),
            "fixed default or maximum",
        )

    def test_follow_headers_are_not_finite_response_headers(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["ReplaySuccess"].update(
                headers={"Connection": {"schema": {"type": "string"}}}
            ),
            "follow-only headers",
        )

    def test_form_serialization_must_match_data_value(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["parameters"]["ReplayQuery"][
                "content"
            ]["application/x-www-form-urlencoded"]["examples"]["finitePage"].update(
                serializedValue="source=wrong&stream=customers&limit=100"
            ),
            "does not match dataValue",
        )

    def test_duplicate_ndjson_example_members_are_rejected(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["ReplaySuccess"][
                "content"
            ]["application/x-ndjson"]["examples"]["snapshotAndCaughtUp"].update(
                value='{"type":"caught_up","type":"caught_up","next_after":null,'
                '"snapshot_through_event_id":null}\n'
            ),
            "duplicate JSON member",
        )

    def test_invalid_events_requires_indexed_details(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["responses"]["AppendBadRequest"][
                "content"
            ]["application/json"]["examples"]["event"]["value"].pop("errors"),
            "'errors' is a required property",
        )

    def test_semantic_invariants_are_checked(self) -> None:
        self.assert_rejected(
            lambda document: document["components"]["schemas"]["LineagePayload"].pop(
                "x-invariants"
            ),
            "successor-lineage invariants",
        )


if __name__ == "__main__":
    unittest.main()
