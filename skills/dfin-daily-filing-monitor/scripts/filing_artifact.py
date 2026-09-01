#!/usr/bin/env python3
"""Fetch, summarize, and select evidence from DFin filing artifacts."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
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
ACCESSION_COMPACT_RE = re.compile(r"^[0-9]{18}$")
FAILURE_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
FORM_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9 /-]{0,49}$")
CAPABILITY_URL_RE = re.compile(
    r"www\.dfin\.pro(?::(?:0*443)?)?/api/v1/artifacts/",
    re.IGNORECASE,
)
DEFAULT_PREVIEW_CHARS = 220
DEFAULT_EVIDENCE_CHARS = 800
MAX_SUMMARIES = 15
MAX_DOC_UUIDS = 20
MAX_COVERAGE_ROWS = 50
DEFAULT_COVERAGE_ISSUES = 25
COVERAGE_STATE_VERSION = 4
SUMMARY_INDEX_VERSION = 2
SUMMARY_INDEX_SUFFIX = ".summary-index.json"
FILING_CENSUS_ARTIFACT_SCHEMA_VERSION = 2
FILING_BUNDLE_ID_RE = re.compile(r"^filing:[0-9a-f]{24}$")
FILING_BUNDLE_CLASSIFICATIONS = frozenset({"confirmed", "flagged", "excluded"})
CANDIDATE_ISSUE_REASONS = frozenset(
    {
        "filing_date_outside_window",
        "malformed_filing_date",
        "malformed_filing_type",
        "issuer_outside_census",
        "issuer_identity_conflict",
        "missing_companion_accession",
        "ticker_identity_conflict",
        "filing_metadata_conflict",
        "unresolved_filing_identity",
    }
)
CANDIDATE_ISSUE_FIELDS = frozenset(
    {"accession", "cik", "filing_date", "filing_type", "ticker"}
)
HARMLESS_CANDIDATE_ISSUE_REASONS = frozenset(
    {"filing_date_outside_window", "issuer_outside_census"}
)
CANDIDATE_ISSUE_EXPECTATIONS = {
    "filing_date_outside_window": "an ISO-8601 filing date within the requested window",
    "malformed_filing_date": "an ISO-8601 filing date within the requested window",
    "malformed_filing_type": "a non-empty filing type",
    "issuer_outside_census": "an issuer in the eligible filing set",
    "issuer_identity_conflict": "CIK and accession metadata that match the eligible filing set",
    "missing_companion_accession": "a valid SEC accession for the companion filing",
    "ticker_identity_conflict": "a ticker associated with the identified issuer",
    "filing_metadata_conflict": "filing metadata that matches the SEC accession",
    "unresolved_filing_identity": "a CIK, ticker, or accession that identifies an eligible filing",
}
ALLOWED_FAILURE_REASONS = frozenset(
    {
        "artifact_unavailable",
        "malformed_response",
        "rate_limited",
        "timeout",
        "unresolved_ticker",
        "coverage_unknown",
        "internal_document_unavailable",
        "internal_search_unavailable",
        "internal_and_sec_unavailable",
        "fast_batch_incomplete",
        "sec_timeout",
        "sec_rate_limited",
        "sec_unavailable",
    }
)
BROAD_FAILURE_REASONS = ALLOWED_FAILURE_REASONS - {
    "unresolved_ticker",
    "fast_batch_incomplete",
}


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
        next_step = payload.get("next")

        if isinstance(next_step, dict):
            candidates.append(next_step.get("after_seconds"))

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


def _expand_filing_bundle(value):
    """Return validated nested evidence for one server filing bundle or ``None``."""
    rv = None

    if isinstance(value, dict) and isinstance(value.get("evidence"), list):
        bundle_id = value.get("bundle_id")
        evidence = value["evidence"]

        if (
            not isinstance(bundle_id, str)
            or FILING_BUNDLE_ID_RE.fullmatch(bundle_id) is None
            or not isinstance(value.get("evidence_count"), int)
            or isinstance(value.get("evidence_count"), bool)
            or value.get("evidence_count") != len(evidence)
            or not evidence
        ):
            raise HelperError("The saved search response contains a malformed filing bundle.")

        expanded = []

        for item in evidence:
            decoded = _decode_result(item)

            if not _looks_like_result(decoded):
                raise HelperError("A filing bundle contains malformed evidence.")

            result = dict(decoded)

            for key in (
                "scan_cik",
                "accession_number",
                "ticker",
                "name",
                "filing_type",
                "filing_date",
            ):
                if result.get(key) in (None, "") and value.get(key) not in (None, ""):
                    result[key] = value[key]

            result["_filing_bundle_id"] = bundle_id
            expanded.append(result)

        rv = expanded

    return rv


def _expanded_results(values, *, strict=True, require_bundles=False):
    """Flatten server filing bundles while preserving legacy result artifacts."""
    rv = []

    for value in values:
        decoded = _decode_result(value)
        expanded = _expand_filing_bundle(decoded)

        if expanded is not None:
            rv.extend(expanded)

        elif not require_bundles and _looks_like_result(decoded):
            rv.append(decoded)

        elif strict:
            raise HelperError("The saved search response contains a malformed filing result.")

    return rv


def _filing_census_artifact_schema(payload):
    """Validate and return the optional filing-census artifact schema version."""
    schema_version = payload.get("schema_version") if isinstance(payload, dict) else None

    if (
        schema_version is not None
        and (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != FILING_CENSUS_ARTIFACT_SCHEMA_VERSION
        )
    ):
        raise HelperError("The saved search response uses an unsupported schema version.")

    return schema_version


def normalize_results(payload):
    """Return normalized result dictionaries from supported artifact shapes."""
    schema_version = _filing_census_artifact_schema(payload)

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

    return _expanded_results(
        values,
        strict=schema_version == FILING_CENSUS_ARTIFACT_SCHEMA_VERSION,
        require_bundles=schema_version == FILING_CENSUS_ARTIFACT_SCHEMA_VERSION,
    )


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


def _sec_cik_and_accession(result):
    """Return issuer CIK/accession only from a validated SEC archive source."""
    source_uri = validate_sec_url(_source_metadata(result).get("source_uri"))
    parsed_source = urlparse(source_uri) if source_uri else None
    source_paths = [parsed_source.path] if parsed_source else []

    if parsed_source and parsed_source.path.lower() in {"/ix", "/ixviewer/doc/action"}:
        source_paths.extend(parse_qs(parsed_source.query).get("doc", []))

    match = next(
        (
            matched
            for source_path in source_paths
            if (matched := SEC_SOURCE_RE.search(source_path))
        ),
        None,
    )

    if match:
        cik = _valid_cik(match.group("cik"))

        if cik is not None:
            return cik, _normalized_accession(match.group("accession"))

    return None, None


def _cik_and_accession(result):
    """Return SEC identity, with a name-derived CIK fallback for bundle grouping."""
    cik, accession = _sec_cik_and_accession(result)

    if cik:
        return cik, accession

    name_match = NAME_CIK_RE.search(str(result.get("name") or ""))
    cik = _valid_cik(name_match.group(1)) if name_match else None
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
        score = float(value)
    except (OverflowError, TypeError, ValueError):
        score = 0.0

    return score if math.isfinite(score) else 0.0


def _finite_number(value):
    """Return whether a JSON number is finite without accepting booleans."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False

    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False

    return finite


def _non_negative_integer(value):
    """Return one non-negative integer without accepting booleans."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _qualified_ticker(value):
    if not isinstance(value, str) or not value.strip():
        return None

    ticker = value.strip()
    return ticker if QUALIFIED_TICKER_RE.fullmatch(ticker.upper()) else None


def _bundle_identity(result):
    server_bundle_id = result.get("_filing_bundle_id")
    cik, accession = _cik_and_accession(result)
    doc_uuid = str(result.get("doc_uuid") or "")

    if isinstance(server_bundle_id, str) and FILING_BUNDLE_ID_RE.fullmatch(server_bundle_id):
        bundle_id = server_bundle_id
        cik = _valid_cik(result.get("scan_cik")) or cik
    elif cik and accession:
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
                "candidate_sources": [],
                "attachment_hints": [],
                "metadata_only": True,
                "_qualified_tickers": {},
                "documents": [],
                "best": None,
            }

        bundle = grouped[bundle_id]
        raw_sources = [result.get("scan_source")]
        match_sources = result.get("match_sources")

        if isinstance(match_sources, (list, tuple)):
            raw_sources.extend(match_sources)

        for raw_source in raw_sources:
            candidate_source = " ".join(str(raw_source or "").split())

            if (
                candidate_source in {"internal", "sec", "sec_fts"}
                and candidate_source not in bundle["candidate_sources"]
            ):
                bundle["candidate_sources"].append(candidate_source)

        attachment_type = " ".join(
            str(result.get("attachment_type") or "").split()
        )[:80]
        file_name = " ".join(str(result.get("file_name") or "").split())[:120]
        attachment_hint = " · ".join(
            value for value in (attachment_type, file_name) if value
        )[:160]

        if (
            attachment_hint
            and attachment_hint not in bundle["attachment_hints"]
            and len(bundle["attachment_hints"]) < 5
        ):
            bundle["attachment_hints"].append(attachment_hint)

        if result.get("evidence_status") != "metadata_only" or content.strip():
            bundle["metadata_only"] = False

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


def _summaries_from_bundles(bundles, *, preview_chars=DEFAULT_PREVIEW_CHARS):
    """Return compact model-facing metadata for already-grouped bundles."""
    preview_chars = max(40, min(int(preview_chars), DEFAULT_PREVIEW_CHARS))
    summaries = []

    for bundle in bundles:
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
                "candidate_sources": list(bundle["candidate_sources"]),
                "attachment_hints": list(bundle["attachment_hints"]),
                "metadata_only": bool(bundle["metadata_only"]),
                "source_uri": _bundle_source_uri(bundle),
                "preview": best["content"][:preview_chars],
            }
        )

    return summaries


def summarize_bundles(
    results,
    *,
    limit=MAX_SUMMARIES,
    offset=0,
    preview_chars=DEFAULT_PREVIEW_CHARS,
):
    """Return bounded model-facing summaries of the best filing bundles."""
    summaries = _summaries_from_bundles(
        group_results(results),
        preview_chars=preview_chars,
    )
    limit = max(1, min(int(limit), MAX_SUMMARIES))
    offset = max(0, int(offset))
    return summaries[offset : offset + limit]


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


def _decode_search_envelope(value):
    """Decode saved API or inline search responses without losing an empty result."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HelperError("The saved search response is not valid JSON.") from exc

    if isinstance(value, dict) and set(value) == {"text"}:
        return _decode_search_envelope(value["text"])

    if (
        isinstance(value, dict)
        and set(value) == {"result"}
        and isinstance(value["result"], (dict, list, str))
    ):
        return _decode_search_envelope(value["result"])

    if not isinstance(value, (dict, list)):
        raise HelperError("The saved search response must be a JSON object or array.")

    return value


def load_search_response(path):
    """Return decoded results plus content and canonical-path receipts."""
    path = Path(path)

    try:
        response_bytes = path.read_bytes()
        response_path = str(path.resolve(strict=True)).encode("utf-8")
        payload = json.loads(response_bytes.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise HelperError(f"Could not read the saved search response: {exc}.") from None
    except json.JSONDecodeError as exc:
        raise HelperError(
            f"Invalid saved search JSON at line {exc.lineno}, column {exc.colno}."
        ) from None

    payload = _decode_search_envelope(payload)
    schema_version = _filing_census_artifact_schema(payload)
    response_id = hashlib.sha256(response_bytes).hexdigest()
    artifact_id = hashlib.sha256(response_path).hexdigest()

    if schema_version == FILING_CENSUS_ARTIFACT_SCHEMA_VERSION and (
        not isinstance(payload, dict)
        or "count" not in payload
        or not isinstance(payload.get("results"), list)
    ):
        raise HelperError("The versioned filing artifact lacks its count or results array.")

    if isinstance(payload, list):
        raw_results = payload
        declared_count = len(raw_results)
    else:
        raw_results = payload.get("results")
        declared_count = payload.get("count")

        if raw_results is None and declared_count == 0:
            raw_results = []

        if not isinstance(raw_results, list):
            raise HelperError(
                "The saved search response must contain a results array or count=0."
            )

        if declared_count is None:
            declared_count = len(raw_results)

    if not _valid_non_negative_integer(declared_count):
        raise HelperError("The saved search response count must be a non-negative integer.")

    if declared_count != len(raw_results):
        raise HelperError("The saved search response count does not match its results.")

    results = _expanded_results(
        raw_results,
        require_bundles=schema_version == FILING_CENSUS_ARTIFACT_SCHEMA_VERSION,
    )

    return results, declared_count, response_id, artifact_id


def _query_plan(values):
    """Return one stable fingerprint for a non-empty thematic query set."""
    normalized = []

    for value in values or []:
        query = " ".join(str(value or "").split()).casefold()

        if not query or len(query) > 300:
            raise HelperError("Every --query must contain 1 to 300 characters.")

        if query not in normalized:
            normalized.append(query)

    if not 1 <= len(normalized) <= 12:
        raise HelperError("Provide between 1 and 12 distinct --query values.")

    canonical = sorted(normalized)
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"query_count": len(canonical), "query_hash": digest}


def _bind_query_plan(state, values):
    """Require every broad and ticker search to use the same thematic queries."""
    plan = _query_plan(values)
    existing = state.get("search_plan")

    if existing is None:
        state["search_plan"] = plan
    elif existing != plan:
        raise HelperError(
            "The search queries do not match the thematic query set already recorded."
        )

    return plan


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
    return text.zfill(10) if CIK_RE.fullmatch(text) and int(text) > 0 else None


def _normalized_accession(value):
    text = str(value or "").strip()

    if ACCESSION_RE.fullmatch(text):
        return text

    if ACCESSION_COMPACT_RE.fullmatch(text):
        return f"{text[:10]}-{text[10:12]}-{text[12:]}"

    return None


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
    observed_by_filing_type = {}

    for row in results:
        if not isinstance(row, dict):
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        accession = _normalized_accession(row.get("accession_number"))
        cik = _valid_cik(row.get("cik"))
        filing_type = " ".join(str(row.get("filing_type") or "").split()).upper()
        filing_date = str(row.get("filing_date") or "").strip()

        issuer_rows = row.get("issuers")

        if issuer_rows is None:
            issuer_rows = [{
                "cik": cik,
                "issuer_name": str(row.get("issuer_name") or ""),
                "tickers": row.get("tickers") if isinstance(row.get("tickers"), list) else [],
            }]

        issuers = []

        if isinstance(issuer_rows, list):
            for issuer in issuer_rows:
                issuer_cik = _valid_cik(issuer.get("cik")) if isinstance(issuer, dict) else None
                issuer_name = issuer.get("issuer_name") if isinstance(issuer, dict) else None
                issuer_tickers = issuer.get("tickers") if isinstance(issuer, dict) else None

                if (
                    issuer_cik is None
                    or not isinstance(issuer_name, str)
                    or not isinstance(issuer_tickers, list)
                ):
                    _append_unique(inconsistencies, "malformed_issuer_association")
                    continue

                issuers.append({
                    "cik": issuer_cik,
                    "issuer_name": issuer_name,
                    "tickers": issuer_tickers,
                })

        if accession is None or cik is None or not filing_type or not issuers:
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        issuers_by_cik = {issuer["cik"]: issuer for issuer in issuers}

        if cik not in issuers_by_cik:
            _append_unique(inconsistencies, "conflicting_accession_identity")
            continue

        try:
            parsed_filing_date = datetime.date.fromisoformat(filing_date)
        except ValueError:
            _append_unique(inconsistencies, "malformed_accession_row")
            continue

        if not window_start <= parsed_filing_date <= window_end:
            _append_unique(inconsistencies, "accession_outside_window")
            continue

        if not any(filing_type.startswith(form) for form in expected_forms):
            _append_unique(inconsistencies, "unexpected_filing_type")
            continue

        existing_accession = accessions.get(accession)
        accession_record = {
            "cik": cik,
            "issuer_ciks": sorted(issuers_by_cik),
            "filing_type": filing_type,
            "filing_date": filing_date,
        }

        if existing_accession is not None:
            if existing_accession != accession_record:
                _append_unique(inconsistencies, "conflicting_accession_identity")
            continue

        accessions[accession] = accession_record
        observed_by_filing_type[filing_type] = (
            observed_by_filing_type.get(filing_type, 0) + 1
        )
        for issuer_cik in sorted(issuers_by_cik):
            issuer = issuers_by_cik[issuer_cik]
            filer = filers.setdefault(
                issuer_cik,
                {
                    "cik": issuer_cik,
                    "issuer_name": issuer["issuer_name"],
                    "tickers": [],
                    "search_ticker": None,
                    "census_tickers": [],
                    "census_search_ticker": None,
                    "accessions": [],
                    "filing_types": [],
                    "filing_dates": [],
                },
            )
            _append_unique(filer["accessions"], accession)
            _append_unique(filer["filing_types"], filing_type)
            _append_unique(filer["filing_dates"], filing_date)
            tickers = issuer["tickers"]

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

    for filer in filers.values():
        filer["census_tickers"] = list(filer["tickers"])
        filer["census_search_ticker"] = filer["search_ticker"]

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

    if by_filing_type != dict(sorted(observed_by_filing_type.items())):
        _append_unique(inconsistencies, "filing_type_population_mismatch")

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
        "search_plan": None,
        "broad_searches": {},
        "broad_failures": {},
        "consumed_responses": {},
        "consumed_artifacts": {},
        "broad_surfaced": [],
        "individually_checked": {},
        "joint_satisfied": {},
        "failed": {},
        "server_checked": {},
        "server_not_checked": {},
        "server_incomplete": {},
        "server_scan": None,
        "bundle_classifications": {},
        "unexpected": [],
        "unexpected_accessions": [],
        "included_companions": {},
        "excluded_post_census": {},
        "candidate_issues": [],
        "census_identity_issues": list(inconsistencies),
        "identity_issues": inconsistencies,
    }
    state["census_fingerprint"] = _census_fingerprint(state)
    return state


def _census_fingerprint(state):
    """Return a stable fingerprint for the immutable census population and scope."""
    payload = {
        "scope": state.get("scope"),
        "enumeration": state.get("enumeration"),
        "accessions": state.get("accessions"),
        "filers": {
            cik: {
                "accessions": filer.get("accessions"),
                "census_tickers": filer.get("census_tickers"),
                "census_search_ticker": filer.get("census_search_ticker"),
            }
            for cik, filer in sorted((state.get("filers") or {}).items())
        },
        "census_identity_issues": state.get("census_identity_issues"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _server_census_fingerprint(state):
    """Return the census-scope fingerprint used by search_filing_census."""
    payload = {
        "accessions": sorted(
            [
                {
                    "accession_number": accession,
                    "ciks": record.get("issuer_ciks", [record.get("cik")]),
                    "filing_type": record.get("filing_type"),
                    "filing_date": record.get("filing_date"),
                }
                for accession, record in state["accessions"].items()
            ],
            key=lambda item: item["accession_number"],
        ),
        "date_from": state["scope"]["date_from"],
        "date_to": state["scope"]["date_to"],
        "filing_types": state["scope"]["expected_forms"],
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _server_query_hash(queries, results_per_query):
    """Return the exact query binding used by search_filing_census."""
    payload = {
        "queries": queries,
        "results_per_query": results_per_query,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _valid_server_scan(state):
    """Return whether a server-bound receipt matches the immutable local census."""
    scan = state.get("server_scan")
    rv = scan is None

    if isinstance(scan, dict):
        outcomes = scan.get("outcomes")
        checked = state.get("server_checked")
        not_checked = state.get("server_not_checked")
        incomplete = state.get("server_incomplete")
        failed = state.get("failed")
        known_ciks = set(state.get("filers") or {})
        mode = scan.get("mode")
        valid_outcomes = isinstance(outcomes, list) and len(outcomes) == len(known_ciks)
        outcome_ciks = set()

        for outcome in outcomes or []:
            cik = _valid_cik(outcome.get("cik")) if isinstance(outcome, dict) else None
            coverage_state = outcome.get("coverage_state") if isinstance(outcome, dict) else None
            source = outcome.get("source") if isinstance(outcome, dict) else None
            status = outcome.get("status") if isinstance(outcome, dict) else None
            reason = outcome.get("reason") if isinstance(outcome, dict) else None
            allowed_sources = (
                {"internal", "sec_fts", "mixed", "none"}
                if mode == "fast"
                else {"internal", "sec", "mixed", "none"}
            )
            route_sources = (
                allowed_sources
                if coverage_state == "covered"
                else {"internal", "sec_fts", "mixed", "none"}
                if mode == "fast"
                else allowed_sources
            )
            valid_route = coverage_state in {
                "covered",
                "uncovered",
                "coverage_unknown",
            } and source in route_sources and (
                (status == "failed" and source in {"internal", "sec", "mixed", "none"})
                or (
                    status == "incomplete"
                    and source in allowed_sources
                )
                or (
                    status in {"checked_hit", "checked_empty"}
                    and source in allowed_sources - {"none"}
                )
                or (status == "not_checked" and mode == "fast")
            )
            valid_outcomes = valid_outcomes and (
                cik in known_ciks
                and cik not in outcome_ciks
                and valid_route
                and status in {
                    "checked_hit",
                    "checked_empty",
                    "not_checked",
                    "incomplete",
                    "failed",
                }
                and (
                    (status in {"checked_hit", "checked_empty"} and reason is None)
                    or (
                        status == "not_checked"
                        and reason == "not_available_in_local_index"
                    )
                    or (status == "incomplete" and reason == "fast_batch_incomplete")
                    or (status == "failed" and reason in ALLOWED_FAILURE_REASONS)
                )
            )

            if cik:
                outcome_ciks.add(cik)

        checked_count = sum(
            outcome.get("status") in {"checked_hit", "checked_empty"}
            for outcome in outcomes or []
            if isinstance(outcome, dict)
        )
        failed_count = sum(
            outcome.get("status") == "failed"
            for outcome in outcomes or []
            if isinstance(outcome, dict)
        )
        not_checked_count = sum(
            outcome.get("status") == "not_checked"
            for outcome in outcomes or []
            if isinstance(outcome, dict)
        )
        incomplete_count = sum(
            outcome.get("status") == "incomplete"
            for outcome in outcomes or []
            if isinstance(outcome, dict)
        )
        expected_checked = {
            outcome["cik"]
            for outcome in outcomes or []
            if isinstance(outcome, dict)
            and outcome.get("status") in {"checked_hit", "checked_empty"}
        }
        expected_failed = {
            outcome["cik"]
            for outcome in outcomes or []
            if isinstance(outcome, dict) and outcome.get("status") == "failed"
        }
        expected_not_checked = {
            outcome["cik"]
            for outcome in outcomes or []
            if isinstance(outcome, dict) and outcome.get("status") == "not_checked"
        }
        expected_incomplete = {
            outcome["cik"]
            for outcome in outcomes or []
            if isinstance(outcome, dict) and outcome.get("status") == "incomplete"
        }
        checked_hit = sum(
            isinstance(outcome, dict) and outcome.get("status") == "checked_hit"
            for outcome in outcomes or []
        )
        checked_empty = checked_count - checked_hit
        expected_complete = (
            state["enumeration"].get("coverage_complete") is True
            and failed_count == 0
            and not_checked_count == 0
            and incomplete_count == 0
            and checked_count == len(known_ciks)
        )
        bundle_ids = scan.get("bundle_ids")
        discarded_out_of_window_bundle_count = scan.get(
            "discarded_out_of_window_bundle_count"
        )
        valid_bundle_ids = bundle_ids is None or (
            isinstance(bundle_ids, list)
            and len(bundle_ids) == len(set(bundle_ids))
            and all(
                isinstance(bundle_id, str)
                and FILING_BUNDLE_ID_RE.fullmatch(bundle_id) is not None
                for bundle_id in bundle_ids
            )
            and (
                len(bundle_ids) == scan.get("result_count")
                if discarded_out_of_window_bundle_count is None
                else (
                    _valid_non_negative_integer(discarded_out_of_window_bundle_count)
                    and len(bundle_ids) + discarded_out_of_window_bundle_count
                    == scan.get("result_count")
                )
            )
        )
        rv = (
            valid_outcomes
            and valid_bundle_ids
            and outcome_ciks == known_ciks
            and scan.get("request_binding") == "server_bound"
            and scan.get("census_fingerprint") == _server_census_fingerprint(state)
            and _valid_query_receipt(scan)
            and _valid_response_id(scan.get("response_id"))
            and _valid_response_id(scan.get("artifact_id"))
            and _valid_non_negative_integer(scan.get("result_count"))
            and scan.get("total_filers") == len(known_ciks)
            and scan.get("checked_count") == checked_count
            and scan.get("failed_count") == failed_count
            and scan.get("not_checked_count") == not_checked_count
            and scan.get("not_checked") == not_checked_count
            and scan.get("checked") == checked_count
            and scan.get("failed") == failed_count
            and scan.get("incomplete_count") == incomplete_count
            and scan.get("incomplete") == incomplete_count
            and scan.get("checked_hit") == checked_hit
            and scan.get("checked_empty") == checked_empty
            and isinstance(scan.get("results_complete"), bool)
            and _valid_non_negative_integer(scan.get("delivered_result_count"))
            and _valid_non_negative_integer(scan.get("omitted_result_count"))
            and scan.get("result_count") == scan.get("delivered_result_count")
            and scan.get("results_complete") is (scan.get("omitted_result_count") == 0)
            and scan.get("complete") is expected_complete
            and scan.get("census_complete") is state["enumeration"].get("coverage_complete")
            and scan.get("census_issues") == state["enumeration"].get("issues")
            and _valid_recovery_receipt(scan, state)
            and checked_count + not_checked_count + failed_count + incomplete_count
            == len(known_ciks)
            and set(checked) == expected_checked
            and set(not_checked) == expected_not_checked
            and set(failed) == expected_failed
            and set(incomplete) == expected_incomplete
        )

    return rv


def _contains_capability_url(value):
    if isinstance(value, str):
        return CAPABILITY_URL_RE.search(value) is not None

    if isinstance(value, dict):
        return any(
            _contains_capability_url(key) or _contains_capability_url(item)
            for key, item in value.items()
        )

    if isinstance(value, list):
        return any(_contains_capability_url(item) for item in value)

    return False


def _valid_query_receipt(value):
    return (
        isinstance(value, dict)
        and set(value) >= {"query_count", "query_hash"}
        and isinstance(value.get("query_count"), int)
        and not isinstance(value.get("query_count"), bool)
        and 1 <= value["query_count"] <= 12
        and isinstance(value.get("query_hash"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["query_hash"]) is not None
    )


def _valid_recovery_issue(issue, state):
    """Return whether one sanitized recovery issue belongs to the frozen census."""
    required_keys = {
        "accession_number",
        "ciks",
        "filing_type",
        "filing_date",
        "dfin_gap_reason",
        "failure_code",
        "attempts",
        "retryable",
        "recommended_action",
    }
    optional_keys = {
        "attachment_document_type",
        "attachment_filename",
        "attachment_extension",
        "response_content_type",
        "size_category",
        "observed_bytes",
        "configured_limit_bytes",
        "observed_count",
        "configured_limit_count",
        "document_rows",
        "non_html_document_rows",
    }
    valid = isinstance(issue, dict) and required_keys <= set(issue) <= required_keys | optional_keys
    accession = _normalized_accession(issue.get("accession_number")) if valid else None
    census_record = state.get("accessions", {}).get(accession) if accession else None
    normalized_ciks = [
        _valid_cik(cik) for cik in issue.get("ciks", [])
    ] if valid and isinstance(issue.get("ciks"), list) else []
    expected_ciks = sorted((census_record or {}).get("issuer_ciks") or [])
    filename = issue.get("attachment_filename") if valid else None
    extension = issue.get("attachment_extension") if valid else None
    response_content_type = issue.get("response_content_type") if valid else None
    document_type = issue.get("attachment_document_type") if valid else None
    size_category = issue.get("size_category") if valid else None
    valid = bool(
        valid
        and accession == issue.get("accession_number")
        and isinstance(census_record, dict)
        and normalized_ciks
        and None not in normalized_ciks
        and len(set(normalized_ciks)) == len(normalized_ciks)
        and sorted(normalized_ciks) == expected_ciks
        and isinstance(issue.get("filing_type"), str)
        and issue.get("filing_type") == census_record.get("filing_type")
        and isinstance(issue.get("filing_date"), str)
        and issue.get("filing_date") == census_record.get("filing_date")
        and FAILURE_REASON_RE.fullmatch(str(issue.get("dfin_gap_reason") or ""))
        and FAILURE_REASON_RE.fullmatch(str(issue.get("failure_code") or ""))
        and isinstance(issue.get("attempts"), int)
        and not isinstance(issue.get("attempts"), bool)
        and issue.get("attempts") >= 1
        and isinstance(issue.get("retryable"), bool)
        and issue.get("recommended_action")
        in {"retry_later", "inspect_filing_attachments", "inspect_filing_metadata"}
        and (
            filename is None
            or isinstance(filename, str)
            and 0 < len(filename) <= 255
            and "/" not in filename
            and "\\" not in filename
            and not any(ord(character) < 32 or ord(character) == 127 for character in filename)
        )
        and (
            extension is None
            or isinstance(extension, str)
            and re.fullmatch(r"\.[a-z0-9]{1,19}", extension) is not None
        )
        and (
            response_content_type is None
            or isinstance(response_content_type, str)
            and 0 < len(response_content_type) <= 120
        )
        and (
            document_type is None
            or isinstance(document_type, str)
            and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", document_type) is not None
        )
        and (
            size_category is None
            or isinstance(size_category, str)
            and FAILURE_REASON_RE.fullmatch(size_category) is not None
        )
        and all(
            _valid_non_negative_integer(issue.get(field_name))
            for field_name in (
                "observed_bytes",
                "configured_limit_bytes",
                "observed_count",
                "configured_limit_count",
                "document_rows",
                "non_html_document_rows",
            )
            if field_name in issue
        )
    )

    return valid


def _valid_search_issue(issue, query_count):
    """Return whether one bounded SEC FTS query issue is structurally safe."""
    required_keys = {
        "query_index",
        "status",
        "failure_code",
        "retryable",
        "truncated",
        "pages_completed",
        "raw_hits_examined",
    }
    valid = isinstance(issue, dict) and set(issue) == required_keys

    if valid:
        query_index = issue.get("query_index")
        valid = bool(
            isinstance(query_index, int)
            and not isinstance(query_index, bool)
            and 0 <= query_index < query_count
            and issue.get("status")
            in {"complete", "truncated", "failed", "partial", "skipped"}
            and FAILURE_REASON_RE.fullmatch(str(issue.get("failure_code") or ""))
            and isinstance(issue.get("retryable"), bool)
            and isinstance(issue.get("truncated"), bool)
            and _valid_non_negative_integer(issue.get("pages_completed"))
            and _valid_non_negative_integer(issue.get("raw_hits_examined"))
        )

    return valid


def _valid_sec_fts_receipt(value, query_count):
    """Return whether one compact fast-mode SEC FTS summary is self-consistent."""
    required_keys = {
        "search_status",
        "index_freshness",
        "queries_total",
        "queries_completed",
        "queries_failed",
        "queries_truncated",
        "pages_completed",
        "raw_hits_examined",
        "in_census_candidates",
        "retained_candidates",
        "locator_failures",
        "discarded_hits",
    }
    optional_keys = {"limitation"}
    discarded_keys = {
        "outside_frozen_census",
        "non_html_attachments",
        "metadata_conflicts",
        "unsafe_metadata",
    }
    discarded = value.get("discarded_hits") if isinstance(value, dict) else None
    valid = bool(
        isinstance(value, dict)
        and required_keys <= set(value) <= required_keys | optional_keys
        and value.get("search_status")
        in {"skipped", "complete", "partial", "unavailable"}
        and value.get("index_freshness") == "not_guaranteed"
        and all(
            _valid_non_negative_integer(value.get(field_name))
            for field_name in required_keys - {
                "search_status",
                "index_freshness",
                "discarded_hits",
            }
        )
        and value.get("queries_total") == query_count
        and value.get("queries_completed") + value.get("queries_failed")
        == query_count
        and value.get("queries_truncated") <= value.get("queries_completed")
        and isinstance(discarded, dict)
        and set(discarded) == discarded_keys
        and all(_valid_non_negative_integer(count) for count in discarded.values())
        and (
            "limitation" not in value
            or FAILURE_REASON_RE.fullmatch(str(value.get("limitation") or ""))
        )
    )

    return valid


def _valid_recovery_scope(value):
    """Return whether HTML recovery scope is bounded and internally consistent."""
    counter_keys = {
        "indexes_read",
        "html_documents_selected",
        "non_html_document_rows_skipped",
        "data_file_rows_skipped",
    }
    valid = bool(
        isinstance(value, dict)
        and set(value) == {"policy", *counter_keys}
        and value.get("policy") == "sec_document_format_html"
        and all(
            _valid_non_negative_integer(value.get(field_name))
            for field_name in counter_keys
        )
    )

    return valid


def _valid_recovery_receipt(value, state, query_count=None):
    """Return whether exact SEC recovery and delivery counters are self-consistent."""
    integer_fields = (
        "exact_accessions_queued",
        "exact_accessions_completed",
        "exact_accessions_retrying",
        "exact_accessions_recovered",
        "exact_accessions_failed",
        "expected_ingestion_delays",
        "unexpected_internal_gaps",
        "unknown_age_gaps",
        "candidate_filer_count",
        "candidate_count",
        "not_checked_count",
        "total_filers",
        "delivered_result_count",
        "omitted_result_count",
    )
    valid_integers = all(
        _valid_non_negative_integer(value.get(field_name))
        for field_name in integer_fields
    )
    internal_failures = value.get("internal_failure_categories")
    recovery_failures = value.get("sec_recovery_failure_categories")
    recovery_issues = value.get("recovery_issues")
    recovery_scope = value.get("recovery_scope")
    search_issues = value.get("search_issues")
    failed_outcome_ciks = {
        outcome.get("cik")
        for outcome in value.get("outcomes") or []
        if isinstance(outcome, dict) and outcome.get("status") == "failed"
    }
    mode = value.get("mode")

    if query_count is None:
        query_count = (state.get("search_plan") or {}).get("query_count")

    if not isinstance(query_count, int) or isinstance(query_count, bool):
        query_count = 0

    sec_fts = value.get("sec_fts")
    sources = value.get("sources")
    expected_source_keys = (
        {"internal", "sec", "sec_fts", "mixed", "none"}
        if mode == "fast"
        else {"internal", "sec", "mixed", "none"}
    )
    source_counts = {
        source: sum(
            isinstance(outcome, dict) and outcome.get("source") == source
            for outcome in value.get("outcomes") or []
        )
        for source in expected_source_keys
    }
    expected_retrieval_scope = "bounded_candidates" if mode == "fast" else "per_filer"
    expected_comprehensive = bool(
        mode == "thorough"
        and value.get("complete") is True
        and value.get("results_complete") is True
    )
    uses_classification_contract = "classification_required" in value
    valid_conclusion_contract = (
        value.get("negative_findings_supported") is False
        and value.get("classification_required") is (mode == "thorough")
        and value.get("retrieval_complete") is expected_comprehensive
        and value.get("comprehensive") is False
        if uses_classification_contract
        else value.get("negative_findings_supported") is (mode == "thorough")
        and value.get("comprehensive") is expected_comprehensive
    )
    sec_fts_limited = bool(
        mode == "fast"
        and isinstance(sec_fts, dict)
        and (
            sec_fts.get("search_status") in {"partial", "unavailable"}
            or (
                _valid_non_negative_integer(sec_fts.get("queries_truncated"))
                and sec_fts.get("queries_truncated") > 0
            )
            or (
                isinstance(search_issues, list)
                and bool(search_issues)
            )
        )
    )
    expected_partial = bool(
        value.get("failed_count")
        or value.get("incomplete_count")
        or value.get("not_checked_count")
        or sec_fts_limited
        or value.get("census_complete") is not True
        or value.get("results_complete") is not True
    )
    expected_follow_up = None

    if value.get("incomplete_count"):
        expected_follow_up = {"mode": "thorough", "reason": "fast_batch_incomplete"}

    elif value.get("candidate_results_capped") is True:
        expected_follow_up = {"mode": "thorough", "reason": "candidate_results_capped"}
    valid_failure_maps = all(
        isinstance(failures, dict)
        and all(
            FAILURE_REASON_RE.fullmatch(str(reason or "")) is not None
            and _valid_non_negative_integer(count)
            for reason, count in failures.items()
        )
        for failures in (internal_failures, recovery_failures)
    )
    rv = (
        valid_integers
        and valid_failure_maps
        and isinstance(value.get("scan_id"), str)
        and re.fullmatch(r"[0-9a-f]{32}", value["scan_id"]) is not None
        and isinstance(recovery_issues, list)
        and _valid_recovery_scope(recovery_scope)
        and all(_valid_recovery_issue(issue, state) for issue in recovery_issues)
        and all(
            set(issue["ciks"]).issubset(failed_outcome_ciks)
            for issue in recovery_issues
        )
        and len({issue["accession_number"] for issue in recovery_issues})
        == len(recovery_issues)
        and mode in {"fast", "thorough"}
        and 1 <= query_count <= 12
        and isinstance(sources, dict)
        and set(sources) == expected_source_keys
        and all(_valid_non_negative_integer(count) for count in sources.values())
        and sources == source_counts
        and value.get("candidate_filer_count") <= value.get("total_filers")
        and value.get("candidate_count")
        == value.get("delivered_result_count") + value.get("omitted_result_count")
        and (
            mode == "fast"
            and _valid_sec_fts_receipt(sec_fts, query_count)
            and isinstance(search_issues, list)
            and len(search_issues) <= 12
            and all(
                _valid_search_issue(issue, query_count)
                for issue in search_issues
            )
            and len({issue["query_index"] for issue in search_issues})
            == len(search_issues)
            or mode == "thorough"
            and sec_fts is None
            and search_issues is None
        )
        and value.get("retrieval_scope") == expected_retrieval_scope
        and valid_conclusion_contract
        and value.get("partial_results") is expected_partial
        and isinstance(value.get("results_complete"), bool)
        and value["exact_accessions_retrying"] == 0
        and value["exact_accessions_completed"] == value["exact_accessions_queued"]
        and value["exact_accessions_completed"]
        == value["exact_accessions_recovered"] + value["exact_accessions_failed"]
        and (
            value["expected_ingestion_delays"]
            + value["unexpected_internal_gaps"]
            + value["unknown_age_gaps"]
            <= value["exact_accessions_queued"]
        )
        and sum(recovery_failures.values()) == value["exact_accessions_failed"]
        and len(recovery_issues) == value["exact_accessions_failed"]
        and dict(sorted(
            (code, sum(issue["failure_code"] == code for issue in recovery_issues))
            for code in recovery_failures
        )) == dict(sorted(recovery_failures.items()))
        and value["results_complete"] is (value["omitted_result_count"] == 0)
        and value.get("recommended_follow_up") == expected_follow_up
    )

    return rv


def _valid_response_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_post_census_record(accession, value, *, known_ciks, companion, scope):
    if (
        not isinstance(accession, str)
        or _normalized_accession(accession) != accession
        or not isinstance(value, dict)
        or set(value) != {"accession", "cik", "ticker", "filing_type", "filing_date"}
        or value.get("accession") != accession
    ):
        return False

    cik = _valid_cik(value.get("cik"))
    ticker = value.get("ticker")

    if (
        cik is None
        or (companion and cik not in known_ciks)
        or (not companion and cik in known_ciks)
    ):
        return False

    if ticker is not None and _qualified_ticker(ticker) is None:
        return False

    try:
        filing_date = datetime.date.fromisoformat(str(value.get("filing_date") or ""))
        date_from = datetime.date.fromisoformat(scope["date_from"])
        date_to = datetime.date.fromisoformat(scope["date_to"])
    except (KeyError, TypeError, ValueError):
        return False

    return (
        date_from <= filing_date <= date_to
        and bool(" ".join(str(value.get("filing_type") or "").split()))
    )


def _response_id_in_use(state, response_id, *, exclude=None):
    owner = state["consumed_responses"].get(response_id)
    excluded_owner = f"{exclude[0]}:{exclude[1]}" if exclude is not None else None
    return owner is not None and owner != excluded_owner


def _artifact_id_in_use(state, artifact_id, *, exclude=None):
    if artifact_id is None:
        return False

    owner = state["consumed_artifacts"].get(artifact_id)
    excluded_owner = f"{exclude[0]}:{exclude[1]}" if exclude is not None else None
    return owner is not None and owner != excluded_owner


def _empty_receipt_id(state, owner, plan):
    """Return an owner- and scope-bound ID for an agent-attested empty response."""
    payload = {
        "owner": owner,
        "date_from": state["scope"]["date_from"],
        "date_to": state["scope"]["date_to"],
        "query_hash": plan["query_hash"],
        "query_count": plan["query_count"],
        "kind": "agent_attested_empty",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_state(state):
    """Reject malformed or internally inconsistent coverage state."""
    if not isinstance(state, dict) or state.get("schema_version") != COVERAGE_STATE_VERSION:
        raise HelperError("The coverage state is missing or has an unsupported schema version.")

    # Version-4 states created before joint-accession support have no derived
    # joint receipt map. Adding the empty map preserves resumability without
    # changing the immutable census or its fingerprint.
    if "joint_satisfied" not in state:
        state["joint_satisfied"] = {}

    if "server_checked" not in state:
        state["server_checked"] = {}

    if "server_not_checked" not in state:
        state["server_not_checked"] = {}

    if "server_incomplete" not in state:
        state["server_incomplete"] = {}

    if "server_scan" not in state:
        state["server_scan"] = None

    if "bundle_classifications" not in state:
        state["bundle_classifications"] = {}

    if "candidate_issues" not in state:
        state["candidate_issues"] = []

    if _contains_capability_url(state):
        raise HelperError("Capability URLs cannot be stored in coverage state.")

    required_objects = (
        "scope",
        "enumeration",
        "accessions",
        "filers",
        "broad_searches",
        "broad_failures",
        "consumed_responses",
        "consumed_artifacts",
        "individually_checked",
        "joint_satisfied",
        "failed",
        "server_checked",
        "server_not_checked",
        "server_incomplete",
        "bundle_classifications",
        "included_companions",
        "excluded_post_census",
    )

    if any(not isinstance(state.get(key), dict) for key in required_objects):
        raise HelperError("The coverage state has a malformed object field.")

    for key in (
        "broad_surfaced",
        "unexpected",
        "unexpected_accessions",
        "census_identity_issues",
        "identity_issues",
        "candidate_issues",
    ):
        if not isinstance(state.get(key), list):
            raise HelperError(f"The coverage state field {key} must be an array.")

    if not all(_valid_candidate_issue(issue) for issue in state["candidate_issues"]):
        raise HelperError("The coverage state contains an invalid candidate issue.")

    scope = state["scope"]
    expected_forms = _normalized_expected_forms(scope.get("expected_forms"))

    if expected_forms != scope.get("expected_forms"):
        raise HelperError("The coverage state contains non-normalized expected forms.")

    _date_window(scope)
    accessions = state["accessions"]
    filers = state["filers"]
    accession_owners = {}

    for accession, record in accessions.items():
        if not isinstance(accession, str) or not ACCESSION_RE.fullmatch(accession):
            raise HelperError("The coverage state contains an invalid accession key.")

        if not isinstance(record, dict):
            raise HelperError("The coverage state contains a malformed accession record.")

        cik = _valid_cik(record.get("cik"))

        if cik is None:
            raise HelperError("The coverage state contains an invalid accession CIK.")

        issuer_ciks = record.get("issuer_ciks", [cik])
        normalized_issuer_ciks = [
            _valid_cik(value) for value in issuer_ciks
        ] if isinstance(issuer_ciks, list) else []

        if (
            not isinstance(issuer_ciks, list)
            or not issuer_ciks
            or cik not in issuer_ciks
            or any(value is None for value in normalized_issuer_ciks)
            or issuer_ciks != sorted(set(normalized_issuer_ciks))
        ):
            raise HelperError("The coverage state contains invalid accession issuer associations.")

        accession_owners[accession] = set(issuer_ciks)

        filing_type = " ".join(str(record.get("filing_type") or "").split()).upper()

        if not filing_type or not any(
            filing_type.startswith(form) for form in expected_forms
        ):
            raise HelperError("The coverage state contains an out-of-scope filing type.")

        try:
            filing_date = datetime.date.fromisoformat(str(record.get("filing_date") or ""))
            date_from = datetime.date.fromisoformat(scope["date_from"])
            date_to = datetime.date.fromisoformat(scope["date_to"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HelperError("The coverage state contains an invalid filing date.") from exc

        if not date_from <= filing_date <= date_to:
            raise HelperError("The coverage state contains an out-of-window accession.")

    for cik, filer in filers.items():
        normalized_cik = _valid_cik(cik)

        if normalized_cik != cik or not isinstance(filer, dict) or filer.get("cik") != cik:
            raise HelperError("The coverage state contains a malformed filer identity.")

        for key in (
            "accessions",
            "filing_types",
            "filing_dates",
            "tickers",
            "census_tickers",
        ):
            if not isinstance(filer.get(key), list):
                raise HelperError("The coverage state contains a malformed filer record.")

        if not filer["accessions"]:
            raise HelperError("Every coverage filer must own at least one accession.")

        for accession in filer["accessions"]:
            if accession not in accessions or cik not in accessions[accession].get("issuer_ciks", [accessions[accession].get("cik")]):
                raise HelperError("The coverage state contains an invalid filer/accession link.")

        expected_filing_types = list(
            dict.fromkeys(accessions[value]["filing_type"] for value in filer["accessions"])
        )
        expected_filing_dates = list(
            dict.fromkeys(accessions[value]["filing_date"] for value in filer["accessions"])
        )

        if (
            filer["filing_types"] != expected_filing_types
            or filer["filing_dates"] != expected_filing_dates
        ):
            raise HelperError("The coverage state contains inconsistent filer metadata.")

        tickers = []

        for value in filer["tickers"]:
            ticker = _qualified_ticker(value)

            if ticker is None or ticker.upper() in {item.upper() for item in tickers}:
                raise HelperError("The coverage state contains malformed ticker aliases.")

            tickers.append(ticker)

        search_ticker = filer.get("search_ticker")

        if search_ticker is not None and (
            _qualified_ticker(search_ticker) is None
            or search_ticker.upper() not in {item.upper() for item in tickers}
        ):
            raise HelperError("The coverage state contains an invalid selected search ticker.")

        census_tickers = filer["census_tickers"]

        if any(
            _qualified_ticker(value) is None
            for value in census_tickers
        ) or len({value.upper() for value in census_tickers}) != len(census_tickers):
            raise HelperError("The coverage state contains malformed frozen ticker aliases.")

        if any(
            value.upper() not in {ticker.upper() for ticker in tickers}
            for value in census_tickers
        ):
            raise HelperError("Frozen ticker aliases must remain present in the filer record.")

        census_search_ticker = filer.get("census_search_ticker")

        if census_search_ticker is not None and (
            _qualified_ticker(census_search_ticker) is None
            or census_search_ticker.upper()
            not in {value.upper() for value in census_tickers}
        ):
            raise HelperError("The coverage state contains an invalid frozen search ticker.")

    if set(accession_owners) != set(accessions) or any(
        owners != {
            cik for cik, filer in filers.items() if accession in filer["accessions"]
        }
        for accession, owners in accession_owners.items()
    ):
        raise HelperError("The coverage state does not assign every accession to its issuer filers.")

    known_ciks = set(filers)

    if not _valid_response_id(state.get("census_fingerprint")):
        raise HelperError("The coverage state is missing its census fingerprint.")

    if state["census_fingerprint"] != _census_fingerprint(state):
        raise HelperError("The frozen census fingerprint does not match the coverage state.")

    if not _valid_server_scan(state):
        raise HelperError("The server-bound census scan receipt is invalid.")

    server_scan_id = (
        state["server_scan"].get("scan_id")
        if isinstance(state.get("server_scan"), dict)
        else None
    )
    server_bundle_ids = set(
        state["server_scan"].get("bundle_ids") or []
        if isinstance(state.get("server_scan"), dict)
        else []
    )

    if not all(
        isinstance(bundle_id, str)
        and bundle_id in server_bundle_ids
        and isinstance(record, dict)
        and set(record) == {"scan_id", "status"}
        and record.get("scan_id") == server_scan_id
        and record.get("status") in FILING_BUNDLE_CLASSIFICATIONS
        for bundle_id, record in state["bundle_classifications"].items()
    ):
        raise HelperError("The coverage state contains malformed filing classifications.")

    for key, companion in (
        ("included_companions", True),
        ("excluded_post_census", False),
    ):
        if not all(
            _valid_post_census_record(
                accession,
                value,
                known_ciks=known_ciks,
                companion=companion,
                scope=scope,
            )
            for accession, value in state[key].items()
        ):
            raise HelperError(f"The coverage state contains malformed {key} records.")

    if set(state["included_companions"]) & set(state["accessions"]):
        raise HelperError("A frozen-census accession cannot also be a companion accession.")

    if set(state["excluded_post_census"]) & (
        set(state["accessions"]) | set(state["included_companions"])
    ):
        raise HelperError("Post-census accession classes must be mutually exclusive.")

    if not all(
        isinstance(value, dict)
        and set(value) == {"cik", "ticker"}
        and (value["cik"] is None or _valid_cik(value["cik"]) is not None)
        and (value["ticker"] is None or _qualified_ticker(value["ticker"]) is not None)
        for value in state["unexpected"]
    ):
        raise HelperError("The coverage state contains a malformed unexpected-filer record.")

    unexpected_accessions = state["unexpected_accessions"]

    if any(
        not isinstance(value, str) or _normalized_accession(value) != value
        for value in unexpected_accessions
    ) or len(unexpected_accessions) != len(set(unexpected_accessions)):
        raise HelperError("The coverage state contains an invalid unexpected accession.")

    if any(cik not in known_ciks for cik in state["broad_surfaced"]):
        raise HelperError("The coverage state contains an unknown broadly surfaced filer.")

    search_plan = state.get("search_plan")

    if search_plan is not None and not _valid_query_receipt(search_plan):
        raise HelperError("The coverage state contains a malformed thematic search plan.")

    for form, receipt in state["broad_searches"].items():
        if form not in expected_forms or not _valid_query_receipt(receipt):
            raise HelperError("The coverage state contains an invalid broad-search receipt.")

        surfaced_ciks = receipt.get("surfaced_ciks")
        authoritative_ciks = receipt.get("authoritative_ciks")

        if (
            not _valid_non_negative_integer(receipt.get("result_count"))
            or not _valid_response_id(receipt.get("response_id"))
            or receipt.get("receipt_kind")
            not in {"validated_result_artifact", "agent_attested_empty"}
            or receipt.get("expected_form") != form
            or receipt.get("date_from") != scope.get("date_from")
            or receipt.get("date_to") != scope.get("date_to")
            or not isinstance(surfaced_ciks, list)
            or not isinstance(authoritative_ciks, list)
            or any(not isinstance(cik, str) for cik in surfaced_ciks)
            or any(not isinstance(cik, str) for cik in authoritative_ciks)
            or len(surfaced_ciks) != len(set(surfaced_ciks))
            or len(authoritative_ciks) != len(set(authoritative_ciks))
            or any(cik not in known_ciks for cik in surfaced_ciks)
            or any(cik not in surfaced_ciks for cik in authoritative_ciks)
        ):
            raise HelperError("A broad-search receipt has an invalid result count or filer set.")

        if state["consumed_responses"].get(receipt["response_id"]) != f"broad:{form}":
            raise HelperError("A broad-search receipt has an invalid response owner.")

        artifact_id = receipt.get("artifact_id")

        if receipt["receipt_kind"] == "validated_result_artifact":
            if (
                receipt["result_count"] == 0
                or not _valid_response_id(artifact_id)
                or state["consumed_artifacts"].get(artifact_id) != f"broad:{form}"
            ):
                raise HelperError("A broad-search artifact receipt is invalid.")
        elif artifact_id is not None or receipt["result_count"] != 0:
            raise HelperError("An attested empty broad-search receipt is invalid.")

        if receipt["receipt_kind"] == "agent_attested_empty" and receipt[
            "response_id"
        ] != _empty_receipt_id(state, f"broad:{form}", receipt):
            raise HelperError("An attested empty broad-search receipt has invalid scope.")

    for form, failure in state["broad_failures"].items():
        if (
            form not in expected_forms
            or form in state["broad_searches"]
            or not _valid_query_receipt(failure)
            or failure.get("expected_form") != form
            or failure.get("date_from") != scope.get("date_from")
            or failure.get("date_to") != scope.get("date_to")
            or failure.get("reason") not in BROAD_FAILURE_REASONS
        ):
            raise HelperError("The coverage state contains an invalid broad-search failure.")

    receipt_surfaced = {
        cik
        for receipt in state["broad_searches"].values()
        for cik in receipt["surfaced_ciks"]
    }

    if set(state["broad_surfaced"]) != receipt_surfaced:
        raise HelperError("The broad-search filer union does not match its form receipts.")

    for cik, receipt in state["individually_checked"].items():
        if cik not in known_ciks or not _valid_query_receipt(receipt):
            raise HelperError("The coverage state contains an invalid ticker-search receipt.")

        receipt_ticker = _qualified_ticker(receipt.get("ticker"))

        if (
            receipt_ticker is None
            or not _valid_non_negative_integer(receipt.get("result_count"))
            or not _valid_response_id(receipt.get("response_id"))
            or receipt.get("receipt_kind")
            not in {"validated_result_artifact", "agent_attested_empty"}
            or receipt.get("date_from") != scope.get("date_from")
            or receipt.get("date_to") != scope.get("date_to")
            or receipt_ticker.upper()
            not in {value.upper() for value in filers[cik]["tickers"]}
        ):
            raise HelperError("The coverage state contains a malformed ticker-search receipt.")

        if state["consumed_responses"].get(receipt["response_id"]) != f"ticker:{cik}":
            raise HelperError("A ticker-search receipt has an invalid response owner.")

        artifact_id = receipt.get("artifact_id")

        if receipt["receipt_kind"] == "validated_result_artifact":
            if (
                receipt["result_count"] == 0
                or not _valid_response_id(artifact_id)
                or state["consumed_artifacts"].get(artifact_id) != f"ticker:{cik}"
            ):
                raise HelperError("A ticker-search artifact receipt is invalid.")
        elif artifact_id is not None or receipt["result_count"] != 0:
            raise HelperError("An attested empty ticker-search receipt is invalid.")

        if receipt["receipt_kind"] == "agent_attested_empty" and receipt[
            "response_id"
        ] != _empty_receipt_id(state, f"ticker:{cik}", receipt):
            raise HelperError("An attested empty ticker-search receipt has invalid scope.")

    response_ids = [
        receipt["response_id"]
        for receipt in list(state["broad_searches"].values())
        + list(state["individually_checked"].values())
    ]
    if state["server_scan"] is not None:
        response_ids.append(state["server_scan"]["response_id"])

    if len(response_ids) != len(set(response_ids)):
        raise HelperError("One saved search response is reused by multiple coverage receipts.")

    valid_response_owners = {f"broad:{form}" for form in expected_forms}
    valid_response_owners.update(f"ticker:{cik}" for cik in known_ciks)
    valid_response_owners.add("server_scan")

    if any(
        not _valid_response_id(response_id) or owner not in valid_response_owners
        for response_id, owner in state["consumed_responses"].items()
    ):
        raise HelperError("The coverage state contains an invalid consumed-response record.")

    if set(state["consumed_responses"]) != set(response_ids):
        raise HelperError("The consumed-response ledger does not match its search receipts.")

    artifact_ids = [
        receipt["artifact_id"]
        for receipt in list(state["broad_searches"].values())
        + list(state["individually_checked"].values())
        if receipt.get("artifact_id") is not None
    ]
    if state["server_scan"] is not None:
        artifact_ids.append(state["server_scan"]["artifact_id"])

    if len(artifact_ids) != len(set(artifact_ids)):
        raise HelperError("One saved artifact path is reused by multiple coverage receipts.")

    if any(
        not _valid_response_id(artifact_id) or owner not in valid_response_owners
        for artifact_id, owner in state["consumed_artifacts"].items()
    ):
        raise HelperError("The coverage state contains an invalid consumed-artifact record.")

    if set(state["consumed_artifacts"]) != set(artifact_ids):
        raise HelperError("The consumed-artifact ledger does not match its search receipts.")

    for cik, failure in state["failed"].items():
        if cik not in known_ciks or not isinstance(failure, dict):
            raise HelperError("The coverage state contains an invalid failed-filer record.")

        if failure.get("reason") not in ALLOWED_FAILURE_REASONS:
            raise HelperError("The coverage state contains an invalid failure reason.")

        failure_ticker = failure.get("ticker")

        if failure_ticker is not None and (
            _qualified_ticker(failure_ticker) is None
            or failure_ticker.upper()
            not in {value.upper() for value in filers[cik]["tickers"]}
        ):
            raise HelperError("The coverage state contains an invalid failed-filer ticker.")

    if not all(
        isinstance(value, str) and FAILURE_REASON_RE.fullmatch(value)
        for value in state["identity_issues"] + state["census_identity_issues"]
    ):
        raise HelperError("The coverage state contains an invalid identity issue code.")

    if any(value not in state["identity_issues"] for value in state["census_identity_issues"]):
        raise HelperError("Frozen census issues cannot be removed from coverage state.")

    surfaced = set(state["broad_surfaced"])
    checked = set(state["individually_checked"])
    server_checked = set(state["server_checked"])
    server_not_checked = set(state["server_not_checked"])
    server_incomplete = set(state["server_incomplete"])
    joint_satisfied = set(state["joint_satisfied"])
    failed = set(state["failed"])

    if (
        surfaced & checked or surfaced & failed or checked & failed
        or joint_satisfied & surfaced or joint_satisfied & checked
        or joint_satisfied & failed
        or server_checked & surfaced or server_checked & checked
        or server_checked & joint_satisfied or server_checked & failed
        or server_not_checked & surfaced or server_not_checked & checked
        or server_not_checked & joint_satisfied or server_not_checked & failed
        or server_not_checked & server_checked
        or server_incomplete & surfaced or server_incomplete & checked
        or server_incomplete & joint_satisfied or server_incomplete & failed
        or server_incomplete & server_checked or server_incomplete & server_not_checked
    ):
        raise HelperError("Coverage filer statuses must be mutually exclusive.")

    if any(
        cik not in known_ciks
        or not isinstance(receipt, dict)
        or receipt.get("status") not in {"checked_hit", "checked_empty"}
        or receipt.get("source") not in {"internal", "sec", "sec_fts", "mixed"}
        for cik, receipt in state["server_checked"].items()
    ):
        raise HelperError("The coverage state contains an invalid server-checked filer.")

    if any(
        cik not in known_ciks
        or not isinstance(receipt, dict)
        or receipt.get("status") != "not_checked"
        or receipt.get("reason") != "not_available_in_local_index"
        or receipt.get("source") not in {"internal", "sec_fts", "mixed", "none"}
        for cik, receipt in state["server_not_checked"].items()
    ):
        raise HelperError("The coverage state contains an invalid not-checked filer.")

    if any(
        cik not in known_ciks
        or not isinstance(receipt, dict)
        or receipt.get("status") != "incomplete"
        or receipt.get("reason") != "fast_batch_incomplete"
        or receipt.get("source") not in {"internal", "sec", "sec_fts", "mixed", "none"}
        for cik, receipt in state["server_incomplete"].items()
    ):
        raise HelperError("The coverage state contains an invalid incomplete filer.")

    for target_cik, joint in state["joint_satisfied"].items():
        source_cik = joint.get("source_cik") if isinstance(joint, dict) else None
        accession = joint.get("accession") if isinstance(joint, dict) else None
        record = state["accessions"].get(accession)
        if (
            target_cik not in known_ciks or source_cik not in state["individually_checked"]
            or source_cik == target_cik or not isinstance(record, dict)
            or target_cik not in record.get("issuer_ciks", [])
            or source_cik not in record.get("issuer_ciks", [])
        ):
            raise HelperError("The coverage state contains an invalid joint receipt.")

    return state


def _write_state(path, state):
    _validate_state(state)

    body = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _write_atomic(path, body)


def _load_state(path):
    state = _load_json_value(path)
    return _validate_state(state)


def reset_searches(state):
    """Clear search-derived state while preserving the immutable census."""
    _validate_state(state)

    for filer in state["filers"].values():
        filer["tickers"] = list(filer["census_tickers"])
        filer["search_ticker"] = filer["census_search_ticker"]

    state["search_plan"] = None
    state["broad_searches"] = {}
    state["broad_failures"] = {}
    state["consumed_responses"] = {}
    state["consumed_artifacts"] = {}
    state["broad_surfaced"] = []
    state["individually_checked"] = {}
    state["joint_satisfied"] = {}
    state["failed"] = {}
    state["server_checked"] = {}
    state["server_not_checked"] = {}
    state["server_incomplete"] = {}
    state["server_scan"] = None
    state["bundle_classifications"] = {}
    state["unexpected"] = []
    state["unexpected_accessions"] = []
    state["included_companions"] = {}
    state["excluded_post_census"] = {}
    state["candidate_issues"] = []
    state["identity_issues"] = list(state["census_identity_issues"])
    return state


def _alias_map(state):
    aliases = {}

    for cik, filer in state["filers"].items():
        for value in filer.get("tickers") or []:
            ticker = _qualified_ticker(value)

            if ticker:
                aliases.setdefault(ticker.upper(), set()).add(cik)

    return aliases


def _post_census_record(result, source_cik, accession):
    return {
        "accession": accession,
        "cik": source_cik,
        "ticker": _qualified_ticker(result.get("ticker")),
        "filing_type": " ".join(str(result.get("filing_type") or "").split()),
        "filing_date": str(result.get("filing_date") or "").strip(),
    }


def _record_companion(state, result, source_cik, accession):
    state["included_companions"].setdefault(
        accession,
        _post_census_record(result, source_cik, accession),
    )


def _record_excluded_post_census(state, result, source_cik, accession):
    state["excluded_post_census"].setdefault(
        accession,
        _post_census_record(result, source_cik, accession),
    )


def _candidate_issue_identity(result, source_cik=None, accession=None):
    """Return bounded, non-evidence metadata for one excluded candidate."""
    scan_cik = _valid_cik(result.get("scan_cik"))
    company = " ".join(str(result.get("name") or "").split())[:160] or None
    filing_type = " ".join(str(result.get("filing_type") or "").split())[:50] or None
    bundle_id = result.get("_filing_bundle_id")
    bundle_id = bundle_id if isinstance(bundle_id, str) and FILING_BUNDLE_ID_RE.fullmatch(bundle_id) else None

    return {
        "company": company,
        "company_identity": "provider_reported",
        "ticker": _qualified_ticker(result.get("ticker")),
        "cik": scan_cik or source_cik,
        "accession": accession,
        "bundle_id": bundle_id,
        "filing_type": filing_type,
    }


def _safe_candidate_value(value):
    """Return a small diagnostic value without retaining URLs or evidence text."""
    if value is None:
        return "missing"

    if isinstance(value, (dict, list, tuple, set)):
        return "non_scalar"

    text = " ".join(str(value).split())[:80]

    if not text:
        return "empty"

    return "redacted" if CAPABILITY_URL_RE.search(text) else text


def _record_candidate_issue(state, result, reason, fields, *, source_cik=None, accession=None):
    """Record one specific, safe reason that a candidate was excluded."""
    if reason not in CANDIDATE_ISSUE_REASONS:
        raise HelperError("The candidate exclusion reason is invalid.")

    issue_fields = sorted(set(fields))

    if not issue_fields or any(field not in CANDIDATE_ISSUE_FIELDS for field in issue_fields):
        raise HelperError("The candidate exclusion fields are invalid.")

    issue = {
        **_candidate_issue_identity(result, source_cik, accession),
        "reason": reason,
        "fields": issue_fields,
        "reported_values": {
            field: _safe_candidate_value(
                (
                    result.get("scan_cik") or source_cik
                    if field == "cik"
                    else accession
                    if field == "accession"
                    else result.get(field)
                )
            )
            for field in issue_fields
        },
        "expected": CANDIDATE_ISSUE_EXPECTATIONS[reason],
        "disposition": "excluded_from_main_results",
    }

    if issue not in state["candidate_issues"]:
        state["candidate_issues"].append(issue)


def _valid_candidate_issue(value):
    if not isinstance(value, dict) or set(value) != {
        "company",
        "company_identity",
        "ticker",
        "cik",
        "accession",
        "bundle_id",
        "filing_type",
        "reason",
        "fields",
        "reported_values",
        "expected",
        "disposition",
    }:
        return False

    company = value.get("company")
    filing_type = value.get("filing_type")
    ticker = value.get("ticker")
    cik = value.get("cik")
    accession = value.get("accession")
    bundle_id = value.get("bundle_id")
    fields = value.get("fields")
    reported_values = value.get("reported_values")
    expected = value.get("expected")
    return (
        (company is None or (isinstance(company, str) and 0 < len(company) <= 160))
        and value.get("company_identity") == "provider_reported"
        and (filing_type is None or (isinstance(filing_type, str) and 0 < len(filing_type) <= 50))
        and (ticker is None or _qualified_ticker(ticker) == ticker)
        and (cik is None or _valid_cik(cik) == cik)
        and (accession is None or _normalized_accession(accession) == accession)
        and (bundle_id is None or FILING_BUNDLE_ID_RE.fullmatch(bundle_id) is not None)
        and value.get("reason") in CANDIDATE_ISSUE_REASONS
        and isinstance(fields, list)
        and bool(fields)
        and fields == sorted(set(fields))
        and all(field in CANDIDATE_ISSUE_FIELDS for field in fields)
        and isinstance(reported_values, dict)
        and set(reported_values) == set(fields)
        and all(
            isinstance(reported_value, str) and 0 < len(reported_value) <= 80
            for reported_value in reported_values.values()
        )
        and expected == CANDIDATE_ISSUE_EXPECTATIONS.get(value.get("reason"))
        and value.get("disposition") == "excluded_from_main_results"
    )


def _saved_accession_record(state, accession):
    """Return the frozen, companion, or excluded record for one accession."""
    for classification, key in (
        ("census", "accessions"),
        ("companion", "included_companions"),
        ("excluded", "excluded_post_census"),
    ):
        record = state[key].get(accession)

        if record is not None:
            return classification, record

    return None, None


def _accession_metadata_matches_result(record, result):
    """Return whether one saved accession has the result's form and date."""
    if not isinstance(record, dict):
        return False

    saved_form = normalize_form(record.get("filing_type"))[0]
    result_form = normalize_form(result.get("filing_type"))[0]
    result_date = str(result.get("filing_date") or "").strip()
    return record.get("filing_date") == result_date and saved_form == result_form


def _accession_record_matches_result(record, source_cik, result):
    """Return whether one saved accession identity matches a search result."""
    issuer_ciks = record.get("issuer_ciks", [record.get("cik")]) if isinstance(record, dict) else []
    return (
        isinstance(record, dict)
        and source_cik in issuer_ciks
        and _accession_metadata_matches_result(record, result)
    )


def _result_source_matches_accession_record(state, source_cik, ticker_ciks, record):
    """Allow authoritative listed issuers or an external SEC archive owner."""
    issuer_ciks = set(record.get("issuer_ciks", [])) if isinstance(record, dict) else set()
    rv = source_cik in issuer_ciks

    if not rv and source_cik not in state["filers"]:
        rv = not ticker_ciks or set(ticker_ciks).issubset(issuer_ciks)

    return rv


def _accession_issuer_ciks(state, accession, source_cik):
    """Return every frozen issuer CIK associated with one authoritative accession."""
    record = state["accessions"].get(accession)
    issuer_ciks = record.get("issuer_ciks", []) if isinstance(record, dict) else []
    return sorted(set(issuer_ciks)) if source_cik in issuer_ciks else [source_cik]


def _eligible_results_for_state(state, results, *, record_issues=False):
    """Filter model-facing summaries to frozen-census companies only."""
    aliases = _alias_map(state)
    eligible = []

    for result in results:
        # The server-bound receipt proves coverage against the frozen census,
        # independently of any extra candidate it happens to deliver.  A
        # syntactically valid candidate outside the requested filing window is
        # therefore irrelevant to both the result set and its audit. Record
        # malformed dates as an ambiguous excluded candidate, while discarding
        # valid out-of-window extras as harmless scope leakage.
        if not " ".join(str(result.get("filing_type") or "").split()):
            if record_issues:
                source_cik, accession = _sec_cik_and_accession(result)
                _record_candidate_issue(
                    state,
                    result,
                    "malformed_filing_type",
                    ["filing_type"],
                    source_cik=source_cik,
                    accession=accession,
                )
            continue

        try:
            in_window = _result_is_within_window(state, result)
        except HelperError:
            if record_issues:
                source_cik, accession = _sec_cik_and_accession(result)
                _record_candidate_issue(
                    state,
                    result,
                    "malformed_filing_date",
                    ["filing_date"],
                    source_cik=source_cik,
                    accession=accession,
                )
            continue

        if not in_window:
            if record_issues:
                source_cik, accession = _sec_cik_and_accession(result)
                _record_candidate_issue(
                    state,
                    result,
                    "filing_date_outside_window",
                    ["filing_date"],
                    source_cik=source_cik,
                    accession=accession,
                )
            continue

        source_cik, accession = _sec_cik_and_accession(result)
        ticker = _qualified_ticker(result.get("ticker"))
        ticker_ciks = aliases.get(ticker.upper(), set()) if ticker else set()
        classification, accession_record = (
            _saved_accession_record(state, accession)
            if accession is not None
            else (None, None)
        )

        if (
            classification == "census"
            and _accession_metadata_matches_result(accession_record, result)
            and _result_source_matches_accession_record(
                state,
                source_cik,
                ticker_ciks,
                accession_record,
            )
        ):
            eligible.append(result)

        elif source_cik in state["filers"]:
            if ticker_ciks and source_cik not in ticker_ciks:
                if record_issues:
                    _record_candidate_issue(
                        state, result, "ticker_identity_conflict", ["ticker"],
                        source_cik=source_cik, accession=accession,
                    )
                continue

            if accession is not None:
                if classification == "excluded":
                    if record_issues:
                        _record_candidate_issue(
                            state, result, "unresolved_filing_identity", ["accession"],
                            source_cik=source_cik, accession=accession,
                        )
                    continue
                if not _accession_record_matches_result(
                    accession_record, source_cik, result,
                ):
                    if record_issues:
                        _record_candidate_issue(
                            state, result, "filing_metadata_conflict",
                            ["accession", "filing_date", "filing_type"],
                            source_cik=source_cik, accession=accession,
                        )
                    continue

            eligible.append(result)
        elif source_cik is None and len(ticker_ciks) == 1:
            eligible.append(result)
        elif record_issues:
            _record_candidate_issue(
                state, result, "unresolved_filing_identity", ["cik", "ticker"],
                source_cik=source_cik, accession=accession,
            )

    return eligible


def _result_is_within_window(state, result):
    """Return whether one validly dated result falls inside the frozen window."""
    filing_date = str(result.get("filing_date") or "").strip()
    filing_type = " ".join(str(result.get("filing_type") or "").split())

    if not filing_type:
        raise HelperError("A search result is missing a filing_type.")

    try:
        parsed_date = datetime.date.fromisoformat(filing_date)
        date_from = datetime.date.fromisoformat(state["scope"]["date_from"])
        date_to = datetime.date.fromisoformat(state["scope"]["date_to"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HelperError("A search result is missing a valid filing_date.") from exc

    return date_from <= parsed_date <= date_to


def _validate_result_window(state, result):
    """Require one search result to fall inside the enumerated filing-date window."""
    if not _result_is_within_window(state, result):
        raise HelperError("A search result falls outside the enumerated date window.")


def add_broad_search_results(
    state,
    results,
    expected_form,
    queries,
    *,
    result_count=None,
    response_id=None,
    artifact_id=None,
    attested_empty=False,
    return_eligible=False,
):
    """Record one scope-validated broad-search receipt and its surfaced filers."""
    _validate_state(state)
    expected_form = _normalized_form(expected_form)

    if expected_form not in state["scope"]["expected_forms"]:
        raise HelperError("--expected-form is not part of the enumerated form universe.")

    if state["individually_checked"] or state["failed"]:
        raise HelperError(
            "Record every broad filing-form search before marking individual filers."
        )

    if result_count is None:
        result_count = len(results)

    if not _valid_non_negative_integer(result_count) or result_count != len(results):
        raise HelperError("The broad-search result count does not match its results.")

    existing_receipt = state["broad_searches"].get(expected_form)

    if existing_receipt is not None:
        raise HelperError(
            "This filing form already has a broad-search receipt. Reset searches "
            "before replacing a recorded search."
        )

    plan = _bind_query_plan(state, queries)
    owner = f"broad:{expected_form}"

    if attested_empty:
        if results or result_count != 0 or response_id is not None or artifact_id is not None:
            raise HelperError(
                "An attested empty broad search cannot include an artifact or results."
            )

        response_id = _empty_receipt_id(state, owner, plan)
        receipt_kind = "agent_attested_empty"
    else:
        if result_count == 0:
            raise HelperError(
                "Use --empty for a successful zero-result broad search instead of an artifact."
            )

        if not _valid_response_id(response_id):
            raise HelperError("The broad search is missing a valid saved-response receipt.")

        artifact_id = artifact_id or response_id

        if not _valid_response_id(artifact_id):
            raise HelperError("The broad search is missing a valid saved-artifact receipt.")

        receipt_kind = "validated_result_artifact"

    if _response_id_in_use(
        state,
        response_id,
        exclude=("broad", expected_form),
    ):
        raise HelperError("The saved search response is already bound to another coverage check.")

    if _artifact_id_in_use(state, artifact_id, exclude=("broad", expected_form)):
        raise HelperError("The saved artifact path is already bound to another coverage check.")

    aliases = _alias_map(state)
    previous_surfaced = set(state["broad_surfaced"])
    matched_ciks = set()
    authoritative_ciks = set()
    eligible_results = []

    for result in results:
        _validate_result_window(state, result)
        filing_type = " ".join(str(result.get("filing_type") or "").split()).upper()

        if not filing_type.startswith(expected_form):
            raise HelperError(
                "A broad-search result does not match its recorded filing-type prefix."
            )

        source_cik, accession = _sec_cik_and_accession(result)
        ticker = _qualified_ticker(result.get("ticker"))
        ticker_ciks = aliases.get(ticker.upper(), set()) if ticker else set()
        matched_cik = None
        association_cik = source_cik
        is_companion = False

        if source_cik in state["filers"]:
            if accession is not None:
                classification, accession_record = _saved_accession_record(
                    state,
                    accession,
                )

                if classification is None:
                    is_companion = True

                elif (
                    classification == "excluded"
                    or source_cik not in accession_record.get("issuer_ciks", [accession_record.get("cik")])
                ):
                    _append_unique(state["identity_issues"], "search_identity_conflict")
                    continue

                elif not _accession_record_matches_result(
                    accession_record,
                    source_cik,
                    result,
                ):
                    _append_unique(
                        state["identity_issues"],
                        "search_accession_metadata_mismatch",
                    )
                    continue

            if ticker_ciks and source_cik not in ticker_ciks:
                _append_unique(state["identity_issues"], "search_identity_conflict")
                continue

            if ticker and not ticker_ciks:
                filer = state["filers"][source_cik]
                filer["tickers"].append(ticker)

                if filer.get("search_ticker") is None:
                    filer["search_ticker"] = ticker

                aliases.setdefault(ticker.upper(), set()).add(source_cik)

            if is_companion:
                _record_companion(state, result, source_cik, accession)

            matched_cik = source_cik

            if accession is not None:
                authoritative_ciks.add(source_cik)

        elif source_cik and ticker_ciks:
            _append_unique(state["identity_issues"], "search_identity_conflict")
            continue

        elif source_cik and accession:
            classification, accession_record = _saved_accession_record(state, accession)

            if (
                classification == "census"
                and _accession_metadata_matches_result(accession_record, result)
                and _result_source_matches_accession_record(
                    state,
                    source_cik,
                    ticker_ciks,
                    accession_record,
                )
            ):
                matched_cik = accession_record["cik"]
                association_cik = accession_record["cik"]
                authoritative_ciks.update(accession_record.get("issuer_ciks", []))

            elif classification in {"census", "companion"}:
                _append_unique(state["identity_issues"], "search_identity_conflict")
            elif classification == "excluded" and not _accession_record_matches_result(
                accession_record,
                source_cik,
                result,
            ):
                _append_unique(
                    state["identity_issues"],
                    "search_accession_metadata_mismatch",
                )
            elif classification is None:
                _record_excluded_post_census(state, result, source_cik, accession)

            if matched_cik is None:
                continue

        elif len(ticker_ciks) == 1:
            matched_cik = next(iter(ticker_ciks))

        elif len(ticker_ciks) > 1:
            _append_unique(state["identity_issues"], "ambiguous_ticker_alias")
            continue

        if matched_cik:
            associated_ciks = (
                _accession_issuer_ciks(state, accession, association_cik)
                if accession is not None and association_cik is not None
                else [matched_cik]
            )
            matched_ciks.update(associated_ciks)
            eligible_results.append(result)
            for associated_cik in associated_ciks:
                state["failed"].pop(associated_cik, None)
                state["individually_checked"].pop(associated_cik, None)
        else:
            unexpected = {
                "cik": source_cik,
                "ticker": ticker,
            }

            if unexpected not in state["unexpected"]:
                state["unexpected"].append(unexpected)
            _append_unique(state["identity_issues"], "unexpected_in_scope_filer")
    state["broad_searches"][expected_form] = {
        **plan,
        "response_id": response_id,
        "artifact_id": artifact_id,
        "receipt_kind": receipt_kind,
        "expected_form": expected_form,
        "date_from": state["scope"]["date_from"],
        "date_to": state["scope"]["date_to"],
        "result_count": result_count,
        "surfaced_ciks": sorted(matched_ciks),
        "authoritative_ciks": sorted(authoritative_ciks),
    }
    state["broad_failures"].pop(expected_form, None)
    state["consumed_responses"][response_id] = owner

    if artifact_id is not None:
        state["consumed_artifacts"][artifact_id] = owner
    state["broad_surfaced"] = sorted(
        {
            cik
            for receipt in state["broad_searches"].values()
            for cik in receipt["surfaced_ciks"]
        }
    )
    added_count = len(set(state["broad_surfaced"]) - previous_surfaced)
    return (added_count, eligible_results) if return_eligible else added_count


def fail_broad_search(state, expected_form, queries, reason):
    """Record one terminal form-scoped retrieval failure without faking a receipt."""
    _validate_state(state)
    expected_form = _normalized_form(expected_form)

    if expected_form not in state["scope"]["expected_forms"]:
        raise HelperError("--expected-form is not part of the enumerated form universe.")

    if expected_form in state["broad_searches"]:
        raise HelperError("This filing form already has a successful broad-search receipt.")

    if state["individually_checked"] or state["failed"]:
        raise HelperError(
            "Record every broad filing-form result before marking individual filers."
        )

    reason = str(reason or "").strip().lower()

    if reason not in BROAD_FAILURE_REASONS:
        raise HelperError(
            "--reason must be one of: artifact_unavailable, malformed_response, "
            "rate_limited, timeout."
        )

    plan = _bind_query_plan(state, queries)
    state["broad_failures"][expected_form] = {
        **plan,
        "expected_form": expected_form,
        "date_from": state["scope"]["date_from"],
        "date_to": state["scope"]["date_to"],
        "reason": reason,
    }
    return expected_form


def _missing_ciks(state):
    expected = set(state["filers"])
    surfaced = set(state["broad_surfaced"])
    checked = set(state["individually_checked"])
    joint_satisfied = set(state["joint_satisfied"])
    server_checked = set(state.get("server_checked") or {})
    server_not_checked = set(state.get("server_not_checked") or {})
    server_incomplete = set(state.get("server_incomplete") or {})
    failed = set(state["failed"])
    return sorted(
        expected
        - surfaced
        - checked
        - joint_satisfied
        - server_checked
        - server_not_checked
        - server_incomplete
        - failed
    )


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


def _resolve_state_cik(state, value):
    cik = _valid_cik(value)

    if cik is None or cik not in state["filers"]:
        raise HelperError("--cik must identify one enumerated filer.")

    return cik


def bind_resolved_ticker(state, cik_value, ticker_value):
    """Bind one independently resolved exchange-qualified ticker to a census filer."""
    _validate_state(state)
    cik = _resolve_state_cik(state, cik_value)
    ticker = _qualified_ticker(ticker_value)

    if ticker is None:
        raise HelperError("--ticker must be one exchange-qualified ticker.")

    filer = state["filers"][cik]

    if filer.get("search_ticker") is not None:
        raise HelperError("This filer already has a selected search ticker.")

    owners = _alias_map(state).get(ticker.upper(), set())

    if owners and owners != {cik}:
        raise HelperError("The resolved ticker is already assigned to another census filer.")

    if cik in state["individually_checked"]:
        raise HelperError("This filer already has an individual-search receipt.")

    failure = state["failed"].get(cik)

    if failure is not None and failure.get("reason") != "unresolved_ticker":
        raise HelperError("Resolve the filer's existing non-ticker failure before binding a ticker.")

    if ticker.upper() not in {value.upper() for value in filer["tickers"]}:
        filer["tickers"].append(ticker)

    filer["search_ticker"] = ticker
    state["failed"].pop(cik, None)
    return cik, ticker


def _filter_ticker_search_results(state, cik, results):
    """Validate one ticker search and retain only frozen-census-company results."""
    aliases = _alias_map(state)
    eligible = []

    for result in results:
        _validate_result_window(state, result)
        source_cik, accession = _sec_cik_and_accession(result)
        ticker = _qualified_ticker(result.get("ticker"))
        ticker_ciks = aliases.get(ticker.upper(), set()) if ticker else set()
        classification, accession_record = (
            _saved_accession_record(state, accession)
            if accession is not None
            else (None, None)
        )
        is_requested_joint_accession = (
            classification == "census"
            and cik in accession_record.get("issuer_ciks", [])
            and _accession_metadata_matches_result(accession_record, result)
            and _result_source_matches_accession_record(
                state,
                source_cik,
                ticker_ciks,
                accession_record,
            )
        )

        if is_requested_joint_accession:
            eligible.append(result)
            continue

        if source_cik in state["filers"]:
            if source_cik != cik or (ticker_ciks and cik not in ticker_ciks):
                raise HelperError(
                    "A ticker-search result belongs to a different filer than --ticker."
                )

            if accession is not None:
                if classification is None:
                    _record_companion(state, result, source_cik, accession)
                elif (
                    classification == "excluded"
                    or source_cik not in accession_record.get("issuer_ciks", [accession_record.get("cik")])
                ):
                    raise HelperError(
                        "A ticker-search accession belongs to a different census filer."
                    )
                elif not _accession_record_matches_result(
                    accession_record,
                    source_cik,
                    result,
                ):
                    raise HelperError(
                        "A ticker-search accession has conflicting filing metadata."
                    )

            eligible.append(result)
        elif source_cik is not None and accession is not None:
            if ticker_ciks:
                raise HelperError(
                    "A ticker-search result belongs to a different filer than --ticker."
                )

            if classification in {"census", "companion"}:
                raise HelperError(
                    "A ticker-search accession belongs to a different census filer."
                )

            if classification == "excluded" and not _accession_record_matches_result(
                accession_record,
                source_cik,
                result,
            ):
                raise HelperError(
                    "A ticker-search accession has conflicting filing metadata."
                )

            if classification is None:
                _record_excluded_post_census(state, result, source_cik, accession)
        elif cik not in ticker_ciks:
            raise HelperError(
                "A ticker-search result cannot be tied to the requested enumerated filer."
            )
        else:
            eligible.append(result)

    return eligible


def mark_filer(
    state,
    ticker_value,
    status,
    reason=None,
    *,
    cik_value=None,
    results=None,
    result_count=None,
    queries=None,
    response_id=None,
    artifact_id=None,
    attested_empty=False,
    return_eligible=False,
):
    """Record one saved-response-backed ticker check or one terminal failed attempt."""
    _validate_state(state)

    if ticker_value is not None:
        ticker, cik = _resolve_state_ticker(state, ticker_value)
    else:
        ticker = None
        cik = _resolve_state_cik(state, cik_value)

    if status not in {"checked", "failed"}:
        raise HelperError("--status must be checked or failed.")

    if cik in state["broad_surfaced"]:
        raise HelperError("This filer was already satisfied by a broad-search receipt.")

    if cik in state["individually_checked"]:
        raise HelperError("This filer already has an individual-search receipt.")

    if cik not in _missing_ciks(state) and cik not in state["failed"]:
        raise HelperError("Only a pending or previously failed filer can be marked.")

    if status == "checked":
        if ticker is None:
            raise HelperError("--ticker is required when --status checked.")

        if results is None or result_count is None or queries is None:
            raise HelperError(
                "A checked filer requires a saved search response and the thematic queries."
            )

        if not _valid_non_negative_integer(result_count) or result_count != len(results):
            raise HelperError("The ticker-search result count does not match its results.")

        plan = _bind_query_plan(state, queries)
        owner = f"ticker:{cik}"

        if attested_empty:
            if results or result_count != 0 or response_id is not None or artifact_id is not None:
                raise HelperError(
                    "An attested empty ticker search cannot include an artifact or results."
                )

            response_id = _empty_receipt_id(state, owner, plan)
            receipt_kind = "agent_attested_empty"
        else:
            if result_count == 0:
                raise HelperError(
                    "Use --empty for a successful zero-result ticker search instead of an artifact."
                )

            if not _valid_response_id(response_id):
                raise HelperError("The ticker search is missing a valid saved-response receipt.")

            artifact_id = artifact_id or response_id

            if not _valid_response_id(artifact_id):
                raise HelperError("The ticker search is missing a valid saved-artifact receipt.")

            receipt_kind = "validated_result_artifact"

        if _response_id_in_use(state, response_id, exclude=("ticker", cik)):
            raise HelperError(
                "The saved search response is already bound to another coverage check."
            )

        if _artifact_id_in_use(state, artifact_id, exclude=("ticker", cik)):
            raise HelperError("The saved artifact path is already bound to another coverage check.")

        eligible_results = _filter_ticker_search_results(state, cik, results)
        state["individually_checked"][cik] = {
            **plan,
            "ticker": ticker,
            "response_id": response_id,
            "artifact_id": artifact_id,
            "receipt_kind": receipt_kind,
            "date_from": state["scope"]["date_from"],
            "date_to": state["scope"]["date_to"],
            "result_count": result_count,
        }
        state["consumed_responses"][response_id] = owner

        if artifact_id is not None:
            state["consumed_artifacts"][artifact_id] = owner

        state["failed"].pop(cik, None)
        for result in eligible_results:
            _source_cik, accession = _sec_cik_and_accession(result)
            accession_record = state["accessions"].get(accession)
            if (
                isinstance(accession_record, dict)
                and cik in accession_record.get("issuer_ciks", [])
                and _accession_metadata_matches_result(accession_record, result)
            ):
                for associated_cik in _accession_issuer_ciks(state, accession, cik):
                    if (
                        associated_cik != cik
                        and associated_cik not in state["broad_surfaced"]
                        and associated_cik not in state["individually_checked"]
                    ):
                        state["joint_satisfied"][associated_cik] = {
                            "source_cik": cik,
                            "accession": accession,
                        }
                        state["failed"].pop(associated_cik, None)
    else:
        if reason is None:
            raise HelperError("--reason is required when --status failed.")

        reason = str(reason or "unspecified").strip().lower()

        if reason not in ALLOWED_FAILURE_REASONS:
            raise HelperError(
                "--reason must be one of: artifact_unavailable, malformed_response, "
                "rate_limited, timeout, unresolved_ticker."
            )

        if cik not in state["individually_checked"]:
            state["failed"][cik] = {"ticker": ticker, "reason": reason}

        eligible_results = []

    return (cik, eligible_results) if return_eligible else cik


def import_server_scan(
    state, artifact_path, queries, results_per_query, *, mode="thorough"
):
    """Validate and import one complete server-bound census search receipt."""
    _validate_state(state)

    if state.get("server_scan") is not None:
        raise HelperError("This coverage state already contains a server-bound census scan.")

    if any(
        (
            state["broad_searches"],
            state["broad_failures"],
            state["individually_checked"],
            state["joint_satisfied"],
            state["failed"],
            state["server_incomplete"],
            state["server_not_checked"],
        )
    ):
        raise HelperError(
            "Reset existing search receipts before importing a server-bound census scan."
        )

    clean_queries = []

    for query in queries or []:
        clean_query = str(query or "").strip()

        if not clean_query or len(clean_query) > 300:
            raise HelperError("Every --query must contain 1 to 300 characters.")

        if clean_query not in clean_queries:
            clean_queries.append(clean_query)

    if not 1 <= len(clean_queries) <= 12:
        raise HelperError("Provide between 1 and 12 distinct --query values.")

    if (
        isinstance(results_per_query, bool)
        or not isinstance(results_per_query, int)
        or not 1 <= results_per_query <= 25
    ):
        raise HelperError("--results-per-query must be between 1 and 25.")

    if mode not in {"fast", "thorough"}:
        raise HelperError("--mode must be fast or thorough.")

    payload = _load_json_value(artifact_path)
    results, result_count, response_id, artifact_id = load_search_response(artifact_path)
    coverage = payload.get("coverage") if isinstance(payload, dict) else None
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    bundle_ids = []

    if isinstance(raw_results, list) and raw_results:
        bundle_values = [
            value
            for value in raw_results
            if isinstance(value, dict) and isinstance(value.get("evidence"), list)
        ]

        if bundle_values and len(bundle_values) != len(raw_results):
            raise HelperError("The server artifact mixes filing bundles and legacy results.")

        if bundle_values:
            bundle_ids = [value.get("bundle_id") for value in bundle_values]

            if (
                len(bundle_ids) != len(set(bundle_ids))
                or any(
                    not isinstance(bundle_id, str)
                    or FILING_BUNDLE_ID_RE.fullmatch(bundle_id) is None
                    for bundle_id in bundle_ids
                )
            ):
                raise HelperError("The server artifact contains invalid filing bundle identities.")

    if not isinstance(coverage, dict) or coverage.get("request_binding") != "server_bound":
        raise HelperError("The saved artifact lacks a server-bound coverage receipt.")

    query_hash = _server_query_hash(clean_queries, results_per_query)

    if coverage.get("query_hash") != query_hash:
        raise HelperError("The server receipt does not match the supplied thematic queries.")

    if coverage.get("census_fingerprint") != _server_census_fingerprint(state):
        raise HelperError("The server receipt does not match the frozen filing census.")

    outcomes = coverage.get("outcomes")

    if not isinstance(outcomes, list):
        raise HelperError("The server receipt is missing filer outcomes.")

    checked_hit = sum(
        isinstance(outcome, dict) and outcome.get("status") == "checked_hit"
        for outcome in outcomes
    )
    checked_empty = sum(
        isinstance(outcome, dict) and outcome.get("status") == "checked_empty"
        for outcome in outcomes
    )
    failed_count = sum(
        isinstance(outcome, dict) and outcome.get("status") == "failed"
        for outcome in outcomes
    )
    not_checked_count = sum(
        isinstance(outcome, dict) and outcome.get("status") == "not_checked"
        for outcome in outcomes
    )
    incomplete_count = sum(
        isinstance(outcome, dict) and outcome.get("status") == "incomplete"
        for outcome in outcomes
    )
    checked_count = checked_hit + checked_empty
    expected_complete = (
        state["enumeration"].get("coverage_complete") is True
        and failed_count == 0
        and not_checked_count == 0
        and incomplete_count == 0
        and checked_count == len(state["filers"])
    )

    if not (
        coverage.get("total_filers") == len(state["filers"])
        and coverage.get("checked_count") == checked_count
        and coverage.get("checked") == checked_count
        and coverage.get("checked_hit") == checked_hit
        and coverage.get("checked_empty") == checked_empty
        and coverage.get("failed_count") == failed_count
        and coverage.get("failed") == failed_count
        and coverage.get("not_checked_count") == not_checked_count
        and coverage.get("not_checked") == not_checked_count
        and coverage.get("incomplete_count") == incomplete_count
        and coverage.get("incomplete") == incomplete_count
        and checked_count + not_checked_count + failed_count + incomplete_count
        == len(state["filers"])
        and coverage.get("mode") == mode
        and coverage.get("complete") is expected_complete
        and coverage.get("census_complete") is state["enumeration"].get("coverage_complete")
        and coverage.get("census_issues") == state["enumeration"].get("issues")
        and coverage.get("date_from") == state["scope"].get("date_from")
        and coverage.get("date_to") == state["scope"].get("date_to")
        and coverage.get("filing_types") == state["scope"].get("expected_forms")
        and _valid_recovery_receipt(coverage, state, len(clean_queries))
        and payload.get("results_complete") is coverage.get("results_complete")
        and payload.get("delivered_result_count") == result_count
        and payload.get("delivered_result_count") == coverage.get("delivered_result_count")
        and payload.get("omitted_result_count") == coverage.get("omitted_result_count")
    ):
        raise HelperError("The server receipt has inconsistent census coverage arithmetic.")

    for outcome in outcomes:
        cik = _valid_cik(outcome.get("cik")) if isinstance(outcome, dict) else None
        status = outcome.get("status") if isinstance(outcome, dict) else None

        if cik not in state["filers"]:
            raise HelperError("The server receipt contains an issuer outside the census.")

        if status in {"checked_hit", "checked_empty"}:
            state["server_checked"][cik] = {
                "source": outcome.get("source"),
                "status": status,
            }

        elif status == "failed":
            state["failed"][cik] = {
                "ticker": state["filers"][cik].get("search_ticker"),
                "reason": outcome.get("reason"),
            }

        elif status == "not_checked":
            state["server_not_checked"][cik] = {
                "source": outcome.get("source"),
                "status": status,
                "reason": outcome.get("reason"),
            }

        elif status == "incomplete":
            state["server_incomplete"][cik] = {
                "source": outcome.get("source"),
                "status": status,
                "reason": outcome.get("reason"),
            }

        else:
            raise HelperError("The server receipt contains an invalid filer outcome.")

    identity_validated_results = []

    for result in results:
        scan_cik = _valid_cik(result.get("scan_cik"))
        source_cik, accession = _sec_cik_and_accession(result)
        census_record = state["accessions"].get(accession) if accession else None
        known_joint_association = (
            isinstance(census_record, dict)
            and scan_cik in (census_record.get("issuer_ciks") or [])
        )

        if scan_cik not in state["filers"]:
            in_scope_source = (
                source_cik in state["filers"]
                or accession in state["accessions"]
            )
            _record_candidate_issue(
                state,
                result,
                "issuer_identity_conflict" if in_scope_source else "issuer_outside_census",
                ["cik", "accession"] if in_scope_source else ["cik"],
                source_cik=source_cik,
                accession=accession,
            )
            continue

        if (
            source_cik is not None and source_cik != scan_cik
            and not known_joint_association
        ):
            _record_candidate_issue(
                state,
                result,
                "issuer_identity_conflict",
                ["cik", "accession"],
                source_cik=source_cik,
                accession=accession,
            )
            continue

        if result.get("companion") is True and accession not in state["accessions"]:
            if accession is None:
                _record_candidate_issue(
                    state,
                    result,
                    "missing_companion_accession",
                    ["accession"],
                    source_cik=source_cik,
                )
                continue

            try:
                companion_is_in_window = _result_is_within_window(state, result)
            except HelperError:
                companion_is_in_window = False

            if companion_is_in_window:
                _record_companion(state, result, scan_cik, accession)

        identity_validated_results.append(result)

    eligible_results = _eligible_results_for_state(
        state,
        identity_validated_results,
        record_issues=True,
    )
    eligible_bundle_ids = []

    if bundle_ids:
        eligible_bundle_id_set = {
            result.get("_filing_bundle_id") for result in eligible_results
        }
        eligible_bundle_ids = [
            bundle_id for bundle_id in bundle_ids if bundle_id in eligible_bundle_id_set
        ]

    plan = {
        "query_count": len(clean_queries),
        "query_hash": query_hash,
    }
    state["search_plan"] = plan
    state["server_scan"] = {
        **plan,
        "scan_id": coverage.get("scan_id"),
        "request_binding": "server_bound",
        "census_fingerprint": coverage.get("census_fingerprint"),
        "response_id": response_id,
        "artifact_id": artifact_id,
        "result_count": result_count,
        "total_filers": coverage.get("total_filers"),
        "checked_count": coverage.get("checked_count"),
        "candidate_filer_count": coverage.get("candidate_filer_count"),
        "candidate_count": coverage.get("candidate_count"),
        "not_checked_count": coverage.get("not_checked_count"),
        "failed_count": coverage.get("failed_count"),
        "checked": coverage.get("checked"),
        "not_checked": coverage.get("not_checked"),
        "failed": coverage.get("failed"),
        "incomplete_count": coverage.get("incomplete_count"),
        "incomplete": coverage.get("incomplete"),
        "complete": coverage.get("complete"),
        "census_complete": coverage.get("census_complete"),
        "census_issues": coverage.get("census_issues"),
        "checked_hit": coverage.get("checked_hit"),
        "checked_empty": coverage.get("checked_empty"),
        "results_complete": coverage.get("results_complete"),
        "delivered_result_count": coverage.get("delivered_result_count"),
        "omitted_result_count": coverage.get("omitted_result_count"),
        "mode": coverage.get("mode"),
        "retrieval_scope": coverage.get("retrieval_scope"),
        "negative_findings_supported": coverage.get("negative_findings_supported"),
        "classification_required": coverage.get("classification_required"),
        "retrieval_complete": coverage.get("retrieval_complete"),
        "partial_results": coverage.get("partial_results"),
        "comprehensive": coverage.get("comprehensive"),
        "recommended_follow_up": coverage.get("recommended_follow_up"),
        "candidate_results_capped": coverage.get("candidate_results_capped"),
        "candidate_discovery_status": coverage.get("candidate_discovery_status"),
        "sources": coverage.get("sources"),
        "sec_fts": coverage.get("sec_fts"),
        "search_issues": coverage.get("search_issues"),
        "exact_accessions_queued": coverage.get("exact_accessions_queued"),
        "temporary_ingestion": coverage.get("temporary_ingestion"),
        "exact_accessions_completed": coverage.get("exact_accessions_completed"),
        "exact_accessions_retrying": coverage.get("exact_accessions_retrying"),
        "exact_accessions_recovered": coverage.get("exact_accessions_recovered"),
        "exact_accessions_failed": coverage.get("exact_accessions_failed"),
        "expected_ingestion_delays": coverage.get("expected_ingestion_delays"),
        "unexpected_internal_gaps": coverage.get("unexpected_internal_gaps"),
        "unknown_age_gaps": coverage.get("unknown_age_gaps"),
        "internal_failure_categories": coverage.get("internal_failure_categories"),
        "sec_recovery_failure_categories": coverage.get("sec_recovery_failure_categories"),
        "recovery_issues": coverage.get("recovery_issues"),
        "recovery_scope": coverage.get("recovery_scope"),
        "outcomes": outcomes,
    }

    if "classification_required" not in coverage:
        state["server_scan"].pop("classification_required", None)
        state["server_scan"].pop("retrieval_complete", None)

    if bundle_ids:
        state["server_scan"]["bundle_ids"] = eligible_bundle_ids
        state["server_scan"]["discarded_out_of_window_bundle_count"] = (
            len(bundle_ids) - len(eligible_bundle_ids)
        )
    state["consumed_responses"][response_id] = "server_scan"
    state["consumed_artifacts"][artifact_id] = "server_scan"
    _validate_state(state)

    return eligible_results


def coverage_issues_page(
    state,
    *,
    limit=DEFAULT_COVERAGE_ISSUES,
    offset=0,
    code=None,
    candidate_reason=None,
    retryability=None,
    attachment_format=None,
):
    """Return one page of sanitized recovery and excluded-candidate issues."""
    _validate_state(state)
    scan = state.get("server_scan")

    if not isinstance(scan, dict):
        raise HelperError("The coverage state does not contain a completed server scan.")

    normalized_code = str(code or "").strip().lower() or None
    normalized_format = str(attachment_format or "").strip().lower() or None

    if normalized_code and FAILURE_REASON_RE.fullmatch(normalized_code) is None:
        raise HelperError("--code is not a valid stable failure code.")

    if candidate_reason not in {None, *CANDIDATE_ISSUE_REASONS}:
        raise HelperError("--candidate-reason is not a valid candidate exclusion reason.")

    if retryability not in {None, "retryable", "deterministic"}:
        raise HelperError("--retryability must be retryable or deterministic.")

    issues = []

    for issue in scan.get("recovery_issues") or []:
        issue_formats = {
            str(value).lower()
            for value in (
                issue.get("attachment_extension"),
                issue.get("response_content_type"),
            )
            if value
        }
        matches = (
            (normalized_code is None or issue.get("failure_code") == normalized_code)
            and (
                retryability is None
                or (retryability == "retryable") is bool(issue.get("retryable"))
            )
            and (normalized_format is None or normalized_format in issue_formats)
        )

        if matches:
            issues.append(issue)

    bounded_limit = max(1, min(int(limit), 100))
    normalized_offset = max(int(offset), 0)
    candidate_issues = [
        issue
        for issue in state["candidate_issues"]
        if candidate_reason is None or issue["reason"] == candidate_reason
    ]
    shown = issues[normalized_offset:normalized_offset + bounded_limit]
    remaining = max(len(issues) - normalized_offset - len(shown), 0)
    rv = {
        "scan_id": scan.get("scan_id"),
        "total_issue_count": len(scan.get("recovery_issues") or []),
        "matching_issue_count": len(issues),
        "offset": normalized_offset,
        "shown_count": len(shown),
        "remaining_issue_count": remaining,
        "issues": shown,
        "candidate_issue_count": len(state["candidate_issues"]),
        "matching_candidate_issue_count": len(candidate_issues),
        "candidate_issues": candidate_issues[
            normalized_offset:normalized_offset + bounded_limit
        ],
        "remaining_candidate_issue_count": max(
            len(candidate_issues) - normalized_offset - bounded_limit,
            0,
        ),
    }

    return rv


def classify_filing_bundles(state, bundle_ids, status):
    """Retain agent classifications for filing bundles bound to one server scan."""
    _validate_state(state)
    scan = state.get("server_scan")

    if not isinstance(scan, dict):
        raise HelperError("The coverage state does not contain a completed server scan.")

    if status not in FILING_BUNDLE_CLASSIFICATIONS:
        raise HelperError("The filing classification is invalid.")

    known_bundle_ids = set(scan.get("bundle_ids") or [])
    selected_bundle_ids = list(dict.fromkeys(bundle_ids or []))

    if not selected_bundle_ids:
        raise HelperError("Provide at least one filing bundle to classify.")

    if any(bundle_id not in known_bundle_ids for bundle_id in selected_bundle_ids):
        raise HelperError("A filing classification references an unknown server bundle.")

    for bundle_id in selected_bundle_ids:
        state["bundle_classifications"][bundle_id] = {
            "scan_id": scan["scan_id"],
            "status": status,
        }

    counts = {
        classification: sum(
            record.get("status") == classification
            and record.get("scan_id") == scan["scan_id"]
            for record in state["bundle_classifications"].values()
        )
        for classification in sorted(FILING_BUNDLE_CLASSIFICATIONS)
    }
    rv = {
        "scan_id": scan["scan_id"],
        "recorded_count": len(selected_bundle_ids),
        "classification_counts": counts,
        "classified_bundle_count": sum(counts.values()),
        "unclassified_bundle_count": max(len(known_bundle_ids) - sum(counts.values()), 0),
    }

    return rv


def coverage_audit(state):
    """Return a compact audit of recorded checks for every expected filer."""
    _validate_state(state)
    enumeration = state["enumeration"]
    scope = state["scope"]
    inconsistencies = list(dict.fromkeys(state["identity_issues"]))
    warnings = []
    accession_count = len(state["accessions"])
    server_outcome_ciks = (
        set(state.get("server_checked") or {})
        | set(state.get("server_not_checked") or {})
        | set(state.get("server_incomplete") or {})
        | set(state.get("failed") or {})
        if state.get("server_scan") is not None
        else set()
    )
    ticker_identity_is_resolved = all(
        _qualified_ticker(filer.get("search_ticker")) is not None
        or cik in state["broad_surfaced"]
        or cik in server_outcome_ciks
        for cik, filer in state["filers"].items()
    )

    if ticker_identity_is_resolved:
        inconsistencies = [
            value
            for value in inconsistencies
            if value not in {"malformed_ticker_alias", "malformed_ticker_aliases"}
        ]

    alias_owners = _alias_map(state)
    ambiguous_ciks = {
        cik
        for owners in alias_owners.values()
        if len(owners) > 1
        for cik in owners
    }
    authoritative_ciks = {
        cik
        for receipt in state["broad_searches"].values()
        for cik in receipt["authoritative_ciks"]
    }

    if ambiguous_ciks and ambiguous_ciks <= authoritative_ciks:
        inconsistencies = [
            value for value in inconsistencies if value != "ambiguous_ticker_alias"
        ]
        warnings.append("ambiguous_ticker_alias_resolved_by_cik")

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

    if state["unexpected"]:
        _append_unique(inconsistencies, "unexpected_in_scope_filer")

    if state["unexpected_accessions"]:
        _append_unique(inconsistencies, "unexpected_in_scope_accession")

    server_bound = state.get("server_scan") is not None

    if server_bound and state["server_scan"].get("results_complete") is not True:
        _append_unique(inconsistencies, "result_delivery_incomplete")

    if server_bound and state.get("server_incomplete"):
        _append_unique(inconsistencies, "fast_scan_incomplete")

    if server_bound and state.get("server_not_checked"):
        _append_unique(inconsistencies, "fast_scan_not_checked")

    sec_fts = state["server_scan"].get("sec_fts") if server_bound else None

    if (
        isinstance(sec_fts, dict)
        and (
            sec_fts.get("search_status") in {"partial", "unavailable"}
            or int(sec_fts.get("queries_truncated") or 0) > 0
        )
    ):
        _append_unique(inconsistencies, "fast_external_search_limited")

    if state["broad_failures"]:
        _append_unique(inconsistencies, "broad_search_failed")

    if scope.get("days") not in (1, 2, 3):
        _append_unique(inconsistencies, "unsupported_date_window")

    expected_forms = set(scope.get("expected_forms") or [])
    recorded_forms = set(state["broad_searches"])
    search_plan = state.get("search_plan")

    if state["filers"] and not server_bound and recorded_forms != expected_forms:
        _append_unique(inconsistencies, "missing_broad_search_receipt")

    if state["filers"] and search_plan is None:
        _append_unique(inconsistencies, "missing_search_plan")
    elif search_plan is not None and not server_bound:
        receipts = (
            list(state["broad_searches"].values())
            + list(state["broad_failures"].values())
            + list(state["individually_checked"].values())
        )

        if any(
            receipt.get("query_hash") != search_plan.get("query_hash")
            or receipt.get("query_count") != search_plan.get("query_count")
            for receipt in receipts
        ):
            _append_unique(inconsistencies, "search_plan_mismatch")

    unsearchable = sorted(
        cik
        for cik, filer in state["filers"].items()
        if _qualified_ticker(filer.get("search_ticker")) is None
        and cik not in state["broad_surfaced"]
        and cik not in state.get("server_checked", {})
        and cik not in state.get("server_not_checked", {})
        and cik not in state.get("server_incomplete", {})
        and (not server_bound or cik not in state["failed"])
    )
    missing = _missing_ciks(state)
    failed = sorted(state["failed"])
    not_checked = sorted(state.get("server_not_checked") or {})
    incomplete = sorted(state.get("server_incomplete") or {})
    ambiguous_candidate_issues = [
        issue
        for issue in state["candidate_issues"]
        if issue["reason"] not in HARMLESS_CANDIDATE_ISSUE_REASONS
    ]

    if ambiguous_candidate_issues:
        warnings.append("candidate_identity_limited")

    complete = (
        not inconsistencies
        and not unsearchable
        and not missing
        and not failed
        and not not_checked
        and not incomplete
    )
    scan_id = state["server_scan"].get("scan_id") if server_bound else None
    bundle_ids = set(state["server_scan"].get("bundle_ids") or []) if server_bound else set()
    classifications = {
        bundle_id: record
        for bundle_id, record in state.get("bundle_classifications", {}).items()
        if bundle_id in bundle_ids and record.get("scan_id") == scan_id
    }
    classification_counts = {
        classification: sum(
            record.get("status") == classification
            for record in classifications.values()
        )
        for classification in sorted(FILING_BUNDLE_CLASSIFICATIONS)
    }
    unclassified_bundle_count = max(len(bundle_ids) - len(classifications), 0)
    server_retrieval_complete = (
        state["server_scan"].get("retrieval_complete")
        if server_bound and "retrieval_complete" in state["server_scan"]
        else state["server_scan"].get("comprehensive")
        if server_bound
        else True
    )
    retrieval_complete = bool(
        complete
        and server_retrieval_complete is True
    )
    comprehensive = bool(
        retrieval_complete
        and (
            state["server_scan"].get("mode") == "thorough"
            if server_bound
            else True
        )
        and unclassified_bundle_count == 0
        and not ambiguous_candidate_issues
    )
    output = {
        "complete": complete,
        "scan_id": scan_id,
        "census_fingerprint": state["census_fingerprint"],
        "as_of": enumeration.get("as_of"),
        "selected_forms": scope.get("expected_forms") or [],
        "date_from": scope.get("date_from"),
        "date_to": scope.get("date_to"),
        "accession_count": accession_count,
        "filer_count": len(state["filers"]),
        "broad_search_form_count": len(state["broad_searches"]),
        "broad_search_failure_count": len(state["broad_failures"]),
        "broad_search_failures": [
            {"filing_type": form, "reason": failure["reason"]}
            for form, failure in sorted(state["broad_failures"].items())
        ],
        "broad_search_filer_count": len(set(state["broad_surfaced"])),
        "individually_checked_filer_count": len(state["individually_checked"]),
        "server_checked_filer_count": len(state.get("server_checked") or {}),
        "candidate_filer_count": (
            state["server_scan"].get("candidate_filer_count") if server_bound else None
        ),
        "candidate_count": (
            state["server_scan"].get("candidate_count") if server_bound else None
        ),
        "candidate_issue_count": len(state["candidate_issues"]),
        "ambiguous_candidate_issue_count": len(ambiguous_candidate_issues),
        "harmless_candidate_issue_count": (
            len(state["candidate_issues"]) - len(ambiguous_candidate_issues)
        ),
        "not_checked_filer_count": len(not_checked),
        "incomplete_filer_count": len(incomplete),
        "mode": state["server_scan"].get("mode") if server_bound else None,
        "retrieval_scope": (
            state["server_scan"].get("retrieval_scope") if server_bound else None
        ),
        "retrieval_complete": retrieval_complete,
        "negative_findings_supported": comprehensive,
        "comprehensive": comprehensive,
        "classification_counts": classification_counts,
        "classified_bundle_count": len(classifications),
        "unclassified_bundle_count": unclassified_bundle_count,
        "recommended_follow_up": (
            state["server_scan"].get("recommended_follow_up")
            if server_bound
            else None
        ),
        "partial_results": (
            state["server_scan"].get("partial_results") if server_bound else not complete
        ),
        "results_complete": (
            state["server_scan"].get("results_complete")
            if server_bound
            else None
        ),
        "delivered_result_count": (
            state["server_scan"].get("delivered_result_count")
            if server_bound
            else None
        ),
        "omitted_result_count": (
            state["server_scan"].get("omitted_result_count")
            if server_bound
            else None
        ),
        "joint_satisfied_filer_count": len(state["joint_satisfied"]),
        "failed_filer_count": len(failed),
        "failed_accession_count": (
            len(state["server_scan"].get("recovery_issues") or [])
            if server_bound
            else 0
        ),
        "search_issue_count": (
            len(state["server_scan"].get("search_issues") or [])
            if server_bound
            else 0
        ),
        "sec_fts": sec_fts,
        "retryable_accession_count": (
            sum(
                bool(issue.get("retryable"))
                for issue in state["server_scan"].get("recovery_issues") or []
            )
            if server_bound
            else 0
        ),
        "unsearchable_filer_count": len(unsearchable),
        "unpolled_filer_count": len(missing),
        "unexpected_filer_count": len(state["unexpected"]),
        "unexpected_accession_count": len(state["unexpected_accessions"]),
        "included_companion_filing_count": len(state["included_companions"]),
        "excluded_post_start_filing_count": len(state["excluded_post_census"]),
        "post_start_exclusion_note": (
            "1 filing was detected after the scan began but is not included here."
            if len(state["excluded_post_census"]) == 1
            else (
                f"{len(state['excluded_post_census'])} filings were detected after the "
                "scan began but are not included here."
                if state["excluded_post_census"]
                else ""
            )
        ),
        "request_binding": "server_bound" if server_bound else "agent_attested",
        "warnings": warnings,
        "coverage_issues": enumeration.get("issues") or [],
        "inconsistencies": inconsistencies,
    }
    return output


def _summary_index_path(artifact_path):
    return Path(f"{Path(artifact_path)}{SUMMARY_INDEX_SUFFIX}")


def _summary_index_payload(
    state,
    response_id,
    artifact_id,
    artifact_stat,
    summaries,
):
    return {
        "schema_version": SUMMARY_INDEX_VERSION,
        "kind": "filing_search_summary_index",
        "response_id": response_id,
        "artifact_id": artifact_id,
        "artifact_size": artifact_stat.st_size,
        "artifact_mtime_ns": artifact_stat.st_mtime_ns,
        "census_fingerprint": state["census_fingerprint"],
        "bundle_count": len(summaries),
        "summaries": summaries,
    }


def _write_summary_index(
    artifact_path,
    state,
    response_id,
    artifact_id,
    results,
    *,
    preview_chars=DEFAULT_PREVIEW_CHARS,
):
    """Persist compact eligible metadata next to one immutable search download."""
    summaries = _summaries_from_bundles(
        group_results(results),
        preview_chars=preview_chars,
    )
    try:
        artifact_stat = Path(artifact_path).stat()
    except OSError as exc:
        raise HelperError(f"Could not inspect the saved search response: {exc}.") from None

    payload = _summary_index_payload(
        state,
        response_id,
        artifact_id,
        artifact_stat,
        summaries,
    )
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    _write_atomic(_summary_index_path(artifact_path), body)
    return summaries


def _valid_saved_summary(value):
    required = {
        "bundle_id",
        "issuer_key",
        "ticker",
        "cik",
        "identity_conflict",
        "company",
        "date",
        "form",
        "score",
        "document_count",
        "candidate_sources",
        "attachment_hints",
        "metadata_only",
        "source_uri",
        "preview",
    }

    if not isinstance(value, dict) or set(value) != required:
        return False

    ticker = value["ticker"]
    cik = value["cik"]
    source_uri = value["source_uri"]
    return (
        isinstance(value["bundle_id"], str)
        and bool(value["bundle_id"])
        and isinstance(value["issuer_key"], str)
        and bool(value["issuer_key"])
        and (ticker is None or _qualified_ticker(ticker) is not None)
        and (cik is None or _valid_cik(cik) is not None)
        and isinstance(value["identity_conflict"], bool)
        and all(
            isinstance(value[key], str)
            for key in ("company", "date", "form", "preview")
        )
        and len(value["preview"]) <= DEFAULT_PREVIEW_CHARS
        and _finite_number(value["score"])
        and _valid_non_negative_integer(value["document_count"])
        and isinstance(value["candidate_sources"], list)
        and len(value["candidate_sources"]) <= 3
        and len(value["candidate_sources"]) == len(set(value["candidate_sources"]))
        and all(
            source in {"internal", "sec", "sec_fts"}
            for source in value["candidate_sources"]
        )
        and isinstance(value["attachment_hints"], list)
        and len(value["attachment_hints"]) <= 5
        and len(value["attachment_hints"]) == len(set(value["attachment_hints"]))
        and all(
            isinstance(hint, str) and 0 < len(hint) <= 160
            for hint in value["attachment_hints"]
        )
        and isinstance(value["metadata_only"], bool)
        and isinstance(source_uri, str)
        and (not source_uri or validate_sec_url(source_uri) == source_uri)
    )


def _load_summary_index(artifact_path, state):
    """Load a compact index only when it is bound to this artifact and census."""
    index_path = _summary_index_path(artifact_path)

    if not index_path.exists():
        return None

    try:
        payload = _load_json_value(index_path)
    except HelperError:
        return None
    required = {
        "schema_version",
        "kind",
        "response_id",
        "artifact_id",
        "artifact_size",
        "artifact_mtime_ns",
        "census_fingerprint",
        "bundle_count",
        "summaries",
    }

    if not isinstance(payload, dict) or set(payload) != required:
        return None

    try:
        resolved_artifact = Path(artifact_path).resolve(strict=True)
        response_path = str(resolved_artifact).encode("utf-8")
        artifact_stat = resolved_artifact.stat()
    except OSError:
        return None

    artifact_id = hashlib.sha256(response_path).hexdigest()
    response_id = payload.get("response_id")
    owner = state["consumed_artifacts"].get(artifact_id)
    summaries = payload.get("summaries")

    if (
        payload.get("schema_version") != SUMMARY_INDEX_VERSION
        or payload.get("kind") != "filing_search_summary_index"
        or payload.get("artifact_id") != artifact_id
        or payload.get("artifact_size") != artifact_stat.st_size
        or payload.get("artifact_mtime_ns") != artifact_stat.st_mtime_ns
        or payload.get("census_fingerprint") != state["census_fingerprint"]
        or not _valid_response_id(response_id)
        or owner is None
        or state["consumed_responses"].get(response_id) != owner
        or not isinstance(summaries, list)
        or payload.get("bundle_count") != len(summaries)
        or not all(_valid_saved_summary(summary) for summary in summaries)
        or _contains_capability_url(payload)
    ):
        return None

    return summaries


def _summary_page_from_summaries(
    summaries,
    *,
    limit,
    offset,
    preview_chars=DEFAULT_PREVIEW_CHARS,
):
    limit = max(1, min(int(limit), MAX_SUMMARIES))
    normalized_offset = max(0, offset)
    preview_chars = max(40, min(int(preview_chars), DEFAULT_PREVIEW_CHARS))
    shown = [
        {**summary, "preview": summary["preview"][:preview_chars]}
        for summary in summaries[normalized_offset : normalized_offset + limit]
    ]
    bundle_count = len(summaries)
    remaining = max(0, bundle_count - normalized_offset - len(shown))
    return {
        "bundle_count": bundle_count,
        "offset": normalized_offset,
        "shown_count": len(shown),
        "remaining_bundle_count": remaining,
        "truncated": remaining > 0,
        "shown": shown,
    }


def _summary_page(results, *, limit, offset, preview_chars):
    summaries = _summaries_from_bundles(
        group_results(results),
        preview_chars=DEFAULT_PREVIEW_CHARS,
    )
    return _summary_page_from_summaries(
        summaries,
        limit=limit,
        offset=offset,
        preview_chars=preview_chars,
    )


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
    summarize.add_argument(
        "--state",
        type=Path,
        help="Filter summaries to companies in one frozen coverage census.",
    )
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
    coverage_init.add_argument(
        "--save",
        type=Path,
        help="Save the fetched immutable census for this scan.",
    )

    coverage_import_scan = subparsers.add_parser("coverage-import-scan")
    coverage_import_scan.add_argument("--state", type=Path, required=True)
    scan_source = coverage_import_scan.add_mutually_exclusive_group(required=True)
    scan_source.add_argument("--artifact", type=Path)
    scan_source.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch, save, and validate one completed census-search artifact.",
    )
    coverage_import_scan.add_argument("--save", type=Path)
    coverage_import_scan.add_argument("--query", action="append", required=True)
    coverage_import_scan.add_argument(
        "--mode", choices=("fast", "thorough"), default="thorough"
    )
    coverage_import_scan.add_argument(
        "--results-per-query",
        type=int,
        default=5,
    )
    coverage_import_scan.add_argument("--limit", type=int, default=MAX_SUMMARIES)
    coverage_import_scan.add_argument("--offset", type=int, default=0)
    coverage_import_scan.add_argument(
        "--preview-chars", type=int, default=DEFAULT_PREVIEW_CHARS
    )

    coverage_reset = subparsers.add_parser("coverage-reset-searches")
    coverage_reset.add_argument("--state", type=Path, required=True)

    coverage_add_search = subparsers.add_parser("coverage-add-search")
    coverage_add_search.add_argument("--state", type=Path, required=True)
    coverage_add_search.add_argument("--expected-form", required=True)
    broad_source = coverage_add_search.add_mutually_exclusive_group(required=True)
    broad_source.add_argument("--artifact", type=Path)
    broad_source.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch, save, validate, and record one search capability in one operation.",
    )
    broad_source.add_argument(
        "--empty",
        action="store_true",
        help="Attest that the just-completed scoped search returned count=0.",
    )
    broad_source.add_argument(
        "--failed",
        action="store_true",
        help="Record a terminal form-scoped search failure after bounded retries.",
    )
    coverage_add_search.add_argument("--reason")
    coverage_add_search.add_argument("--save", type=Path)
    coverage_add_search.add_argument("--query", action="append", required=True)
    coverage_add_search.add_argument("--limit", type=int, default=MAX_SUMMARIES)
    coverage_add_search.add_argument("--offset", type=int, default=0)
    coverage_add_search.add_argument(
        "--preview-chars", type=int, default=DEFAULT_PREVIEW_CHARS
    )

    coverage_missing = subparsers.add_parser("coverage-missing")
    coverage_missing.add_argument("--state", type=Path, required=True)
    coverage_missing.add_argument("--limit", type=int, default=MAX_COVERAGE_ROWS)
    coverage_missing.add_argument("--offset", type=int, default=0)

    coverage_issues = subparsers.add_parser("coverage-issues")
    coverage_issues.add_argument("--state", type=Path, required=True)
    coverage_issues.add_argument("--limit", type=int, default=DEFAULT_COVERAGE_ISSUES)
    coverage_issues.add_argument("--offset", type=int, default=0)
    coverage_issues.add_argument("--code")
    coverage_issues.add_argument(
        "--candidate-reason", choices=tuple(sorted(CANDIDATE_ISSUE_REASONS))
    )
    coverage_issues.add_argument(
        "--retryability",
        choices=("retryable", "deterministic"),
    )
    coverage_issues.add_argument("--format", dest="attachment_format")

    coverage_classify = subparsers.add_parser("coverage-classify")
    coverage_classify.add_argument("--state", type=Path, required=True)
    coverage_classify.add_argument("--bundle", action="append", required=True)
    coverage_classify.add_argument(
        "--status",
        choices=tuple(sorted(FILING_BUNDLE_CLASSIFICATIONS)),
        required=True,
    )

    coverage_bind_ticker = subparsers.add_parser("coverage-bind-ticker")
    coverage_bind_ticker.add_argument("--state", type=Path, required=True)
    coverage_bind_ticker.add_argument("--cik", required=True)
    coverage_bind_ticker.add_argument("--ticker", required=True)

    coverage_mark = subparsers.add_parser("coverage-mark")
    coverage_mark.add_argument("--state", type=Path, required=True)
    coverage_identity = coverage_mark.add_mutually_exclusive_group(required=True)
    coverage_identity.add_argument("--ticker")
    coverage_identity.add_argument("--cik")
    coverage_mark.add_argument("--status", choices=("checked", "failed"), required=True)
    coverage_mark.add_argument("--reason")
    ticker_source = coverage_mark.add_mutually_exclusive_group()
    ticker_source.add_argument("--artifact", type=Path)
    ticker_source.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch, save, validate, and record one ticker search in one operation.",
    )
    ticker_source.add_argument(
        "--empty",
        action="store_true",
        help="Attest that the just-completed scoped ticker search returned count=0.",
    )
    coverage_mark.add_argument("--save", type=Path)
    coverage_mark.add_argument("--query", action="append")
    coverage_mark.add_argument("--limit", type=int, default=MAX_SUMMARIES)
    coverage_mark.add_argument("--offset", type=int, default=0)
    coverage_mark.add_argument(
        "--preview-chars", type=int, default=DEFAULT_PREVIEW_CHARS
    )

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

            summaries = None

            if arguments.state is not None:
                state = _load_state(arguments.state)
                summaries = _load_summary_index(artifact_path, state)

            if summaries is None:
                if arguments.state is not None:
                    (
                        results,
                        _result_count,
                        response_id,
                        artifact_id,
                    ) = load_search_response(artifact_path)
                    owner = state["consumed_artifacts"].get(artifact_id)

                    if (
                        owner is None
                        or state["consumed_responses"].get(response_id) != owner
                    ):
                        raise HelperError(
                            "The saved search artifact is not bound to an active "
                            "coverage receipt."
                        )

                    results = _eligible_results_for_state(state, results)
                else:
                    results = load_artifact(artifact_path)

                output = _summary_page(
                    results,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    preview_chars=arguments.preview_chars,
                )
            else:
                output = _summary_page_from_summaries(
                    summaries,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    preview_chars=arguments.preview_chars,
                )

            output["summary_index_used"] = summaries is not None
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
            if arguments.state.exists():
                raise HelperError(
                    "The coverage state already exists; one scan can initialize its census only once."
                )

            expected_forms = _normalized_expected_forms(arguments.expected_form)

            if arguments.fetch:
                if arguments.save is None:
                    raise HelperError("--save is required with coverage-init --fetch.")

                if arguments.save.resolve() == arguments.state.resolve():
                    raise HelperError("--save and --state must use different paths.")

                url = sys.stdin.read().strip()
                body = fetch_artifact_bytes(url)

                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise HelperError(
                        "The downloaded enumeration artifact is not valid UTF-8 JSON."
                    ) from exc
            else:
                if arguments.save is not None:
                    raise HelperError("--save is accepted only with coverage-init --fetch.")

                if arguments.artifact.resolve() == arguments.state.resolve():
                    raise HelperError(
                        "The census --artifact and --state must use different paths."
                    )

                payload = _load_json_value(arguments.artifact)

            state = _enumeration_state(payload, expected_forms)

            if arguments.fetch:
                _write_atomic(arguments.save, body)

            _write_state(arguments.state, state)
            output = {
                "enumeration_complete": state["enumeration"]["coverage_complete"],
                "census_fingerprint": state["census_fingerprint"],
                "as_of": state["enumeration"]["as_of"],
                "date_from": state["scope"]["date_from"],
                "date_to": state["scope"]["date_to"],
                "days": state["scope"]["days"],
                "selected_forms": state["scope"]["expected_forms"],
                "accession_count": len(state["accessions"]),
                "filer_count": len(state["filers"]),
                "missing_filer_count": len(_missing_ciks(state)),
                "coverage_issues": state["enumeration"]["issues"],
                "inconsistencies": state["identity_issues"],
            }

        elif arguments.command == "coverage-import-scan":
            state = _load_state(arguments.state)

            if arguments.fetch:
                if arguments.save is None:
                    raise HelperError("--save is required with coverage-import-scan --fetch.")

                if arguments.save.resolve() == arguments.state.resolve():
                    raise HelperError("--save and --state must use different paths.")

                url = sys.stdin.read().strip()
                body = fetch_artifact_bytes(url)
                _write_atomic(arguments.save, body)
                artifact_path = arguments.save

            else:
                if arguments.save is not None:
                    raise HelperError("--save is accepted only with --fetch.")

                artifact_path = arguments.artifact

            eligible_results = import_server_scan(
                state,
                artifact_path,
                arguments.query,
                arguments.results_per_query,
                mode=arguments.mode,
            )
            _write_state(arguments.state, state)
            results, bundle_count, response_id, artifact_id = load_search_response(artifact_path)
            summaries = _write_summary_index(
                artifact_path,
                state,
                response_id,
                artifact_id,
                eligible_results,
            )
            main_result_count = (
                len(state["server_scan"]["bundle_ids"])
                if "bundle_ids" in state["server_scan"]
                else len(eligible_results)
            )
            output = {
                "status": "recorded",
                "request_binding": "server_bound",
                "scan_id": state["server_scan"].get("scan_id"),
                "result_count": bundle_count,
                "provider_delivered_result_count": bundle_count,
                "eligible_result_count": main_result_count,
                "main_result_count": main_result_count,
                "eligible_evidence_count": len(eligible_results),
                "checked_filer_count": len(state["server_checked"]),
                "candidate_filer_count": state["server_scan"].get(
                    "candidate_filer_count"
                ),
                "candidate_count": state["server_scan"].get("candidate_count"),
                "not_checked_filer_count": len(state["server_not_checked"]),
                "failed_filer_count": len(state["failed"]),
                "incomplete_filer_count": len(state["server_incomplete"]),
                "failed_accession_count": len(
                    state["server_scan"].get("recovery_issues") or []
                ),
                "search_issue_count": len(
                    state["server_scan"].get("search_issues") or []
                ),
                "sec_fts": state["server_scan"].get("sec_fts"),
                "coverage_issues_available": True,
                "candidate_issue_count": len(state["candidate_issues"]),
                "excluded_candidate_issue_count": len(state["candidate_issues"]),
                "candidate_issues": state["candidate_issues"][:DEFAULT_COVERAGE_ISSUES],
                "remaining_candidate_issue_count": max(
                    len(state["candidate_issues"]) - DEFAULT_COVERAGE_ISSUES,
                    0,
                ),
                "recommended_follow_up": state["server_scan"].get(
                    "recommended_follow_up"
                ),
                "missing_filer_count": len(_missing_ciks(state)),
                "included_companion_filing_count": len(state["included_companions"]),
                "summary_index_available": True,
                **_summary_page_from_summaries(
                    summaries,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    preview_chars=arguments.preview_chars,
                ),
            }

        elif arguments.command == "coverage-reset-searches":
            state = _load_state(arguments.state)
            fingerprint = state["census_fingerprint"]
            reset_searches(state)
            _write_state(arguments.state, state)
            output = {
                "status": "searches_reset",
                "census_fingerprint": fingerprint,
                "as_of": state["enumeration"]["as_of"],
                "selected_forms": state["scope"]["expected_forms"],
                "accession_count": len(state["accessions"]),
                "filer_count": len(state["filers"]),
                "missing_filer_count": len(_missing_ciks(state)),
                "coverage_issues": state["enumeration"]["issues"],
            }

        elif arguments.command == "coverage-issues":
            state = _load_state(arguments.state)
            output = coverage_issues_page(
                state,
                limit=arguments.limit,
                offset=arguments.offset,
                code=arguments.code,
                candidate_reason=arguments.candidate_reason,
                retryability=arguments.retryability,
                attachment_format=arguments.attachment_format,
            )

        elif arguments.command == "coverage-classify":
            state = _load_state(arguments.state)
            output = classify_filing_bundles(
                state,
                arguments.bundle,
                arguments.status,
            )
            _write_state(arguments.state, state)

        elif arguments.command == "coverage-add-search":
            state = _load_state(arguments.state)
            eligible_results = []
            summaries = []
            summary_index_available = False

            if arguments.fetch:
                if arguments.save is None:
                    raise HelperError("--save is required with coverage-add-search --fetch.")
                if arguments.save.resolve() == arguments.state.resolve():
                    raise HelperError("--save and --state must use different paths.")
                url = sys.stdin.read().strip()
                body = fetch_artifact_bytes(url)
                _write_atomic(arguments.save, body)
                artifact_path = arguments.save
            else:
                if arguments.save is not None:
                    raise HelperError("--save is accepted only with --fetch.")
                artifact_path = arguments.artifact

            if arguments.failed:
                if arguments.reason is None:
                    raise HelperError("--reason is required with --failed.")

                recorded_form = fail_broad_search(
                    state,
                    arguments.expected_form,
                    arguments.query,
                    arguments.reason,
                )
                added_count = 0
            elif arguments.empty:
                if arguments.reason is not None:
                    raise HelperError("--reason is accepted only with --failed.")

                results = []
                result_count = 0
                response_id = None
                artifact_id = None
            else:
                if arguments.reason is not None:
                    raise HelperError("--reason is accepted only with --failed.")

                results, result_count, response_id, artifact_id = load_search_response(
                    artifact_path
                )

            if not arguments.failed:
                added_count, eligible_results = add_broad_search_results(
                    state,
                    results,
                    arguments.expected_form,
                    arguments.query,
                    result_count=result_count,
                    response_id=response_id,
                    artifact_id=artifact_id,
                    attested_empty=arguments.empty,
                    return_eligible=True,
                )
                recorded_form = _normalized_form(arguments.expected_form)

                if artifact_path is not None:
                    summaries = _write_summary_index(
                        artifact_path,
                        state,
                        response_id,
                        artifact_id,
                        eligible_results,
                    )
                    summary_index_available = True

            _write_state(arguments.state, state)
            output = {
                "added_filer_count": added_count,
                "recorded_form": recorded_form,
                "status": "failed" if arguments.failed else "recorded",
                "broad_search_form_count": len(state["broad_searches"]),
                "broad_search_failure_count": len(state["broad_failures"]),
                "broad_search_filer_count": len(state["broad_surfaced"]),
                "missing_filer_count": len(_missing_ciks(state)),
                "unexpected_filer_count": len(state["unexpected"]),
                "included_companion_filing_count": len(state["included_companions"]),
                "excluded_post_start_filing_count": len(state["excluded_post_census"]),
                "identity_issues": state["identity_issues"],
                "summary_index_available": summary_index_available,
                **_summary_page_from_summaries(
                    summaries,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    preview_chars=arguments.preview_chars,
                ),
            }

        elif arguments.command == "coverage-missing":
            state = _load_state(arguments.state)
            output = missing_filers(
                state,
                offset=arguments.offset,
                limit=arguments.limit,
            )

        elif arguments.command == "coverage-bind-ticker":
            state = _load_state(arguments.state)
            cik, ticker = bind_resolved_ticker(
                state,
                arguments.cik,
                arguments.ticker,
            )
            _write_state(arguments.state, state)
            output = {
                "cik": cik,
                "ticker": ticker,
                "status": "bound",
                "missing_filer_count": len(_missing_ciks(state)),
            }

        elif arguments.command == "coverage-mark":
            state = _load_state(arguments.state)
            eligible_results = []
            summaries = []
            summary_index_available = False
            artifact_path = None

            if arguments.status == "checked":
                if arguments.reason is not None:
                    raise HelperError("--reason is accepted only when --status failed.")

                if not (arguments.artifact is not None or arguments.fetch or arguments.empty):
                    raise HelperError(
                        "Use --artifact or --fetch for non-empty results, or --empty for "
                        "count=0 when --status checked."
                    )

                if arguments.fetch:
                    if arguments.save is None:
                        raise HelperError("--save is required with coverage-mark --fetch.")
                    if arguments.save.resolve() == arguments.state.resolve():
                        raise HelperError("--save and --state must use different paths.")
                    url = sys.stdin.read().strip()
                    body = fetch_artifact_bytes(url)
                    _write_atomic(arguments.save, body)
                    artifact_path = arguments.save
                else:
                    if arguments.save is not None:
                        raise HelperError("--save is accepted only with --fetch.")
                    artifact_path = arguments.artifact

                if arguments.empty:
                    results = []
                    result_count = 0
                    response_id = None
                    artifact_id = None
                else:
                    results, result_count, response_id, artifact_id = load_search_response(
                        artifact_path
                    )
            else:
                if (
                    arguments.artifact is not None
                    or arguments.fetch
                    or arguments.empty
                    or arguments.save is not None
                    or arguments.query is not None
                ):
                    raise HelperError(
                        "Search sources, --save, and --query are accepted only when "
                        "--status checked."
                    )

                results = None
                result_count = None
                response_id = None
                artifact_id = None

            cik, eligible_results = mark_filer(
                state,
                arguments.ticker,
                arguments.status,
                arguments.reason,
                cik_value=arguments.cik,
                results=results,
                result_count=result_count,
                queries=arguments.query,
                response_id=response_id,
                artifact_id=artifact_id,
                attested_empty=arguments.empty,
                return_eligible=True,
            )

            if arguments.status == "checked" and artifact_path is not None:
                summaries = _write_summary_index(
                    artifact_path,
                    state,
                    response_id,
                    artifact_id,
                    eligible_results,
                )
                summary_index_available = True

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
                "included_companion_filing_count": len(state["included_companions"]),
                "excluded_post_start_filing_count": len(state["excluded_post_census"]),
                "summary_index_available": summary_index_available,
                **_summary_page_from_summaries(
                    summaries,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    preview_chars=arguments.preview_chars,
                ),
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
