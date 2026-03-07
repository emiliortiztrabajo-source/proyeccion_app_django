from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import BytesIO

import pandas as pd
from django.db import transaction

from dashboard.models import DailyProjection, Expense, IncomeEntry, PaymentDayRule, Provider, Scenario
from dashboard.services.parsing import DIAS_COL_ES, extract_rate_from_label, list_escenario_cols, month_amount_col, parse_header_fecha, parse_monto


SHEET_MAIN = "ESCENARIO 1"
SHEET_INGRESOS_DIARIOS = "INGRESOSXDIA-HABIL"
SHEET_GASTOS = "Gastos"
SHEET_DIAS = "DIAS"

CONCEPT_CAJA_BASE = "CAJA INICIAL"
CONCEPT_GASTOS = "GASTOS PROYECTADOS"
CONCEPT_INGRESOS = "INGRESOS FINANCIEROS PROYECTADOS"
CONCEPT_RESCATE = "RESCATE DE FCI"
CONCEPT_INTERES = "INTERES DIARIO"
CONCEPT_INVERSIONES = "INVERSIONES FCI"
CONCEPT_INTERESES_ACUM = "INTERESES ACUMULADOS"
CONCEPT_INTERESES_REC = "INTERESES RECUPERADO"
CONCEPT_TOTAL = "TOTAL"


def _normalize_name(value):
    return str(value).strip().upper()


def _load_sheet(excel_bytes: bytes, sheet_name: str, header=0):
    return pd.read_excel(BytesIO(excel_bytes), sheet_name=sheet_name, engine="openpyxl", header=header)


def _upsert_scenario(scenario_name: str, year: int, start_month: int, main_df: pd.DataFrame) -> Scenario:
    first_col = main_df.columns[0]
    labels = main_df[first_col].astype(str)
    daily_interest_label = next((x for x in labels if "INTERES DIARIO" in x.upper()), "INTERES DIARIO")
    daily_rate = extract_rate_from_label(daily_interest_label) or Decimal("0.000967")

    scenario, _ = Scenario.objects.update_or_create(
        name=scenario_name,
        year=year,
        defaults={
            "start_month": start_month,
            "daily_interest_rate": daily_rate,
            "is_active": True,
        },
    )
    return scenario


def _import_daily_projections(excel_bytes: bytes, scenario: Scenario, year: int):
    df = _load_sheet(excel_bytes, SHEET_MAIN)
    scenario_cols = list_escenario_cols(df)
    if not scenario_cols:
        raise ValueError("No se encontraron columnas de escenario en la hoja principal.")

    scenario_col = scenario_cols[0]
    first_col = df.columns[0]
    labels = df[first_col].astype(str).str.strip().str.upper()

    date_cols = []
    col_to_date = {}
    for col in df.columns:
        if col == scenario_col:
            continue
        parsed = parse_header_fecha(col, year)
        if parsed:
            date_cols.append(col)
            col_to_date[col] = parsed

    if not date_cols:
        raise ValueError("No se encontraron columnas de fecha en la hoja principal.")

    def row_value(row_name, date_col):
        row = df[labels == row_name]
        if row.empty:
            return None
        return parse_monto(row.iloc[0][date_col])

    records = []
    for date_col in date_cols:
        projection_date = col_to_date[date_col]
        records.append(
            DailyProjection(
                scenario=scenario,
                projection_date=projection_date,
                caja_inicial=row_value(CONCEPT_CAJA_BASE, date_col),
                gastos_proyectados_excel=row_value(CONCEPT_GASTOS, date_col),
                ingresos_financieros_excel=row_value(CONCEPT_INGRESOS, date_col),
                rescate_fci=row_value(CONCEPT_RESCATE, date_col),
                interes_diario_excel=row_value(CONCEPT_INTERES, date_col),
                inversiones_fci=row_value(CONCEPT_INVERSIONES, date_col),
                intereses_acumulados=row_value(CONCEPT_INTERESES_ACUM, date_col),
                intereses_recuperado=row_value(CONCEPT_INTERESES_REC, date_col),
                total_excel=row_value(CONCEPT_TOTAL, date_col),
            )
        )

    DailyProjection.objects.bulk_create(records, batch_size=1000)


def _import_ingresos_diarios(excel_bytes: bytes, scenario: Scenario, year: int):
    df = _load_sheet(excel_bytes, SHEET_INGRESOS_DIARIOS, header=1)
    cols = list(df.columns)

    def is_day_col(col):
        txt = str(col).strip().upper()
        if txt in ("DIA HABIAL", "DIA HABIL", "%%"):
            return False
        return "DIA" in txt

    pairs = []
    for idx in range(len(cols) - 1):
        left, right = cols[idx], cols[idx + 1]
        if is_day_col(left) and not is_day_col(right):
            pairs.append((left, right))

    if not pairs:
        return

    long_rows = []
    for day_col, amount_col in pairs:
        tmp = df[[day_col, amount_col]].copy()
        tmp.columns = ["entry_date", "amount"]
        long_rows.append(tmp)

    merged = pd.concat(long_rows, ignore_index=True)
    merged["entry_date"] = pd.to_datetime(merged["entry_date"], errors="coerce")
    merged["amount"] = pd.to_numeric(merged["amount"], errors="coerce").fillna(0)
    merged = merged.dropna(subset=["entry_date"])
    merged = merged[merged["entry_date"].dt.year == year]

    grouped = merged.groupby(merged["entry_date"].dt.date, as_index=False)["amount"].sum()
    records = [
        IncomeEntry(
            scenario=scenario,
            entry_date=row["entry_date"],
            amount=Decimal(str(row["amount"])).quantize(Decimal("0.01")),
            source_tag="excel",
        )
        for _, row in grouped.iterrows()
        if float(row["amount"]) != 0.0
    ]
    IncomeEntry.objects.bulk_create(records, batch_size=1000)


def _import_payment_rules(excel_bytes: bytes, scenario: Scenario, year: int, start_month: int):
    dias_df = _load_sheet(excel_bytes, SHEET_DIAS)
    if "ETIQUETA" not in dias_df.columns:
        return

    etiquetas = dias_df["ETIQUETA"].astype(str).str.strip()
    records = []
    for month in range(start_month, 13):
        month_col = DIAS_COL_ES.get(month)
        if month_col not in dias_df.columns:
            continue
        month_dates = pd.to_datetime(dias_df[month_col], errors="coerce")

        for label, day in zip(etiquetas, month_dates):
            if pd.isna(day):
                continue
            if int(day.year) != year:
                continue
            records.append(
                PaymentDayRule(
                    scenario=scenario,
                    label=label,
                    month=month,
                    payment_date=day.date(),
                )
            )

    PaymentDayRule.objects.bulk_create(records, batch_size=1000)


def _find_amount_and_date_col(gastos_df: pd.DataFrame, year: int, month: int):
    target = month_amount_col(year, month)
    cols = list(gastos_df.columns)
    idx = None
    for i, col in enumerate(cols):
        if str(col).strip().lower() == target.lower():
            idx = i
            break

    if idx is None:
        return None, None

    amount_col = cols[idx]
    date_col = None
    if idx + 1 < len(cols) and "escenario" in str(cols[idx + 1]).strip().lower():
        date_col = cols[idx + 1]
    return amount_col, date_col


def _import_expenses(excel_bytes: bytes, scenario: Scenario, year: int, start_month: int):
    gastos_df = _load_sheet(excel_bytes, SHEET_GASTOS)
    dias_df = _load_sheet(excel_bytes, SHEET_DIAS)

    if "Proveedor" not in gastos_df.columns or "PAGO DIA" not in gastos_df.columns:
        return

    dias_df["ETIQUETA_N"] = dias_df["ETIQUETA"].astype(str).str.strip().str.upper()
    gastos_df["PAGO_DIA_N"] = gastos_df["PAGO DIA"].astype(str).str.strip().str.upper()

    provider_cache = {name: provider for name, provider in Provider.objects.values_list("name", "id")}
    provider_objs = {}

    to_create = []

    for month in range(start_month, 13):
        amount_col, date_col = _find_amount_and_date_col(gastos_df, year, month)
        if not amount_col:
            continue

        rule_date_map = {}
        dias_col = DIAS_COL_ES.get(month)
        if dias_col and dias_col in dias_df.columns:
            tmp = dias_df[["ETIQUETA_N", dias_col]].copy()
            tmp[dias_col] = pd.to_datetime(tmp[dias_col], errors="coerce")
            for etq, dt in zip(tmp["ETIQUETA_N"], tmp[dias_col]):
                if pd.isna(dt):
                    continue
                rule_date_map[etq] = dt.date()

        amount_series = pd.to_numeric(gastos_df[amount_col], errors="coerce").fillna(0.0)
        date_series = pd.to_datetime(gastos_df[date_col], errors="coerce") if date_col else None

        for idx, amount in amount_series.items():
            if float(amount) == 0.0:
                continue

            provider_name = str(gastos_df.at[idx, "Proveedor"]).strip()
            if not provider_name or provider_name.lower() == "nan":
                provider_name = "Proveedor sin nombre"

            provider_id = provider_cache.get(provider_name)
            if not provider_id:
                provider = provider_objs.get(provider_name)
                if not provider:
                    provider = Provider.objects.create(name=provider_name)
                    provider_objs[provider_name] = provider
                provider_id = provider.id
                provider_cache[provider_name] = provider_id

            payment_label = str(gastos_df.at[idx, "PAGO DIA"]).strip()
            payment_date = None
            if date_series is not None and pd.notna(date_series.at[idx]):
                payment_date = date_series.at[idx].date()
            if not payment_date:
                payment_date = rule_date_map.get(str(gastos_df.at[idx, "PAGO_DIA_N"]).upper())

            to_create.append(
                Expense(
                    scenario=scenario,
                    provider_id=provider_id,
                    year=year,
                    month=month,
                    amount=Decimal(str(amount)).quantize(Decimal("0.01")),
                    payment_date=payment_date,
                    payment_label=payment_label,
                    financial_code=str(gastos_df.at[idx, "Cod. Financiero"]).strip()
                    if "Cod. Financiero" in gastos_df.columns
                    else "",
                    purchase_order=str(gastos_df.at[idx, "OC"]).strip() if "OC" in gastos_df.columns else "",
                    nueva_clasificacion=str(gastos_df.at[idx, "Nueva Clasificación"]).strip()
                    if "Nueva Clasificación" in gastos_df.columns
                    else "",
                    clasif_cash=str(gastos_df.at[idx, "Clasif. Cash"]).strip() if "Clasif. Cash" in gastos_df.columns else "",
                    source_tag="excel",
                )
            )

    Expense.objects.bulk_create(to_create, batch_size=1000)


def _clear_scenario_data(scenario: Scenario):
    DailyProjection.objects.filter(scenario=scenario).delete()
    IncomeEntry.objects.filter(scenario=scenario).delete()
    PaymentDayRule.objects.filter(scenario=scenario).delete()
    Expense.objects.filter(scenario=scenario).delete()


def import_excel_bytes(*, excel_bytes: bytes, scenario_name: str = "ESCENARIO 1", year: int = 2026, start_month: int = 3, replace_existing: bool = True):
    main_df = _load_sheet(excel_bytes, SHEET_MAIN)

    with transaction.atomic():
        scenario = _upsert_scenario(scenario_name=scenario_name, year=year, start_month=start_month, main_df=main_df)

        if replace_existing:
            _clear_scenario_data(scenario)

        _import_daily_projections(excel_bytes=excel_bytes, scenario=scenario, year=year)
        _import_ingresos_diarios(excel_bytes=excel_bytes, scenario=scenario, year=year)
        _import_payment_rules(excel_bytes=excel_bytes, scenario=scenario, year=year, start_month=start_month)
        _import_expenses(excel_bytes=excel_bytes, scenario=scenario, year=year, start_month=start_month)

    return {
        "scenario_id": scenario.id,
        "scenario": str(scenario),
        "daily_projections": DailyProjection.objects.filter(scenario=scenario).count(),
        "income_entries": IncomeEntry.objects.filter(scenario=scenario).count(),
        "payment_rules": PaymentDayRule.objects.filter(scenario=scenario).count(),
        "expenses": Expense.objects.filter(scenario=scenario).count(),
    }


def import_excel_file(file_path: str, **kwargs):
    with open(file_path, "rb") as f:
        content = f.read()
    return import_excel_bytes(excel_bytes=content, **kwargs)
