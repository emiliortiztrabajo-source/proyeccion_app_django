from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

import pandas as pd

from dashboard.models import IncomeEntry, Scenario


TABULAR_REQUIRED_COLUMNS = ["Fecha", "Monto"]
FALLBACK_SHEET_NAME = "INGRESOSXDIA-HABIL"


@dataclass
class IncomeImportResult:
    processed: int
    created: int
    updated: int
    errors: list[str]


def _parse_date(value):
    if pd.isna(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _parse_amount(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        parsed = Decimal(str(value))
    else:
        text = str(value).strip().replace("$", "").replace(" ", "")
        text = text.replace(".", "").replace(",", ".")
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except Exception:
            return None
    if parsed <= 0:
        return None
    return parsed.quantize(Decimal("0.01"))


def _clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_source(value):
    normalized = _clean_text(value).lower()
    return normalized or "importado"


def _detect_tabular_format(excel_bytes: bytes):
    df = pd.read_excel(BytesIO(excel_bytes), engine="openpyxl")
    return all(column in df.columns for column in TABULAR_REQUIRED_COLUMNS), df


def _load_fallback_income_rows(excel_bytes: bytes):
    df = pd.read_excel(BytesIO(excel_bytes), sheet_name=FALLBACK_SHEET_NAME, engine="openpyxl", header=1)
    cols = list(df.columns)

    def is_day_col(col):
        txt = str(col).strip().upper()
        if txt in ("DIA HABIAL", "DIA HABIL", "%%"):
            return False
        return "DIA" in txt

    pairs = []
    for idx in range(len(cols) - 1):
        left = cols[idx]
        right = cols[idx + 1]
        if is_day_col(left) and not is_day_col(right):
            pairs.append((left, right))

    if not pairs:
        raise ValueError(
            "El Excel no tiene el formato esperado. Usá una hoja con columnas Fecha/Monto o la solapa INGRESOSXDIA-HABIL."
        )

    rows = []
    for day_col, amount_col in pairs:
        temp_df = df[[day_col, amount_col]].copy()
        temp_df.columns = ["Fecha", "Monto"]
        rows.append(temp_df)

    merged = pd.concat(rows, ignore_index=True)
    merged["Nota"] = ""
    merged["Origen"] = "excel"
    return merged


def import_incomes_from_excel(*, excel_bytes: bytes, scenario: Scenario) -> IncomeImportResult:
    is_tabular, df = _detect_tabular_format(excel_bytes)
    if not is_tabular:
        df = _load_fallback_income_rows(excel_bytes)

    created = 0
    updated = 0
    errors: list[str] = []

    for idx, row in df.iterrows():
        excel_row = idx + 2
        entry_date = _parse_date(row.get("Fecha"))
        amount = _parse_amount(row.get("Monto"))
        note = _clean_text(row.get("Nota")) if "Nota" in df.columns else ""
        source_tag = _normalize_source(row.get("Origen")) if "Origen" in df.columns else "importado"

        row_errors = []
        if entry_date is None:
            row_errors.append("Fecha obligatoria y válida")
        if amount is None:
            row_errors.append("Monto obligatorio y mayor a 0")
        if row_errors:
            errors.append(f"Fila {excel_row}: " + "; ".join(row_errors))
            continue

        income_entry, was_created = IncomeEntry.objects.get_or_create(
            scenario=scenario,
            entry_date=entry_date,
            defaults={
                "amount": amount,
                "note": note,
                "source_tag": source_tag,
            },
        )
        if was_created:
            created += 1
            continue

        income_entry.amount = amount
        income_entry.note = note
        income_entry.source_tag = source_tag
        income_entry.save(update_fields=["amount", "note", "source_tag", "updated_at"])
        updated += 1

    return IncomeImportResult(processed=len(df.index), created=created, updated=updated, errors=errors)