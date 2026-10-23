"""
Gateway-specific Excel import adapters.

Each adapter reads raw DataFrames from an Excel file and produces
a list of normalized record dictionaries ready for database insertion.

Rules:
- Use Decimal for all monetary values, never float arithmetic
- Preserve source row numbers (1-indexed including header)
- Log warnings without silently discarding rows
- Never guess column meanings — raise explicit errors for missing required cols
- Do not normalize currencies that cannot be identified
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

KNOWN_CURRENCIES = {
    "INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY", "CHF",
    "HKD", "MYR", "THB", "IDR", "PHP", "VND", "KRW", "NZD", "MXN", "BRL",
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _optional_text(value: Any) -> Optional[str]:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_currency(raw: Any) -> Optional[str]:
    if _is_missing(raw):
        return None
    code = str(raw).strip().upper()
    if code in KNOWN_CURRENCIES:
        return code
    return code if len(code) == 3 and code.isalpha() else None


def safe_decimal(value: Any, field_name: str = "") -> Tuple[Optional[Decimal], Optional[str]]:
    """Return (decimal_value, warning_message). Never raises."""
    if _is_missing(value):
        return None, None
    raw = str(value).strip().replace(",", "")
    if raw == "" or raw.lower() in ("nan", "none", "null", "-"):
        return None, None
    try:
        return Decimal(raw), None
    except InvalidOperation:
        return None, f"Cannot parse '{raw}' as decimal for field '{field_name}'"


def parse_dt_gwa(raw: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """Parse Gateway A date strings: DD/MM/YYYY HH:MM:SS or DD-MM-YYYY."""
    if _is_missing(raw):
        return None, None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw, None
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc), None
        except ValueError:
            continue
    return None, f"Cannot parse date '{s}'"


def parse_dt_gwb(raw: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """Parse Gateway B timestamps (pandas already parses most as datetime64)."""
    if _is_missing(raw):
        return None, None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw, None
    if hasattr(raw, "to_pydatetime"):
        dt = raw.to_pydatetime()
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt, None
    return parse_dt_gwa(raw)


def find_header_row(filepath: str, sheet_name: str, max_scan: int = 10) -> int:
    """Return 0-indexed row of the best header row (most non-blank cells)."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb[sheet_name]
    best_row, best_count = 0, 0
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True)):
        count = sum(1 for c in row if c is not None and str(c).strip())
        if count > best_count:
            best_count = count
            best_row = i  # 0-indexed for pandas
    wb.close()
    return best_row


@dataclass
class ParseResult:
    records: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    rejected_rows: int = 0
    total_rows: int = 0

    def add_warning(self, row_number: int, field_name: str, message: str,
                    raw_value: Any = None, severity: str = "warning") -> None:
        self.warnings.append({
            "row_number": row_number,
            "field_name": field_name,
            "message": message,
            "raw_value": str(raw_value)[:200] if raw_value is not None else None,
            "severity": severity,
        })


# ---------------------------------------------------------------------------
# Gateway A — Payments Adapter
# ---------------------------------------------------------------------------

GWA_PAYMENTS_REQUIRED = {"id", "amount", "currency", "status", "order_id", "created_at"}


def parse_gwa_payments(filepath: str) -> ParseResult:
    """Parse GatewayA_payments_*.xlsx (Sheet1, header row 2 → 0-indexed=1)."""
    result = ParseResult()
    sheet_name = "Sheet1"
    header_row = find_header_row(filepath, sheet_name)
    df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row, engine="openpyxl")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    result.total_rows = len(df)

    missing_required = GWA_PAYMENTS_REQUIRED - set(df.columns)
    if missing_required:
        raise ValueError(f"GatewayA payments missing required columns: {missing_required}")

    for idx, row in df.iterrows():
        row_num = int(idx) + header_row + 2  # 1-indexed source row
        rec: Dict[str, Any] = {
            "gateway": "gateway_a",
            "dataset_type": "gwa_payments",
            "source_row_number": row_num,
            "raw_data": {k: (None if (isinstance(v, float) and pd.isna(v)) else str(v))
                         for k, v in row.items()},
        }
        warnings_for_row: List[str] = []

        # Required: id
        pid = row.get("id")
        if pid is None or (isinstance(pid, float) and pd.isna(pid)):
            result.add_warning(row_num, "id", "Payment ID is blank — row skipped", severity="error")
            result.rejected_rows += 1
            continue
        rec["source_identifier"] = str(pid).strip()
        rec["gateway_payment_id"] = str(pid).strip()

        # Amount
        gross, warn = safe_decimal(row.get("amount"), "amount")
        if warn:
            result.add_warning(row_num, "amount", warn, row.get("amount"))
        rec["gross_amount"] = gross

        # Currency
        currency = normalize_currency(row.get("currency"))
        if not currency:
            result.add_warning(row_num, "currency", f"Unrecognized currency: {row.get('currency')}", severity="error")
            result.rejected_rows += 1
            continue
        rec["currency"] = currency

        # Status
        status = str(row.get("status", "")).strip().lower()
        rec["status"] = status if status else "unknown"

        # Order ID
        oid = row.get("order_id")
        rec["gateway_order_id"] = str(oid).strip() if oid and not (isinstance(oid, float) and pd.isna(oid)) else None

        # Fee and Tax
        fee, warn = safe_decimal(row.get("fee"), "fee")
        if warn:
            result.add_warning(row_num, "fee", warn, row.get("fee"))
        rec["fee"] = fee
        rec["fee_currency"] = "INR"  # GatewayA fees are INR per data profile

        tax, warn = safe_decimal(row.get("tax"), "tax")
        if warn:
            result.add_warning(row_num, "tax", warn, row.get("tax"))
        rec["tax"] = tax
        rec["tax_currency"] = "INR"

        # Amount refunded
        amt_refunded, _ = safe_decimal(row.get("amount_refunded"), "amount_refunded")
        rec["amount_refunded"] = amt_refunded

        # Payment method
        method = row.get("method")
        rec["payment_method"] = str(method).strip() if method and not (isinstance(method, float) and pd.isna(method)) else None

        # International flag
        intl = row.get("international")
        rec["is_international"] = bool(int(intl)) if intl is not None and not (isinstance(intl, float) and pd.isna(intl)) else None

        # Captured
        captured = row.get("captured")
        rec["is_captured"] = bool(int(captured)) if captured is not None and not (isinstance(captured, float) and pd.isna(captured)) else None

        # Card details
        rec["card_network"] = str(row.get("card_network", "")).strip() or None
        rec["card_type"] = str(row.get("card_type", "")).strip() or None
        rec["error_code"] = str(row.get("error_code", "")).strip() or None

        # Timestamp
        dt, warn = parse_dt_gwa(row.get("created_at"))
        if warn:
            result.add_warning(row_num, "created_at", warn, row.get("created_at"))
        rec["transacted_at"] = dt

        # Extra metadata
        rec["gateway_metadata"] = {
            "auth_code": str(row.get("auth_code", "")).strip() or None,
            "arn": str(row.get("payments_arn", "")).strip() or None,
            "rrn": str(row.get("payments_rrn", "")).strip() or None,
            "refund_status": str(row.get("refund_status", "")).strip() or None,
            "flow": str(row.get("flow", "")).strip() or None,
        }

        result.records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Gateway A — Transactions Adapter
# ---------------------------------------------------------------------------

GWA_TXN_REQUIRED = {"entity_id", "type", "currency", "created_at"}


def parse_gwa_transactions(filepath: str) -> ParseResult:
    """Parse GatewayA_transactions_*.xlsx (Sheet1, header row 1 → 0-indexed=0)."""
    result = ParseResult()
    sheet_name = "Sheet1"
    header_row = find_header_row(filepath, sheet_name)
    df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row, engine="openpyxl")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    result.total_rows = len(df)

    missing_required = GWA_TXN_REQUIRED - set(df.columns)
    if missing_required:
        raise ValueError(f"GatewayA transactions missing required columns: {missing_required}")

    for idx, row in df.iterrows():
        row_num = int(idx) + header_row + 2
        rec: Dict[str, Any] = {
            "gateway": "gateway_a",
            "dataset_type": "gwa_transactions",
            "source_row_number": row_num,
            "raw_data": {k: (None if (isinstance(v, float) and pd.isna(v)) else str(v))
                         for k, v in row.items()},
        }

        # entity_id is the transaction identifier (could be payment id, refund id, etc.)
        eid = row.get("entity_id")
        if eid is None or (isinstance(eid, float) and pd.isna(eid)):
            result.add_warning(row_num, "entity_id", "entity_id is blank — row skipped", severity="error")
            result.rejected_rows += 1
            continue
        rec["source_identifier"] = str(eid).strip()
        rec["gateway_txn_id"] = str(eid).strip()

        # Type
        txn_type = str(row.get("type", "")).strip().lower()
        rec["txn_type"] = txn_type or "unknown"

        # Currency
        currency = normalize_currency(row.get("currency"))
        if not currency:
            result.add_warning(row_num, "currency", f"Unrecognized currency: {row.get('currency')}")
            currency = "INR"  # GatewayA txns are all INR per profile
        rec["currency"] = currency

        # Amounts
        for col, field in [("debit", "debit_amount"), ("credit", "credit_amount"),
                             ("amount", "gross_amount"), ("fee", "fee"), ("tax", "tax")]:
            val, warn = safe_decimal(row.get(col), col)
            if warn:
                result.add_warning(row_num, col, warn, row.get(col))
            rec[field] = val

        # Settlement info
        sid = row.get("settlement_id")
        rec["settlement_id"] = str(sid).strip() if sid and not (isinstance(sid, float) and pd.isna(sid)) else None
        utr = row.get("settlement_utr")
        rec["settlement_utr"] = str(utr).strip() if utr and not (isinstance(utr, float) and pd.isna(utr)) else None

        # Order ID
        oid = row.get("order_id")
        rec["gateway_order_id"] = str(oid).strip() if oid and not (isinstance(oid, float) and pd.isna(oid)) else None

        # Settled flag
        settled = row.get("settled")
        rec["is_settled"] = bool(int(settled)) if settled is not None and not (isinstance(settled, float) and pd.isna(settled)) else None

        # Card details
        rec["card_network"] = str(row.get("card_network", "")).strip() or None
        rec["card_type"] = str(row.get("card_type", "")).strip() or None
        rec["payment_method"] = str(row.get("method", "")).strip() or None

        # Timestamps
        dt_created, warn = parse_dt_gwa(row.get("created_at"))
        if warn:
            result.add_warning(row_num, "created_at", warn, row.get("created_at"))
        rec["transacted_at"] = dt_created

        dt_settled, warn = parse_dt_gwa(row.get("settled_at"))
        if warn:
            result.add_warning(row_num, "settled_at", warn, row.get("settled_at"))
        rec["settled_at"] = dt_settled

        # dispute
        rec["gateway_metadata"] = {
            "dispute_id": str(row.get("dispute_id", "")).strip() or None,
            "card_issuer": str(row.get("card_issuer", "")).strip() or None,
            "order_receipt": str(row.get("order_receipt", "")).strip() or None,
            "on_hold": row.get("on_hold"),
        }

        result.records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Gateway A — Refunds Adapter
# ---------------------------------------------------------------------------

GWA_REFUND_REQUIRED = {"id", "amount", "currency", "payment_id", "created_at", "status"}


def parse_gwa_refunds(filepath: str) -> ParseResult:
    """Parse GatewayA_refunds_*.xlsx (Sheet1, header row 2 → 0-indexed=1)."""
    result = ParseResult()
    sheet_name = "Sheet1"
    header_row = find_header_row(filepath, sheet_name)
    df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row, engine="openpyxl")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    result.total_rows = len(df)

    missing_required = GWA_REFUND_REQUIRED - set(df.columns)
    if missing_required:
        raise ValueError(f"GatewayA refunds missing required columns: {missing_required}")

    for idx, row in df.iterrows():
        row_num = int(idx) + header_row + 2
        rec: Dict[str, Any] = {
            "gateway": "gateway_a",
            "dataset_type": "gwa_refunds",
            "source_row_number": row_num,
            "raw_data": {k: (None if (isinstance(v, float) and pd.isna(v)) else str(v))
                         for k, v in row.items()},
        }

        rid = row.get("id")
        if rid is None or (isinstance(rid, float) and pd.isna(rid)):
            result.add_warning(row_num, "id", "Refund ID is blank — row skipped", severity="error")
            result.rejected_rows += 1
            continue
        rec["source_identifier"] = str(rid).strip()
        rec["gateway_refund_id"] = str(rid).strip()

        # Amount
        amount, warn = safe_decimal(row.get("amount"), "amount")
        if warn:
            result.add_warning(row_num, "amount", warn, row.get("amount"))
        if amount is None:
            result.add_warning(row_num, "amount", "Refund amount is missing — row skipped", severity="error")
            result.rejected_rows += 1
            continue
        rec["amount"] = amount

        # Currency
        currency = normalize_currency(row.get("currency"))
        if not currency:
            result.add_warning(row_num, "currency", f"Unrecognized currency: {row.get('currency')}", severity="error")
            result.rejected_rows += 1
            continue
        rec["currency"] = currency

        # Payment link
        pid = row.get("payment_id")
        rec["gateway_payment_id"] = str(pid).strip() if pid and not (isinstance(pid, float) and pd.isna(pid)) else None

        # Status
        rec["status"] = str(row.get("status", "")).strip().lower() or "unknown"

        # ARN — stored as large float in profile, convert carefully
        arn_raw = row.get("arn")
        if arn_raw is not None and not (isinstance(arn_raw, float) and pd.isna(arn_raw)):
            try:
                # Excel stores ARN as float — convert via Decimal to avoid scientific notation
                rec["arn"] = str(Decimal(str(arn_raw)).to_integral_value())
            except Exception:
                rec["arn"] = str(arn_raw)
        else:
            rec["arn"] = None

        # Timestamp
        dt, warn = parse_dt_gwa(row.get("created_at"))
        if warn:
            result.add_warning(row_num, "created_at", warn, row.get("created_at"))
        rec["refunded_at"] = dt

        result.records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Gateway B — Balance Transactions Adapter
# ---------------------------------------------------------------------------

GWB_REQUIRED = {"balance_transaction_id", "currency", "gross", "fee", "net", "reporting_category"}


def parse_gwb_balance(filepath: str) -> ParseResult:
    """Parse GatewayB_*.xlsx (sheet 'GatewayB Sep'26', header row 2 → 0-indexed=1)."""
    result = ParseResult()
    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    # Find the correct sheet — name may contain special apostrophe
    sheet_name = None
    for sn in wb.sheetnames:
        if "gateway" in sn.lower() or "gwb" in sn.lower():
            sheet_name = sn
            break
    wb.close()
    if sheet_name is None:
        raise ValueError(f"Cannot find GatewayB sheet in {filepath}. Available: {wb.sheetnames}")

    header_row = find_header_row(filepath, sheet_name)
    df = pd.read_excel(filepath, sheet_name=sheet_name, header=header_row, engine="openpyxl")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    result.total_rows = len(df)

    missing_required = GWB_REQUIRED - set(df.columns)
    if missing_required:
        raise ValueError(f"GatewayB balance transactions missing required columns: {missing_required}")

    for idx, row in df.iterrows():
        row_num = int(idx) + header_row + 2
        rec: Dict[str, Any] = {
            "gateway": "gateway_b",
            "dataset_type": "gwb_balance",
            "source_row_number": row_num,
            "raw_data": {k: (None if (isinstance(v, float) and pd.isna(v)) else str(v))
                         for k, v in row.items()},
        }

        txn_id = row.get("balance_transaction_id")
        if txn_id is None or (isinstance(txn_id, float) and pd.isna(txn_id)):
            result.add_warning(row_num, "balance_transaction_id", "Transaction ID is blank — row skipped", severity="error")
            result.rejected_rows += 1
            continue
        rec["source_identifier"] = str(txn_id).strip()
        rec["gateway_txn_id"] = str(txn_id).strip()

        # Reporting category → txn_type
        cat = str(row.get("reporting_category", "")).strip().lower()
        rec["txn_type"] = cat or "unknown"
        rec["reporting_category"] = cat

        # Currency
        currency = normalize_currency(row.get("currency"))
        if not currency:
            result.add_warning(row_num, "currency", f"Unrecognized currency: {row.get('currency')}")
            currency = "INR"
        rec["currency"] = currency

        # Amounts — GWB has gross, fee, net directly
        for col, field in [("gross", "gross_amount"), ("fee", "fee"), ("net", "net_amount")]:
            val, warn = safe_decimal(row.get(col), col)
            if warn:
                result.add_warning(row_num, col, warn, row.get(col))
            rec[field] = val

        # Customer-facing (cross-currency)
        cf_amount, _ = safe_decimal(row.get("customer_facing_amount"), "customer_facing_amount")
        rec["customer_facing_amount"] = cf_amount
        cf_curr = normalize_currency(row.get("customer_facing_currency"))
        rec["customer_facing_currency"] = cf_curr

        # Source/charge links
        sid = row.get("source_id")
        rec["gateway_payment_id"] = _optional_text(sid)

        charge_id = row.get("charge_id")
        pmt_intent = row.get("payment_intent_id")

        # Geography
        country = _optional_text(row.get("country"))
        rec["country"] = country.upper() if country else None

        # Card details
        rec["card_brand"] = _optional_text(row.get("card_brand"))
        rec["card_network"] = _optional_text(row.get("card_network"))
        rec["card_funding"] = _optional_text(row.get("card_funding"))

        # Payout/settlement
        payout_id = row.get("automatic_payout_id")
        rec["payout_id"] = _optional_text(payout_id)

        # Timestamps — GWB timestamps already parsed as datetime64 by pandas
        dt_created, warn = parse_dt_gwb(row.get("created_utc"))
        if warn:
            result.add_warning(row_num, "created_utc", warn, row.get("created_utc"))
        rec["transacted_at"] = dt_created

        dt_avail, warn = parse_dt_gwb(row.get("available_on_utc"))
        if warn:
            result.add_warning(row_num, "available_on_utc", warn, row.get("available_on_utc"))
        rec["available_on"] = dt_avail

        dt_payout, warn = parse_dt_gwb(row.get("automatic_payout_effective_at_utc"))
        if warn:
            result.add_warning(row_num, "automatic_payout_effective_at_utc", warn)
        rec["settled_at"] = dt_payout

        rec["is_settled"] = rec["payout_id"] is not None

        rec["gateway_metadata"] = {
            "charge_id": _optional_text(charge_id),
            "payment_intent_id": _optional_text(pmt_intent),
            "trace_id": _optional_text(row.get("trace_id")),
            "product_names": _optional_text(row.get("product_names")),
            "invoice_id": _optional_text(row.get("invoice_id")),
            "subscription_id": _optional_text(row.get("subscription_id")),
            "payout_reference_token": _optional_text(row.get("payout_reference_token")),
            "dispute_reason": _optional_text(row.get("dispute_reason")),
        }

        result.records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

ADAPTER_MAP = {
    "gwa_payments": parse_gwa_payments,
    "gwa_transactions": parse_gwa_transactions,
    "gwa_refunds": parse_gwa_refunds,
    "gwb_balance": parse_gwb_balance,
}


def parse_dataset(dataset_type: str, filepath: str) -> ParseResult:
    adapter = ADAPTER_MAP.get(dataset_type)
    if adapter is None:
        raise ValueError(f"No adapter for dataset_type='{dataset_type}'. "
                         f"Available: {list(ADAPTER_MAP.keys())}")
    return adapter(filepath)
