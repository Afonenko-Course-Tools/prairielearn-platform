"""Закрытые native bindings сохраняют формы ответа и точные matching ordinals."""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from delivery4 import binding4
from delivery_types import ResponseSlot
from grading_job import JobError


def binding(kind: str, values: object, method: str = "external") -> dict[str, object]:
    return {
        "kind": "native-answer",
        "uuid": "37d79ee7-fd7d-44db-bd45-6587711862a5",
        "grading": {"method": method},
        "answerType": kind,
        "responseSlots": values,
        "upstreamGradingMethod": "Manual" if method == "manual" else "Internal",
    }


class DeliveryBindingShapes(unittest.TestCase):
    def test_all_native_answer_forms_keep_declared_grading_method(self) -> None:
        cases: list[tuple[str, list[ResponseSlot], str]] = [
            (
                "manual",
                [{"name": "answer", "type": "manual", "anchor": "answer"}],
                "manual",
            ),
            (
                "numeric",
                [{"name": "answer", "type": "numeric", "anchor": "answer"}],
                "external",
            ),
            (
                "single-choice",
                [
                    {
                        "name": "answer",
                        "type": "single-choice",
                        "anchor": "a",
                        "ordinal": 0,
                        "labelAnchor": "label-a",
                    },
                    {
                        "name": "answer",
                        "type": "single-choice",
                        "anchor": "b",
                        "ordinal": 1,
                        "labelAnchor": "label-b",
                    },
                ],
                "external",
            ),
            (
                "matching",
                [
                    {
                        "name": "match-0",
                        "type": "matching",
                        "anchor": "a",
                        "ordinal": 0,
                        "labelAnchor": "label-a",
                        "options": [{"anchor": "option-a", "ordinal": 0.0}],
                    }
                ],
                "external",
            ),
            (
                "multipart",
                [
                    {
                        "name": "explanation",
                        "type": "manual",
                        "anchor": "a",
                        "labelAnchor": "label-a",
                    },
                    {
                        "name": "number",
                        "type": "numeric",
                        "anchor": "b",
                        "labelAnchor": "label-b",
                    },
                ],
                "mixed",
            ),
        ]
        for kind, values, method in cases:
            with self.subTest(kind=kind):
                # Проверяется JSON boundary, включая прежнее равенство option ordinal=0.0 и index=0.
                value: object = json.loads(json.dumps(binding(kind, values, method)))
                self.assertEqual(binding4(value), method)

    def test_malformed_or_unbound_native_slot_is_rejected(self) -> None:
        cases: list[dict[str, object]] = [
            binding(
                "numeric",
                [
                    {
                        "name": "answer",
                        "type": "numeric",
                        "anchor": "a",
                        "private": "unexpected",
                    }
                ],
            ),
            binding(
                "single-choice",
                [
                    {
                        "name": "answer",
                        "type": "single-choice",
                        "anchor": "a",
                        "ordinal": True,
                        "labelAnchor": "label-a",
                    },
                    {
                        "name": "answer",
                        "type": "single-choice",
                        "anchor": "b",
                        "ordinal": 1,
                        "labelAnchor": "label-b",
                    },
                ],
            ),
            binding(
                "matching",
                [
                    {
                        "name": "match-0",
                        "type": "matching",
                        "anchor": "a",
                        "ordinal": 0,
                        "labelAnchor": "label-a",
                        "options": [{"anchor": "option-a", "ordinal": 1}],
                    }
                ],
            ),
            binding(
                "multipart",
                [
                    {
                        "name": "number-a",
                        "type": "numeric",
                        "anchor": "same",
                        "labelAnchor": "label-a",
                    },
                    {
                        "name": "number-b",
                        "type": "numeric",
                        "anchor": "same",
                        "labelAnchor": "label-b",
                    },
                ],
            ),
        ]
        for value in cases:
            with (
                self.subTest(answer_type=value["answerType"]),
                self.assertRaises(JobError),
            ):
                binding4(value)
