#!/usr/bin/env python3
"""Fetch, summarize, and select evidence from DFin filing artifacts."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ALLOWED_HOST = "www.dfin.pro"
ARTIFACT_PATH_RE = re.compile(r"^/api/v1/artifacts/[A-Za-z0-9_-]+/?$")
SEC_SOURCE_RE = re.compile(
    r"/Archives/edgar/data/(?P<cik>\d+)/(?P<accession>\d{18})/",
    re.IGNORECASE,
)
NAME_CIK_RE = re.compile(r"\bCIK\s*0*(\d+)\b", re.IGNORECASE)
KNOWN_FORMS = ("10-K", "10-Q", "20-F", "8-K", "6-K")
QUALIFIED_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]*\.[A-Z0-9]{2,8}$")
CIK_RE = re.compile(r"^[0-9]{1,10}$")
ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
FAILURE_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
FORM_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9 /-]{0,49}$")
CAPABILITY_URL_FRAGMENT = "www.dfin.pro/api/v1/artifacts/"
DEFAULT_PREVIEW_CHARS = 220
DEFAULT_EVIDENCE_CHARS = 800
MAX_SUMMARIES = 15
MAX_DOC_UUIDS = 20
MAX_COVERAGE_ROWS = 50
COVERAGE_STATE_VERSION = 1


class HelperError(Exception):
    """Report one expected helper failure without a traceback."""


def validate_artifact_url(value, *, allow_index=True):
    """Return a validated DFin artifact URL without exposing it in errors."""
    if not isinstance(value, str) or not value:
        raise HelperError("The artifact URL is missing.")

    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HelperError("The artifact URL is malformed.") from exc
    valid_query = not parsed.query

    if allow_index and parsed.query:
        try:
            query = parse_qs(parsed.query, strict_parsing=True)
        except ValueError as exc:
            raise HelperError("The artifact URL query is malformed.") from exc
        valid_query = (
            set(query) == {"index"}
            and len(query["index"]) == 1
            and query["index"][0].isdigit()
        )

    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not ARTIFACT_PATH_RE.fullmatch(parsed.path)
        or parsed.fragment
        or not valid_query
    ):
        raise HelperError("The artifact URL is not an approved DFin capability URL.")

    return value


def validate_sec_url(value):
    """Return one approved SEC HTTPS URL, or None for malformed input."""
    if not isinstance(value, str) or not value:
        return None

    parsed = urlparse(value)

    try:
        port = parsed.port
    except ValueError:
        return None

    hostname = (parsed.hostname or "").lower()

    if (
        parsed.scheme != "https"
        or not (hostname == "sec.gov" or hostname.endswith(".sec.gov"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return None

    return value


def _retry_delay(response, body):
    """Return a bounded server-directed retry delay for a 202 response."""
    candidates = []
    header_value = response.headers.get("Retry-After")

    if header_value:
        candidates.append(header_value)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        payload = {}

    if isinstance(payload, dict):
        candidates.extend(
            payload.get(key)
            for key in ("retry_after_seconds", "retry_after")
        )

    for candidate in candidates:
        try:
            return max(1.0, min(float(candidate), 30.0))
        except (TypeError, ValueError):
            continue

    return 5.0


def fetch_artifact_bytes(
    url,
    *,
    attempts=3,
    timeout=45,
    open_url=urlopen,
    sleep=time.sleep,
):
    """Fetch a reusable filing artifact with bounded 202/transport retries."""
    validate_artifact_url(url)
    last_error = None

    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "dfin-filing-monitor",
                },
            )

            with open_url(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                body = response.read()

                if status == 200:
                    return body

                if status == 202:
                    last_error = HelperError("The filing artifact is still processing.")

                    if attempt + 1 < attempts:
                        sleep(_retry_delay(response, body))
                        continue

                    break

                raise HelperError(
                    f"The filing artifact returned unexpected HTTP status {status}."
                )
        except HTTPError as exc:
            if exc.code == 202:
                body = exc.read()
                last_error = HelperError("The filing artifact is still processing.")

                if attempt + 1 < attempts:
                    sleep(_retry_delay(exc, body))
                    continue

                break

            raise HelperError(
                f"The filing artifact returned HTTP status {exc.code}."
            ) from None
        except (TimeoutError, URLError, OSError) as exc:
            last_error = exc

            if attempt + 1 < attempts:
                sleep(5.0)
                continue

    if isinstance(last_error, HelperError):
        raise last_error

    raise HelperError(
        "The filing artifact could not be downloaded after bounded retries."
    )


def _write_atomic(path, body):
    """Write bytes atomically beside the requested destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )

    try:
        with os.fdopen(file_descriptor, "wb") as output_file:
            output_file.write(body)
            output_file.flush()
            os.fsync(output_file.fileno())

        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _decode_result(value):
    """Decode string and one-field text wrappers returned by MCP stacks."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None

    if isinstance(value, dict) and set(value) == {"text"}:
        try:
            value = json.loads(value["text"])
        except (TypeError, json.JSONDecodeError):
            return None

    return value if isinstance(value, dict) else None


def _looks_like_result(value):
    """Recognize one filing search result without accepting arbitrary objects."""
    if not isinstance(value, dict):
        return False

    has_document = any(key in value for key in ("doc_uuid", "content", "source_uri"))
    has_filing = any(
        key in value
        for key in ("filing_type", "filing_date", "ticker", "meta_data")
    )
    return has_document and has_filing


def normalize_results(payload):
    """Return normalized result dictionaries from supported artifact shapes."""
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            values = payload["results"]
        elif isinstance(payload.get("result"), list):
            values = payload["result"]
        elif _looks_like_result(payload.get("result")):
            values = [payload["result"]]
        elif _looks_like_result(payload):
            values = [payload]
        else:
            raise HelperError(
                "Unsupported artifact object; expected filing results or one result."
            )
    elif isinstance(payload, list):
        values = payload
    else:
        raise HelperError(
            "Unsupported artifact shape; expected an object envelope or list."
        )

    return [decoded for value in values if (decoded := _decode_result(value))]


def load_artifact(path):
    """Read and normalize one saved UTF-8 filing artifact."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HelperError(f"Could not read the saved filing artifact: {exc}.") from None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HelperError(
            f"Invalid filing artifact JSON at line {exc.lineno}, column {exc.colno}."
        ) from None

    return normalize_results(payload)


def _source_metadata(result):
    metadata = result.get("meta_data")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}

    if not metadata.get("source_uri") and isinstance(result.get("source_uri"), str):
        metadata["source_uri"] = result["source_uri"]

    return metadata


def _cik_and_accession(result):
    source_uri = validate_sec_url(_source_metadata(result).get("source_uri"))
    match = SEC_SOURCE_RE.search(source_uri or "")

    if match:
        return match.group("cik").zfill(10), match.group("accession")

    name_match = NAME_CIK_RE.search(str(result.get("name") or ""))
    cik = name_match.group(1).zfill(10) if name_match else None
    return cik, None


def normalize_form(value):
    """Split one filing type into base form and document designation."""
    text = " ".join(str(value or "").split())
    upper = text.upper()

    for form in KNOWN_FORMS:
        if upper == form or upper.startswith(f"{form} "):
            designation = text[len(form) :].strip() or None
            return form, designation

    return text or "Unknown", None


def _safe_score(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _non_negative_integer(value):
    """Return one non-negative integer without accepting booleans."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _qualified_ticker(value):
    if not isinstance(value, str) or not value.strip():
        return None

    ticker = value.strip()
    return ticker if QUALIFIED_TICKER_RE.fullmatch(ticker.upper()) else None


def _bundle_identity(result):
    cik, accession = _cik_and_accession(result)
    doc_uuid = str(result.get("doc_uuid") or "")

    if cik and accession:
        bundle_id = f"sec:{cik}:{accession}"
    elif doc_uuid:
        digest = hashlib.sha256(doc_uuid.encode("utf-8")).hexdigest()[:16]
        bundle_id = f"doc:{digest}"
    else:
        stable_bits = "|".join(
            str(result.get(key) or "")
            for key in ("ticker", "name", "filing_date", "filing_type")
        )
        digest = hashlib.sha256(stable_bits.encode("utf-8")).hexdigest()[:16]
        bundle_id = f"unknown:{digest}"

    ticker = result.get("ticker")
    ticker = ticker.strip() if isinstance(ticker, str) and ticker.strip() else None
    issuer_ticker = _qualified_ticker(ticker)
    issuer_key = issuer_ticker or (f"cik:{cik}" if cik else f"bundle:{bundle_id}")
    return bundle_id, issuer_key, ticker, cik


def group_results(results):
    """Group search-result chunks into accession-level filing bundles."""
    grouped = {}

    for index, result in enumerate(results):
        bundle_id, issuer_key, ticker, cik = _bundle_identity(result)
        form, designation = normalize_form(result.get("filing_type"))
        score = _safe_score(result.get("reranking_score"))
        metadata = _source_metadata(result)
        doc_uuid = result.get("doc_uuid")
        source_uri = metadata.get("source_uri")
        content = result.get("content")
        content = content if isinstance(content, str) else ""

        if bundle_id not in grouped:
            grouped[bundle_id] = {
                "id": bundle_id,
                "issuer_key": issuer_key,
                "ticker": ticker,
                "cik": cik,
                "company": str(result.get("name") or ""),
                "date": str(result.get("filing_date") or ""),
                "form": form,
                "identity_conflict": False,
                "_qualified_tickers": {},
                "documents": [],
                "best": None,
            }

        bundle = grouped[bundle_id]
        qualified_ticker = _qualified_ticker(ticker)

        if qualified_ticker:
            bundle["_qualified_tickers"][qualified_ticker.upper()] = qualified_ticker
        elif bundle["ticker"] is None and ticker:
            bundle["ticker"] = ticker

        if not bundle["company"] and result.get("name"):
            bundle["company"] = str(result.get("name"))

        if not bundle["date"] and result.get("filing_date"):
            bundle["date"] = str(result.get("filing_date"))

        if bundle["form"] == "Unknown" and form != "Unknown":
            bundle["form"] = form
        document_key = (doc_uuid, source_uri)

        if document_key not in {
            (document["doc_uuid"], document["source_uri"])
            for document in bundle["documents"]
        }:
            bundle["documents"].append(
                {
                    "doc_uuid": doc_uuid,
                    "source_uri": source_uri,
                    "designation": designation,
                    "result_indexes": [index],
                }
            )
        else:
            for document in bundle["documents"]:
                if (document["doc_uuid"], document["source_uri"]) == document_key:
                    document["result_indexes"].append(index)
                    break

        candidate = {
            "index": index,
            "score": score,
            "content": content,
            "content_chars": _non_negative_integer(result.get("content_chars")),
            "chunk_num": _non_negative_integer(result.get("chunk_num")),
            "source_uri": source_uri,
            "doc_uuid": doc_uuid,
            "designation": designation,
        }

        if bundle["best"] is None or score > bundle["best"]["score"]:
            bundle["best"] = candidate

    bundles = []

    for bundle in grouped.values():
        qualified_tickers = bundle.pop("_qualified_tickers")

        if len(qualified_tickers) == 1:
            bundle["ticker"] = next(iter(qualified_tickers.values()))
            bundle["issuer_key"] = bundle["ticker"]
        elif len(qualified_tickers) > 1:
            bundle["ticker"] = None
            bundle["identity_conflict"] = True
            bundle["issuer_key"] = (
                f"cik:{bundle['cik']}"
                if bundle["cik"]
                else f"bundle:{bundle['id']}"
            )

        bundles.append(bundle)

    return sorted(
        bundles,
        key=lambda bundle: (-bundle["best"]["score"], bundle["id"]),
    )


def _bundle_source_uri(bundle):
    preferred = validate_sec_url(bundle["best"]["source_uri"])

    if preferred:
        return preferred

    return next(
        (
            validated
            for document in bundle["documents"]
            if (validated := validate_sec_url(document["source_uri"]))
        ),
        "",
    )


def summarize_bundles(
    results,
    *,
    limit=MAX_SUMMARIES,
    offset=0,
    preview_chars=DEFAULT_PREVIEW_CHARS,
):
    """Return bounded model-facing summaries of the best filing bundles."""
    limit = max(1, min(int(limit), MAX_SUMMARIES))
    offset = max(0, int(offset))
    preview_chars = max(40, min(int(preview_chars), DEFAULT_PREVIEW_CHARS))
    summaries = []

    bundles = group_results(results)

    for bundle in bundles[offset : offset + limit]:
        best = bundle["best"]
        summaries.append(
            {
                "bundle_id": bundle["id"],
                "issuer_key": bundle["issuer_key"],
                "ticker": bundle["ticker"],
                "cik": bundle["cik"],
                "identity_conflict": bundle["identity_conflict"],
                "company": bundle["company"],
                "date": bundle["date"],
                "form": bundle["form"],
                "score": round(best["score"], 6),
                "document_count": len(bundle["documents"]),
                "source_uri": _bundle_source_uri(bundle),
                "preview": best["content"][:preview_chars],
            }
        )

    return summaries


def _batches(values, size=MAX_DOC_UUIDS):
    return [values[index : index + size] for index in range(0, len(values), size)]


def select_bundles(
    results,
    bundle_ids,
    *,
    evidence_chars=DEFAULT_EVIDENCE_CHARS,
):
    """Return bounded evidence and UUID batches for selected bundles only."""
    requested = list(dict.fromkeys(bundle_ids))
    grouped = {bundle["id"]: bundle for bundle in group_results(results)}
    missing = [bundle_id for bundle_id in requested if bundle_id not in grouped]

    if missing:
        raise HelperError(
            "One or more selected bundle IDs are absent from the saved artifact."
        )

    evidence_chars = max(80, min(int(evidence_chars), DEFAULT_EVIDENCE_CHARS))
    selected = []

    for bundle_id in requested:
        bundle = grouped[bundle_id]
        uuids = list(
            dict.fromkeys(
                document["doc_uuid"]
                for document in bundle["documents"]
                if isinstance(document["doc_uuid"], str)
                and document["doc_uuid"]
            )
        )
        best = bundle["best"]
        selected.append(
            {
                "bundle_id": bundle_id,
                "ticker": bundle["ticker"],
                "cik": bundle["cik"],
                "identity_conflict": bundle["identity_conflict"],
                "company": bundle["company"],
                "date": bundle["date"],
                "form": bundle["form"],
                "source_uri": _bundle_source_uri(bundle),
                "uuid_batches": _batches(uuids),
                "evidence_location": {
                    "doc_uuid": best["doc_uuid"],
                    "chunk_num": best["chunk_num"],
                    "content_chars": (
                        best["content_chars"]
                        if best["content_chars"] is not None
                        else len(best["content"])
                    ),
                },
                "evidence": best["content"][:evidence_chars],
            }
        )

    return selected


def _load_json_value(path):
    """Read one saved UTF-8 JSON value without normalizing its envelope."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HelperError(f"Could not read the saved JSON input: {exc}.") from None

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HelperError(
            f"Invalid JSON input at line {exc.lineno}, column {exc.colno}."
        ) from None


def _decode_envelope(value):
    """Decode common MCP wrappers around one response object."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HelperError("The coverage response is not valid JSON.") from exc

    if isinstance(value, dict) and set(value) == {"text"}:
        return _decode_envelope(value["text"])

    if (
        isinstance(value, dict)
        and set(value) == {"result"}
        and isinstance(value["result"], (dict, str))
    ):
        return _decode_envelope(value["result"])

    if not isinstance(value, dict):
        raise HelperError("The coverage response must be a JSON object.")

    return value


def _normalized_form(value):
    """Return one non-empty uppercase form prefix."""
    form = " ".join(str(value or "").split()).upper()

    if not FORM_PREFIX_RE.fullmatch(form):
        raise HelperError("Every expected form must be a non-empty form prefix.")

    return form


def _normalized_expected_forms(values):
    """Normalize and deduplicate expected form prefixes in caller order."""
    forms = []

    for value in values or []:
        form = _normalized_form(value)

        if form not in forms:
            forms.append(form)

    if not forms:
        raise HelperError("At least one --expected-form value is required.")

    return forms


def _valid_non_negative_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_cik(value):
    text = str(value or "").strip()
    return text.zfill(10) if CIK_RE.fullmatch(text) else None


def _date_window(filters):
    """Return validated inclusive date bounds limited to three calendar days."""
    try:
        date_from = datetime.date.fromisoformat(str(filters.get("date_from") or ""))
        date_to = datetime.date.fromisoformat(str(filters.get("date_to") or ""))
    except ValueError as exc:
        raise HelperError(
            "The enumeration response must include valid date_from and date_to filters."
        ) from exc

    days = (date_to - date_from).days + 1

    if not 1 <= days <= 3:
        raise HelperError(
            "The daily filing monitor supports inclusive windows of one to three calendar days."
        )

    response_days = filters.get("days")

    if response_days != days:
        raise HelperError(
            "The enumeration days filter does not match its inclusive date window."
        )

    return date_from.isoformat(), date_to.isoformat(), days


def _append_unique(values, value):
    if value not in values:
        values.append(value)


def _enumeration_state(payload, expected_forms):
    """Build a coverage ledger from one accession-level enumeration response."""
    response = _decode_envelope(payload)
    filters = response.get("filters")
    coverage = response.get("coverage")
    results = response.get("results")

    if not isinstance(filters, dict) or not isinstance(coverage, dict):
        raise HelperError("The enumeration response is missing filters or coverage metadata.")

    if not isinstance(results, list):
        raise HelperError("The enumeration response must contain a results array.")

    if response.get("result_level") != "accession" or filters.get("result_level") != "accession":
        raise HelperError("Run list_latest_filings with result_level='accession'.")

    if filters.get("limit") != -1:
        raise HelperError("Run list_latest_filings with limit=-1 for complete enumeration.")

    if filters.get("ticker") not in (None, ""):
        raise HelperError("The coverage census must omit ticker and enumerate all selected filers.")

    if filters.get("data_in_db_only") is not False:
        raise HelperError("Run list_latest_filings with data_in_db_only=false.")

    response_forms = _normalized_expected_forms(filters.get("filing_types"))

    if set(response_forms) != set(expected_forms):
        raise HelperError(
            "The enumeration filing_types do not match the expected form universe."
        )

    date_from, date_to, days = _date_window(filters)
    window_start = datetime.date.fromisoformat(date_from)
    window_end = datetime.date.fromisoformat(date_to)
    inconsistencies = []
    accessions = {}
    filers = {}

    for row in results:
        if not isinstance(row, dict):
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        accession = str(row.get("accession_number") or "").strip()
        cik = _valid_cik(row.get("cik"))
        filing_type = " ".join(str(row.get("filing_type") or "").split()).upper()
        filing_date = str(row.get("filing_date") or "").strip()

        if not ACCESSION_RE.fullmatch(accession) or cik is None or not filing_type:
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        try:
            parsed_filing_date = datetime.date.fromisoformat(filing_date)
        except ValueError:
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        if not window_start <= parsed_filing_date <= window_end:
            _append_unique(inconsistencies, "accession_outside_window")

        if not any(filing_type.startswith(form) for form in expected_forms):
            _append_unique(inconsistencies, "unexpected_filing_type")

        existing_accession = accessions.get(accession)
        accession_record = {
            "cik": cik,
            "filing_type": filing_type,
            "filing_date": filing_date,
        }

        if existing_accession is not None:
            if existing_accession != accession_record:
                _append_unique(inconsistencies, "conflicting_accession_identity")
            continue

        accessions[accession] = accession_record
        filer = filers.setdefault(
            cik,
            {
                "cik": cik,
                "issuer_name": str(row.get("issuer_name") or ""),
                "tickers": [],
                "search_ticker": None,
                "accessions": [],
                "filing_types": [],
                "filing_dates": [],
            },
        )
        _append_unique(filer["accessions"], accession)
        _append_unique(filer["filing_types"], filing_type)
        _append_unique(filer["filing_dates"], filing_date)
        tickers = row.get("tickers")

        if not isinstance(tickers, list):
            _append_unique(inconsistencies, "malformed_ticker_aliases")
            tickers = []

        known_tickers = {value.upper() for value in filer["tickers"]}

        for ticker_value in tickers:
            ticker = _qualified_ticker(ticker_value)

            if ticker is None:
                _append_unique(inconsistencies, "malformed_ticker_alias")
                continue

            canonical_ticker = ticker.upper()

            if canonical_ticker not in known_tickers:
                filer["tickers"].append(ticker)
                known_tickers.add(canonical_ticker)

            if filer["search_ticker"] is None:
                filer["search_ticker"] = ticker

    alias_owners = {}

    for cik, filer in filers.items():
        for ticker in filer["tickers"]:
            alias_owners.setdefault(ticker.upper(), set()).add(cik)

    if any(len(owners) > 1 for owners in alias_owners.values()):
        _append_unique(inconsistencies, "ambiguous_ticker_alias")

    count = response.get("count")
    total_count = response.get("total_count")
    accession_count = coverage.get("accession_count")

    for value in (count, total_count, accession_count):
        if not _valid_non_negative_integer(value):
            raise HelperError("Enumeration counts must be non-negative integers.")

    if len(results) != count:
        _append_unique(inconsistencies, "returned_count_mismatch")

    if len(accessions) != accession_count:
        _append_unique(inconsistencies, "accession_count_mismatch")

    if total_count != accession_count:
        _append_unique(inconsistencies, "total_count_mismatch")

    issues = coverage.get("issues")

    if not isinstance(issues, list) or not all(
        isinstance(value, str) and FAILURE_REASON_RE.fullmatch(value)
        for value in issues
    ):
        raise HelperError("coverage.issues must be an array of issue codes.")

    by_filing_type = coverage.get("by_filing_type")

    if not isinstance(by_filing_type, dict):
        raise HelperError("coverage.by_filing_type must be an object.")

    if not all(
        isinstance(key, str) and _valid_non_negative_integer(value)
        for key, value in by_filing_type.items()
    ):
        raise HelperError("coverage.by_filing_type must contain non-negative counts.")

    if sum(by_filing_type.values()) != accession_count:
        _append_unique(inconsistencies, "filing_type_count_mismatch")

    as_of = coverage.get("as_of")

    if not isinstance(as_of, str) or not as_of.strip():
        _append_unique(inconsistencies, "missing_as_of")
    else:
        try:
            datetime.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            _append_unique(inconsistencies, "malformed_as_of")

    state = {
        "schema_version": COVERAGE_STATE_VERSION,
        "scope": {
            "expected_forms": expected_forms,
            "date_from": date_from,
            "date_to": date_to,
            "days": days,
        },
        "enumeration": {
            "result_level": response.get("result_level"),
            "count": count,
            "total_count": total_count,
            "has_more": response.get("has_more"),
            "coverage_complete": coverage.get("complete"),
            "as_of": as_of,
            "accession_count": accession_count,
            "by_filing_type": by_filing_type,
            "issues": issues,
        },
        "accessions": accessions,
        "filers": filers,
        "broad_surfaced": [],
        "individually_checked": {},
        "failed": {},
        "unexpected": [],
        "identity_issues": inconsistencies,
    }
    return state


def _contains_capability_url(value):
    if isinstance(value, str):
        return CAPABILITY_URL_FRAGMENT in value.lower()

    if isinstance(value, dict):
        return any(
            _contains_capability_url(key) or _contains_capability_url(item)
            for key, item in value.items()
        )

    if isinstance(value, list):
        return any(_contains_capability_url(item) for item in value)

    return False


def _write_state(path, state):
    if _contains_capability_url(state):
        raise HelperError("Capability URLs cannot be written to coverage state.")

    body = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _write_atomic(path, body)


def _load_state(path):
    state = _load_json_value(path)

    if not isinstance(state, dict) or state.get("schema_version") != COVERAGE_STATE_VERSION:
        raise HelperError("The coverage state is missing or has an unsupported schema version.")

    required_objects = ("scope", "enumeration", "accessions", "filers")

    if any(not isinstance(state.get(key), dict) for key in required_objects):
        raise HelperError("The coverage state is malformed.")

    for key in ("broad_surfaced", "unexpected", "identity_issues"):
        if not isinstance(state.get(key), list):
            raise HelperError("The coverage state is malformed.")

    for key in ("individually_checked", "failed"):
        if not isinstance(state.get(key), dict):
            raise HelperError("The coverage state is malformed.")

    return state


def _alias_map(state):
    aliases = {}

    for cik, filer in state["filers"].items():
        for value in filer.get("tickers") or []:
            ticker = _qualified_ticker(value)

            if ticker:
                aliases.setdefault(ticker.upper(), set()).add(cik)

    return aliases


def add_broad_search_results(state, results):
    """Record expected filers surfaced by one broad filing search artifact."""
    aliases = _alias_map(state)
    surfaced = set(state["broad_surfaced"])
    added = set()

    for result in results:
        source_cik, _accession = _cik_and_accession(result)
        ticker = _qualified_ticker(result.get("ticker"))
        ticker_ciks = aliases.get(ticker.upper(), set()) if ticker else set()
        matched_cik = None

        if source_cik in state["filers"]:
            if ticker_ciks and source_cik not in ticker_ciks:
                _append_unique(state["identity_issues"], "search_identity_conflict")
                continue

            if ticker and not ticker_ciks:
                filer = state["filers"][source_cik]
                filer["tickers"].append(ticker)

                if filer.get("search_ticker") is None:
                    filer["search_ticker"] = ticker

                aliases.setdefault(ticker.upper(), set()).add(source_cik)
            matched_cik = source_cik

        elif source_cik and ticker_ciks:
            _append_unique(state["identity_issues"], "search_identity_conflict")
            continue

        elif len(ticker_ciks) == 1:
            matched_cik = next(iter(ticker_ciks))

        elif len(ticker_ciks) > 1:
            _append_unique(state["identity_issues"], "ambiguous_ticker_alias")
            continue

        if matched_cik:
            surfaced.add(matched_cik)
            added.add(matched_cik)
        else:
            unexpected = {
                "cik": source_cik,
                "ticker": ticker,
            }

            if unexpected not in state["unexpected"]:
                state["unexpected"].append(unexpected)

    state["broad_surfaced"] = sorted(surfaced)
    return len(added)


def _missing_ciks(state):
    expected = set(state["filers"])
    surfaced = set(state["broad_surfaced"])
    checked = set(state["individually_checked"])
    return sorted(expected - surfaced - checked)


def missing_filers(state, *, offset=0, limit=MAX_COVERAGE_ROWS):
    """Return one bounded page of filers still requiring scoped search."""
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), MAX_COVERAGE_ROWS))
    missing = _missing_ciks(state)
    shown = []

    for cik in missing[offset : offset + limit]:
        filer = state["filers"][cik]
        shown.append(
            {
                "cik": cik,
                "ticker": filer.get("search_ticker"),
                "ticker_aliases": filer.get("tickers") or [],
                "accession_count": len(filer.get("accessions") or []),
            }
        )

    return {
        "missing_filer_count": len(missing),
        "offset": offset,
        "shown_count": len(shown),
        "remaining_count": max(0, len(missing) - offset - len(shown)),
        "missing": shown,
    }


def _resolve_state_ticker(state, value):
    ticker = _qualified_ticker(value)

    if ticker is None:
        raise HelperError("--ticker must be an exchange-qualified ticker from coverage-missing.")

    matches = _alias_map(state).get(ticker.upper(), set())

    if len(matches) != 1:
        raise HelperError("The ticker does not resolve to exactly one enumerated filer.")

    return ticker, next(iter(matches))


def mark_filer(state, ticker_value, status, reason=None):
    """Record one completed or failed ticker-scoped follow-up."""
    ticker, cik = _resolve_state_ticker(state, ticker_value)

    if status == "checked":
        state["individually_checked"][cik] = {"ticker": ticker}
        state["failed"].pop(cik, None)
    else:
        reason = str(reason or "unspecified").strip().lower()

        if not FAILURE_REASON_RE.fullmatch(reason):
            raise HelperError(
                "--reason must be a short lowercase issue code using letters, numbers, "
                "underscores, or hyphens."
            )

        if cik not in state["individually_checked"]:
            state["failed"][cik] = {"ticker": ticker, "reason": reason}

    return cik


def coverage_audit(state):
    """Return a compact coverage audit and whether every expected filer was checked."""
    enumeration = state["enumeration"]
    scope = state["scope"]
    inconsistencies = list(dict.fromkeys(state["identity_issues"]))
    accession_count = len(state["accessions"])

    if enumeration.get("result_level") != "accession":
        _append_unique(inconsistencies, "invalid_result_level")

    if enumeration.get("coverage_complete") is not True:
        _append_unique(inconsistencies, "enumeration_incomplete")

    if enumeration.get("issues"):
        _append_unique(inconsistencies, "coverage_issues_present")

    if enumeration.get("has_more") is not False:
        _append_unique(inconsistencies, "enumeration_has_more")

    if enumeration.get("count") != accession_count:
        _append_unique(inconsistencies, "returned_count_mismatch")

    if enumeration.get("total_count") != accession_count:
        _append_unique(inconsistencies, "total_count_mismatch")

    if enumeration.get("accession_count") != accession_count:
        _append_unique(inconsistencies, "accession_count_mismatch")

    if scope.get("days") not in (1, 2, 3):
        _append_unique(inconsistencies, "unsupported_date_window")

    unsearchable = sorted(
        cik
        for cik, filer in state["filers"].items()
        if _qualified_ticker(filer.get("search_ticker")) is None
    )
    missing = _missing_ciks(state)
    failed = sorted(state["failed"])
    complete = not inconsistencies and not unsearchable and not missing and not failed
    output = {
        "complete": complete,
        "as_of": enumeration.get("as_of"),
        "selected_forms": scope.get("expected_forms") or [],
        "date_from": scope.get("date_from"),
        "date_to": scope.get("date_to"),
        "accession_count": accession_count,
        "filer_count": len(state["filers"]),
        "broad_search_filer_count": len(set(state["broad_surfaced"])),
        "individually_checked_filer_count": len(state["individually_checked"]),
        "failed_filer_count": len(failed),
        "unsearchable_filer_count": len(unsearchable),
        "unpolled_filer_count": len(missing),
        "coverage_issues": enumeration.get("issues") or [],
        "inconsistencies": inconsistencies,
    }
    return output


def _argument_parser():
    parser = argparse.ArgumentParser(
        description="Process DFin filing artifacts without emitting full results."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize")
    source = summarize.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact", type=Path)
    source.add_argument(
        "--fetch",
        action="store_true",
        help="Read one capability URL from stdin and download it.",
    )
    summarize.add_argument("--save", type=Path)
    summarize.add_argument("--limit", type=int, default=MAX_SUMMARIES)
    summarize.add_argument("--offset", type=int, default=0)
    summarize.add_argument(
        "--preview-chars",
        type=int,
        default=DEFAULT_PREVIEW_CHARS,
    )

    select = subparsers.add_parser("select")
    select.add_argument("--artifact", type=Path, required=True)
    select.add_argument("--bundle", action="append", required=True)
    select.add_argument(
        "--evidence-chars",
        type=int,
        default=DEFAULT_EVIDENCE_CHARS,
    )

    coverage_init = subparsers.add_parser("coverage-init")
    coverage_init.add_argument("--state", type=Path, required=True)
    coverage_init.add_argument("--expected-form", action="append", required=True)
    coverage_source = coverage_init.add_mutually_exclusive_group(required=True)
    coverage_source.add_argument("--artifact", type=Path)
    coverage_source.add_argument(
        "--fetch",
        action="store_true",
        help="Read one enumeration capability URL from stdin and download it.",
    )

    coverage_add_search = subparsers.add_parser("coverage-add-search")
    coverage_add_search.add_argument("--state", type=Path, required=True)
    coverage_add_search.add_argument("--artifact", type=Path, required=True)

    coverage_missing = subparsers.add_parser("coverage-missing")
    coverage_missing.add_argument("--state", type=Path, required=True)
    coverage_missing.add_argument("--limit", type=int, default=MAX_COVERAGE_ROWS)
    coverage_missing.add_argument("--offset", type=int, default=0)

    coverage_mark = subparsers.add_parser("coverage-mark")
    coverage_mark.add_argument("--state", type=Path, required=True)
    coverage_mark.add_argument("--ticker", required=True)
    coverage_mark.add_argument("--status", choices=("checked", "failed"), required=True)
    coverage_mark.add_argument("--reason")

    coverage_audit_parser = subparsers.add_parser("coverage-audit")
    coverage_audit_parser.add_argument("--state", type=Path, required=True)
    return parser


def main(argv=None):
    """Run the helper and emit exactly one compact JSON value."""
    parser = _argument_parser()

    try:
        arguments = parser.parse_args(argv)

        exit_code = 0

        if arguments.command == "summarize":
            artifact_path = arguments.artifact

            if arguments.fetch:
                if arguments.save is None:
                    raise HelperError("--save is required with --fetch.")

                url = sys.stdin.read().strip()
                body = fetch_artifact_bytes(url)
                _write_atomic(arguments.save, body)
                artifact_path = arguments.save
            elif arguments.save is not None:
                raise HelperError("--save is accepted only with --fetch.")

            results = load_artifact(artifact_path)
            bundle_count = len(group_results(results))
            shown = summarize_bundles(
                results,
                limit=arguments.limit,
                offset=arguments.offset,
                preview_chars=arguments.preview_chars,
            )
            normalized_offset = max(0, arguments.offset)
            remaining = max(0, bundle_count - normalized_offset - len(shown))
            output = {
                "bundle_count": bundle_count,
                "offset": normalized_offset,
                "shown_count": len(shown),
                "remaining_bundle_count": remaining,
                "truncated": remaining > 0,
                "shown": shown,
            }
        elif arguments.command == "select":
            results = load_artifact(arguments.artifact)
            output = {
                "selected": select_bundles(
                    results,
                    arguments.bundle,
                    evidence_chars=arguments.evidence_chars,
                )
            }

        elif arguments.command == "coverage-init":
            expected_forms = _normalized_expected_forms(arguments.expected_form)

            if arguments.fetch:
                url = sys.stdin.read().strip()
                body = fetch_artifact_bytes(url)

                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise HelperError(
                        "The downloaded enumeration artifact is not valid UTF-8 JSON."
                    ) from exc
            else:
                payload = _load_json_value(arguments.artifact)

            state = _enumeration_state(payload, expected_forms)
            _write_state(arguments.state, state)
            output = {
                "enumeration_complete": state["enumeration"]["coverage_complete"],
                "as_of": state["enumeration"]["as_of"],
                "selected_forms": state["scope"]["expected_forms"],
                "accession_count": len(state["accessions"]),
                "filer_count": len(state["filers"]),
                "missing_filer_count": len(_missing_ciks(state)),
                "coverage_issues": state["enumeration"]["issues"],
                "inconsistencies": state["identity_issues"],
            }

        elif arguments.command == "coverage-add-search":
            state = _load_state(arguments.state)
            results = load_artifact(arguments.artifact)
            added_count = add_broad_search_results(state, results)
            _write_state(arguments.state, state)
            output = {
                "added_filer_count": added_count,
                "broad_search_filer_count": len(state["broad_surfaced"]),
                "missing_filer_count": len(_missing_ciks(state)),
                "unexpected_filer_count": len(state["unexpected"]),
                "identity_issues": state["identity_issues"],
            }

        elif arguments.command == "coverage-missing":
            state = _load_state(arguments.state)
            output = missing_filers(
                state,
                offset=arguments.offset,
                limit=arguments.limit,
            )

        elif arguments.command == "coverage-mark":
            state = _load_state(arguments.state)
            cik = mark_filer(
                state,
                arguments.ticker,
                arguments.status,
                arguments.reason,
            )
            _write_state(arguments.state, state)
            output = {
                "cik": cik,
                "ticker": arguments.ticker,
                "status": (
                    "checked"
                    if cik in state["individually_checked"]
                    else "failed"
                ),
                "missing_filer_count": len(_missing_ciks(state)),
                "failed_filer_count": len(state["failed"]),
            }

        else:
            state = _load_state(arguments.state)
            output = coverage_audit(state)
            exit_code = 0 if output["complete"] else 3

        json.dump(output, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
        return exit_code
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Hint: keep capability URLs private and verify the requested artifact, "
            "coverage state, and command arguments.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
