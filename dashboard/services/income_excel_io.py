from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
import unicodedata

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


def _normalize_column_name(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.strip().lower().split())


def _clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_date(value):
    if pd.isna(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
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
    return parsed.quantize(Decimal("0.01"))


def _normalize_source(value):
    normalized = _clean_text(value).lower()
    return normalized or "importado"


def _read_excel(excel_bytes: bytes, **kwargs):
    return pd.read_excel(BytesIO(excel_bytes), engine="openpyxl", **kwargs)


def _detect_tabular_format(excel_bytes: bytes):
    df = _read_excel(excel_bytes)
    return all(column in df.columns for column in TABULAR_REQUIRED_COLUMNS), df


def _match_movements_columns(df):
    normalized_map = {_normalize_column_name(column): column for column in df.columns}
    if "descripcion" not in normalized_map:
        for column in df.columns:
            normalized = _normalize_column_name(column)
            if normalized.startswith("descripci"):
                normalized_map["descripcion"] = column
                break
    required = {
        "clasificacion": None,
        "cta": None,
        "fecha": None,
        "descripcion": None,
        "importe": None,
        "saldo": None,
        "aclaraciones": None,
    }
    for key in required:
        required[key] = normalized_map.get(key)
    if any(value is None for value in required.values()):
        return None
    return required


def _load_movements_income_rows(excel_bytes: bytes):
    try:
        df = _read_excel(excel_bytes, sheet_name="Movimientos")
    except ValueError as exc:
        raise ValueError(
            "El Excel no tiene el formato esperado. Usa columnas Fecha/Monto, la hoja INGRESOSXDIA-HABIL o la hoja Movimientos."
        ) from exc

    columns = _match_movements_columns(df)
    if not columns:
        raise ValueError(
            "El Excel no tiene el formato esperado. Usa columnas Fecha/Monto, la hoja INGRESOSXDIA-HABIL o la hoja Movimientos."
        )

    rows = []
    errors = []
    for idx, row in df.iterrows():
        excel_row = idx + 2
        entry_date = _parse_date(row.get(columns["fecha"]))
        amount = _parse_amount(row.get(columns["importe"]))
        classification = _clean_text(row.get(columns["clasificacion"]))
        account = _clean_text(row.get(columns["cta"]))
        description = _clean_text(row.get(columns["descripcion"]))
        remarks = _clean_text(row.get(columns["aclaraciones"]))
        balance = _parse_amount(row.get(columns["saldo"]))

        if remarks.lower() != "ingresos":
            continue

        row_errors = []
        if entry_date is None:
            row_errors.append("Fecha obligatoria y valida")
        if amount is None or amount <= 0:
            row_errors.append("Importe obligatorio y mayor a 0")
        if row_errors:
            errors.append(f"Fila {excel_row}: " + "; ".join(row_errors))
            continue

        rows.append(
            {
                "entry_date": entry_date,
                "amount": amount,
                "classification": classification,
                "account": account,
                "description": description,
                "balance": balance,
                "remarks": remarks,
                "note": description,
                "source_tag": "movimientos",
            }
        )

    return rows, errors


def _load_fallback_income_rows(excel_bytes: bytes):
    df = _read_excel(excel_bytes, sheet_name=FALLBACK_SHEET_NAME, header=1)
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
            "El Excel no tiene el formato esperado. Usa una hoja con columnas Fecha/Monto, la solapa INGRESOSXDIA-HABIL o la hoja Movimientos."
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


def _import_tabular_rows(*, df, scenario: Scenario):
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
            row_errors.append("Fecha obligatoria y valida")
        if amount is None or amount <= 0:
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


def _import_movement_rows(*, rows, scenario: Scenario, errors):
    entry_dates = sorted({row["entry_date"] for row in rows})
    deleted_count = 0
    for entry_date in entry_dates:
        deleted_count += IncomeEntry.objects.filter(
            scenario=scenario,
            source_tag="movimientos",
            entry_date=entry_date,
        ).delete()[0]

    IncomeEntry.objects.bulk_create(
        [
            IncomeEntry(
                scenario=scenario,
                entry_date=row["entry_date"],
                amount=row["amount"],
                source_tag=row["source_tag"],
                note=row["note"],
                classification=row["classification"],
                account=row["account"],
                description=row["description"],
                balance=row["balance"],
                remarks=row["remarks"],
            )
            for row in rows
        ],
        batch_size=1000,
    )
    return IncomeImportResult(
        processed=len(rows) + len(errors),
        created=len(rows),
        updated=deleted_count,
        errors=errors,
    )


def import_incomes_from_excel(*, excel_bytes: bytes, scenario: Scenario) -> IncomeImportResult:
    is_tabular, df = _detect_tabular_format(excel_bytes)
    if is_tabular:
        return _import_tabular_rows(df=df, scenario=scenario)

    try:
        movement_rows, movement_errors = _load_movements_income_rows(excel_bytes)
    except ValueError:
        df = _load_fallback_income_rows(excel_bytes)
        return _import_tabular_rows(df=df, scenario=scenario)

    return _import_movement_rows(rows=movement_rows, scenario=scenario, errors=movement_errors)
