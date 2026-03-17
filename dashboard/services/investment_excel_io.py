from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
import re

import pandas as pd
from django.db import transaction

from dashboard.models import InvestmentDailyFlow, InvestmentDailySnapshot, Scenario


DEFAULT_DAILY_RATE = Decimal("0.000967")
SOURCE_SHEET = "Hoja6 (2)"
DATE_COL_PATTERN = re.compile(r"^\d{1,2}-[a-z]{3}$", re.IGNORECASE)
MONTH_MAP = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


@dataclass
class InvestmentImportResult:
    processed_days: int
    first_date: date | None
    last_date: date | None
    cuts_count: int


def _parse_decimal(value):
    if pd.isna(value):
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        text = str(value).strip().replace("$", "").replace(" ", "")
        text = text.replace(".", "").replace(",", ".")
        if not text:
            return Decimal("0")
        try:
            return Decimal(text).quantize(Decimal("0.01"))
        except Exception:
            return Decimal("0")


def _parse_header_date(raw_col: str, year: int):
    text = str(raw_col).strip().lower()
    if not DATE_COL_PATTERN.match(text):
        return None
    day_txt, month_txt = text.split("-", 1)
    month_num = MONTH_MAP.get(month_txt)
    if month_num is None:
        return None
    try:
        return date(year, month_num, int(day_txt))
    except ValueError:
        return None


def _is_investment_label(label: str | None) -> bool:
    """Return True if the given row label should be treated as investment flows."""
    if not label:
        return False
    norm = str(label).strip().lower()
    if not norm:
        return False

    # These labels are not real investment flows and should not be included in calculations.
    blacklist = [
        "total",
        "total general",
        "libre disponibilidad",
        "total inversion",
        "saldo inicial",
        "saldo final",
    ]

    for b in blacklist:
        if b in norm:
            return False

    return True


def _load_total_row(excel_bytes: bytes):
    df = pd.read_excel(BytesIO(excel_bytes), sheet_name=SOURCE_SHEET, engine="openpyxl", header=0)
    if df.empty:
        raise ValueError("La hoja Hoja6 (2) está vacía.")
    label_col = df.columns[0]
    labels = df[label_col].astype(str).str.strip().str.lower()
    row = df[labels == "total"]
    if row.empty:
        raise ValueError("No se encontró la fila 'Total' en Hoja6 (2).")
    return row.iloc[0], list(df.columns[1:])


def import_investment_snapshots_from_excel(*, excel_bytes: bytes, scenario: Scenario, year: int, daily_rate: Decimal = DEFAULT_DAILY_RATE):
    total_row, columns = _load_total_row(excel_bytes)

    # Parse all rows (except the Total row) to keep a breakdown of investments per date.
    df = pd.read_excel(BytesIO(excel_bytes), sheet_name=SOURCE_SHEET, engine="openpyxl", header=0)
    label_col = df.columns[0]
    labels = df[label_col].astype(str).str.strip().str.lower()
    total_mask = labels == "total"

    flows_by_date: dict[date, dict[str, Decimal]] = {}
    for _, row in df[~total_mask].iterrows():
        label = str(row[label_col]).strip()
        if not _is_investment_label(label):
            continue
        for raw_col in columns:
            parsed_date = _parse_header_date(raw_col, year)
            if parsed_date is None:
                continue
            amount = _parse_decimal(row.get(raw_col))
            if amount == 0:
                continue
            flows_by_date.setdefault(parsed_date, {})[label] = (
                flows_by_date.get(parsed_date, {}).get(label, Decimal("0")) + amount
            )

    # Compute net_flow as the sum of investment flows (excluding excluded labels)
    # rather than relying on the Excel "Total" row, which can include non-investment movements.
    net_flow_per_day: dict[date, Decimal] = {}
    for day, label_map in flows_by_date.items():
        net_flow_per_day[day] = sum(label_map.values())

    parsed_days = []
    active_capital = Decimal("0")
    cumulative_yield = Decimal("0")
    cuts_count = 0
    parsed_dates = []

    for raw_col in columns:
        parsed_date = _parse_header_date(raw_col, year)
        if parsed_date is None:
            continue
        parsed_dates.append(parsed_date)

        # Use only investment flow amounts for the net flow, not the Excel 'Total' row.
        net_flow = net_flow_per_day.get(parsed_date, Decimal("0"))

        candidate_capital = active_capital + net_flow
        was_cut = candidate_capital < 0
        if was_cut:
            cuts_count += 1
        active_capital = max(Decimal("0"), candidate_capital)

        # We still store daily_yield/cumulative_yield for compatibility, but the
        # true performance comes from cuotaparte evolution (see dashboard view logic).
        daily_yield = (active_capital * daily_rate).quantize(Decimal("0.01"))
        cumulative_yield += daily_yield
        parsed_days.append(
            InvestmentDailySnapshot(
                scenario=scenario,
                snapshot_date=parsed_date,
                net_flow=net_flow,
                active_capital=active_capital,
                daily_yield=daily_yield,
                cumulative_yield=cumulative_yield,
                was_cut=was_cut,
            )
        )

    if not parsed_days:
        raise ValueError("No se detectaron columnas de fecha válidas en Hoja6 (2).")

    with transaction.atomic():
        # Clear existing snapshots (and their flows via cascade) for the year.
        InvestmentDailySnapshot.objects.filter(scenario=scenario, snapshot_date__year=year).delete()
        InvestmentDailySnapshot.objects.bulk_create(parsed_days, batch_size=1000)

        # Load the newly created snapshots to attach flows.
        created_snapshots = {
            s.snapshot_date: s
            for s in InvestmentDailySnapshot.objects.filter(
                scenario=scenario, snapshot_date__in=parsed_dates
            )
        }

        flows_to_create = []
        for snapshot_date, label_map in flows_by_date.items():
            snapshot = created_snapshots.get(snapshot_date)
            if not snapshot:
                continue
            for label, amount in label_map.items():
                flows_to_create.append(
                    InvestmentDailyFlow(snapshot=snapshot, label=label, amount=amount)
                )
        if flows_to_create:
            InvestmentDailyFlow.objects.bulk_create(flows_to_create, batch_size=1000)

    return InvestmentImportResult(
        processed_days=len(parsed_days),
        first_date=parsed_days[0].snapshot_date,
        last_date=parsed_days[-1].snapshot_date,
        cuts_count=cuts_count,
    )
