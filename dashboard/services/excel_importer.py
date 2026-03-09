from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pandas as pd
from django.db import transaction

from dashboard.models import DailyProjection, Expense, IncomeEntry, PaymentDayRule, Provider, Scenario
from dashboard.services.parsing import DIAS_COL_ES, MONTH_ABBR_ES, extract_rate_from_label, month_amount_col, parse_monto


SHEET_MAIN = "ESCENARIO 1"
SHEET_INGRESOS_DIARIOS = "INGRESOSXDIA-HABIL"
SHEET_GASTOS = "Gastos"
SHEET_DIAS = "DIAS"

CONCEPT_CAJA_BASE = "CAJA INICIAL"
CONCEPT_GASTOS = "GASTOS PROYECTADOS"
CONCEPT_INGRESOS = "INGRESOS FINANCIEROS PROYECTADOS"
CONCEPT_RESCATE = "RESCATE DE FCI"
CONCEPT_INTERES = "INTERES DIARIO (0.0967%)"
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
    first_col = df.columns[0]
    labels = df[first_col].astype(str).map(_normalize_name)

    # Normalizamos headers para resolver columnas tipo "01-mar" sin depender de may/min.
    normalized_col_map = {str(col).strip().lower(): col for col in df.columns}

    def find_row(row_name):
        normalized_name = _normalize_name(row_name)
        row = df[labels == normalized_name]
        if row.empty:
            return None
        return row.iloc[0]

    def col_for_day(day: date):
        month_abbr_es = MONTH_ABBR_ES.get(day.month, "").lower()
        key = f"{day.day:02d}-{month_abbr_es}"
        return normalized_col_map.get(key)

    def row_day_value(row_data, day: date):
        if row_data is None:
            return None
        day_col = col_for_day(day)
        if not day_col:
            return None
        return parse_monto(row_data.get(day_col))

    start = date(year, scenario.start_month, 1)
    end = date(year, 12, 31)

    row_caja = find_row(CONCEPT_CAJA_BASE)
    row_gastos = find_row(CONCEPT_GASTOS)
    row_ingresos = find_row(CONCEPT_INGRESOS)
    row_rescate = find_row(CONCEPT_RESCATE)
    row_interes = find_row(CONCEPT_INTERES)
    row_inversiones = find_row(CONCEPT_INVERSIONES)
    row_intereses_acum = find_row(CONCEPT_INTERESES_ACUM)
    row_intereses_rec = find_row(CONCEPT_INTERESES_REC)
    row_total = find_row(CONCEPT_TOTAL)

    records = []
    day = start
    while day <= end:
        records.append(
            DailyProjection(
                scenario=scenario,
                projection_date=day,
                caja_inicial=row_day_value(row_caja, day),
                gastos_proyectados_excel=row_day_value(row_gastos, day),
                ingresos_financieros_excel=row_day_value(row_ingresos, day),
                rescate_fci=row_day_value(row_rescate, day),
                interes_diario_excel=row_day_value(row_interes, day),
                inversiones_fci=row_day_value(row_inversiones, day),
                intereses_acumulados=row_day_value(row_intereses_acum, day),
                intereses_recuperado=row_day_value(row_intereses_rec, day),
                total_excel=row_day_value(row_total, day),
            )
        )
        day += timedelta(days=1)

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
