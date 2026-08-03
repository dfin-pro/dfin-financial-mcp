"""Tests for the bundled Markdown table-context extractor."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "skills/dfin-research/scripts/extract_table_context.py"
)
SPEC = importlib.util.spec_from_file_location(
    "extract_table_context",
    SCRIPT_PATH,
)
EXTRACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACTOR)


class ExtractTableContextTests(unittest.TestCase):
    """Verify table matching, selection, and corrective CLI failures."""

    @staticmethod
    def _table(label="Metric", context=None):
        """Return one canonical Markdown table with optional prose."""
        lines = []

        if context is not None:
            lines.append(context)

        lines.extend(
            [
                f"| {label} | Value |",
                "| --- | ---: |",
                f"| {label} value | 10 |",
            ]
        )

        return "\n".join(lines)

    def _invoke(self, argv):
        """Run main with captured output and decode emitted JSONL."""
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = EXTRACTOR.main(argv)

        rows = [
            json.loads(line)
            for line in stdout.getvalue().splitlines()
        ]
        rv = (status, rows, stderr.getvalue())

        return rv

    def _run_main(self, payload, *arguments):
        """Run the helper against one temporary JSON payload."""
        with tempfile.TemporaryDirectory() as temp_directory:
            input_path = Path(temp_directory) / "result.json"
            input_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            rv = self._invoke([str(input_path), *arguments])

        return rv

    def _run_raw(self, raw_input, *arguments):
        """Run the helper against one temporary raw input file."""
        with tempfile.TemporaryDirectory() as temp_directory:
            input_path = Path(temp_directory) / "result.json"
            input_path.write_text(raw_input, encoding="utf-8")
            rv = self._invoke([str(input_path), *arguments])

        return rv

    def _assert_corrective_error(self, status, rows, stderr):
        """Check the shared two-line corrective error contract."""
        error_lines = stderr.strip().splitlines()

        self.assertEqual(status, 2)
        self.assertEqual(rows, [])
        self.assertEqual(len(error_lines), 2)
        self.assertTrue(error_lines[0].startswith("error: "))
        self.assertTrue(error_lines[1].startswith("Hint: "))
        self.assertNotIn("Traceback", stderr)
        self.assertIn("RESULTS.json -i 3", error_lines[1])
        self.assertIn("RESULTS.json -i 3 -i 7", error_lines[1])
        self.assertIn("RESULTS.json -a", error_lines[1])
        self.assertIn(EXTRACTOR._argument_parser().prog, error_lines[1])

    def test_extracts_content_with_multiple_tables_and_nearest_context(self):
        content = (
            "Outside the context choice\n"
            "Revenue summary\n"
            "\n"
            "USD millions\n"
            "| Metric | Value |\n"
            "| --- | ---: |\n"
            "| Revenue | 10 |\n"
            "\n"
            "Margin summary\n"
            "Period | Margin\n"
            ":--- | ---:\n"
            "2026 | 20%\n"
        )

        status, rows, stderr = self._run_main({"content": content})

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            rows,
            [
                {
                    "table_number": 1,
                    "header_line": 5,
                    "header": "| Metric | Value |",
                    "context": "Revenue summary USD millions",
                },
                {
                    "table_number": 2,
                    "header_line": 10,
                    "header": "Period | Margin",
                    "context": "Margin summary",
                },
            ],
        )

    def test_accepts_authenticated_note_body(self):
        status, rows, stderr = self._run_main(
            {"body": self._table("Note metric")}
        )

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(rows[0]["header"], "| Note metric | Value |")
        self.assertNotIn("result_index", rows[0])

    def test_prefers_content_when_content_and_body_are_strings(self):
        status, rows, stderr = self._run_main(
            {
                "content": self._table("Content metric"),
                "body": self._table("Body metric"),
            }
        )

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(rows[0]["header"], "| Content metric | Value |")

    def test_single_content_takes_precedence_over_results_metadata(self):
        payload = {
            "content": self._table("Top-level metric"),
            "results": [
                {"content": self._table("Nested metric")},
            ],
        }

        status, rows, stderr = self._run_main(payload)

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["header"],
            "| Top-level metric | Value |",
        )
        self.assertNotIn("result_index", rows[0])
        self.assertNotIn("Nested metric", rows[0]["header"])

    def test_keeps_last_thirty_context_words(self):
        context_words = [f"word{index}" for index in range(35)]
        body = self._table(
            "Metric",
            context=" ".join(context_words),
        )

        status, rows, stderr = self._run_main({"body": body})

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            rows[0]["context"],
            " ".join(context_words[-30:]),
        )

    def test_omits_context_when_no_preceding_prose_exists(self):
        status, rows, stderr = self._run_main(
            {"content": self._table()}
        )

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertNotIn("context", rows[0])

    def test_returns_successful_empty_output_without_a_table(self):
        status, rows, stderr = self._run_main(
            {"content": "Ordinary prose only."}
        )

        self.assertEqual((status, rows, stderr), (0, [], ""))

    def test_ignores_malformed_and_mismatched_tables(self):
        content = (
            "Metric | Value\n"
            "--- | invalid\n"
            "\n"
            "Metric | Value | Period\n"
            "--- | ---"
        )

        status, rows, stderr = self._run_main({"content": content})

        self.assertEqual((status, rows, stderr), (0, [], ""))

    def test_full_artifact_defaults_to_result_zero(self):
        payload = {
            "count": 2,
            "results": [
                {"content": self._table("Zero")},
                {"content": self._table("One")},
            ],
        }

        status, rows, stderr = self._run_main(payload)

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result_index"], 0)
        self.assertEqual(rows[0]["header"], "| Zero | Value |")

    def test_accepts_top_level_result_list(self):
        payload = [
            {"content": self._table("List zero")},
            {"content": self._table("List one")},
        ]

        status, rows, stderr = self._run_main(payload, "-i", "1")

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(rows[0]["result_index"], 1)
        self.assertEqual(rows[0]["header"], "| List one | Value |")

    def test_repeated_indexes_preserve_order_and_deduplicate(self):
        payload = [
            {"content": self._table(str(index))}
            for index in range(4)
        ]

        status, rows, stderr = self._run_main(
            payload,
            "-i",
            "3",
            "-i",
            "1",
            "-i",
            "3",
        )

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [row["result_index"] for row in rows],
            [3, 1],
        )
        self.assertEqual(
            [row["header"] for row in rows],
            ["| 3 | Value |", "| 1 | Value |"],
        )

    def test_all_inspects_every_result(self):
        payload = [
            {"content": self._table("Zero")},
            {"content": self._table("One")},
        ]

        status, rows, stderr = self._run_main(payload, "--all")

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [row["result_index"] for row in rows],
            [0, 1],
        )

    def test_table_numbering_resets_within_each_selected_result(self):
        two_tables = self._table("First") + "\n\n" + self._table("Second")
        payload = [
            {"content": two_tables},
            {"content": two_tables},
        ]

        status, rows, stderr = self._run_main(payload, "--all")

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [
                (row["result_index"], row["table_number"])
                for row in rows
            ],
            [(0, 1), (0, 2), (1, 1), (1, 2)],
        )

    def test_single_result_accepts_index_zero_and_all(self):
        payload = {"content": self._table()}

        indexed = self._run_main(payload, "--index", "0")
        inspected_all = self._run_main(payload, "--all")

        self.assertEqual(indexed[0], 0)
        self.assertEqual(indexed[2], "")
        self.assertNotIn("result_index", indexed[1][0])
        self.assertEqual(inspected_all, indexed)

    def test_single_result_rejects_other_indexes(self):
        status, rows, stderr = self._run_main(
            {"content": self._table()},
            "--index",
            "1",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn(
            "This file contains one result. Omit --index or use --index 0.",
            stderr,
        )

    def test_empty_collection_succeeds_without_an_index(self):
        default_result = self._run_main({"results": []})
        all_result = self._run_main([], "--all")

        self.assertEqual(default_result, (0, [], ""))
        self.assertEqual(all_result, (0, [], ""))

    def test_empty_collection_rejects_an_explicit_index(self):
        status, rows, stderr = self._run_main([], "--index", "0")

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Result index 0 is out of range", stderr)
        self.assertIn("contains no results", stderr)

    def test_rejects_a_negative_collection_index(self):
        status, rows, stderr = self._run_main(
            [{"content": self._table()}],
            "--index",
            "-1",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Result index -1 is invalid", stderr)
        self.assertIn("0 or greater", stderr)

    def test_out_of_range_index_includes_valid_range(self):
        payload = [
            {"content": self._table(str(index))}
            for index in range(4)
        ]

        status, rows, stderr = self._run_main(
            payload,
            "--index",
            "5",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Result index 5 is out of range", stderr)
        self.assertIn("accepts 0 through 3", stderr)

    def test_invalid_json_includes_location_and_corrective_hint(self):
        status, rows, stderr = self._run_raw("{\n  invalid")

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Invalid JSON at line 2, column", stderr)
        self.assertIn("raw indexed result or artifact", stderr)

    def test_unreadable_path_includes_corrective_hint(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_path = Path(temp_directory) / "missing.json"
            status, rows, stderr = self._invoke([str(missing_path)])

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Could not read", stderr)
        self.assertIn("Check the path", stderr)
        self.assertIn("UTF-8 JSON", stderr)

    def test_unsupported_json_shape_explains_accepted_shapes(self):
        status, rows, stderr = self._run_main({"count": 2})

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Unsupported JSON shape", stderr)
        self.assertIn("single object containing string content or body", stderr)
        self.assertIn("envelope containing a results list", stderr)
        self.assertIn("top-level result list", stderr)

    def test_top_level_note_preview_directs_agent_to_get_note(self):
        payload = {
            "public_id": "NoteAbC123",
            "subject": "Preview",
            "body_preview": "Partial note body",
        }

        for arguments in ((), ("--index", "0")):
            with self.subTest(arguments=arguments):
                status, rows, stderr = self._run_main(
                    payload,
                    *arguments,
                )

                self._assert_corrective_error(status, rows, stderr)
                self.assertIn(
                    'get_note(public_id="NoteAbC123")',
                    stderr,
                )
                self.assertIn("save that response as JSON", stderr)
                self.assertIn("run this helper on the saved file", stderr)

    def test_note_preview_directs_agent_to_get_note(self):
        payload = {
            "results": [
                {
                    "public_id": "NoteAbC123",
                    "body_preview": "Partial note body",
                }
            ]
        }

        status, rows, stderr = self._run_main(payload)

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn(
            'get_note(public_id="NoteAbC123")',
            stderr,
        )
        self.assertIn("save that response as JSON", stderr)

    def test_result_without_text_explains_valid_inputs(self):
        status, rows, stderr = self._run_main(
            {"results": [{"title": "No complete text"}]}
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Result index 0", stderr)
        self.assertIn("indexed document result containing string content", stderr)
        self.assertIn("authenticated get_note response", stderr)

    def test_all_and_index_are_corrective_argument_error(self):
        status, rows, stderr = self._run_main(
            [{"content": self._table()}],
            "--all",
            "--index",
            "0",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Invalid arguments", stderr)
        self.assertIn("not allowed with argument", stderr)

    def test_non_integer_index_is_corrective_argument_error(self):
        status, rows, stderr = self._run_main(
            [{"content": self._table()}],
            "--index",
            "abc",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Invalid arguments", stderr)
        self.assertIn("invalid int value", stderr)

    def test_validates_every_selection_before_emitting_output(self):
        payload = [
            {"content": self._table("Valid")},
            {"title": "Missing complete text"},
        ]

        status, rows, stderr = self._run_main(
            payload,
            "--index",
            "0",
            "--index",
            "1",
        )

        self._assert_corrective_error(status, rows, stderr)
        self.assertIn("Result index 1", stderr)


if __name__ == "__main__":
    unittest.main()
