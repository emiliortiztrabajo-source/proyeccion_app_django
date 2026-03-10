from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd

from dashboard.models import Expense, Provider, Scenario


EXPORT_COLUMNS = [
    "ID",
    "Cod. Financiero",
    "Nueva Clasificación",
    "Clasif. Cash",
    "Proveedor",
    "PAGO DIA",
    "OC",
    "Mes",
    "Año",
    "Fecha de pago real",
    "Monto",
    "Origen",
]

REQUIRED_COLUMNS = [
    "Cod. Financiero",
    "Nueva Clasificación",
    "Clasif. Cash",
    "Proveedor",
    "PAGO DIA",
    "OC",
    "Mes",
    "Año",
    "Fecha de pago real",
    "Monto",
    "Origen",
]


@dataclass
class ExpenseImportResult:
    processed: int
    created: int
    updated: int
    errors: list[str]


def _clean_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_positive_decimal(value):
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


def _parse_int(value):
    if pd.isna(value):
        return None
    try:
        return int(value)
    except Exception:
        try:
            return int(str(value).strip())
        except Exception:
            return None


def _parse_date(value):
    if pd.isna(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _normalize_origin(value: str) -> str:
    normalized = _clean_text(value).upper()
    if not normalized:
        return Expense.SOURCE_IMPORTADO
    allowed = {Expense.SOURCE_EXCEL, Expense.SOURCE_MANUAL, Expense.SOURCE_IMPORTADO}
    return normalized if normalized in allowed else ""


def export_expenses_to_excel(expenses_qs) -> bytes:
    rows = []
    for exp in expenses_qs.select_related("provider"):
        rows.append(
            {
                "ID": exp.id,
                "Cod. Financiero": exp.financial_code,
                "Nueva Clasificación": exp.nueva_clasificacion,
                "Clasif. Cash": exp.clasif_cash,
                "Proveedor": exp.provider.name if exp.provider_id else "",
                "PAGO DIA": exp.payment_label,
                "OC": exp.purchase_order,
                "Mes": exp.month,
                "Año": exp.year,
                "Fecha de pago real": exp.payment_date,
                "Monto": float(exp.amount or 0),
                "Origen": exp.source_tag,
            }
        )

    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Gastos")
    return output.getvalue()


def import_expenses_from_excel(*, excel_bytes: bytes, scenario: Scenario) -> ExpenseImportResult:
    df = pd.read_excel(BytesIO(excel_bytes), engine="openpyxl")
    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise ValueError("Faltan columnas obligatorias: " + ", ".join(missing_columns))

    created = 0
    updated = 0
    errors: list[str] = []

    provider_cache = {name.strip().upper(): obj for name, obj in Provider.objects.all().values_list("name", "id")}

    for idx, row in df.iterrows():
        excel_row = idx + 2

        provider_name = _clean_text(row.get("Proveedor"))
        nueva_clasificacion = _clean_text(row.get("Nueva Clasificación"))
        payment_label = _clean_text(row.get("PAGO DIA"))
        financial_code = _clean_text(row.get("Cod. Financiero"))
        clasif_cash = _clean_text(row.get("Clasif. Cash"))
        purchase_order = _clean_text(row.get("OC"))
        month = _parse_int(row.get("Mes"))
        year = _parse_int(row.get("Año"))
        payment_date = _parse_date(row.get("Fecha de pago real"))
        amount = _parse_positive_decimal(row.get("Monto"))
        origin = _normalize_origin(row.get("Origen"))
        id_value = _parse_int(row.get("ID")) if "ID" in df.columns else None

        row_errors = []
        if not provider_name:
            row_errors.append("Proveedor obligatorio")
        if not nueva_clasificacion:
            row_errors.append("Nueva Clasificación obligatoria")
        if month is None or month < 1 or month > 12:
            row_errors.append("Mes obligatorio y válido (1-12)")
        if year is None:
            row_errors.append("Año obligatorio")
        if payment_date is None:
            row_errors.append("Fecha de pago real obligatoria")
        if amount is None:
            row_errors.append("Monto obligatorio y mayor a 0")
        if not origin:
            row_errors.append("Origen inválido (EXCEL, MANUAL o IMPORTADO)")

        if row_errors:
            errors.append(f"Fila {excel_row}: " + "; ".join(row_errors))
            continue

        provider_key = provider_name.upper()
        provider_id = provider_cache.get(provider_key)
        if provider_id:
            provider = Provider.objects.get(id=provider_id)
        else:
            provider, _ = Provider.objects.get_or_create(name=provider_name)
            provider_cache[provider_key] = provider.id

        expense = None
        if id_value:
            expense = Expense.objects.filter(id=id_value, scenario=scenario).first()
            if expense is None:
                errors.append(f"Fila {excel_row}: ID {id_value} no existe para el escenario activo")
                continue

        if expense is None:
            expense = (
                Expense.objects.filter(
                    scenario=scenario,
                    year=year,
                    month=month,
                    provider=provider,
                    payment_date=payment_date,
                    payment_label=payment_label,
                    financial_code=financial_code,
                    purchase_order=purchase_order,
                )
                .order_by("id")
                .first()
            )

        payload = {
            "scenario": scenario,
            "provider": provider,
            "year": year,
            "month": month,
            "amount": amount,
            "payment_date": payment_date,
            "payment_label": payment_label,
            "financial_code": financial_code,
            "purchase_order": purchase_order,
            "nueva_clasificacion": nueva_clasificacion,
            "clasif_cash": clasif_cash,
            "source_tag": origin,
        }

        if expense is None:
            Expense.objects.create(**payload)
            created += 1
        else:
            for field, value in payload.items():
                setattr(expense, field, value)
            expense.save()
            updated += 1

    return ExpenseImportResult(processed=len(df.index), created=created, updated=updated, errors=errors)
