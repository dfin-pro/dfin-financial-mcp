#!/usr/bin/env python3
"""Extract Markdown table headers and context from selected search results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


MARKDOWN_TABLE_DELIMITER_CELL_RE = re.compile(r":?-{3,}:?")
CONTEXT_LINE_LIMIT = 2
CONTEXT_SCAN_LINES = 4
CONTEXT_WORD_LIMIT = 30


class HelperInputError(Exception):
    """Report an expected invocation or input error without a traceback."""


class _HelpfulArgumentParser(argparse.ArgumentParser):
    """Raise helper input errors instead of exiting on invalid arguments."""

    def error(self, message):
        """Raise one consistently handled argument error."""
        raise HelperInputError(f"Invalid arguments: {message}")


def _split_markdown_row(line):
    """Return unescaped-pipe cells from one possible Markdown table row."""
    clean_line = line.strip()

    if clean_line.startswith("|"):
        clean_line = clean_line[1:]

    if clean_line.endswith("|") and not clean_line.endswith(r"\|"):
        clean_line = clean_line[:-1]

    rv = re.split(r"(?<!\\)\|", clean_line)

    return rv


def _table_context(lines, header_index):
    """Return bounded prose nearest to a table header."""
    window_start = max(header_index - CONTEXT_SCAN_LINES, 0)
    candidates = []

    for line in lines[window_start:header_index]:
        normalized_line = " ".join(line.split())

        if normalized_line and "|" not in normalized_line:
            candidates.append(normalized_line)

    selected_lines = candidates[-CONTEXT_LINE_LIMIT:]
    context_words = " ".join(selected_lines).split()
    rv = " ".join(context_words[-CONTEXT_WORD_LIMIT:])

    return rv


def extract_table_contexts(value):
    """Return compact metadata for every canonical Markdown table in text."""
    lines = value.splitlines() if isinstance(value, str) else []
    rv = []

    for delimiter_index in range(1, len(lines)):
        header_index = delimiter_index - 1
        header_line = lines[header_index].strip()
        delimiter_line = lines[delimiter_index].strip()

        if "|" in header_line and "|" in delimiter_line:
            header_cells = _split_markdown_row(header_line)
            delimiter_cells = _split_markdown_row(delimiter_line)
            valid_delimiter = bool(delimiter_cells) and all(
                MARKDOWN_TABLE_DELIMITER_CELL_RE.fullmatch(cell.strip())
                for cell in delimiter_cells
            )

            if valid_delimiter and len(header_cells) == len(delimiter_cells):
                table = {
                    "table_number": len(rv) + 1,
                    "header_line": header_index + 1,
                    "header": " ".join(header_line.split()),
                }
                context = _table_context(lines, header_index)

                if context:
                    table["context"] = context

                rv.append(table)

    return rv


def _load_payload(input_path):
    """Load one UTF-8 JSON payload with corrective expected errors."""
    try:
        raw_input = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HelperInputError(
            f"Could not read {input_path}: {exc}. Check the path and save "
            "the MCP response as UTF-8 JSON."
        ) from None

    try:
        rv = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        raise HelperInputError(
            f"Invalid JSON at line {exc.lineno}, column {exc.colno}. Save "
            "the raw indexed result or artifact as JSON and retry."
        ) from None

    return rv


def _deduplicated_indexes(indexes):
    """Return requested indexes once each while preserving their order."""
    seen = set()
    rv = []

    for index in indexes or []:
        if index not in seen:
            seen.add(index)
            rv.append(index)

    return rv


def _result_text(result, result_label):
    """Return complete result text or raise a specific corrective error."""
    rv = None

    if isinstance(result, dict):
        content = result.get("content")
        body = result.get("body")

        if isinstance(content, str):
            rv = content
        elif isinstance(body, str):
            rv = body

    if rv is None:
        public_id = result.get("public_id") if isinstance(result, dict) else None
        message = (
            f"{result_label} does not contain complete string content or body. "
        )

        if isinstance(public_id, str) and public_id:
            message += (
                "Call get_note(public_id="
                f"{json.dumps(public_id, ensure_ascii=False)}), save that "
                "response as JSON, then run this helper on the saved file."
            )
        else:
            message += (
                "Pass an indexed document result containing string content, "
                "or an authenticated get_note response containing string body."
            )

        raise HelperInputError(message)

    return rv


def _selected_results(payload, requested_indexes, inspect_all):
    """Return fully validated selected result indexes and complete text."""
    indexes = _deduplicated_indexes(requested_indexes)
    is_single_result = isinstance(payload, dict) and (
        isinstance(payload.get("content"), str)
        or isinstance(payload.get("body"), str)
        or (
            isinstance(payload.get("public_id"), str)
            and bool(payload["public_id"])
        )
    )
    results = None
    rv = []

    if is_single_result:
        if any(index != 0 for index in indexes):
            raise HelperInputError(
                "This file contains one result. Omit --index or use --index 0."
            )

        rv = [(None, _result_text(payload, "This result"))]
    elif isinstance(payload, dict) and isinstance(payload.get("results"), list):
        results = payload["results"]
    elif isinstance(payload, list):
        results = payload
    else:
        raise HelperInputError(
            "Unsupported JSON shape. Accepted inputs are a single object "
            "containing string content or body, an envelope containing a "
            "results list, or a top-level result list."
        )

    if results is not None:
        if any(index < 0 for index in indexes):
            rejected_index = next(index for index in indexes if index < 0)
            raise HelperInputError(
                f"Result index {rejected_index} is invalid. Use a zero-based "
                "index of 0 or greater."
            )

        if indexes:
            selected_indexes = indexes
        elif inspect_all:
            selected_indexes = list(range(len(results)))
        elif results:
            selected_indexes = [0]
        else:
            selected_indexes = []

        for index in selected_indexes:
            if index >= len(results):
                if results:
                    valid_range = f"0 through {len(results) - 1}"
                    message = (
                        f"Result index {index} is out of range. This file "
                        f"accepts {valid_range}."
                    )
                else:
                    message = (
                        f"Result index {index} is out of range. This file "
                        "contains no results."
                    )

                raise HelperInputError(message)

        for index in selected_indexes:
            text = _result_text(results[index], f"Result index {index}")
            rv.append((index, text))

    return rv


def _argument_parser():
    """Build the helper command-line parser."""
    parser = _HelpfulArgumentParser(
        description="Print Markdown table headers and nearby context as JSONL."
    )
    parser.add_argument(
        "result_json",
        type=Path,
        help="Indexed result, note response, or complete search artifact",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "-i",
        "--index",
        action="append",
        dest="indexes",
        metavar="N",
        type=int,
        help="zero-based result index; repeat to select several",
    )
    selection.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="inspect_all",
        help="inspect every result in a full artifact or list",
    )

    return parser


def _invocation_hint(program_name):
    """Return compact valid retry examples for every expected error."""
    rv = (
        f"Hint: single result: {program_name} RESULT.json; full artifact: "
        f"{program_name} RESULTS.json -i 3; several results: {program_name} "
        f"RESULTS.json -i 3 -i 7; all results: {program_name} RESULTS.json -a."
    )

    return rv


def main(argv=None):
    """Run the command-line extractor and return a process exit status."""
    parser = _argument_parser()
    rv = 0

    try:
        args = parser.parse_args(argv)
        payload = _load_payload(args.result_json)
        selected_results = _selected_results(
            payload,
            args.indexes,
            args.inspect_all,
        )

        for result_index, result_text in selected_results:
            for table in extract_table_contexts(result_text):
                if result_index is not None:
                    table = {"result_index": result_index, **table}

                print(
                    json.dumps(
                        table,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )

    except HelperInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(_invocation_hint(parser.prog), file=sys.stderr)
        rv = 2

    return rv


if __name__ == "__main__":
    raise SystemExit(main())
