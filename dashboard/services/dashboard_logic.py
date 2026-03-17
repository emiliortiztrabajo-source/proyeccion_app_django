import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from dashboard.models import DailyProjection, Expense, IncomeEntry, Scenario
from dashboard.services.parsing import MONTH_NAME_ES


def _decimal(value):
    return value if value is not None else Decimal("0")


def _normalize_scenario_name(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def is_dashboard_visible_scenario(scenario: Scenario) -> bool:
    normalized_name = _normalize_scenario_name(scenario.name)
    return "optimista" not in normalized_name


def get_dashboard_scenarios():
    scenarios = Scenario.objects.order_by("-year", "name")
    return [scenario for scenario in scenarios if is_dashboard_visible_scenario(scenario)]


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def build_year_cash_projection(scenario: Scenario, year: int, start_month: int | None = None):
    if start_month is None:
        start_month = scenario.start_month
    start = date(year, start_month, 1)
    end = date(year, 12, 31)

    projection_qs = DailyProjection.objects.filter(
        scenario=scenario,
        projection_date__gte=start,
        projection_date__lte=end,
    ).order_by("projection_date")
    projection_map = {obj.projection_date: obj for obj in projection_qs}

    income_map = {
        row["entry_date"]: row["total"]
        for row in IncomeEntry.objects.filter(
            scenario=scenario,
            entry_date__gte=start,
            entry_date__lte=end,
        )
        .values("entry_date")
        .annotate(total=Sum("amount"))
    }

    expense_map = {
        row["payment_date"]: row["total"]
        for row in Expense.objects.filter(
            scenario=scenario,
            payment_date__gte=start,
            payment_date__lte=end,
        )
        .values("payment_date")
        .annotate(total=Sum("amount"))
    }

    first_projection = projection_qs.exclude(caja_inicial__isnull=True).first()
    caja_ini_day1 = first_projection.caja_inicial if first_projection else None

    rows = []
    prev_total = None

    for day in _daterange(start, end):
        projection = projection_map.get(day)

        ingreso = income_map.get(day)
        if ingreso is None and projection:
            ingreso = projection.ingresos_financieros_excel
        ingreso = _decimal(ingreso)

        gasto = -_decimal(expense_map.get(day))

        caja_inicial = caja_ini_day1 if prev_total is None else prev_total

        if caja_inicial is None:
            neto = None
            remanente = None
            total = None
        else:
            neto = caja_inicial + ingreso + gasto
            remanente = neto
            total = remanente

        interes = projection.interes_diario_excel if projection else None
        if total is not None:
            prev_total = total

        rows.append(
            {
                "fecha": day,
                "caja_base": caja_inicial,
                "ingresos_proy": ingreso,
                "gastos_proy": gasto,
                "neto_proy": neto,
                "remanente": remanente,
                "interes_diario": interes,
                "total": total,
                "mes": day.month,
                "mes_nombre": MONTH_NAME_ES[day.month],
                "dia": day.day,
            }
        )

    return rows


def build_real_projection_snapshot(*, scenario: Scenario, year: int, month: int):
    projection_qs = DailyProjection.objects.filter(
        scenario=scenario,
        projection_date__year=year,
        projection_date__month=month,
    ).order_by("projection_date")
    projection_map = {obj.projection_date: obj for obj in projection_qs}

    income_map = {
        row["entry_date"]: row["total"]
        for row in IncomeEntry.objects.filter(
            scenario=scenario,
            entry_date__year=year,
            entry_date__month=month,
        )
        .values("entry_date")
        .annotate(total=Sum("amount"))
    }
    expense_map = {
        row["payment_date"]: row["total"]
        for row in Expense.objects.filter(
            scenario=scenario,
            payment_date__year=year,
            payment_date__month=month,
        )
        .values("payment_date")
        .annotate(total=Sum("amount"))
    }

    daily_rows = []
    projected_income_total = Decimal("0")
    actual_income_total = Decimal("0")
    projected_expense_total = Decimal("0")
    actual_expense_total = Decimal("0")
    days_with_real_data = 0

    for projection_date, projection in projection_map.items():
        projected_income = _decimal(projection.ingresos_financieros_excel)
        projected_expense = _decimal(projection.gastos_proyectados_excel)
        actual_income_value = income_map.get(projection_date)
        actual_expense_value = expense_map.get(projection_date)
        actual_income = _decimal(actual_income_value)
        actual_expense = _decimal(actual_expense_value)
        has_actual_income = actual_income_value is not None
        has_actual_expense = actual_expense_value is not None
        if has_actual_income or has_actual_expense:
            days_with_real_data += 1

        projected_income_total += projected_income
        actual_income_total += actual_income
        projected_expense_total += projected_expense
        actual_expense_total += actual_expense

        daily_rows.append(
            {
                "fecha": projection_date,
                "projected_income": projected_income,
                "actual_income": actual_income,
                "income_variance": actual_income - projected_income,
                "projected_expense": projected_expense,
                "actual_expense": actual_expense,
                "expense_variance": actual_expense - projected_expense,
                "has_actual_income": has_actual_income,
                "has_actual_expense": has_actual_expense,
                "actual_net": actual_income - actual_expense,
                "projected_net": projected_income - projected_expense,
                "net_variance": (actual_income - actual_expense) - (projected_income - projected_expense),
            }
        )

    return {
        "rows": daily_rows,
        "projected_income_total": projected_income_total,
        "actual_income_total": actual_income_total,
        "projected_expense_total": projected_expense_total,
        "actual_expense_total": actual_expense_total,
        "income_variance_total": actual_income_total - projected_income_total,
        "expense_variance_total": actual_expense_total - projected_expense_total,
        "projected_net_total": projected_income_total - projected_expense_total,
        "actual_net_total": actual_income_total - actual_expense_total,
        "net_variance_total": (actual_income_total - actual_expense_total) - (projected_income_total - projected_expense_total),
        "days_with_real_data": days_with_real_data,
        "days_in_projection": len(daily_rows),
    }


def monthly_interest_summary(cash_rows, start_month: int):
    monthly = {m: Decimal("0") for m in range(start_month, 13)}
    for row in cash_rows:
        month = row["mes"]
        if month < start_month:
            continue
        if row["interes_diario"] is not None:
            monthly[month] += row["interes_diario"]

    return [
        {
            "mes": m,
            "mes_nombre": MONTH_NAME_ES[m],
            "interes_mes": monthly[m],
        }
        for m in range(start_month, 13)
    ]


def get_month_calendar_payload(cash_rows, year: int, month: int):
    today = date.today()
    by_day_interest = {
        row["fecha"]: row["interes_diario"]
        for row in cash_rows
        if row["mes"] == month
    }

    first_weekday_mon0, ndays = calendar.monthrange(year, month)
    offset = first_weekday_mon0
    start_grid = date(year, month, 1) - timedelta(days=offset)
    grid_dates = [start_grid + timedelta(days=i) for i in range(42)]
    weeks = [grid_dates[i : i + 7] for i in range(0, 42, 7)]

    rendered_weeks = []
    for week in weeks:
        rendered_week = []
        for day in week:
            rendered_week.append(
                {
                    "date": day,
                    "in_month": day.month == month,
                    "interes": by_day_interest.get(day),
                    "is_today": day == today,
                }
            )
        rendered_weeks.append(rendered_week)

    return {
        "weeks": rendered_weeks,
        "dow_labels": ["L", "M", "Mi", "J", "V", "S", "D"],
    }


def filtered_expenses(*, scenario, year, month, provider=None, payment_date=None, sort_field=None, sort_dir="asc"):
    qs = Expense.objects.filter(scenario=scenario, year=year, month=month).select_related("provider")
    if provider:
        qs = qs.filter(provider=provider)
    if payment_date:
        qs = qs.filter(payment_date=payment_date)

    allowed_sort_fields = {
        "payment_date": "payment_date",
        "payment_label": "payment_label",
        "provider": "provider__name",
        "nueva_clasificacion": "nueva_clasificacion",
        "source_tag": "source_tag",
        "amount": "amount",
    }
    if not sort_field:
        qs = qs.order_by("payment_date", "-amount", "id")
    else:
        effective_sort_field = allowed_sort_fields.get(sort_field, "payment_date")
        direction_prefix = "-" if sort_dir == "desc" else ""
        qs = qs.order_by(f"{direction_prefix}{effective_sort_field}", "id")

    total = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return qs, total


def resolve_default_scenario():
    active_scenarios = [scenario for scenario in Scenario.objects.filter(is_active=True).order_by("-year", "name") if is_dashboard_visible_scenario(scenario)]
    if active_scenarios:
        return active_scenarios[0]

    visible_scenarios = get_dashboard_scenarios()
    return visible_scenarios[0] if visible_scenarios else None
