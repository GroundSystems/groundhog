from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
import unittest
from typing import Any

from verify.conformance.validate import (
    HTTP_METHODS,
    _validate_instance,
    dereference,
    load_document,
    resolve_local,
    validate_instance_invariants,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "verify" / "conformance" / "fixtures" / "query-v1"
DOCUMENT = load_document(ROOT / "openapi.yaml")
QUERY_ERROR_CODES = {
    "invalid_query",
    "invalid_cursor",
    "relation_not_found",
    "field_not_found",
    "query_timeout",
    "index_required",
    "frontier_chain_mismatch",
    "cursor_expired",
    "query_limit_exceeded",
    "generation_corrupt",
    "query_unavailable",
    "projection_frontier_timeout",
}


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON member {key!r}")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_members
    )
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def _response_examples(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = response.get("content", {})
    if not isinstance(content, Mapping):
        return []
    media = content.get("application/json", {})
    if not isinstance(media, Mapping):
        return []
    examples = media.get("examples", {})
    if not isinstance(examples, Mapping):
        return []
    return [value for value in examples.values() if isinstance(value, Mapping)]


class QueryFixtureTests(unittest.TestCase):
    def test_manifest_lists_every_fixture_once(self) -> None:
        manifest = _load_json(FIXTURES / "manifest.json")
        self.assertEqual(manifest.get("v"), 1)
        cases = manifest.get("cases")
        self.assertIsInstance(cases, list)
        assert isinstance(cases, list)

        listed_files: list[str] = []
        for case in cases:
            self.assertIsInstance(case, dict)
            assert isinstance(case, dict)
            fixture_file = case.get("file")
            self.assertIsInstance(fixture_file, str)
            assert isinstance(fixture_file, str)
            listed_files.append(fixture_file)
            self.assertEqual(fixture_file.startswith("valid/"), case.get("valid"))
            self.assertIsInstance(case.get("focus"), str)
            self.assertTrue((FIXTURES / fixture_file).is_file())

        self.assertEqual(len(listed_files), len(set(listed_files)))
        fixture_files = {
            path.relative_to(FIXTURES).as_posix()
            for directory in ("valid", "invalid")
            for path in (FIXTURES / directory).glob("*.json")
        }
        self.assertEqual(set(listed_files), fixture_files)

    def test_payload_fixtures_match_their_expected_validity(self) -> None:
        cases = _load_json(FIXTURES / "manifest.json")["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                schema_reference = f"#/components/schemas/{case['schema']}"
                resolve_local(DOCUMENT, schema_reference)
                payload = _load_json(FIXTURES / case["file"])
                errors: list[str] = []
                _validate_instance(
                    DOCUMENT,
                    {"$ref": schema_reference},
                    payload,
                    case["name"],
                    errors,
                )
                errors.extend(validate_instance_invariants(case["schema"], payload))
                if case["valid"]:
                    self.assertEqual(errors, [])
                else:
                    self.assertNotEqual(errors, [])

    def test_stable_query_errors_match_statuses_and_response_examples(self) -> None:
        fixture = _load_json(FIXTURES / "stable-query-errors.json")
        self.assertEqual(fixture.get("v"), 1)
        expected = fixture.get("errors")
        self.assertIsInstance(expected, dict)
        assert isinstance(expected, dict)
        self.assertEqual(set(expected), QUERY_ERROR_CODES)

        error_code = resolve_local(DOCUMENT, "#/components/schemas/ErrorCode")
        self.assertIsInstance(error_code, Mapping)
        actual_statuses = error_code["x-http-status"]
        self.assertEqual(
            {code: actual_statuses[code] for code in QUERY_ERROR_CODES}, expected
        )

        observed: dict[str, int] = {}
        responses = DOCUMENT["paths"]["/v1/query"]["post"]["responses"]
        for status, raw_response in responses.items():
            response = dereference(DOCUMENT, raw_response)
            for example in _response_examples(response):
                payload = example.get("value")
                if isinstance(payload, Mapping) and payload.get("error") in expected:
                    observed[str(payload["error"])] = int(status)
        self.assertEqual(observed, expected)

    def test_catalog_get_and_head_publish_the_same_status_contract(self) -> None:
        for path in ("/v1/catalog", "/v1/catalog/relations/{relation}"):
            with self.subTest(path=path):
                path_item = DOCUMENT["paths"][path]
                get = path_item["get"]
                head = path_item["head"]
                self.assertEqual(get["parameters"], head["parameters"])
                self.assertEqual(set(get["responses"]), set(head["responses"]))

                for status in get["responses"]:
                    get_response = dereference(DOCUMENT, get["responses"][status])
                    head_response = dereference(DOCUMENT, head["responses"][status])
                    self.assertIn("content", get_response)
                    self.assertNotIn("content", head_response)
                    self.assertEqual(
                        set(get_response.get("headers", {})),
                        set(head_response.get("headers", {})),
                    )

    def test_query_and_catalog_expose_only_the_declared_methods(self) -> None:
        query_methods = set(DOCUMENT["paths"]["/v1/query"]) & HTTP_METHODS
        self.assertEqual(query_methods, {"post"})
        for path in ("/v1/catalog", "/v1/catalog/relations/{relation}"):
            catalog_methods = set(DOCUMENT["paths"][path]) & HTTP_METHODS
            self.assertEqual(catalog_methods, {"get", "head"})


if __name__ == "__main__":
    unittest.main()
