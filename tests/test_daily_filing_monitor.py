"""Regression tests for the DFin daily filing monitor helpers."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills/dfin-daily-filing-monitor"


def _load_module(name, relative_path):
    path = SKILL_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILING = _load_module("daily_filing_artifact", "scripts/filing_artifact.py")
BUILDER = _load_module("daily_filing_dashboard", "scripts/build_dashboard.py")


class FakeResponse:
    """Provide the small urllib response surface used by the helpers."""

    def __init__(self, status, payload, headers=None):
        self.status = status
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


def _filing_result(
    *,
    ticker="MSFT.US",
    cik="789019",
    accession="000119312526333770",
    document="main.htm",
    doc_uuid="doc-1",
    filing_type="8-K",
    score=0.5,
    content="Material event evidence",
    name="Microsoft Corporation",
    chunk_num=None,
    content_chars=None,
):
    result = {
        "ticker": ticker,
        "name": name,
        "filing_type": filing_type,
        "filing_date": "2026-08-06",
        "doc_uuid": doc_uuid,
        "content": content,
        "reranking_score": score,
        "meta_data": {
            "source_uri": (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{accession}/{document}"
            )
        },
    }
    if chunk_num is not None:
        result["chunk_num"] = chunk_num
    if content_chars is not None:
        result["content_chars"] = content_chars
    return result


def _accession_row(
    *,
    cik="0000789019",
    accession="0000789019-26-000001",
    tickers=None,
    filing_type="8-K",
    filing_date="2026-08-06",
    issuer_name="Microsoft Corporation",
):
    return {
        "type": "filing_accession",
        "accession_number": accession,
        "cik": cik,
        "issuer_name": issuer_name,
        "tickers": ["MSFT.US"] if tickers is None else tickers,
        "filing_type": filing_type,
        "filing_date": filing_date,
    }


def _enumeration_payload(
    results=None,
    *,
    filing_types=None,
    days=2,
    date_from="2026-08-05",
    date_to="2026-08-06",
    complete=True,
    has_more=False,
    count=None,
    total_count=None,
    accession_count=None,
    issues=None,
):
    results = [_accession_row()] if results is None else results
    filing_types = ["8-K"] if filing_types is None else filing_types
    unique_accessions = {
        row.get("accession_number")
        for row in results
        if isinstance(row, dict) and row.get("accession_number")
    }
    by_filing_type = {}

    for row in results:
        if isinstance(row, dict) and row.get("filing_type"):
            by_filing_type[row["filing_type"]] = (
                by_filing_type.get(row["filing_type"], 0) + 1
            )

    return {
        "document_type": "filing",
        "result_level": "accession",
        "count": len(results) if count is None else count,
        "total_count": (
            len(unique_accessions) if total_count is None else total_count
        ),
        "has_more": has_more,
        "coverage": {
            "complete": complete,
            "as_of": "2026-08-06T18:42:00Z",
            "accession_count": (
                len(unique_accessions)
                if accession_count is None
                else accession_count
            ),
            "by_filing_type": by_filing_type,
            "issues": [] if issues is None else issues,
        },
        "filters": {
            "ticker": None,
            "filing_types": filing_types,
            "limit": -1,
            "days": days,
            "data_in_db_only": False,
            "result_level": "accession",
            "date_from": date_from,
            "date_to": date_to,
        },
        "results": results,
    }


def _stock_payload():
    return {
        "ticker": "MSFT.US",
        "company_name": "Microsoft Corporation",
        "description": "Builds software and cloud products. </script> remains data.",
        "profile": {
            "cik": "0000789019",
            "fiscal_year_end": "June",
            "gics_sector": "Information Technology",
            "gics_industry": "Software",
            "gics_subindustry": "Systems Software",
        },
        "price": {
            "price": "$499.86",
            "change": "+$12.40",
            "change_percent": "+2.54%",
            "market_cap": "$3.66T",
            "forward_pe": "23.58",
            "high_52_week": "$538.66",
            "low_52_week": "$352.83",
            "volume": "32,774,067",
            "average_volume_52_week": "31,328,502",
        },
        "returns": {
            "to_date_returns": {
                "wtd": None,
                "mtd": "0.000%",
                "ytd": "1.243%",
            },
            "trailing_returns": {"1y": {"cumulative": "-6.897%"}},
        },
        "technicals": {"beta": 1.099},
        "earnings_history": {
            "2026-06-30": {
                "eps_actual": 4.74,
                "eps_estimate": 4.21,
                "surprise_percent": 12.5891,
            },
            "2026-03-31": {
                "eps_actual": 4.09,
                "eps_estimate": 4.09,
                "surprise_percent": 0,
            },
            "2025-12-31": {
                "eps_actual": 3.8,
                "eps_estimate": 3.9,
                "surprise_percent": -2.5,
            },
            "2025-09-30": {
                "eps_actual": 3.72,
                "eps_estimate": 3.66,
                "surprise_percent": 1.6393,
            },
            "2025-06-30": {
                "eps_actual": 3.65,
                "eps_estimate": 3.38,
                "surprise_percent": 7.9882,
            },
        },
        "database": {"filings": ["must not leak"]},
        "user": {"notes": ["must not leak"]},
    }


def _stock_batch(payload=None, ticker="MSFT.US"):
    payload = _stock_payload() if payload is None else payload
    return {
        "format": "inline",
        "count": 1,
        "success_count": 1,
        "error_count": 0,
        "results": {ticker: {"data": payload}},
    }


def _inline_stock_markdown():
    return """# Microsoft Corporation (MSFT.US)

## Price
Price: $499.86 USD; Change: +$12.40 (+2.54%); Volume/52w avg: 32,774,067/31,328,502; 52w H/L: $538.66/$352.83; Market cap: $3.66T; Forward P/E: 23.58

## Returns
| Period | Cumulative | CAGR |
| --- | --- | --- |
| 1y | -6.897% | -6.897% |

To date: WTD: -1.0%; MTD: 0.000%; QTD: 1.0%; YTD: 1.243%

## Fundamentals
### Profile
CIK: 0000789019; FY end: June; Sector: Information Technology; Industry: Software; Subindustry: Systems Software

### Description
Builds software and cloud products.

### Technicals
Beta: 1.099; Short ratio: 1.2

### Earnings History
| Period | Report | EPS actual | EPS estimate | EPS difference | Surprise % |
| --- | --- | --- | --- | --- | --- |
| 2026-06-30 | 2026-07-30 | 4.74 | 4.21 | 0.53 | 12.5891 |
| 2026-03-31 | 2026-04-30 | 4.09 | 4.09 | 0 | 0 |
"""


def _manifest(stock_url="https://www.dfin.pro/api/v1/artifacts/Stock123"):
    return {
        "title": "Management </script> Changes",
        "ftype": "8-K / 6-K",
        "range": "Aug 5–6, 2026",
        "stock_context_url": stock_url,
        "companies": [
            {
                "ticker": "MSFT.US",
                "name": "Microsoft Corporation",
                "exchange": "NASDAQ",
                "ratios": {
                    "ticker": "MSFT.US",
                    "year": 2025,
                    "ratios": {
                        "returnOnEquity": 0.3328,
                        "returnOnInvestedCapital": 0.2795,
                        "netDebtToEBITDA": 0.5116,
                        "ebitdaMargin": 0.5685,
                    },
                },
                "filings": [
                    {
                        "id": "sec:0000789019:accession",
                        "ft": "8-K",
                        "fd": "Aug 6",
                        "fl": "javascript:alert(1)",
                        "tags": ["confirmed", "appointments", "bad tag'"],
                        "flag": False,
                        "ev": [
                            [
                                "pill-in",
                                "APPOINTMENT",
                                "O'Reilly </script>",
                                "CEO; $(touch /tmp/nope) ''', effective now",
                            ]
                        ],
                        "docs": 2,
                    }
                ],
            }
        ],
    }


class FilingArtifactTests(unittest.TestCase):
    def test_normalizes_envelopes_strings_and_text_wrappers(self):
        result = _filing_result()
        payload = {
            "results": [
                result,
                json.dumps(result),
                {"text": json.dumps(result)},
                "not json",
            ]
        }

        self.assertEqual(len(FILING.normalize_results(payload)), 3)

    def test_normalizes_indexed_single_results_and_rejects_arbitrary_objects(self):
        result = _filing_result()

        self.assertEqual(FILING.normalize_results(result), [result])
        self.assertEqual(FILING.normalize_results({"result": result}), [result])

        with self.assertRaises(FILING.HelperError):
            FILING.normalize_results({"status": "ok"})

    def test_groups_exhibits_by_accession_and_keeps_ticker_primary(self):
        results = [
            _filing_result(doc_uuid="main", filing_type="8-K"),
            _filing_result(
                doc_uuid="exhibit",
                document="ex10-2.htm",
                filing_type="8-K 10.2",
                score=0.6,
            ),
        ]

        bundles = FILING.group_results(results)

        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0]["issuer_key"], "MSFT.US")
        self.assertEqual(bundles[0]["ticker"], "MSFT.US")
        self.assertEqual(bundles[0]["form"], "8-K")
        self.assertEqual(len(bundles[0]["documents"]), 2)
        self.assertEqual(bundles[0]["best"]["designation"], "10.2")

    def test_selected_bundle_preserves_exact_evidence_location(self):
        result = _filing_result(
            doc_uuid="selected-doc",
            chunk_num=7,
            content_chars=3149,
        )

        selected = FILING.select_bundles(
            [result],
            ["sec:0000789019:000119312526333770"],
        )[0]

        self.assertEqual(
            selected["evidence_location"],
            {
                "doc_uuid": "selected-doc",
                "chunk_num": 7,
                "content_chars": 3149,
            },
        )

    def test_selected_bundle_uses_bounded_content_length_as_location_fallback(self):
        result = _filing_result(content="short evidence", chunk_num=-1)

        selected = FILING.select_bundles(
            [result],
            ["sec:0000789019:000119312526333770"],
        )[0]

        self.assertEqual(selected["evidence_location"]["chunk_num"], None)
        self.assertEqual(
            selected["evidence_location"]["content_chars"],
            len("short evidence"),
        )

    def test_promotes_unique_qualified_ticker_from_later_bundle_result(self):
        results = [
            _filing_result(ticker=None, doc_uuid="external"),
            _filing_result(ticker="MSFT.US", doc_uuid="internal"),
        ]

        summary = FILING.summarize_bundles(results)[0]

        self.assertEqual(summary["ticker"], "MSFT.US")
        self.assertEqual(summary["issuer_key"], "MSFT.US")
        self.assertFalse(summary["identity_conflict"])

    def test_conflicting_qualified_tickers_fall_back_to_secondary_identity(self):
        results = [
            _filing_result(ticker="MSFT.US", doc_uuid="first"),
            _filing_result(ticker="AAPL.US", doc_uuid="second"),
        ]

        summary = FILING.summarize_bundles(results)[0]

        self.assertIsNone(summary["ticker"])
        self.assertEqual(summary["issuer_key"], "cik:0000789019")
        self.assertTrue(summary["identity_conflict"])

    def test_non_sec_source_cannot_supply_accession_identity(self):
        result = _filing_result(doc_uuid="temporary-document")
        result["meta_data"]["source_uri"] = (
            "https://evil.test/Archives/edgar/data/789019/"
            "000119312526333770/main.htm"
        )

        summary = FILING.summarize_bundles([result])[0]

        self.assertTrue(summary["bundle_id"].startswith("doc:"))
        self.assertEqual(summary["source_uri"], "")

    def test_null_ticker_issuers_do_not_share_one_bucket(self):
        results = [
            _filing_result(ticker=None, cik="111", accession="1" * 18),
            _filing_result(ticker=None, cik="222", accession="2" * 18),
        ]

        bundles = FILING.group_results(results)

        self.assertEqual(
            {bundle["issuer_key"] for bundle in bundles},
            {"cik:0000000111", "cik:0000000222"},
        )

    def test_fallback_bundle_id_does_not_expose_document_uuid(self):
        result = _filing_result(
            ticker=None,
            cik="",
            accession="",
            doc_uuid="temporary-sensitive-document-uuid",
            name="Issuer without CIK",
        )
        result["meta_data"]["source_uri"] = ""

        summary = FILING.summarize_bundles([result])[0]

        self.assertTrue(summary["bundle_id"].startswith("doc:"))
        self.assertNotIn("temporary-sensitive-document-uuid", summary["bundle_id"])
        self.assertNotIn("temporary-sensitive-document-uuid", json.dumps(summary))

    def test_summary_is_capped_and_previews_are_bounded(self):
        results = [
            _filing_result(
                cik=str(index + 1),
                accession=str(index + 1).zfill(18),
                doc_uuid=f"doc-{index}",
                content="x" * 1000,
                score=100 - index,
            )
            for index in range(25)
        ]

        summaries = FILING.summarize_bundles(results, limit=100, preview_chars=999)

        self.assertEqual(len(summaries), 15)
        self.assertTrue(all(len(row["preview"]) <= 220 for row in summaries))
        self.assertTrue(all("doc_uuid" not in row for row in summaries))
        self.assertTrue(all(row["source_uri"].startswith("https://www.sec.gov/") for row in summaries))

    def test_summary_cli_reports_bounded_paging_metadata(self):
        results = [
            _filing_result(
                cik=str(index + 1),
                accession=str(index + 1).zfill(18),
                doc_uuid=f"doc-{index}",
                score=100 - index,
            )
            for index in range(20)
        ]

        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "results.json"
            artifact.write_text(json.dumps({"results": results}), encoding="utf-8")
            stdout = io.StringIO()

            with mock.patch("sys.stdout", stdout):
                result = FILING.main(
                    [
                        "summarize",
                        "--artifact",
                        str(artifact),
                        "--limit",
                        "5",
                        "--offset",
                        "3",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["bundle_count"], 20)
        self.assertEqual(payload["offset"], 3)
        self.assertEqual(payload["shown_count"], 5)
        self.assertEqual(payload["remaining_bundle_count"], 12)
        self.assertTrue(payload["truncated"])

    def test_sec_provenance_rejects_credentials_ports_and_other_hosts(self):
        valid = "https://www.sec.gov/Archives/edgar/data/1/example.htm"
        self.assertEqual(FILING.validate_sec_url(valid), valid)

        for rejected in (
            "http://www.sec.gov/Archives/example.htm",
            "https://user@www.sec.gov/Archives/example.htm",
            "https://www.sec.gov:444/Archives/example.htm",
            "https://sec.gov.evil.test/Archives/example.htm",
        ):
            with self.subTest(rejected=rejected):
                self.assertIsNone(FILING.validate_sec_url(rejected))

    def test_selection_batches_no_more_than_twenty_uuids(self):
        results = [
            _filing_result(
                doc_uuid=f"doc-{index}",
                document=f"ex-{index}.htm",
                score=index,
            )
            for index in range(41)
        ]
        bundle_id = FILING.group_results(results)[0]["id"]

        selected = FILING.select_bundles(results, [bundle_id])[0]

        self.assertEqual([len(batch) for batch in selected["uuid_batches"]], [20, 20, 1])
        self.assertLessEqual(len(selected["evidence"]), 800)

    def test_validates_only_approved_artifact_urls(self):
        approved = "https://www.dfin.pro/api/v1/artifacts/Abc_123-xyz?index=4"

        self.assertEqual(FILING.validate_artifact_url(approved), approved)

        for rejected in (
            "http://www.dfin.pro/api/v1/artifacts/x",
            "https://evil.test/api/v1/artifacts/x",
            "https://www.dfin.pro:bad/api/v1/artifacts/x",
            "https://www.dfin.pro/other/x",
            "https://www.dfin.pro/api/v1/artifacts/x?broken",
            "https://www.dfin.pro/api/v1/artifacts/x?token=secret",
        ):
            with self.subTest(rejected=rejected):
                with self.assertRaises(FILING.HelperError):
                    FILING.validate_artifact_url(rejected)

    def test_fetch_retries_202_without_exposing_url(self):
        responses = [
            FakeResponse(202, {"retry_after_seconds": 1}),
            FakeResponse(200, {"results": []}),
        ]
        sleeps = []

        body = FILING.fetch_artifact_bytes(
            "https://www.dfin.pro/api/v1/artifacts/Abc123",
            open_url=lambda *_args, **_kwargs: responses.pop(0),
            sleep=sleeps.append,
        )

        self.assertEqual(json.loads(body), {"results": []})
        self.assertEqual(sleeps, [1.0])

    def test_coverage_state_reconciles_broad_and_individual_filers(self):
        results = [
            _accession_row(
                tickers=["MSFT.US", "MSFT.A.US"],
                filing_type="8-K",
            ),
            _accession_row(
                accession="0000789019-26-000002",
                tickers=["MSFT.US"],
                filing_type="6-K",
            ),
            _accession_row(
                cik="0000320193",
                accession="0000320193-26-000001",
                tickers=["AAPL.US"],
                filing_type="8-K",
                issuer_name="Apple Inc.",
            ),
        ]
        state = FILING._enumeration_state(
            _enumeration_payload(results, filing_types=["8-K", "6-K"]),
            ["8-K", "6-K"],
        )

        self.assertEqual(state["filers"]["0000789019"]["search_ticker"], "MSFT.US")
        self.assertEqual(
            state["filers"]["0000789019"]["tickers"],
            ["MSFT.US", "MSFT.A.US"],
        )
        self.assertEqual(len(state["accessions"]), 3)

        added = FILING.add_broad_search_results(state, [_filing_result()])
        missing = FILING.missing_filers(state)

        self.assertEqual(added, 1)
        self.assertEqual([row["ticker"] for row in missing["missing"]], ["AAPL.US"])
        self.assertFalse(FILING.coverage_audit(state)["complete"])

        FILING.mark_filer(state, "AAPL.US", "failed", "rate_limited")
        self.assertEqual(FILING.coverage_audit(state)["failed_filer_count"], 1)

        FILING.mark_filer(state, "AAPL.US", "checked")
        audit = FILING.coverage_audit(state)

        self.assertTrue(audit["complete"])
        self.assertEqual(audit["accession_count"], 3)
        self.assertEqual(audit["filer_count"], 2)
        self.assertEqual(audit["broad_search_filer_count"], 1)
        self.assertEqual(audit["individually_checked_filer_count"], 1)
        self.assertEqual(audit["failed_filer_count"], 0)

    def test_broad_search_uses_ticker_fallback_and_rejects_identity_conflict(self):
        state = FILING._enumeration_state(
            _enumeration_payload(
                [
                    _accession_row(),
                    _accession_row(
                        cik="0000320193",
                        accession="0000320193-26-000001",
                        tickers=["AAPL.US"],
                        issuer_name="Apple Inc.",
                    ),
                ]
            ),
            ["8-K"],
        )
        ticker_only = _filing_result(ticker="AAPL.US", cik="", accession="")
        ticker_only["meta_data"]["source_uri"] = ""

        self.assertEqual(FILING.add_broad_search_results(state, [ticker_only]), 1)
        self.assertIn("0000320193", state["broad_surfaced"])

        conflict = _filing_result(ticker="AAPL.US")
        self.assertEqual(FILING.add_broad_search_results(state, [conflict]), 0)
        self.assertIn("search_identity_conflict", state["identity_issues"])
        self.assertFalse(FILING.coverage_audit(state)["complete"])

    def test_empty_inline_enumeration_initializes_and_audits_complete(self):
        payload = _enumeration_payload([], count=0, total_count=0, accession_count=0)

        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "empty.json"
            state_path = Path(directory) / "coverage.json"
            artifact.write_text(json.dumps({"text": json.dumps(payload)}), encoding="utf-8")
            stdout = io.StringIO()

            with mock.patch("sys.stdout", stdout):
                result = FILING.main(
                    [
                        "coverage-init",
                        "--state",
                        str(state_path),
                        "--expected-form",
                        "8-k",
                        "--artifact",
                        str(artifact),
                    ]
                )

            init_output = json.loads(stdout.getvalue())
            saved_state = state_path.read_text(encoding="utf-8")
            audit_stdout = io.StringIO()

            with mock.patch("sys.stdout", audit_stdout):
                audit_result = FILING.main(
                    ["coverage-audit", "--state", str(state_path)]
                )

        self.assertEqual(result, 0)
        self.assertEqual(init_output["filer_count"], 0)
        self.assertEqual(init_output["accession_count"], 0)
        self.assertNotIn("https://", saved_state)
        self.assertEqual(audit_result, 0)
        self.assertTrue(json.loads(audit_stdout.getvalue())["complete"])

    def test_coverage_rejects_windows_over_three_days(self):
        valid_windows = (
            (1, "2026-08-06", "2026-08-06"),
            (2, "2026-08-05", "2026-08-06"),
            (3, "2026-08-04", "2026-08-06"),
        )

        for days, date_from, date_to in valid_windows:
            with self.subTest(days=days):
                state = FILING._enumeration_state(
                    _enumeration_payload(
                        days=days,
                        date_from=date_from,
                        date_to=date_to,
                    ),
                    ["8-K"],
                )
                self.assertEqual(state["scope"]["days"], days)

        payload = _enumeration_payload(
            days=4,
            date_from="2026-08-05",
            date_to="2026-08-08",
        )

        with self.assertRaisesRegex(FILING.HelperError, "one to three calendar days"):
            FILING._enumeration_state(payload, ["8-K"])

    def test_coverage_audit_reports_incomplete_and_mismatched_enumeration(self):
        duplicate = _accession_row()
        payload = _enumeration_payload(
            [duplicate, dict(duplicate)],
            complete=False,
            has_more=True,
            total_count=1,
            accession_count=1,
            issues=["source_changed_during_scan"],
        )
        state = FILING._enumeration_state(payload, ["8-K"])
        FILING.mark_filer(state, "MSFT.US", "checked")
        audit = FILING.coverage_audit(state)

        self.assertFalse(audit["complete"])
        self.assertEqual(audit["coverage_issues"], ["source_changed_during_scan"])
        self.assertIn("enumeration_incomplete", audit["inconsistencies"])
        self.assertIn("enumeration_has_more", audit["inconsistencies"])
        self.assertIn("returned_count_mismatch", audit["inconsistencies"])

    def test_coverage_missing_is_bounded_and_pageable(self):
        rows = [
            _accession_row(
                cik=str(index).zfill(10),
                accession=f"{index:010d}-26-{index:06d}",
                tickers=[f"T{index}.US"],
                issuer_name=f"Issuer {index}",
            )
            for index in range(1, 56)
        ]
        state = FILING._enumeration_state(_enumeration_payload(rows), ["8-K"])

        first = FILING.missing_filers(state, limit=999)
        second = FILING.missing_filers(state, offset=50)

        self.assertEqual(first["shown_count"], 50)
        self.assertEqual(first["remaining_count"], 5)
        self.assertEqual(second["shown_count"], 5)
        self.assertEqual(second["remaining_count"], 0)

    def test_coverage_mark_requires_stable_reason_and_known_ticker(self):
        state = FILING._enumeration_state(_enumeration_payload(), ["8-K"])

        with self.assertRaisesRegex(FILING.HelperError, "short lowercase issue code"):
            FILING.mark_filer(
                state,
                "MSFT.US",
                "failed",
                "https://www.dfin.pro/api/v1/artifacts/Secret",
            )

        with self.assertRaisesRegex(FILING.HelperError, "exactly one enumerated filer"):
            FILING.mark_filer(state, "AAPL.US", "checked")

    def test_coverage_audit_rejects_unsearchable_and_ambiguous_filers(self):
        state = FILING._enumeration_state(
            _enumeration_payload(
                [_accession_row(tickers=[])],
            ),
            ["8-K"],
        )
        audit = FILING.coverage_audit(state)

        self.assertFalse(audit["complete"])
        self.assertEqual(audit["unsearchable_filer_count"], 1)

        self.assertEqual(
            FILING.add_broad_search_results(state, [_filing_result(ticker="MSFT.US")]),
            1,
        )
        self.assertEqual(state["filers"]["0000789019"]["search_ticker"], "MSFT.US")
        self.assertTrue(FILING.coverage_audit(state)["complete"])

        ambiguous_state = FILING._enumeration_state(
            _enumeration_payload(
                [
                    _accession_row(tickers=["SAME.US"]),
                    _accession_row(
                        cik="0000320193",
                        accession="0000320193-26-000001",
                        tickers=["SAME.US"],
                        issuer_name="Apple Inc.",
                    ),
                ]
            ),
            ["8-K"],
        )

        self.assertIn("ambiguous_ticker_alias", ambiguous_state["identity_issues"])
        self.assertFalse(FILING.coverage_audit(ambiguous_state)["complete"])

    def test_coverage_state_never_persists_capability_urls(self):
        row = _accession_row()
        row["filing_url"] = "https://www.sec.gov/Archives/example.htm"
        state = FILING._enumeration_state(_enumeration_payload([row]), ["8-K"])

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "coverage.json"
            FILING._write_state(state_path, state)
            saved = state_path.read_text(encoding="utf-8")
            self.assertNotIn("https://", saved)

            state["unexpected"].append(
                {"note": "https://www.dfin.pro/api/v1/artifacts/Secret"}
            )

            with self.assertRaisesRegex(FILING.HelperError, "Capability URLs"):
                FILING._write_state(state_path, state)

    def test_coverage_cli_reconciles_search_marks_and_audits(self):
        enumeration = _enumeration_payload(
            [
                _accession_row(),
                _accession_row(
                    cik="0000320193",
                    accession="0000320193-26-000001",
                    tickers=["AAPL.US"],
                    issuer_name="Apple Inc.",
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            enumeration_path = directory / "enumeration.json"
            search_path = directory / "search.json"
            state_path = directory / "coverage.json"
            enumeration_path.write_text(json.dumps(enumeration), encoding="utf-8")
            search_path.write_text(
                json.dumps({"results": [_filing_result()]}),
                encoding="utf-8",
            )

            commands = [
                [
                    "coverage-init",
                    "--state",
                    str(state_path),
                    "--expected-form",
                    "8-K",
                    "--artifact",
                    str(enumeration_path),
                ],
                [
                    "coverage-add-search",
                    "--state",
                    str(state_path),
                    "--artifact",
                    str(search_path),
                ],
                [
                    "coverage-mark",
                    "--state",
                    str(state_path),
                    "--ticker",
                    "AAPL.US",
                    "--status",
                    "checked",
                ],
                ["coverage-audit", "--state", str(state_path)],
            ]
            outputs = []

            for command in commands:
                stdout = io.StringIO()

                with mock.patch("sys.stdout", stdout):
                    result = FILING.main(command)

                self.assertEqual(result, 0)
                outputs.append(json.loads(stdout.getvalue()))

        self.assertEqual(outputs[1]["broad_search_filer_count"], 1)
        self.assertEqual(outputs[1]["missing_filer_count"], 1)
        self.assertEqual(outputs[2]["missing_filer_count"], 0)
        self.assertTrue(outputs[3]["complete"])


class DashboardBuilderTests(unittest.TestCase):
    def test_extracts_structured_fields_without_database_or_user_data(self):
        fields = BUILDER.extract_stock_fields(_stock_payload())

        self.assertEqual(fields["ticker"], "MSFT.US")
        self.assertEqual(fields["r"], [2.54, None, 0.0, 1.243, -6.897])
        self.assertEqual([row[0] for row in fields["eps"]], [1, 0, -1, 1])
        self.assertEqual(
            [row[1].split(":", 1)[0] for row in fields["eps"]],
            ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"],
        )
        self.assertNotIn("database", fields)
        self.assertNotIn("user", fields)

    def test_builds_nested_filings_scales_ratios_and_reports_status(self):
        data, statuses, cache = BUILDER.build_data(
            _manifest(),
            stock_fetcher=lambda _url: _stock_batch(),
        )
        company = data["cos"][0]

        self.assertEqual(statuses, [{"ticker": "MSFT.US", "stock_context": "ok"}])
        self.assertEqual(set(cache), {"MSFT.US"})
        self.assertEqual(company["roe"], "33.3%")
        self.assertEqual(company["roic"], "28.0%")
        self.assertEqual(company["em"], "56.9%")
        self.assertEqual(company["nd"], "0.51×")
        self.assertEqual(company["rvintage"], "FY2025 · June year-end")
        self.assertEqual(company["fs"][0]["tags"], ["confirmed", "appointments"])
        self.assertEqual(data["stats"][0], [1, "Companies"])
        self.assertEqual(data["stats"][1], [1, "Filing bundles"])

    def test_artifact_payload_does_not_require_inline_format_marker(self):
        batch = _stock_batch()
        batch.pop("format")

        data, statuses, cache = BUILDER.build_data(
            _manifest(),
            stock_fetcher=lambda _url: batch,
        )

        self.assertEqual(statuses, [{"ticker": "MSFT.US", "stock_context": "ok"}])
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(set(cache), {"MSFT.US"})

    def test_uses_allowlisted_cache_without_refetching(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        manifest = _manifest(stock_url=None)
        calls = []

        data, statuses, cache = BUILDER.build_data(
            manifest,
            stock_cache={"MSFT.US": cached},
            stock_fetcher=lambda url: calls.append(url),
        )

        self.assertEqual(calls, [])
        self.assertEqual(statuses[0]["stock_context"], "cached")
        self.assertEqual(data["cos"][0]["d"], cached["description"])
        self.assertEqual(cache, {"MSFT.US": cached})

    def test_fresh_ticker_mismatch_fails_loudly(self):
        payload = _stock_payload()
        payload["ticker"] = "AAPL.US"

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Stock context identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(
                _manifest(),
                stock_fetcher=lambda _url: _stock_batch(payload),
            )

    def test_cached_ticker_mismatch_is_evicted_and_refetched(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["ticker"] = "AAPL.US"
        calls = []

        data, statuses, cache = BUILDER.build_data(
            _manifest(),
            stock_cache={"MSFT.US": cached},
            stock_fetcher=lambda url: (calls.append(url), _stock_batch())[1],
        )

        self.assertEqual(
            calls,
            ["https://www.dfin.pro/api/v1/artifacts/Stock123"],
        )
        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(set(cache), {"MSFT.US"})

    def test_cached_cik_mismatch_is_evicted_and_refetched(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["cik"] = "0000320193"
        calls = []
        manifest = _manifest()
        manifest["companies"][0]["cik"] = "0000789019"

        data, statuses, cache = BUILDER.build_data(
            manifest,
            stock_cache={"MSFT.US": cached},
            stock_fetcher=lambda url: (calls.append(url), _stock_batch())[1],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(cache["MSFT.US"]["cik"], "0000789019")

    def test_cached_malformed_cik_is_evicted_and_refetched(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["cik"] = "bad-cik"
        calls = []

        data, statuses, cache = BUILDER.build_data(
            _manifest(),
            stock_cache={"MSFT.US": cached},
            stock_fetcher=lambda url: (calls.append(url), _stock_batch())[1],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(cache["MSFT.US"]["cik"], "0000789019")

    def test_invalid_cache_with_refresh_required_remains_retryable(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["ticker"] = "AAPL.US"

        def refresh_required(_url):
            raise BUILDER.ArtifactRefreshRequired("request one fresh URL")

        data, statuses, cache = BUILDER.build_data(
            _manifest(),
            stock_cache={"MSFT.US": cached},
            stock_fetcher=refresh_required,
        )

        self.assertEqual(statuses[0]["stock_context"], "refresh_required")
        self.assertEqual(data["cos"][0]["p"], "—")
        self.assertEqual(cache, {})

    def test_invalid_cache_without_fresh_source_fails_loudly(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["ticker"] = "AAPL.US"

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "identity mismatch and no fresh source.*MSFT.US",
        ):
            BUILDER.build_data(
                _manifest(stock_url=None),
                stock_cache={"MSFT.US": cached},
            )

    def test_cik_mismatch_fails_loudly(self):
        manifest = _manifest()
        manifest["companies"][0]["cik"] = "0000000001"

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Stock context identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(
                manifest,
                stock_fetcher=lambda _url: _stock_batch(),
            )

    def test_malformed_supplied_stock_cik_fails_loudly(self):
        payload = _stock_payload()
        payload["profile"]["cik"] = "bad-cik"

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Stock context identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(
                _manifest(),
                stock_fetcher=lambda _url: _stock_batch(payload),
            )

    def test_ratio_ticker_mismatch_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["ratios"]["ticker"] = "AAPL.US"

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Financial-ratio identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(manifest)

    def test_ratio_payload_without_ticker_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["ratios"].pop("ticker")

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Financial-ratio identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(manifest)

    def test_falsey_non_object_ratio_payload_fails_loudly(self):
        for ratios in ([], "", 0, False):
            with self.subTest(ratios=ratios):
                manifest = _manifest(stock_url=None)
                manifest["companies"][0]["ratios"] = ratios

                with self.assertRaisesRegex(
                    BUILDER.HelperError,
                    "Financial-ratio identity mismatch for MSFT.US",
                ):
                    BUILDER.build_data(manifest)

    def test_every_duplicate_ratio_response_is_identity_checked(self):
        valid = _manifest(stock_url=None)["companies"][0]["ratios"]
        mismatched = json.loads(json.dumps(valid))
        mismatched["ticker"] = "AAPL.US"

        for payloads in ((valid, mismatched), (mismatched, valid)):
            with self.subTest(first_ticker=payloads[0]["ticker"]):
                manifest = _manifest(stock_url=None)
                manifest["companies"][0]["ratios"] = payloads[0]
                duplicate = json.loads(json.dumps(manifest["companies"][0]))
                duplicate["ratios"] = payloads[1]
                duplicate["filings"][0]["id"] = "second-accession"
                manifest["companies"].append(duplicate)

                with self.assertRaisesRegex(
                    BUILDER.HelperError,
                    "Financial-ratio identity mismatch for MSFT.US",
                ):
                    BUILDER.build_data(manifest)

    def test_duplicate_ratio_responses_select_newest_valid_year(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["ratios"] = {
            "ticker": "MSFT.US",
            "year": 2024,
            "ratios": {"returnOnEquity": 0.10},
        }
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["ratios"] = {
            "ticker": "MSFT.US",
            "year": 2025,
            "ratios": {"returnOnEquity": 0.20},
        }
        duplicate["filings"][0]["id"] = "second-accession"
        manifest["companies"].append(duplicate)

        data, _statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(data["cos"][0]["roe"], "20.0%")
        self.assertEqual(data["cos"][0]["rvintage"], "FY2025")

    def test_duplicate_empty_ratio_payload_does_not_hide_valid_response(self):
        manifest = _manifest(stock_url=None)
        valid = manifest["companies"][0]["ratios"]
        manifest["companies"][0]["ratios"] = {}
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["ratios"] = valid
        duplicate["filings"][0]["id"] = "second-accession"
        manifest["companies"].append(duplicate)

        data, _statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(data["cos"][0]["roe"], "33.3%")
        self.assertEqual(data["cos"][0]["rvintage"], "FY2025")

    def test_unresolved_ticker_is_not_fetched_or_ratio_enriched(self):
        manifest = _manifest()
        manifest["companies"][0]["ticker"] = "MSFT"
        calls = []

        data, statuses, cache = BUILDER.build_data(
            manifest,
            stock_fetcher=lambda url: calls.append(url),
        )

        self.assertEqual(calls, [])
        self.assertEqual(statuses[0]["stock_context"], "unresolved")
        self.assertEqual(data["cos"][0]["roe"], "—")
        self.assertEqual(cache, {})

    def test_merges_duplicate_company_and_bundle_records(self):
        manifest = _manifest(stock_url=None)
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["filings"][0]["tags"] = ["confirmed", "board"]
        duplicate["filings"][0]["ev"] = [
            ["pill-board", "BOARD", "Director", "Joined the board"]
        ]
        duplicate["filings"][0]["docs"] = 4
        manifest["companies"].append(duplicate)

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(len(data["cos"]), 1)
        self.assertEqual(len(data["cos"][0]["fs"]), 1)
        self.assertEqual(data["cos"][0]["fs"][0]["docs"], 4)
        self.assertEqual(len(data["cos"][0]["fs"][0]["ev"]), 2)
        self.assertEqual(
            data["cos"][0]["fs"][0]["tags"],
            ["confirmed", "appointments", "board"],
        )
        self.assertNotIn("manifest_issues", statuses[0])

    def test_preserves_accessions_and_omits_only_conflicting_bundle(self):
        manifest = _manifest(stock_url=None)
        second = json.loads(json.dumps(manifest["companies"][0]))
        second["filings"] = [
            {
                "id": "sec:0000789019:second-accession",
                "ft": "8-K",
                "fd": "Aug 5",
                "tags": ["confirmed"],
                "ev": [],
                "docs": 1,
            },
            {
                "id": "sec:0000789019:accession",
                "ft": "10-Q",
                "fd": "Aug 6",
                "tags": ["confirmed"],
                "ev": [],
                "docs": 2,
            },
        ]
        manifest["companies"].append(second)

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(
            [filing["id"] for filing in data["cos"][0]["fs"]],
            ["sec:0000789019:second-accession"],
        )
        self.assertEqual(statuses[0]["manifest_issues"], ["manifest_conflict"])

    def test_fully_conflicted_company_is_omitted_with_diagnostic(self):
        manifest = _manifest(stock_url=None)
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["filings"][0]["ft"] = "10-Q"
        manifest["companies"].append(duplicate)

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(data["cos"], [])
        self.assertEqual(
            statuses,
            [
                {
                    "ticker": "MSFT.US",
                    "stock_context": "not_requested",
                    "manifest_issues": ["manifest_conflict"],
                }
            ],
        )

    def test_equivalent_form_and_date_representations_merge(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["filings"][0]["fd"] = "2026-08-06"
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["filings"][0]["ft"] = "8-k"
        duplicate["filings"][0]["fd"] = "Aug 6"
        manifest["companies"].append(duplicate)

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(len(data["cos"]), 1)
        self.assertEqual(len(data["cos"][0]["fs"]), 1)
        self.assertNotIn("manifest_issues", statuses[0])

    def test_different_partial_filing_dates_conflict(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["filings"][0]["fd"] = "Aug 6"
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["filings"][0]["fd"] = "Aug 7"
        manifest["companies"].append(duplicate)

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(data["cos"], [])
        self.assertEqual(statuses[0]["manifest_issues"], ["manifest_conflict"])

    def test_conflicting_company_ciks_fail_loudly(self):
        manifest = _manifest()
        manifest["companies"][0]["cik"] = "789019"
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["cik"] = "320193"
        duplicate["filings"][0]["id"] = "sec:0000320193:other-accession"
        manifest["companies"].append(duplicate)
        calls = []

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "conflicting company identities: MSFT.US",
        ):
            BUILDER.build_data(
                manifest,
                stock_fetcher=lambda url: calls.append(url),
            )

        self.assertEqual(calls, [])

    def test_one_cik_cannot_belong_to_two_resolved_tickers(self):
        manifest = _manifest()
        manifest["companies"][0]["cik"] = "0000789019"
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["ticker"] = "AAPL.US"
        duplicate["name"] = "Apple Inc."
        duplicate["ratios"]["ticker"] = "AAPL.US"
        duplicate["filings"][0]["id"] = "apple-accession"
        manifest["companies"].append(duplicate)
        calls = []

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            r"CIK 0000789019 \(AAPL\.US, MSFT\.US\)",
        ):
            BUILDER.build_data(
                manifest,
                stock_fetcher=lambda url: calls.append(url),
            )

        self.assertEqual(calls, [])

    def test_merged_company_consumes_shared_stock_url_once(self):
        manifest = _manifest(stock_url="https://www.dfin.pro/api/v1/artifacts/BatchStock")
        duplicate = json.loads(json.dumps(manifest["companies"][0]))
        duplicate["filings"][0]["id"] = "sec:0000789019:second-accession"
        manifest["companies"].append(duplicate)
        calls = []

        _data, statuses, _cache = BUILDER.build_data(
            manifest,
            stock_fetcher=lambda url: (calls.append(url), _stock_batch())[1],
        )

        self.assertEqual(
            calls,
            ["https://www.dfin.pro/api/v1/artifacts/BatchStock"],
        )
        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertNotIn("manifest_issues", statuses[0])

    def test_inline_stock_batch_does_not_call_artifact_fetcher(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = _stock_batch(_inline_stock_markdown())
        calls = []

        data, statuses, cache = BUILDER.build_data(
            manifest,
            stock_fetcher=lambda url: calls.append(url),
        )

        self.assertEqual(calls, [])
        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(data["cos"][0]["r"], [2.54, -1.0, 0.0, 1.243, -6.897])
        self.assertEqual(data["cos"][0]["eps"], [[-1, "2026-03-31: +0.0%"], [1, "2026-06-30: +12.6%"]])
        self.assertEqual(set(cache), {"MSFT.US"})

    def test_inline_ticker_only_title_is_accepted(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = _stock_batch(
            "# MSFT.US\n\n"
            "## Price\nPrice: $499.86 USD; Change: +$1.00 (+0.20%)"
        )

        data, statuses, cache = BUILDER.build_data(manifest)

        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "$499.86")
        self.assertEqual(set(cache), {"MSFT.US"})

    def test_inline_title_only_sparse_results_are_accepted(self):
        for markdown in (
            "# MSFT.US",
            "# Microsoft Corporation (MSFT.US)",
        ):
            with self.subTest(markdown=markdown):
                manifest = _manifest(stock_url=None)
                manifest["stock_context"] = _stock_batch(markdown)

                data, statuses, cache = BUILDER.build_data(manifest)

                self.assertEqual(statuses[0]["stock_context"], "ok")
                self.assertEqual(data["cos"][0]["p"], "—")
                self.assertEqual(data["cos"][0]["r"], [None] * 5)
                self.assertEqual(set(cache), {"MSFT.US"})

    def test_inline_unforeseen_price_fields_are_accepted(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = _stock_batch(
            "# Microsoft Corporation (MSFT.US)\n\n"
            "## Price\ncustom: reported"
        )

        data, statuses, cache = BUILDER.build_data(manifest)

        self.assertEqual(statuses[0]["stock_context"], "ok")
        self.assertEqual(data["cos"][0]["p"], "—")
        self.assertEqual(set(cache), {"MSFT.US"})

    def test_malformed_inline_stock_batch_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = {
            "MSFT.US": {"data": _inline_stock_markdown()}
        }

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "complete response object",
        ):
            BUILDER.build_data(manifest)

    def test_malformed_inline_ticker_data_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = _stock_batch(
            "# Microsoft Corporation (MSFT.US)\n\n"
            "## Price\nPrice $499.86, return 2.54%"
        )

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "no parseable price or returns section",
        ):
            BUILDER.build_data(manifest)

    def test_missing_requested_ticker_result_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        second = json.loads(json.dumps(manifest["companies"][0]))
        second["ticker"] = "AAPL.US"
        second["name"] = "Apple Inc."
        second["ratios"]["ticker"] = "AAPL.US"
        second["filings"][0]["id"] = "sec:0000320193:apple-accession"
        manifest["companies"].append(second)
        manifest["stock_context"] = _stock_batch()

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "missing requested ticker results: AAPL.US",
        ):
            BUILDER.build_data(manifest)

    def test_upstream_identity_mismatch_error_fails_loudly(self):
        manifest = _manifest(stock_url=None)
        batch = _stock_batch()
        batch["success_count"] = 0
        batch["error_count"] = 1
        batch["results"]["MSFT.US"] = {
            "error": {
                "type": "identity_mismatch",
                "message": "Stock context identity did not match MSFT.US.",
            }
        }
        manifest["stock_context"] = batch

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "Stock context identity mismatch for MSFT.US",
        ):
            BUILDER.build_data(manifest)

    def test_identity_failure_cli_does_not_write_dashboard(self):
        manifest = _manifest(stock_url=None)
        payload = _stock_payload()
        payload["ticker"] = "AAPL.US"
        manifest["stock_context"] = _stock_batch(payload)

        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "dashboard.html"
            output = Path(directory) / "result.html"
            template.write_text("/* INJECT_DATA */", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch("sys.stdin", io.StringIO(json.dumps(manifest))),
                mock.patch("sys.stdout", stdout),
                mock.patch("sys.stderr", stderr),
            ):
                result = BUILDER.main(
                    [
                        "--template",
                        str(template),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Stock context identity mismatch", stderr.getvalue())

    def test_malformed_artifact_stock_batch_fails_loudly(self):
        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "does not contain ticker-keyed results",
        ):
            BUILDER.build_data(
                _manifest(),
                stock_fetcher=lambda _url: {"results": {}},
            )

    def test_compact_text_rows_exclude_dashboard_only_context(self):
        manifest = _manifest(stock_url=None)
        manifest["stock_context"] = _stock_batch(_inline_stock_markdown())
        data, _statuses, _cache = BUILDER.build_data(manifest)

        rows = BUILDER.compact_text_rows(data)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "MSFT.US")
        self.assertEqual(rows[0]["price"], "$499.86")
        self.assertEqual(rows[0]["one_year"], -6.897)
        self.assertNotIn("description", rows[0])
        self.assertNotIn("eps", rows[0])
        self.assertNotIn("roe", rows[0])

    def test_rejects_inline_and_artifact_stock_sources_together(self):
        manifest = _manifest()
        manifest["stock_context"] = _stock_batch()

        with self.assertRaisesRegex(
            BUILDER.HelperError,
            "either stock_context_url or stock_context",
        ):
            BUILDER.build_data(manifest)

    def test_shared_batch_keeps_failed_ticker_card_without_enrichment(self):
        manifest = _manifest()
        second = json.loads(json.dumps(manifest["companies"][0]))
        second["ticker"] = "AAPL.US"
        second["name"] = "Apple Inc."
        second["ratios"]["ticker"] = "AAPL.US"
        second["filings"][0]["id"] = "sec:0000320193:apple-accession"
        manifest["companies"].append(second)
        batch = _stock_batch()
        batch.update({"count": 2, "error_count": 1})
        batch["results"]["AAPL.US"] = {
            "error": {
                "type": "availability",
                "message": "Stock context is temporarily unavailable for AAPL.US.",
            }
        }
        calls = []

        data, statuses, cache = BUILDER.build_data(
            manifest,
            stock_fetcher=lambda url: (calls.append(url), batch)[1],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(data["cos"]), 2)
        self.assertEqual(
            {status["ticker"]: status["stock_context"] for status in statuses},
            {"MSFT.US": "ok", "AAPL.US": "unavailable"},
        )
        self.assertEqual(set(cache), {"MSFT.US"})
        apple = next(company for company in data["cos"] if company["t"] == "AAPL.US")
        self.assertEqual(apple["p"], "—")
        self.assertEqual(apple["d"], "")

    def test_unresolved_ciks_remain_separate_and_empty_companies_are_omitted(self):
        manifest = {"companies": []}

        for cik in ("111", "222"):
            manifest["companies"].append(
                {
                    "ticker": None,
                    "cik": cik,
                    "name": f"Issuer {cik}",
                    "filings": [{"id": f"sec:{cik}:accession", "ft": "8-K"}],
                }
            )

        manifest["companies"].append({"ticker": "EMPTY.US", "filings": []})
        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(len(data["cos"]), 2)
        self.assertEqual(
            [status["stock_context"] for status in statuses],
            ["unresolved", "unresolved"],
        )

    def test_missing_bundle_ids_do_not_merge_unresolved_issuers(self):
        manifest = {
            "companies": [
                {"name": "Issuer A", "filings": [{"ft": "8-K"}]},
                {"name": "Issuer B", "filings": [{"ft": "8-K"}]},
            ]
        }

        data, statuses, _cache = BUILDER.build_data(manifest)

        self.assertEqual(data["cos"], [])
        self.assertEqual(len(statuses), 2)
        self.assertTrue(
            all(status["manifest_issues"] == ["manifest_conflict"] for status in statuses)
        )

    def test_loaded_cache_is_allowlisted_and_unrelated_entries_are_dropped(self):
        cached = BUILDER.extract_stock_fields(_stock_payload())
        cached["database"] = {"filings": ["raw"]}
        cached["user"] = {"notes": ["raw"]}
        unrelated = dict(cached, ticker="AAPL.US")

        _data, statuses, cache = BUILDER.build_data(
            _manifest(stock_url=None),
            stock_cache={"MSFT.US": cached, "AAPL.US": unrelated},
        )

        self.assertEqual(statuses[0]["stock_context"], "cached")
        self.assertEqual(set(cache), {"MSFT.US"})
        self.assertNotIn("database", cache["MSFT.US"])
        self.assertNotIn("user", cache["MSFT.US"])

    def test_python_sec_link_validation_removes_malformed_sources(self):
        manifest = _manifest(stock_url=None)
        manifest["companies"][0]["filings"][0]["fl"] = (
            "https://user@www.sec.gov:444/Archives/example.htm"
        )

        data, _statuses, _cache = BUILDER.build_data(manifest)
        self.assertEqual(data["cos"][0]["fs"][0]["fl"], "")

    def test_single_use_transport_failure_is_not_retried(self):
        calls = []

        def fail(*_args, **_kwargs):
            calls.append(1)
            raise URLError("timeout")

        with self.assertRaises(BUILDER.ArtifactRefreshRequired):
            BUILDER.fetch_stock_context(
                "https://www.dfin.pro/api/v1/artifacts/Stock123",
                open_url=fail,
                sleep=lambda _seconds: None,
            )

        self.assertEqual(len(calls), 1)

    def test_stock_context_rejects_malformed_or_queried_urls(self):
        for rejected in (
            "https://www.dfin.pro:bad/api/v1/artifacts/Stock123",
            "https://www.dfin.pro/api/v1/artifacts/Stock123?index=0",
        ):
            with self.subTest(rejected=rejected):
                with self.assertRaises(BUILDER.HelperError):
                    BUILDER.validate_stock_artifact_url(rejected)

    def test_stock_fetch_retries_only_explicit_202(self):
        responses = [
            FakeResponse(202, {"retry_after_seconds": 1}),
            FakeResponse(200, _stock_payload()),
        ]
        sleeps = []

        payload = BUILDER.fetch_stock_context(
            "https://www.dfin.pro/api/v1/artifacts/Stock123",
            open_url=lambda *_args, **_kwargs: responses.pop(0),
            sleep=sleeps.append,
        )

        self.assertEqual(payload["ticker"], "MSFT.US")
        self.assertEqual(sleeps, [1.0])

    def test_html_serialization_blocks_script_termination(self):
        manifest = _manifest()
        manifest["companies"][0]["filings"][0]["ev"][0][0] = ["pill-event"]
        data, _statuses, _cache = BUILDER.build_data(
            manifest,
            stock_fetcher=lambda _url: _stock_batch(),
        )
        rendered = BUILDER.render_dashboard(
            '<script type="application/json">/* INJECT_DATA */</script>',
            data,
        )

        self.assertNotIn("</script> Changes", rendered)
        self.assertNotIn("O'Reilly </script>", rendered)
        self.assertIn(r"\u003c/script\u003e", rendered)
        self.assertNotIn("stock_context_url", rendered)
        self.assertNotIn("must not leak", rendered)
        self.assertEqual(data["cos"][0]["fs"][0]["ev"][0][0], "pill-event")


class SkillContractTests(unittest.TestCase):
    def test_skill_and_dashboard_encode_the_new_contract(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        dashboard = (SKILL_ROOT / "dashboard.html").read_text(encoding="utf-8")

        plugin_versions = {
            json.loads((REPOSITORY_ROOT / manifest_path).read_text(encoding="utf-8"))["version"]
            for manifest_path in (
                ".claude-plugin/plugin.json",
                ".codex-plugin/plugin.json",
            )
        }
        self.assertEqual(len(plugin_versions), 1)
        plugin_version = plugin_versions.pop()

        for skill_path in sorted((REPOSITORY_ROOT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill_path.parent.name):
                version_line = next(
                    (
                        line
                        for line in skill_path.read_text(encoding="utf-8").splitlines()
                        if line.startswith("DFin skill version: ")
                    ),
                    None,
                )
                self.assertIsNotNone(version_line)
                self.assertEqual(
                    version_line.split(": ", 1)[1].split(",", 1)[0],
                    plugin_version,
                )

        self.assertIn("delivery: api", skill)
        self.assertIn("delivery: inline", skill)
        self.assertIn("and `delivery: api`", skill)
        self.assertNotIn("automatically based on response size", skill)
        self.assertIn("Call `get_stock_context` once with all resolved `tickers`", skill)
        self.assertIn('"stock_context_url": "<single-use batch capability>"', skill)
        self.assertIn('"stock_context": {<complete ticker-keyed batch>}', skill)
        self.assertIn(
            "including `format`, `count`, `success_count`, `error_count`, and `results`",
            skill,
        )
        self.assertIn("Never retype, truncate, paraphrase, or hand-summarize", skill)
        self.assertIn("aborts the build", skill)
        self.assertIn("newest integer fiscal year", skill)
        self.assertIn("two resolved tickers sharing one non-empty CIK", skill)
        self.assertIn("a supplied malformed CIK aborts", skill)
        self.assertIn("build_dashboard.py --text --stock-cache", skill)
        self.assertIn("management changes announced today", skill)
        self.assertIn("morning scan for debt restructuring", skill)
        self.assertIn("ask for one monitoring theme and make no DFin calls", skill)
        self.assertIn("ratio ticker mismatch aborts the build", skill)
        self.assertIn("--offset", skill)
        self.assertIn("list_latest_filings", skill)
        self.assertIn("result_level: accession", skill)
        self.assertIn("limit: -1", skill)
        self.assertIn("coverage-init", skill)
        self.assertIn("coverage-add-search", skill)
        self.assertIn("coverage-missing", skill)
        self.assertIn("coverage-mark", skill)
        self.assertIn("coverage-audit", skill)
        self.assertIn("inclusive windows of one to three calendar days", skill)
        self.assertIn("plausible SEC disclosure paths", skill)
        self.assertIn("expand the form set, rerun enumeration", skill)
        self.assertIn("**Omit `filing_type`**", skill)
        self.assertIn("methodology_delegation", skill)
        self.assertIn("Do not create one worker per ticker", skill)
        self.assertIn("successful zero-result response also counts as checked", skill)
        self.assertIn("does not prove perfect thematic recall", skill)
        self.assertNotIn("what happened in filings today", skill)
        self.assertNotIn("what companies announced [topic] this week?", skill)
        self.assertNotIn("Use seven days", skill)
        self.assertNotIn("results_per_query: 20", skill)
        self.assertNotIn('ticker: "<TICKER>.US"', skill)
        self.assertIn('type="application/json"', dashboard)
        self.assertNotIn("onclick=", dashboard)
        self.assertIn("addEventListener", dashboard)
        self.assertIn('rel="noopener noreferrer"', dashboard)


if __name__ == "__main__":
    unittest.main()
