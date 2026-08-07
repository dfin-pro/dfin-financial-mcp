#!/usr/bin/env python3
"""Fetch, summarize, and select evidence from DFin filing artifacts."""

from __future__ import annotations

import argparse
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
DEFAULT_PREVIEW_CHARS = 220
DEFAULT_EVIDENCE_CHARS = 800
MAX_SUMMARIES = 15
MAX_DOC_UUIDS = 20


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
    return parser


def main(argv=None):
    """Run the helper and emit exactly one compact JSON value."""
    parser = _argument_parser()

    try:
        arguments = parser.parse_args(argv)

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
        else:
            results = load_artifact(arguments.artifact)
            output = {
                "selected": select_bundles(
                    results,
                    arguments.bundle,
                    evidence_chars=arguments.evidence_chars,
                )
            }

        json.dump(output, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Hint: keep the capability URL private, use summarize first, "
            "then select only the bundles that need evidence.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
