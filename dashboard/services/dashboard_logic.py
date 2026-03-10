import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from dashboard.models import DailyProjection, Expense, IncomeEntry, Scenario
from dashboard.services.parsing import MONTH_NAME_ES


def _decimal(value):
    return value if value is not None else Decimal("0")


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def build_year_cash_projection(scenario: Scenario, year: int):
    start = date(year, scenario.start_month, 1)
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

        gasto = -abs(_decimal(expense_map.get(day)))

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
    return Scenario.objects.filter(is_active=True).order_by("-year", "name").first() or Scenario.objects.order_by("-year", "name").first()
