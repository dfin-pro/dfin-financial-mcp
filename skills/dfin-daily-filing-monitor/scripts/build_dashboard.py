#!/usr/bin/env python3
"""Build a safe filing-monitor dashboard from compact and artifact-delivered data."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ALLOWED_HOST = "www.dfin.pro"
ARTIFACT_PATH_RE = re.compile(r"^/api/v1/artifacts/[A-Za-z0-9_-]+/?$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
QUALIFIED_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]*\.[A-Z0-9]{2,8}$")
BADGE_BACKGROUNDS = (
    "#101923",
    "#142231",
    "#1d2935",
    "#12ce5d",
    "#0f9d49",
    "#167247",
    "#d2b90a",
)
BADGE_FOREGROUNDS = ("#ffffff", "#cae8d7")
PILL_CLASSES = {
    "pill-in",
    "pill-out",
    "pill-promo",
    "pill-board",
    "pill-interim",
    "pill-deal",
    "pill-debt",
    "pill-spin",
    "pill-event",
}
RATIO_PERCENT_FIELDS = {
    "returnOnEquity": "roe",
    "returnOnInvestedCapital": "roic",
    "ebitdaMargin": "em",
}
STOCK_CACHE_KEYS = {
    "company_name",
    "ticker",
    "cik",
    "fy_end",
    "sector",
    "industry",
    "subindustry",
    "description",
    "p",
    "pc",
    "pp",
    "mc",
    "pe",
    "b",
    "r",
    "lo",
    "hi",
    "cur",
    "rb",
    "rc",
    "v",
    "vr",
    "vh",
    "eps",
}


class HelperError(Exception):
    """Report one expected helper failure without a traceback."""


class ArtifactRefreshRequired(HelperError):
    """Tell the caller to request a fresh single-use capability URL."""


def validate_stock_artifact_url(value):
    """Return an approved single-use DFin artifact URL."""
    if not isinstance(value, str) or not value:
        raise HelperError("A stock-context artifact URL is missing.")

    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HelperError("The stock-context artifact URL is malformed.") from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not ARTIFACT_PATH_RE.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise HelperError(
            "A stock-context URL is not an approved DFin capability URL."
        )

    return value


def validate_sec_url(value):
    """Return one approved SEC HTTPS URL, or an empty string."""
    if not isinstance(value, str) or not value:
        return ""

    parsed = urlparse(value)

    try:
        port = parsed.port
    except ValueError:
        return ""

    hostname = (parsed.hostname or "").lower()

    if (
        parsed.scheme != "https"
        or not (hostname == "sec.gov" or hostname.endswith(".sec.gov"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        return ""

    return value


def _canonical_ticker(value):
    text = str(value or "").strip().upper()
    return text if QUALIFIED_TICKER_RE.fullmatch(text) else ""


def _canonical_cik(value):
    text = str(value or "").strip()
    return text.lstrip("0").zfill(10) if text.isdigit() else ""


def _retry_delay(response, body):
    candidates = [response.headers.get("Retry-After")]

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


def fetch_stock_context(
    url,
    *,
    attempts=3,
    timeout=45,
    open_url=urlopen,
    sleep=time.sleep,
):
    """Fetch one single-use stock package, retrying only explicit 202 states."""
    validate_stock_artifact_url(url)

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
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        raise ArtifactRefreshRequired(
                            "The stock-context artifact returned invalid JSON; "
                            "request one fresh URL."
                        ) from None

                    if not isinstance(payload, dict):
                        raise ArtifactRefreshRequired(
                            "The stock-context artifact shape is invalid; "
                            "request one fresh URL."
                        )

                    return payload

                if status == 202:
                    if attempt + 1 < attempts:
                        sleep(_retry_delay(response, body))
                        continue

                    raise ArtifactRefreshRequired(
                        "The stock-context artifact remained in processing; "
                        "request one fresh URL."
                    )

                raise ArtifactRefreshRequired(
                    "The stock-context artifact could not be consumed; "
                    "request one fresh URL."
                )
        except HTTPError as exc:
            if exc.code == 202 and attempt + 1 < attempts:
                sleep(_retry_delay(exc, exc.read()))
                continue

            raise ArtifactRefreshRequired(
                "The stock-context artifact could not be consumed; "
                "request one fresh URL."
            ) from None
        except (TimeoutError, URLError, OSError):
            raise ArtifactRefreshRequired(
                "The single-use stock-context fetch failed; request one fresh URL."
            ) from None

    raise ArtifactRefreshRequired(
        "The stock-context artifact remained unavailable; request one fresh URL."
    )


def _markdown_section(markdown, heading):
    """Return one ATX-heading section without crossing into the next section."""
    match = re.search(
        rf"(?ms)^{re.escape(heading)}[ \t]*\n(.*?)(?=^#{{1,3}}[ \t]+|\Z)",
        markdown,
    )
    return match.group(1).strip() if match else ""


def _semicolon_fields(line):
    """Parse compact `Label: value; ...` fields without interpreting values."""
    fields = {}

    for part in line.split(";"):
        if ":" not in part:
            continue

        key, value = part.split(":", 1)
        fields[key.strip()] = value.strip()

    return fields


def _inline_stock_markdown(markdown):
    """Convert one compact inline stock-context document to structured fields."""
    if not isinstance(markdown, str) or not markdown or len(markdown) > 100_000:
        raise HelperError("An inline stock-context result is malformed or oversized.")

    heading = re.search(r"(?m)^#\s+(.+?)\s+\(([^()]+)\)\s*$", markdown)

    if not heading:
        raise HelperError("An inline stock-context result has no ticker heading.")

    company_name = heading.group(1).strip()
    ticker = _canonical_ticker(heading.group(2))

    if not ticker:
        raise HelperError("An inline stock-context result has an invalid ticker.")

    price_fields = _semicolon_fields(_markdown_section(markdown, "## Price"))
    price_value = price_fields.get("Price", "")
    price_match = re.match(r"^(\S+)(?:\s+[A-Z]{3})?$", price_value)
    change_value = price_fields.get("Change", "")
    change_match = re.match(r"^(.*?)\s+\(([^()]+)\)$", change_value)
    high_low = [
        value.strip()
        for value in price_fields.get("52w H/L", "").split("/", 1)
    ]
    volume_average = [
        value.strip()
        for value in price_fields.get("Volume/52w avg", "").split("/", 1)
    ]
    price = {
        "price": price_match.group(1) if price_match else price_value,
        "change": change_match.group(1).strip() if change_match else change_value,
        "change_percent": change_match.group(2).strip() if change_match else "",
        "high_52_week": high_low[0] if len(high_low) == 2 else "",
        "low_52_week": high_low[1] if len(high_low) == 2 else "",
        "volume": volume_average[0] if len(volume_average) == 2 else "",
        "average_volume_52_week": (
            volume_average[1] if len(volume_average) == 2 else ""
        ),
        "market_cap": price_fields.get("Market cap", ""),
        "forward_pe": price_fields.get("Forward P/E", ""),
    }

    returns_section = _markdown_section(markdown, "## Returns")
    one_year_match = re.search(
        r"(?mi)^\|\s*1y\s*\|\s*([^|]+?)\s*\|",
        returns_section,
    )
    to_date_match = re.search(r"(?m)^To date:\s*(.+)$", returns_section)
    to_date = _semicolon_fields(to_date_match.group(1)) if to_date_match else {}
    returns = {
        "to_date_returns": {
            key.lower(): to_date.get(key)
            for key in ("WTD", "MTD", "YTD")
            if to_date.get(key) is not None
        },
        "trailing_returns": {
            "1y": {
                "cumulative": one_year_match.group(1).strip()
                if one_year_match
                else None
            }
        },
    }

    profile_fields = _semicolon_fields(_markdown_section(markdown, "### Profile"))
    profile = {
        "cik": profile_fields.get("CIK", ""),
        "fiscal_year_end": profile_fields.get("FY end", ""),
        "gics_sector": profile_fields.get("Sector", ""),
        "gics_industry": profile_fields.get("Industry", ""),
        "gics_subindustry": profile_fields.get("Subindustry", ""),
    }
    technical_fields = _semicolon_fields(
        _markdown_section(markdown, "### Technicals")
    )
    earnings = {}

    for line in _markdown_section(markdown, "### Earnings History").splitlines():
        if not line.lstrip().startswith("|"):
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]

        if len(cells) < 6 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue

        earnings[cells[0]] = {
            "eps_actual": cells[2],
            "eps_estimate": cells[3],
            "surprise_percent": cells[5],
        }

    return {
        "ticker": ticker,
        "company_name": company_name,
        "price": price,
        "returns": returns,
        "profile": profile,
        "description": _markdown_section(markdown, "### Description"),
        "technicals": {"beta": technical_fields.get("Beta")},
        "earnings_history": earnings,
    }


def _stock_batch_results(payload):
    """Validate a ticker-keyed stock-context batch without exposing unused fields."""
    results = payload.get("results") if isinstance(payload, dict) else None
    count = payload.get("count") if isinstance(payload, dict) else None
    success_count = payload.get("success_count") if isinstance(payload, dict) else None
    error_count = payload.get("error_count") if isinstance(payload, dict) else None

    if (
        not isinstance(results, dict)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or not isinstance(success_count, int)
        or isinstance(success_count, bool)
        or not isinstance(error_count, int)
        or isinstance(error_count, bool)
        or count != len(results)
        or success_count + error_count != count
    ):
        raise HelperError("The stock-context artifact does not contain ticker-keyed results.")

    validated = {}

    for ticker, result in results.items():
        canonical_ticker = _canonical_ticker(ticker)

        if not canonical_ticker or not isinstance(result, dict):
            raise HelperError("The stock-context artifact contains an invalid ticker result.")

        data_value = result.get("data")
        has_data = isinstance(data_value, (dict, str))
        has_error = isinstance(result.get("error"), dict)

        if has_data == has_error or canonical_ticker in validated:
            raise HelperError("The stock-context artifact contains an invalid ticker result.")

        if isinstance(data_value, str):
            result = dict(result)
            result["data"] = _inline_stock_markdown(data_value)

        validated[canonical_ticker] = result

    observed_successes = sum("data" in result for result in validated.values())

    if observed_successes != success_count:
        raise HelperError("The stock-context artifact contains inconsistent ticker counts.")

    return validated


def _number(value):
    """Parse one formatted numeric value without treating missing data as zero."""
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None

    if not isinstance(value, str):
        return None

    text = value.strip().replace("−", "-")

    if not text or text in {"—", "-", "N/A", "NA", "null"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.+-]", "", text)

    try:
        number = float(cleaned)
    except ValueError:
        return None

    return -number if negative else number


def _format_compact(value):
    number = _number(value)

    if number is None:
        return "—"

    absolute = abs(number)

    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if absolute >= threshold:
            return f"{number / threshold:.1f}{suffix}"

    return f"{number:,.0f}"


def _return_value(value):
    return _number(value)


def _format_ratio(value, *, percentage=False):
    number = _number(value)

    if number is None:
        return "—"

    if percentage:
        return f"{number * 100:.1f}%"

    return f"{number:.2f}×"


def _safe_tags(value):
    if not isinstance(value, list):
        return []

    return list(
        dict.fromkeys(
            tag
            for tag in value
            if isinstance(tag, str) and TAG_RE.fullmatch(tag)
        )
    )


def _safe_events(value):
    if not isinstance(value, list):
        return []

    events = []

    for row in value:
        if not isinstance(row, list) or len(row) != 4:
            continue

        pill, label, subject, detail = row
        events.append(
            [
                pill if isinstance(pill, str) and pill in PILL_CLASSES else "pill-event",
                str(label or "Event"),
                str(subject or ""),
                str(detail or ""),
            ]
        )

    return events


def _safe_filings(value):
    if not isinstance(value, list):
        return [], bool(value)

    filings = []
    invalid = False

    for filing in value:
        if not isinstance(filing, dict):
            invalid = True
            continue

        bundle_id = filing.get("id")

        if not isinstance(bundle_id, str) or not bundle_id.strip():
            invalid = True
            continue

        tags = _safe_tags(filing.get("tags"))
        flag = bool(filing.get("flag"))

        if flag and "flagged" not in tags:
            tags.append("flagged")
        elif not flag and "confirmed" not in tags:
            tags.append("confirmed")

        filings.append(
            {
                "id": bundle_id.strip(),
                "ft": str(filing.get("ft") or "Filing"),
                "fd": str(filing.get("fd") or "—"),
                "fl": validate_sec_url(filing.get("fl")),
                "tags": tags,
                "flag": flag,
                "flagnote": str(filing.get("flagnote") or ""),
                "ev": _safe_events(filing.get("ev")),
                "docs": max(0, int(_number(filing.get("docs")) or 0)),
            }
        )

    return filings, invalid


def _canonical_form(value):
    return " ".join(str(value or "").split()).upper()


def _canonical_filing_date(value):
    text = " ".join(str(value or "").split())

    if not text or text == "—":
        return None

    for date_format in (
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
    ):
        try:
            parsed = datetime.strptime(text, date_format).date()
            return (parsed.year, parsed.month, parsed.day)
        except ValueError:
            continue

    for date_format in ("%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(
                f"{text} 2000",
                f"{date_format} %Y",
            ).date()
            return (None, parsed.month, parsed.day)
        except ValueError:
            continue

    return ("text", text.casefold())


def _filing_dates_conflict(current, incoming):
    if current is None or incoming is None:
        return False

    if current[0] == "text" or incoming[0] == "text":
        return current != incoming

    current_year, current_month, current_day = current
    incoming_year, incoming_month, incoming_day = incoming

    if (current_month, current_day) != (incoming_month, incoming_day):
        return True

    return bool(
        current_year
        and incoming_year
        and current_year != incoming_year
    )


def _merge_filing_lists(existing, incoming, blocked=None):
    """Merge repeated bundle IDs and omit locally conflicting bundles."""
    order = []
    by_id = {}
    blocked = set(blocked or ())
    conflict = False

    for filing in [*existing, *incoming]:
        bundle_id = filing["id"]

        if bundle_id in blocked:
            continue

        if bundle_id not in by_id:
            by_id[bundle_id] = dict(filing)
            by_id[bundle_id]["tags"] = list(filing["tags"])
            by_id[bundle_id]["ev"] = [list(event) for event in filing["ev"]]
            order.append(bundle_id)
            continue

        current = by_id[bundle_id]

        current_form = _canonical_form(current["ft"])
        incoming_form = _canonical_form(filing["ft"])
        current_date = _canonical_filing_date(current["fd"])
        incoming_date = _canonical_filing_date(filing["fd"])
        form_conflict = (
            current_form != incoming_form
            and current_form != "FILING"
            and incoming_form != "FILING"
        )
        date_conflict = _filing_dates_conflict(current_date, incoming_date)

        if form_conflict or date_conflict:
            conflict = True
            blocked.add(bundle_id)
            by_id.pop(bundle_id, None)
            order = [value for value in order if value != bundle_id]
            continue

        if current_form == "FILING" and incoming_form != "FILING":
            current["ft"] = filing["ft"]

        if current["fd"] == "—" and filing["fd"] != "—":
            current["fd"] = filing["fd"]

        current["tags"] = list(dict.fromkeys([*current["tags"], *filing["tags"]]))
        current["flag"] = current["flag"] or filing["flag"]

        if current["flag"]:
            current["tags"] = [tag for tag in current["tags"] if tag != "confirmed"]

            if "flagged" not in current["tags"]:
                current["tags"].append("flagged")
        else:
            current["tags"] = [tag for tag in current["tags"] if tag != "flagged"]

            if "confirmed" not in current["tags"]:
                current["tags"].append("confirmed")

        if not current["flagnote"] and filing["flagnote"]:
            current["flagnote"] = filing["flagnote"]

        if not current["fl"] and filing["fl"]:
            current["fl"] = filing["fl"]

        current["docs"] = max(current["docs"], filing["docs"])
        seen_events = {tuple(event) for event in current["ev"]}

        for event in filing["ev"]:
            event_key = tuple(event)

            if event_key not in seen_events:
                current["ev"].append(list(event))
                seen_events.add(event_key)

    return [by_id[bundle_id] for bundle_id in order], conflict, blocked


def _normalized_companies(companies):
    """Merge manifest company records around ticker-primary identities."""
    merged = {}
    order = []

    for index, company in enumerate(companies):
        if not isinstance(company, dict):
            continue

        ticker = str(company.get("ticker") or company.get("t") or "").strip()
        canonical_ticker = _canonical_ticker(ticker)
        cik = _canonical_cik(company.get("cik"))
        filings, invalid_filings = _safe_filings(
            company.get("filings") or company.get("fs")
        )

        if canonical_ticker:
            identity = f"ticker:{canonical_ticker}"
        elif cik:
            identity = f"cik:{cik}"
        elif filings:
            identity = f"bundle:{filings[0]['id']}"
        else:
            identity = f"record:{index}"

        if identity not in merged:
            normalized_filings, filing_conflict, blocked_bundle_ids = (
                _merge_filing_lists([], filings)
            )
            merged[identity] = {
                "_identity": identity,
                "_canonical_ticker": canonical_ticker,
                "_identity_conflict": False,
                "_manifest_issues": (
                    ["manifest_conflict"]
                    if filing_conflict or invalid_filings
                    else []
                ),
                "_blocked_bundle_ids": blocked_bundle_ids,
                "ticker": ticker,
                "name": str(company.get("name") or company.get("n") or ""),
                "cik": cik,
                "exchange": str(company.get("exchange") or ""),
                "ratios": company.get("ratios"),
                "bg": company.get("bg"),
                "fg": company.get("fg"),
                "filings": normalized_filings,
            }
            order.append(identity)
            continue

        current = merged[identity]

        if invalid_filings and "manifest_conflict" not in current["_manifest_issues"]:
            current["_manifest_issues"].append("manifest_conflict")

        if not current["name"] and (company.get("name") or company.get("n")):
            current["name"] = str(company.get("name") or company.get("n"))

        if not current["exchange"] and company.get("exchange"):
            current["exchange"] = str(company.get("exchange"))

        if current["cik"] and cik and current["cik"] != cik:
            current["_identity_conflict"] = True

            if "manifest_conflict" not in current["_manifest_issues"]:
                current["_manifest_issues"].append("manifest_conflict")
        elif not current["cik"] and cik:
            current["cik"] = cik

        if current["ratios"] is None and company.get("ratios") is not None:
            current["ratios"] = company.get("ratios")

        (
            current["filings"],
            filing_conflict,
            current["_blocked_bundle_ids"],
        ) = _merge_filing_lists(
            current["filings"], filings, current["_blocked_bundle_ids"]
        )

        if filing_conflict and "manifest_conflict" not in current["_manifest_issues"]:
            current["_manifest_issues"].append("manifest_conflict")

    renderable = []
    diagnostics = []

    for identity in order:
        company = merged[identity]

        if company["filings"]:
            renderable.append(company)
            continue

        if not company["_manifest_issues"]:
            continue

        stock_status = (
            "identity_mismatch"
            if company["_identity_conflict"]
            else "not_requested"
            if company["_canonical_ticker"]
            else "unresolved"
        )
        diagnostics.append(
            {
                "ticker": company["ticker"],
                "stock_context": stock_status,
                "manifest_issues": company["_manifest_issues"],
            }
        )

    return renderable, diagnostics


def _stock_identity_matches(expected_ticker, expected_cik, stock):
    if _canonical_ticker(stock.get("ticker")) != expected_ticker:
        return False

    stock_cik = _canonical_cik(stock.get("cik"))
    return not (expected_cik and stock_cik and expected_cik != stock_cik)


def _sanitize_stock_cache_entry(value):
    if not isinstance(value, dict):
        return None

    return {key: value[key] for key in STOCK_CACHE_KEYS if key in value}


def _ratio_identity_matches(expected_ticker, ratios):
    return (
        isinstance(ratios, dict)
        and _canonical_ticker(ratios.get("ticker")) == expected_ticker
    )


def extract_stock_fields(payload):
    """Allowlist and normalize the stock fields used by the dashboard."""
    price = payload.get("price") if isinstance(payload.get("price"), dict) else {}
    returns = (
        payload.get("returns") if isinstance(payload.get("returns"), dict) else {}
    )
    to_date = (
        returns.get("to_date_returns")
        if isinstance(returns.get("to_date_returns"), dict)
        else {}
    )
    trailing = (
        returns.get("trailing_returns")
        if isinstance(returns.get("trailing_returns"), dict)
        else {}
    )
    one_year = trailing.get("1y") if isinstance(trailing.get("1y"), dict) else {}
    profile = (
        payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    )
    technicals = (
        payload.get("technicals")
        if isinstance(payload.get("technicals"), dict)
        else {}
    )
    earnings = (
        payload.get("earnings_history")
        if isinstance(payload.get("earnings_history"), dict)
        else {}
    )

    current = _number(price.get("price"))
    low = _number(price.get("low_52_week"))
    high = _number(price.get("high_52_week"))
    volume = _number(price.get("volume"))
    average_volume = _number(price.get("average_volume_52_week"))
    volume_ratio = (
        volume / average_volume
        if volume is not None and average_volume not in (None, 0)
        else None
    )
    change_percent = _return_value(price.get("change_percent"))
    returns_row = [
        change_percent,
        _return_value(to_date.get("wtd")),
        _return_value(to_date.get("mtd")),
        _return_value(to_date.get("ytd")),
        _return_value(one_year.get("cumulative")),
    ]

    eps = []

    for period in sorted(earnings)[-4:]:
        row = earnings.get(period)

        if not isinstance(row, dict):
            continue

        actual = _number(row.get("eps_actual"))
        estimate = _number(row.get("eps_estimate"))

        if actual is None or estimate is None or actual == estimate:
            beat = -1
        else:
            beat = 1 if actual > estimate else 0

        surprise = _number(row.get("surprise_percent"))
        title = period

        if surprise is not None:
            title += f": {surprise:+.1f}%"

        eps.append([beat, title])

    range_position = (
        (current - low) / (high - low) * 100
        if current is not None
        and low is not None
        and high is not None
        and high > low
        else None
    )
    range_badge = None
    range_class = None

    if range_position is not None and range_position <= 10:
        range_badge = "↓ Near 52W Low"
        range_class = "badge-low"
    elif range_position is not None and range_position >= 95:
        range_badge = "★ Near 52W High"
        range_class = "badge-high"

    result = {
        "company_name": str(payload.get("company_name") or ""),
        "ticker": str(payload.get("ticker") or ""),
        "cik": str(profile.get("cik") or ""),
        "fy_end": str(profile.get("fiscal_year_end") or ""),
        "sector": str(profile.get("gics_sector") or ""),
        "industry": str(profile.get("gics_industry") or ""),
        "subindustry": str(profile.get("gics_subindustry") or ""),
        "description": str(payload.get("description") or ""),
        "p": str(price.get("price") or "—"),
        "pc": " ".join(
            value
            for value in (
                str(price.get("change") or "").strip(),
                f"({price.get('change_percent')})"
                if price.get("change_percent")
                else "",
            )
            if value
        ),
        "pp": (
            True
            if change_percent is not None and change_percent > 0
            else False
            if change_percent is not None and change_percent < 0
            else None
        ),
        "mc": str(price.get("market_cap") or "—"),
        "pe": str(price.get("forward_pe") or "—"),
        "b": (
            f"{_number(technicals.get('beta')):.2f}"
            if _number(technicals.get("beta")) is not None
            else "—"
        ),
        "r": returns_row,
        "lo": low,
        "hi": high,
        "cur": current,
        "rb": range_badge,
        "rc": range_class,
        "v": _format_compact(volume),
        "vr": f"{volume_ratio:.2f}×" if volume_ratio is not None else None,
        "vh": volume_ratio > 1.5 if volume_ratio is not None else False,
        "eps": eps,
    }
    return result


def _ratio_fields(ratios, fiscal_year_end):
    if not isinstance(ratios, dict):
        ratios = {}

    values = ratios.get("ratios")
    values = values if isinstance(values, dict) else ratios
    year = ratios.get("year")
    output = {
        short_key: _format_ratio(values.get(source_key), percentage=True)
        for source_key, short_key in RATIO_PERCENT_FIELDS.items()
    }
    output["nd"] = _format_ratio(values.get("netDebtToEBITDA"))

    if isinstance(year, int):
        output["rvintage"] = f"FY{year}"

        if fiscal_year_end:
            output["rvintage"] += f" · {fiscal_year_end} year-end"
    else:
        output["rvintage"] = ""

    return output


def build_data(manifest, *, stock_fetcher=fetch_stock_context, stock_cache=None):
    """Build allowlisted dashboard DATA from a compact manifest."""
    if not isinstance(manifest, dict):
        raise HelperError("The dashboard manifest must be a JSON object.")

    companies = manifest.get("companies")

    if not isinstance(companies, list):
        raise HelperError("The dashboard manifest requires a companies list.")

    provided_stock_cache = stock_cache if isinstance(stock_cache, dict) else {}
    stock_cache = {}
    output_companies = []
    statuses = []
    normalized_companies, normalization_diagnostics = _normalized_companies(companies)
    sanitized_provided_cache = {
        ticker: sanitized
        for key, value in provided_stock_cache.items()
        if (ticker := _canonical_ticker(key))
        if (sanitized := _sanitize_stock_cache_entry(value)) is not None
    }
    requested_tickers = {
        company["_canonical_ticker"]
        for company in normalized_companies
        if company["_canonical_ticker"] and not company["_identity_conflict"]
    }
    uncached_tickers = requested_tickers.difference(sanitized_provided_cache)
    stock_url = manifest.get("stock_context_url")
    inline_stock_context = manifest.get("stock_context")
    fresh_results = {}
    batch_status = "not_requested"

    if stock_url and inline_stock_context is not None:
        raise HelperError(
            "Provide either stock_context_url or stock_context, not both."
        )

    if uncached_tickers:
        if stock_url:
            try:
                batch_payload = stock_fetcher(stock_url)
                fresh_results = _stock_batch_results(batch_payload)
                batch_status = "ok"
                del batch_payload
            except ArtifactRefreshRequired:
                batch_status = "refresh_required"
            except HelperError:
                batch_status = "invalid"
        elif inline_stock_context is not None:
            try:
                fresh_results = _stock_batch_results(inline_stock_context)
                batch_status = "ok"
            except HelperError:
                batch_status = "invalid"

    for index, company in enumerate(normalized_companies):
        ticker = company["ticker"]
        canonical_ticker = company["_canonical_ticker"]
        expected_cik = company["cik"]
        cached_stock = sanitized_provided_cache.get(canonical_ticker)
        fresh_result = fresh_results.get(canonical_ticker)
        stock = {}
        stock_status = "not_requested"

        if not canonical_ticker:
            stock_status = "unresolved"
        elif company["_identity_conflict"]:
            stock_status = "identity_mismatch"
        elif isinstance(cached_stock, dict):
            if _stock_identity_matches(canonical_ticker, expected_cik, cached_stock):
                stock = cached_stock
                stock_cache[canonical_ticker] = cached_stock
                stock_status = "cached"
            else:
                stock_status = "identity_mismatch"
        elif isinstance(fresh_result, dict) and isinstance(fresh_result.get("data"), dict):
            try:
                candidate_stock = extract_stock_fields(fresh_result["data"])

                if _stock_identity_matches(
                    canonical_ticker,
                    expected_cik,
                    candidate_stock,
                ):
                    stock = candidate_stock
                    stock_cache[canonical_ticker] = stock
                    stock_status = "ok"
                else:
                    stock_status = "identity_mismatch"
            except HelperError:
                stock_status = "invalid"
        elif isinstance(fresh_result, dict) and isinstance(fresh_result.get("error"), dict):
            error_type = str(fresh_result["error"].get("type") or "availability")
            stock_status = (
                "identity_mismatch"
                if error_type == "identity_mismatch"
                else "unavailable"
            )
        elif batch_status in {"refresh_required", "invalid"}:
            stock_status = batch_status
        elif batch_status == "ok":
            stock_status = "unavailable"

        fiscal_year_end = stock.get("fy_end", "")
        ratios = company.get("ratios")
        ratio_identity_mismatch = False

        if stock_status in {"identity_mismatch", "unresolved"}:
            usable_ratios = None
        elif isinstance(ratios, dict) and ratios:
            if _ratio_identity_matches(canonical_ticker, ratios):
                usable_ratios = ratios
            else:
                usable_ratios = None
                ratio_identity_mismatch = True
        else:
            usable_ratios = None

        ratio_fields = _ratio_fields(
            usable_ratios,
            fiscal_year_end,
        )
        exchange = str(company.get("exchange") or "")
        sector = stock.get("subindustry") or stock.get("sector") or ""
        subtitle = " · ".join(value for value in (exchange, sector) if value)
        background = company.get("bg")
        foreground = company.get("fg")

        if background not in BADGE_BACKGROUNDS:
            background = BADGE_BACKGROUNDS[index % len(BADGE_BACKGROUNDS)]

        if foreground not in BADGE_FOREGROUNDS:
            foreground = "#ffffff"

        output_company = {
            "t": ticker,
            "cik": str(expected_cik or stock.get("cik") or ""),
            "n": str(
                company.get("name")
                or company.get("n")
                or stock.get("company_name")
                or ticker
            ),
            "s": subtitle,
            "bg": background,
            "fg": foreground,
            "p": stock.get("p", "—"),
            "pc": stock.get("pc", ""),
            "pp": stock.get("pp"),
            "mc": stock.get("mc", "—"),
            "b": stock.get("b", "—"),
            "r": stock.get("r", [None, None, None, None, None]),
            "lo": stock.get("lo"),
            "hi": stock.get("hi"),
            "cur": stock.get("cur"),
            "rb": stock.get("rb"),
            "rc": stock.get("rc"),
            "v": stock.get("v", "—"),
            "vr": stock.get("vr"),
            "vh": stock.get("vh", False),
            "pe": stock.get("pe", "—"),
            "eps": stock.get("eps", []),
            "d": stock.get("description", ""),
            "fs": company["filings"],
            **ratio_fields,
        }
        output_companies.append(output_company)
        status = {"ticker": ticker, "stock_context": stock_status}

        if company["_manifest_issues"]:
            status["manifest_issues"] = company["_manifest_issues"]

        if ratio_identity_mismatch:
            status["ratio_context"] = "ratio_identity_mismatch"

        statuses.append(status)

    statuses.extend(normalization_diagnostics)

    bundle_count = sum(len(company["fs"]) for company in output_companies)
    confirmed = sum(
        1
        for company in output_companies
        for filing in company["fs"]
        if not filing["flag"]
    )
    flagged = bundle_count - confirmed
    filters = [
        ["all", f"All ({bundle_count})"],
        ["confirmed", f"Confirmed ({confirmed})"],
        ["flagged", f"Flagged ({flagged})"],
    ]
    requested_filters = manifest.get("filters")

    if isinstance(requested_filters, list):
        existing = {row[0] for row in filters}

        for row in requested_filters:
            if (
                isinstance(row, list)
                and len(row) == 2
                and isinstance(row[0], str)
                and TAG_RE.fullmatch(row[0])
                and row[0] not in existing
            ):
                filters.append([row[0], str(row[1])])
                existing.add(row[0])

    data = {
        "title": str(manifest.get("title") or "Filing Monitor"),
        "ftype": str(manifest.get("ftype") or "8-K / 6-K"),
        "range": str(manifest.get("range") or ""),
        "stats": [
            [len(output_companies), "Companies"],
            [bundle_count, "Filing bundles"],
            [confirmed, "Confirmed"],
            [flagged, "Flagged"],
        ],
        "filters": filters,
        "cos": output_companies,
    }
    return data, statuses, stock_cache


def html_safe_json(value):
    """Serialize JSON safely for an HTML script-data element."""
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    replacements = {
        "&": "\\u0026",
        "<": "\\u003c",
        ">": "\\u003e",
        "\u2028": "\\u2028",
        "\u2029": "\\u2029",
    }

    for source, target in replacements.items():
        serialized = serialized.replace(source, target)

    return serialized


def render_dashboard(template, data):
    """Inject safe JSON into exactly one dashboard template marker."""
    marker = "/* INJECT_DATA */"

    if template.count(marker) != 1:
        raise HelperError("The dashboard template must contain one data marker.")

    return template.replace(marker, html_safe_json(data))


def compact_text_rows(data):
    """Return only the filing, event, price, change, and one-year text fields."""
    rows = []

    for company in data.get("cos", []):
        returns = company.get("r")
        one_year = returns[4] if isinstance(returns, list) and len(returns) > 4 else None

        for filing in company.get("fs", []):
            rows.append(
                {
                    "ticker": company.get("t") or "—",
                    "company": company.get("n") or "",
                    "events": filing.get("ev") or [],
                    "price": company.get("p") or "—",
                    "change": company.get("pc") or "",
                    "one_year": one_year,
                    "filing": filing.get("fl") or "",
                    "form": filing.get("ft") or "Filing",
                    "date": filing.get("fd") or "—",
                    "flag": bool(filing.get("flag")),
                    "flagnote": filing.get("flagnote") or "",
                }
            )

    return rows


def _write_atomic_text(path, text):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
        text=True,
    )

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output_file:
            output_file.write(text)
            output_file.flush()
            os.fsync(output_file.fileno())

        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _argument_parser():
    parser = argparse.ArgumentParser(
        description="Build a safe filing-monitor result from a JSON manifest on stdin."
    )
    parser.add_argument("--template", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--text",
        action="store_true",
        help="Emit compact text-mode rows instead of writing a dashboard.",
    )
    parser.add_argument(
        "--stock-cache",
        type=Path,
        help="Temporary allowlisted stock fields for retrying a failed batch.",
    )
    return parser


def main(argv=None):
    parser = _argument_parser()

    try:
        arguments = parser.parse_args(argv)

        try:
            manifest = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            raise HelperError(
                f"Invalid dashboard manifest JSON at line {exc.lineno}, "
                f"column {exc.colno}."
            ) from None

        if arguments.text:
            if arguments.template is not None or arguments.output is not None:
                raise HelperError("Do not use --template or --output with --text.")
            template = None
        else:
            if arguments.template is None or arguments.output is None:
                raise HelperError(
                    "Dashboard mode requires both --template and --output."
                )

            try:
                template = arguments.template.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise HelperError(
                    f"Could not read the dashboard template: {exc}."
                ) from None

        stock_cache = {}

        if arguments.stock_cache and arguments.stock_cache.exists():
            try:
                cached_value = json.loads(
                    arguments.stock_cache.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HelperError(f"Could not read the temporary stock cache: {exc}.") from None

            if not isinstance(cached_value, dict):
                raise HelperError("The temporary stock cache must contain a JSON object.")

            stock_cache = cached_value

        data, statuses, stock_cache = build_data(
            manifest,
            stock_cache=stock_cache,
        )

        if arguments.stock_cache:
            _write_atomic_text(
                arguments.stock_cache,
                json.dumps(
                    stock_cache,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )

        if arguments.text:
            status = {
                "rows": compact_text_rows(data),
                "stock_context": statuses,
            }
        else:
            rendered = render_dashboard(template, data)
            _write_atomic_text(arguments.output, rendered)
            status = {
                "saved": str(arguments.output.resolve()),
                "companies": len(data["cos"]),
                "filing_bundles": sum(
                    len(company["fs"]) for company in data["cos"]
                ),
                "stock_context": statuses,
            }
        json.dump(status, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "Hint: pass compact manifest JSON on stdin; request a fresh "
            "get_stock_context batch URL when status is refresh_required.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
