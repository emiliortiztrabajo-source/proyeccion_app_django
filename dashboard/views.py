from datetime import date, datetime, timedelta
from decimal import Decimal
from bisect import bisect_right

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.db.models import Min, Sum
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.management import call_command
from urllib.parse import urlencode

from .forms import (
	DashboardFilterForm,
	ExcelImportForm,
	ExpenseExcelImportForm,
	ExpenseFilterForm,
	ExpenseForm,
	IncomeEntryForm,
	IncomeExcelImportForm,
	InvestmentExcelImportForm,
	ManualExpenseForm,
)
from .models import Expense, ExpenseChangeLog, FundCuotaparteHistory, IncomeEntry, InvestmentDailySnapshot, Provider, Scenario
from .services.cafci_api import CafciApiError, CafciNetworkError, build_cafci_snapshot
from .services.expense_excel_io import export_expenses_to_excel, import_expenses_from_excel
from .services.dashboard_logic import (
	build_real_projection_snapshot,
	build_year_cash_projection,
	filtered_expenses,
	get_dashboard_scenarios,
	get_month_calendar_payload,
	is_dashboard_visible_scenario,
	monthly_interest_summary,
	resolve_default_scenario,
)
from .services.parsing import MONTH_NAME_ES
from .services.excel_importer import import_excel_bytes
from .services.income_excel_io import import_incomes_from_excel
from .services.investment_excel_io import import_investment_snapshots_from_excel
from decimal import InvalidOperation


CAFCI_CALCULATOR_FUND_ID = ""
CAFCI_CALCULATOR_FUND_CLASS = ""
CAFCI_CALCULATOR_FUND_NAME = "1822 RAICES INVERSION"
CAFCI_DAILY_FUND_NAMES = [
	"1822 RAICES AHORRO PLUS",
	"1822 RAICES VALORES FIDUCIARIOS",
	"1822 RAICES AHORRO PESOS",
	"1822 RAICES RENTA EN PESOS",
	"1822 RAICES VALORES NEGOCIABLES",
	"1822 RAICES INFRAESTRUCTURA",
	"1822 RAICES INVERSION",
	"1822 RAICES DOLARES PLUS",
]
CAFCI_1822_BASE_HISTORY = [
	("10/03/2026", "87.539829"),
	("09/03/2026", "87.415505"),
	("06/03/2026", "87.310665"),
	("05/03/2026", "87.241441"),
	("04/03/2026", "87.17636"),
	("03/03/2026", "87.018081"),
	("02/03/2026", "86.886538"),
	("27/02/2026", "86.693581"),
	("26/02/2026", "86.334127"),
	("25/02/2026", "85.932665"),
	("24/02/2026", "85.765632"),
	("23/02/2026", "85.417524"),
	("20/02/2026", "85.328437"),
	("19/02/2026", "85.123479"),
	("18/02/2026", "85.187438"),
	("13/02/2026", "85.029407"),
	("12/02/2026", "84.53174"),
	("11/02/2026", "84.263955"),
	("10/02/2026", "84.241634"),
	("09/02/2026", "84.095859"),
	("06/02/2026", "84.045319"),
	("05/02/2026", "83.647474"),
	("04/02/2026", "83.422105"),
	("03/02/2026", "82.973268"),
	("02/02/2026", "82.898985"),
	("30/01/2026", "82.978661"),
	("29/01/2026", "82.735238"),
	("28/01/2026", "82.857579"),
	("27/01/2026", "82.768305"),
	("26/01/2026", "82.466267"),
	("23/01/2026", "82.284222"),
	("22/01/2026", "81.959325"),
	("21/01/2026", "81.665615"),
	("20/01/2026", "81.80756"),
	("19/01/2026", "81.893661"),
	("16/01/2026", "82.115937"),
	("15/01/2026", "82.118145"),
	("14/01/2026", "82.344989"),
	("13/01/2026", "82.303846"),
	("12/01/2026", "82.223723"),
	("09/01/2026", "82.136299"),
	("08/01/2026", "81.800055"),
]


def _normalize_text(value):
	if value is None:
		return ""
	text = str(value).strip().lower()
	replacements = {
		"á": "a",
		"é": "e",
		"í": "i",
		"ó": "o",
		"ú": "u",
		"ü": "u",
		"ñ": "n",
	}
	for old, new in replacements.items():
		text = text.replace(old, new)
	return " ".join(text.split())


def _sum_interest(rows):
	total = Decimal("0")
	for row in rows:
		if row["interes_diario"] is not None:
			total += row["interes_diario"]
	return total


def _parse_history_date(raw_value):
	if not raw_value:
		return None
	if isinstance(raw_value, date):
		return raw_value
	text = str(raw_value).strip()
	if not text:
		return None
	for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
		try:
			return datetime.strptime(text, fmt).date()
		except ValueError:
			continue
	return None


def _sanitize_rate_decimal(value):
	if value is None:
		return None
	try:
		parsed = Decimal(str(value))
	except Exception:
		return None
	if not parsed.is_finite() or parsed.is_nan():
		return None
	return parsed


def _rate_decimal_to_plain_string(value):
	parsed = _sanitize_rate_decimal(value)
	if parsed is None:
		return ""
	text = format(parsed, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return text or "0"


def _compute_cuotaparte_average_daily_rate(history_points):
	def _normalize_quote_value(raw_value):
		try:
			parsed = Decimal(str(raw_value))
		except Exception:
			return None
		if parsed <= 0:
			return None
		# Historic manual base is in regular cuotaparte units (~80-100),
		# while CAFCI feed can come as "mil cuotapartes" (~80000-100000).
		if parsed >= Decimal("1000"):
			parsed = parsed / Decimal("1000")
		return parsed

	clean_points = []
	for point_date, point_value in history_points:
		parsed_date = _parse_history_date(point_date)
		if parsed_date is None:
			continue
		parsed_value = _normalize_quote_value(point_value)
		if parsed_value is None:
			continue
		clean_points.append((parsed_date, parsed_value))

	if len(clean_points) < 2:
		return None, 0

	# Keep a single value per date (last value wins) and sort ascending.
	by_date = {}
	for point_date, point_value in clean_points:
		by_date[point_date] = point_value
	ordered = sorted(by_date.items(), key=lambda x: x[0])

	if len(ordered) < 2:
		return None, len(ordered)

	daily_returns = []
	for idx in range(1, len(ordered)):
		previous_value = ordered[idx - 1][1]
		current_value = ordered[idx][1]
		if previous_value == 0:
			continue
		daily_returns.append((current_value / previous_value) - Decimal("1"))

	if not daily_returns:
		return None, len(ordered)

	average_rate = sum(daily_returns, Decimal("0")) / Decimal(len(daily_returns))
	return average_rate, len(ordered)


def _compute_geometric_daily_rate_for_fund(fund_name):
	"""Compute geometric average daily rate from DB points for a fund.

	Returns (rate_decimal, points_used) where rate_decimal is the daily
	geometric rate as a Decimal (e.g. 0.0011) or None if not computable.
	"""
	try:
		db_points = list(
			FundCuotaparteHistory.objects.filter(fund_name=fund_name)
			.values_list("quote_date", "cuotaparte")
			.order_by("quote_date")
		)
	except (OperationalError, ProgrammingError):
		return None, 0

	points_count = len(db_points)
	if points_count < 2:
		return None, points_count

	first_value = db_points[0][1]
	last_value = db_points[-1][1]
	try:
		first_dec = Decimal(str(first_value))
		last_dec = Decimal(str(last_value))
	except Exception:
		return None, points_count

	if first_dec <= 0 or last_dec <= 0:
		return None, points_count

	n = points_count - 1
	try:
		# Use float for fractional exponent then convert back to Decimal for consistency.
		rate_float = (float(last_dec) / float(first_dec)) ** (1.0 / n) - 1.0
		rate_dec = Decimal(str(rate_float))
	except Exception:
		return None, points_count

	return rate_dec, points_count


def _compute_geometric_from_points(history_points):
	"""Compute geometric daily rate from an explicit list of (date, value) points.

	Returns (rate_decimal, points_used).
	"""
	clean_points = []
	for d, v in history_points:
		parsed_date = _parse_history_date(d)
		if parsed_date is None:
			continue
		try:
			val = Decimal(str(v))
		except Exception:
			continue
		if val <= 0:
			continue
		clean_points.append((parsed_date, val))

	if len(clean_points) < 2:
		return None, len(clean_points)

	ordered = sorted(clean_points, key=lambda x: x[0])
	first_dec = ordered[0][1]
	last_dec = ordered[-1][1]
	n = len(ordered) - 1
	try:
		rate_float = (float(last_dec) / float(first_dec)) ** (1.0 / n) - 1.0
		rate_dec = Decimal(str(rate_float))
	except Exception:
		return None, len(ordered)

	return rate_dec, len(ordered)


def _build_1822_estimated_rate(rows):
	normalized_target = _normalize_text(CAFCI_CALCULATOR_FUND_NAME)
	history_points = list(CAFCI_1822_BASE_HISTORY)

	# Persist latest downloaded values so future days are accumulated automatically.
	for row in rows:
		fund_name = row.get("fund_name") or row.get("requested_name") or ""
		if _normalize_text(fund_name).find(normalized_target) < 0:
			continue
		if row.get("daily_date") and row.get("cuotaparte") is not None:
			try:
				FundCuotaparteHistory.objects.update_or_create(
					fund_name=CAFCI_CALCULATOR_FUND_NAME,
					quote_date=row.get("daily_date"),
					defaults={"cuotaparte": row.get("cuotaparte")},
				)
			except (OperationalError, ProgrammingError):
				# Migration may still be pending; keep running with the manual base history.
				pass

	try:
		db_points = list(
			FundCuotaparteHistory.objects.filter(fund_name=CAFCI_CALCULATOR_FUND_NAME)
			.values_list("quote_date", "cuotaparte")
		)
	except (OperationalError, ProgrammingError):
		db_points = []

	history_points.extend(db_points)

	for row in rows:
		fund_name = row.get("fund_name") or row.get("requested_name") or ""
		if _normalize_text(fund_name).find(normalized_target) < 0:
			continue
		if row.get("daily_date") and row.get("cuotaparte") is not None:
			history_points.append((row.get("daily_date"), row.get("cuotaparte")))

	return _compute_cuotaparte_average_daily_rate(history_points)


def _format_expense_value(field, value):
	if field == "provider":
		return value.name if value else "—"
	if field == "payment_date":
		return value.isoformat() if value else "—"
	if field == "amount":
		return f"{value:.2f}" if value is not None else "—"
	return str(value) if value not in (None, "") else "—"


def _build_expense_update_summary(before_expense, after_expense):
	tracked_fields = [
		("provider", "Proveedor"),
		("payment_date", "Fecha"),
		("payment_label", "PAGO DIA"),
		("amount", "Monto"),
		("nueva_clasificacion", "Nueva clasificación"),
		("clasif_cash", "Clasif. cash"),
		("financial_code", "Cod. financiero"),
		("purchase_order", "OC"),
		("source_tag", "Origen"),
	]

	changes = []
	for field_name, label in tracked_fields:
		before_value = getattr(before_expense, field_name)
		after_value = getattr(after_expense, field_name)
		if before_value != after_value:
			changes.append(
				f"{label}: {_format_expense_value(field_name, before_value)} -> {_format_expense_value(field_name, after_value)}"
			)

	return "; ".join(changes) if changes else "Sin cambios de datos."


def _log_expense_change(*, request, expense, action, comment, change_summary):
	ExpenseChangeLog.objects.create(
		scenario=expense.scenario,
		expense=expense,
		action=action,
		comment=comment,
		change_summary=change_summary,
		changed_by=request.user if request.user.is_authenticated else None,
	)


def _build_cafci_context(request):
	today = date.today()
	basic_context = {
		"cafci_ficha": None,
		"cafci_error": None,
		"cafci_notice": None,
		"cafci_local_updated_at": None,
		"cafci_source_ficha": None,
		"cafci_daily_info_items": [],
		"cafci_selected_fund": CAFCI_CALCULATOR_FUND_ID,
		"cafci_selected_class": CAFCI_CALCULATOR_FUND_CLASS,
		"cafci_target_name": CAFCI_CALCULATOR_FUND_NAME,
		"cafci_fund_rows": [],
		"cafci_1822_estimated_rate_decimal": None,
		"cafci_1822_estimated_rate_pct": None,
		"cafci_1822_points_used": 0,
	}
	errors = []
	network_issue = False
	rows = []
	calculator_ficha = None
	normalized_target = _normalize_text(CAFCI_CALCULATOR_FUND_NAME)

	for fund_name in CAFCI_DAILY_FUND_NAMES:
		try:
			# Use local-only planilla to avoid live network calls on each request.
			snapshot = build_cafci_snapshot(
				fund="",
				fund_class="",
				fund_name=fund_name,
				start_date=today,
				end_date=today,
				local_only=True,
			)
			ficha = snapshot.get("ficha") or {}
			found_name = ficha.get("fundName") or fund_name
			rows.append(
				{
					"requested_name": fund_name,
					"fund_name": found_name,
					"daily_date": ficha.get("dailyDate"),
					"cuotaparte": ficha.get("cuotaparte"),
					"cuotaparte_previous": ficha.get("cuotapartePrevious"),
					"daily_return": ficha.get("dailyReturn"),
					"source": ficha.get("source"),
				}
			)
			if calculator_ficha is None and _normalize_text(found_name).find(normalized_target) >= 0:
				calculator_ficha = ficha
		except CafciApiError as exc:
			if isinstance(exc, CafciNetworkError):
				network_issue = True
				break
			errors.append(f"{fund_name}: {exc}")

	if errors and not rows:
		rows = [
			{
				"requested_name": fund_name,
				"fund_name": fund_name,
				"daily_date": None,
				"cuotaparte": None,
				"cuotaparte_previous": None,
				"daily_return": None,
				"source": None,
			}
			for fund_name in CAFCI_DAILY_FUND_NAMES
		]

	if calculator_ficha is None:
		for row in rows:
			if _normalize_text(row.get("requested_name")).find(normalized_target) >= 0:
				calculator_ficha = {
					"fundName": row.get("fund_name"),
					"dailyDate": row.get("daily_date"),
					"cuotaparte": row.get("cuotaparte"),
					"cuotapartePrevious": row.get("cuotaparte_previous"),
					"dailyReturn": row.get("daily_return"),
					"source": row.get("source"),
					"dailyInfoItems": [],
				}
				break

	estimated_rate_decimal, points_used = _build_1822_estimated_rate(rows)
	# Also compute a recent 7-day average from DB if available and prefer it
	recent_rate_decimal, recent_points = _compute_recent_7day_rate()
	# Compute geometric average daily rate using all DB history points for the target fund
	geometric_rate_decimal, geometric_points = _compute_geometric_daily_rate_for_fund(CAFCI_CALCULATOR_FUND_NAME)

	# Decide data source: prefer Excel-derived series once we have >=7 excel rows
	try:
		excel_count = (
			FundCuotaparteHistory.objects.filter(
				fund_name__icontains=CAFCI_CALCULATOR_FUND_NAME,
				is_from_excel=True,
			)
			.values("quote_date")
			.distinct()
			.count()
		)
	except (OperationalError, ProgrammingError):
		excel_count = 0

	source_mode = "excel" if excel_count >= 7 else "manual"

	# Build the series to compute arithmetic/geometric rates according to source_mode
	if source_mode == "excel":
		try:
			db_rows = list(
				FundCuotaparteHistory.objects.filter(
					fund_name__icontains=CAFCI_CALCULATOR_FUND_NAME,
					is_from_excel=True,
				)
				.order_by("quote_date")
				.values_list("quote_date", "cuotaparte")
			)
		except (OperationalError, ProgrammingError):
			db_rows = []
		series_points = [(r[0], r[1]) for r in db_rows]
	else:
		series_points = list(CAFCI_1822_BASE_HISTORY)

	# Arithmetic rate from series
	arith_rate_decimal, arith_points = _compute_cuotaparte_average_daily_rate(series_points)
	# Geometric rate from series
	geom_rate_decimal, geom_points = _compute_geometric_from_points(series_points)
	estimated_rate_decimal = _sanitize_rate_decimal(estimated_rate_decimal)
	recent_rate_decimal = _sanitize_rate_decimal(recent_rate_decimal)
	geometric_rate_decimal = _sanitize_rate_decimal(geometric_rate_decimal)
	arith_rate_decimal = _sanitize_rate_decimal(arith_rate_decimal)
	geom_rate_decimal = _sanitize_rate_decimal(geom_rate_decimal)
	estimated_rate_pct = None
	if estimated_rate_decimal is not None:
		estimated_rate_pct = estimated_rate_decimal * Decimal("100")
	series_arith_pct = arith_rate_decimal * Decimal("100") if arith_rate_decimal is not None else None
	series_geom_pct = geom_rate_decimal * Decimal("100") if geom_rate_decimal is not None else None

	for row in rows:
		fund_name = row.get("fund_name") or row.get("requested_name") or ""
		# Keep displayed estimated average consistent with the active source series first.
		if _normalize_text(fund_name).find(normalized_target) >= 0:
			if series_arith_pct is not None and arith_points >= 2:
				row["estimated_avg_return_pct"] = series_arith_pct
			elif series_geom_pct is not None and geom_points >= 2:
				row["estimated_avg_return_pct"] = series_geom_pct
			elif geometric_rate_decimal is not None and geometric_points >= 2:
				row["estimated_avg_return_pct"] = geometric_rate_decimal * Decimal("100")
			elif recent_rate_decimal is not None and recent_points >= 2:
				row["estimated_avg_return_pct"] = recent_rate_decimal * Decimal("100")
			elif estimated_rate_pct is not None:
				row["estimated_avg_return_pct"] = estimated_rate_pct
			else:
				row["estimated_avg_return_pct"] = None
		else:
			row["estimated_avg_return_pct"] = None

	basic_context["cafci_fund_rows"] = rows
	basic_context["cafci_local_updated_at"] = timezone.localtime(timezone.now()) if rows else None
	basic_context["cafci_1822_estimated_rate_decimal"] = estimated_rate_decimal
	basic_context["cafci_1822_7day_rate_decimal"] = recent_rate_decimal
	basic_context["cafci_1822_7day_points_used"] = recent_points
	basic_context["cafci_1822_history_geom_rate_decimal"] = geometric_rate_decimal
	basic_context["cafci_1822_history_geom_points_used"] = geometric_points
	basic_context["cafci_1822_source_mode"] = source_mode
	basic_context["cafci_1822_series_arith_rate_decimal"] = arith_rate_decimal
	basic_context["cafci_1822_series_arith_points"] = arith_points
	basic_context["cafci_1822_series_geom_rate_decimal"] = geom_rate_decimal
	basic_context["cafci_1822_series_geom_points"] = geom_points
	basic_context["cafci_1822_series_arith_rate_decimal_str"] = _rate_decimal_to_plain_string(arith_rate_decimal)
	basic_context["cafci_1822_series_geom_rate_decimal_str"] = _rate_decimal_to_plain_string(geom_rate_decimal)
	basic_context["cafci_1822_geometric_rate_decimal"] = geom_rate_decimal
	basic_context["cafci_1822_geometric_points_used"] = geom_points
	# Also expose geometric rate as percentage for easier template rendering
	if geom_rate_decimal is not None:
		try:
			basic_context["cafci_1822_geometric_rate_pct"] = float(geom_rate_decimal * Decimal("100"))
		except Exception:
			basic_context["cafci_1822_geometric_rate_pct"] = None
	else:
		basic_context["cafci_1822_geometric_rate_pct"] = None
	basic_context["cafci_1822_estimated_rate_pct"] = estimated_rate_pct
	basic_context["cafci_1822_points_used"] = points_used

	if calculator_ficha is not None:
		basic_context.update(
			{
				"cafci_ficha": calculator_ficha,
				"cafci_daily_info_items": calculator_ficha.get("dailyInfoItems") or [],
				"cafci_source_ficha": calculator_ficha.get("source"),
			}
		)

	if errors:
		basic_context["cafci_error"] = " | ".join(errors)
	elif network_issue:
		basic_context["cafci_notice"] = (
			"No se pudo conectar con CAFCI (error SSL/TLS o red). "
			"La app sigue funcionando con el promedio estimado local para la calculadora."
		)

	if not rows and not errors:
		basic_context["cafci_error"] = "No se encontraron los fondos solicitados en la planilla diaria de CAFCI."

	return basic_context


def _compute_recent_7day_rate():
	"""Compute average daily return using up to the last 7 calendar days of DB points.

	Returns tuple (average_decimal, points_used).
	"""
	try:
		cutoff = date.today() - timedelta(days=7)
		db_points = list(
			FundCuotaparteHistory.objects.filter(fund_name=CAFCI_CALCULATOR_FUND_NAME, quote_date__gte=cutoff)
			.values_list("quote_date", "cuotaparte")
		)
	except (OperationalError, ProgrammingError):
		db_points = []

	if not db_points:
		return None, 0

	return _compute_cuotaparte_average_daily_rate(db_points)


def _resolve_request_scenario(request):
	scenario = resolve_default_scenario()
	raw_scenario_id = request.POST.get("scenario_id") or request.GET.get("scenario_id")
	if not raw_scenario_id:
		return scenario
	try:
		scenario_id = int(raw_scenario_id)
	except (TypeError, ValueError):
		return scenario
	requested_scenario = Scenario.objects.filter(pk=scenario_id).first()
	if requested_scenario is None or not is_dashboard_visible_scenario(requested_scenario):
		return scenario
	return requested_scenario


def _is_real_scenario(scenario):
	if scenario is None:
		return False
	return "real" in _normalize_text(scenario.name)


def _build_home_url(*, scenario, year=None, month=None, provider=None, payment_date=None, anchor=None):
	params = {"scenario_id": scenario.id}
	if year is not None:
		params["year"] = year
	if month is not None:
		params["month"] = month
	if provider is not None:
		params["provider"] = provider
	if payment_date is not None:
		params["payment_date"] = payment_date.isoformat() if hasattr(payment_date, "isoformat") else payment_date
	url = f"{reverse('dashboard:home')}?{urlencode(params)}"
	if anchor:
		url = f"{url}{anchor}"
	return url


@login_required
def dashboard_home(request):
	available_scenarios = get_dashboard_scenarios()
	scenario = _resolve_request_scenario(request)
	requested_scenario_id = request.GET.get("scenario_id")
	if requested_scenario_id:
		try:
			requested_scenario_id = int(requested_scenario_id)
			scenario = next((s for s in available_scenarios if s.id == requested_scenario_id), scenario)
		except (TypeError, ValueError):
			pass

	if not scenario:
		return render(request, "dashboard/home.html", {"no_data": True})

	provider_qs = scenario.expenses.values_list("provider_id", flat=True).distinct()
	today = date.today()

	# Determine the selected year (may come from query params) so we can build the month selector correctly.
	selected_year = scenario.year
	raw_year = request.GET.get("year")
	if raw_year:
		try:
			selected_year = int(raw_year)
		except (TypeError, ValueError):
			selected_year = scenario.year

	# Determine the earliest month with data so the user can navigate to January/Febrero if needed.
	dashboard_start_month = scenario.start_month
	min_investment_date = (
		InvestmentDailySnapshot.objects.filter(scenario=scenario, snapshot_date__year=selected_year)
			.aggregate(min_date=Min("snapshot_date"))["min_date"]
	)
	if min_investment_date:
		dashboard_start_month = min(dashboard_start_month, min_investment_date.month)

	period_form = DashboardFilterForm(
		request.GET or None,
		year=selected_year,
		start_month=dashboard_start_month,
		scenario_choices=[(s.id, f"{s.name} ({s.year})") for s in available_scenarios],
		selected_scenario_id=scenario.id,
	)
	expense_filter_form = ExpenseFilterForm(
		request.GET or None,
		provider_queryset=Provider.objects.filter(id__in=provider_qs),
	)

	selected_month = dashboard_start_month
	raw_month = request.GET.get("month")
	if raw_month:
		try:
			selected_month = int(raw_month)
		except (TypeError, ValueError):
			selected_month = dashboard_start_month
	elif raw_year is None and scenario.year == today.year:
		selected_month = today.month
	if selected_month < dashboard_start_month:
		selected_month = dashboard_start_month
	period_form.fields["year"].initial = selected_year
	period_form.fields["month"].initial = selected_month
	selected_provider = None
	selected_payment_date = None

	if period_form.is_valid():
		selected_form_scenario_id = int(period_form.cleaned_data["scenario_id"])
		selected_scenario = next((s for s in available_scenarios if s.id == selected_form_scenario_id), None)
		if selected_scenario is not None and selected_scenario.id != scenario.id:
			scenario = selected_scenario
			provider_qs = scenario.expenses.values_list("provider_id", flat=True).distinct()
			expense_filter_form = ExpenseFilterForm(
				request.GET or None,
				provider_queryset=Provider.objects.filter(id__in=provider_qs),
			)
		selected_year = period_form.cleaned_data["year"]
		selected_month = int(period_form.cleaned_data["month"])

		# Recompute the earliest month with data for the chosen scenario/year so the month selector can include Enero/Feb.
		dashboard_start_month = scenario.start_month
		min_investment_date = (
			InvestmentDailySnapshot.objects.filter(scenario=scenario, snapshot_date__year=selected_year)
				.aggregate(min_date=Min("snapshot_date"))["min_date"]
		)
		if min_investment_date:
			dashboard_start_month = min(dashboard_start_month, min_investment_date.month)
		if selected_month < dashboard_start_month:
			selected_month = dashboard_start_month
		period_form.fields["month"].choices = [(m, MONTH_NAME_ES[m]) for m in range(dashboard_start_month, 13)]
		period_form.fields["month"].initial = selected_month

	if expense_filter_form.is_valid():
		selected_provider = expense_filter_form.cleaned_data.get("provider")
		selected_payment_date = expense_filter_form.cleaned_data.get("payment_date")

	requested_sort = request.GET.get("sort")
	requested_dir = request.GET.get("dir", "asc")
	allowed_sorts = {
		"payment_date",
		"payment_label",
		"provider",
		"nueva_clasificacion",
		"source_tag",
		"amount",
	}
	effective_sort = requested_sort if requested_sort in allowed_sorts else ""
	effective_dir = "desc" if requested_dir == "desc" else "asc"

	def _next_dir_for(field_name):
		if effective_sort == field_name and effective_dir == "asc":
			return "desc"
		return "asc"

	is_real_scenario = _is_real_scenario(scenario)
	cash_rows = build_year_cash_projection(scenario=scenario, year=selected_year, start_month=dashboard_start_month)
	month_rows = [row for row in cash_rows if row["mes"] == selected_month]
	real_snapshot = build_real_projection_snapshot(scenario=scenario, year=selected_year, month=selected_month)
	# Rolling projection: show only selected month and onward.
	monthly_summary = monthly_interest_summary(cash_rows, selected_month)
	chart_summary = monthly_interest_summary(cash_rows, dashboard_start_month)
	calendar_payload = get_month_calendar_payload(cash_rows, selected_year, selected_month)

	investment_rows = list(
		InvestmentDailySnapshot.objects.filter(
			scenario=scenario,
			snapshot_date__year=selected_year,
			snapshot_date__month=selected_month,
		)
		.prefetch_related("flows")
		.order_by("snapshot_date")
	)
	investment_rows_current = list(
		InvestmentDailySnapshot.objects.filter(
			scenario=scenario,
			snapshot_date__lte=date.today(),
		)
		.prefetch_related("flows")
		.order_by("snapshot_date")
	)
	if not is_real_scenario:
		investment_rows = []
		investment_rows_current = []

	# Preload cuotaparte history so we can compute how each investment evolved until today.
	fund_name = CAFCI_CALCULATOR_FUND_NAME
	cuotaparte_qs = FundCuotaparteHistory.objects.filter(fund_name=fund_name).order_by("quote_date")
	cuotaparte_history = {r.quote_date: r.cuotaparte for r in cuotaparte_qs}
	cuotaparte_dates = sorted(cuotaparte_history.keys())

	latest_cuotaparte = cuotaparte_history.get(cuotaparte_dates[-1]) if cuotaparte_dates else None

	def _format_currency(value: Decimal | None) -> str:
		if value is None:
			return "—"
		return f"$ {value:,.2f}"

	def _find_cuotaparte_before_or_on(target: date) -> Decimal | None:
		if not cuotaparte_dates:
			return None
		idx = bisect_right(cuotaparte_dates, target)
		if idx == 0:
			return None
		return cuotaparte_history[cuotaparte_dates[idx - 1]]

	def _build_active_investment_lots(snapshots):
		open_lots = []

		def _consume_lots(remaining, *, preferred_label=None):
			for same_label_only in (True, False):
				if remaining <= 0:
					break
				for lot in open_lots:
					if remaining <= 0:
						break
					if lot["amount"] <= 0:
						continue
					if preferred_label:
						if same_label_only and lot["label"] != preferred_label:
							continue
						if not same_label_only and lot["label"] == preferred_label:
							continue
					consume_amount = min(lot["amount"], remaining)
					lot["amount"] -= consume_amount
					remaining -= consume_amount
			return remaining

		for snap in snapshots:
			for flow in snap.flows.all():
				amount = flow.amount or Decimal("0")
				if amount > 0:
					open_lots.append(
						{
							"snapshot_date": snap.snapshot_date,
							"label": flow.label,
							"amount": amount,
						}
					)
				elif amount < 0:
					_consume_lots(-amount, preferred_label=flow.label)

		return [lot for lot in open_lots if lot["amount"] > 0]

	last_cut_date = None
	for row in investment_rows_current:
		if row.was_cut:
			last_cut_date = row.snapshot_date
	active_snapshots = [
		row for row in investment_rows_current if last_cut_date is None or row.snapshot_date > last_cut_date
	]
	active_investment_lots = _build_active_investment_lots(active_snapshots)
	active_investment_capital = sum((lot["amount"] for lot in active_investment_lots), Decimal("0"))
	active_lots_by_date = {}
	for lot in active_investment_lots:
		date_bucket = active_lots_by_date.setdefault(
			lot["snapshot_date"],
			{"net_flow": Decimal("0"), "flows": {}},
		)
		date_bucket["net_flow"] += lot["amount"]
		date_bucket["flows"][lot["label"]] = date_bucket["flows"].get(lot["label"], Decimal("0")) + lot["amount"]

	# Add investment flows tooltip data for the calendar view.
	investment_by_date = {row.snapshot_date: row for row in investment_rows}
	for week in calendar_payload["weeks"]:
		for day in week:
			if not day["in_month"]:
				day["net_flow"] = None
				day["investment_tooltip"] = ""
				continue
			active_entry = active_lots_by_date.get(day["date"]) if is_real_scenario else None
			snapshot = investment_by_date.get(day["date"])
			if is_real_scenario and not active_entry:
				day["interes"] = snapshot.daily_yield if snapshot else day.get("interes")
				day["net_flow"] = None
				day["investment_tooltip"] = ""
				continue
			if not is_real_scenario and not snapshot:
				day["net_flow"] = None
				day["investment_tooltip"] = ""
				continue

			# Override daily interest with the actual yield from the imported investment snapshot
			if snapshot:
				day["interes"] = snapshot.daily_yield
			if is_real_scenario:
				day["net_flow"] = active_entry["net_flow"]
				parts = [
					f"Fecha: {day['date']:%d/%m/%Y}",
					f"Total invertido vigente: {_format_currency(active_entry['net_flow'])}",
				]
				flows = sorted(active_entry["flows"].items())
				if flows:
					parts.append("Desglose activo:")
					for label, amount in flows:
						parts.append(f"{label}: {_format_currency(amount)}")
				else:
					parts.append("Sin desglose disponible.")
				day["investment_tooltip"] = "\n".join(parts)
			else:
				day["net_flow"] = snapshot.net_flow
				parts = [
					f"Fecha: {snapshot.snapshot_date:%d/%m/%Y}",
					f"Total invertido ese día: {_format_currency(snapshot.net_flow)}",
				]

				flows = list(snapshot.flows.all())
				if flows:
					parts.append("Desglose de la inversión:")
					for flow in flows:
						parts.append(f"{flow.label}: {_format_currency(flow.amount)}")
				else:
					parts.append("Sin desglose disponible.")

				day["investment_tooltip"] = "\n".join(parts)

	expense_qs, expense_total = filtered_expenses(
		scenario=scenario,
		year=selected_year,
		month=selected_month,
		provider=selected_provider,
		payment_date=selected_payment_date,
		sort_field=effective_sort or None,
		sort_dir=effective_dir,
	)
	expense_change_logs = scenario.expense_change_logs.select_related("changed_by", "expense", "expense__provider")[:120]

	monthly_incomes = IncomeEntry.objects.filter(
		scenario=scenario,
		entry_date__year=selected_year,
		entry_date__month=selected_month,
	).order_by("entry_date")
	income_total = monthly_incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0")

	# Calculator options come from the selected month only, independent from table filters.
	calc_expenses_qs = (
		Expense.objects.filter(
			scenario=scenario,
			year=selected_year,
			month=selected_month,
		)
		.select_related("provider")
		.exclude(payment_date__isnull=True)
		.exclude(amount=0)
		.order_by("provider__name", "payment_date", "payment_label", "id")
	)
	calc_expense_options = [
		{
			"id": exp.id,
			"provider": exp.provider.name.strip() if exp.provider and exp.provider.name else "",
			"payment_date": exp.payment_date,
			"payment_label": (exp.payment_label or "").strip(),
			"amount": float(exp.amount or 0),
		}
		for exp in calc_expenses_qs[:1000]
	]
	chart_labels = [x["mes_nombre"] for x in chart_summary]
	chart_values = [float(x["interes_mes"] or 0) for x in chart_summary]

	latest_investment_current = investment_rows_current[-1] if investment_rows_current else None
	investment_active_capital = active_investment_capital if is_real_scenario else (latest_investment_current.active_capital if latest_investment_current else Decimal("0"))
	investment_daily_yield = latest_investment_current.daily_yield if latest_investment_current else Decimal("0")
	investment_cumulative_yield = latest_investment_current.cumulative_yield if latest_investment_current else Decimal("0")
	investment_cut_days = sum(1 for row in investment_rows_current if row.was_cut)

	# Compute total interest and weighted average daily rate for currently active investment lots.
	investment_active_interest_total = Decimal("0")
	investment_daily_rate_pct = Decimal("0")
	weighted_daily_rate_sum = Decimal("0")
	weighted_amount_total = Decimal("0")
	latest_quote_date = cuotaparte_dates[-1] if cuotaparte_dates else None
	if latest_cuotaparte is not None and latest_quote_date is not None:
		for lot in active_investment_lots:
			cuota_origen = _find_cuotaparte_before_or_on(lot["snapshot_date"])
			if cuota_origen in (None, 0):
				continue
			rendimiento = (latest_cuotaparte / cuota_origen) - Decimal("1")
			days_elapsed = max((latest_quote_date - lot["snapshot_date"]).days, 1)
			daily_rate_decimal = rendimiento / Decimal(days_elapsed)
			investment_active_interest_total += lot["amount"] * rendimiento
			weighted_daily_rate_sum += lot["amount"] * daily_rate_decimal
			weighted_amount_total += lot["amount"]
	if weighted_amount_total > 0:
		investment_daily_rate_pct = (weighted_daily_rate_sum / weighted_amount_total) * Decimal("100")

	expense_qs, expense_total = filtered_expenses(
		scenario=scenario,
		year=selected_year,
		month=selected_month,
		provider=selected_provider,
		payment_date=selected_payment_date,
		sort_field=effective_sort or None,
		sort_dir=effective_dir,
	)
	context = {
		"scenario": scenario,
		"is_real_scenario": is_real_scenario,
		"selected_scenario_id": scenario.id,
		"available_scenarios": available_scenarios,
		"show_cafci_panel": scenario.interest_mode == Scenario.INTEREST_MODE_WEEKLY_AVG,
		"period_form": period_form,
		"expense_filter_form": expense_filter_form,
		"month_name": MONTH_NAME_ES[selected_month],
		"selected_year": selected_year,
		"selected_month": selected_month,
		"calendar_payload": calendar_payload,
		"month_rows": month_rows,
		"monthly_summary": monthly_summary,
		"chart_labels": chart_labels,
		"chart_values": chart_values,
		"expense_rows": expense_qs[:250],
		"expense_total": expense_total,
		"expense_change_logs": expense_change_logs,
		"income_rows": monthly_incomes[:250],
		"income_total": income_total,
		"total_mes": _sum_interest(month_rows),
		"total_hasta_hoy": _sum_interest([row for row in cash_rows if row["fecha"] <= today]),
		"total_anual": _sum_interest([row for row in cash_rows if row["mes"] >= selected_month]),
		"daily_rate_pct": float(scenario.daily_interest_rate * Decimal("100")),
		"daily_rate_pct_input": f"{(scenario.daily_interest_rate * Decimal('100')):.4f}",
		"adelanto_daily_rate_decimal": f"{scenario.daily_interest_rate:.6f}",
		"calc_expense_options": calc_expense_options,
		"real_projection_rows": real_snapshot["rows"],
		"real_projected_income_total": real_snapshot["projected_income_total"],
		"real_actual_income_total": real_snapshot["actual_income_total"],
		"real_projected_expense_total": real_snapshot["projected_expense_total"],
		"real_actual_expense_total": real_snapshot["actual_expense_total"],
		"real_income_variance_total": real_snapshot["income_variance_total"],
		"real_expense_variance_total": real_snapshot["expense_variance_total"],
		"real_projected_net_total": real_snapshot["projected_net_total"],
		"real_actual_net_total": real_snapshot["actual_net_total"],
		"real_net_variance_total": real_snapshot["net_variance_total"],
		"real_days_with_data": real_snapshot["days_with_real_data"],
		"real_days_in_projection": real_snapshot["days_in_projection"],
		"investment_rows": investment_rows,
		"investment_active_capital": investment_active_capital,
		"investment_daily_yield": investment_daily_yield,
		"investment_cumulative_yield": investment_cumulative_yield,
		"investment_cut_days": investment_cut_days,
		"investment_daily_rate_pct": investment_daily_rate_pct,
		"investment_last_date": latest_investment_current.snapshot_date if latest_investment_current else None,
		"investment_active_interest_total": investment_active_interest_total,
		"expense_sort": effective_sort,
		"expense_dir": effective_dir,
		"next_dir_payment_date": _next_dir_for("payment_date"),
		"next_dir_payment_label": _next_dir_for("payment_label"),
		"next_dir_provider": _next_dir_for("provider"),
		"next_dir_nueva_clasificacion": _next_dir_for("nueva_clasificacion"),
		"next_dir_source_tag": _next_dir_for("source_tag"),
		"next_dir_amount": _next_dir_for("amount"),
		"today": date.today(),
		"home_url_with_scenario": _build_home_url(scenario=scenario, year=selected_year, month=selected_month),
	}
	if context["show_cafci_panel"]:
		context.update(_build_cafci_context(request))

	fixed_rate_decimal = _sanitize_rate_decimal(scenario.daily_interest_rate) or Decimal("0")
	context["scenario_interest_mode"] = scenario.interest_mode

	if scenario.interest_mode == Scenario.INTEREST_MODE_WEEKLY_AVG:
		# Weekly-average scenario: prefer calculated rates from series/history.
		preferred_rates = [
			_sanitize_rate_decimal(context.get("cafci_1822_series_arith_rate_decimal")),
			_sanitize_rate_decimal(context.get("cafci_1822_series_geom_rate_decimal")),
			_sanitize_rate_decimal(context.get("cafci_1822_geometric_rate_decimal")),
			_sanitize_rate_decimal(context.get("cafci_1822_7day_rate_decimal")),
			_sanitize_rate_decimal(context.get("cafci_1822_estimated_rate_decimal")),
		]
		selected_rate_decimal = next((r for r in preferred_rates if r is not None), fixed_rate_decimal)
		context["daily_rate_pct"] = float(selected_rate_decimal * Decimal("100"))
		context["daily_rate_pct_input"] = f"{(selected_rate_decimal * Decimal('100')):.4f}"
		context["adelanto_daily_rate_decimal"] = _rate_decimal_to_plain_string(selected_rate_decimal)
		context["calculator_rate_arith_decimal"] = _rate_decimal_to_plain_string(
			_sanitize_rate_decimal(context.get("cafci_1822_series_arith_rate_decimal")) or selected_rate_decimal
		)
		context["calculator_rate_geom_decimal"] = _rate_decimal_to_plain_string(
			_sanitize_rate_decimal(context.get("cafci_1822_series_geom_rate_decimal")) or selected_rate_decimal
		)
	else:
		# Fixed scenario: keep explicit configured rate (e.g., 0.0967%) everywhere in calculators.
		context["daily_rate_pct"] = float(fixed_rate_decimal * Decimal("100"))
		context["daily_rate_pct_input"] = f"{(fixed_rate_decimal * Decimal('100')):.4f}"
		fixed_rate_str = _rate_decimal_to_plain_string(fixed_rate_decimal)
		context["adelanto_daily_rate_decimal"] = fixed_rate_str
		context["calculator_rate_arith_decimal"] = fixed_rate_str
		context["calculator_rate_geom_decimal"] = fixed_rate_str

	return render(request, "dashboard/home.html", context)


@login_required
def expense_list(request):
	scenario = _resolve_request_scenario(request)
	qs = Expense.objects.none() if scenario is None else Expense.objects.filter(scenario=scenario).select_related("provider").order_by("-year", "month", "payment_date")
	return render(request, "dashboard/expense_list.html", {"scenario": scenario, "expenses": qs[:400]})


@login_required
@permission_required("dashboard.change_expense", raise_exception=True)
def expense_edit(request, pk):
	expense = get_object_or_404(Expense.objects.select_related("scenario"), pk=pk)
	if request.method == "POST":
		before_expense = Expense.objects.select_related("provider").get(pk=expense.pk)
		form = ExpenseForm(request.POST, instance=expense)
		if form.is_valid():
			expense = form.save()
			comment = form.cleaned_data["change_comment"].strip()
			summary = _build_expense_update_summary(before_expense, expense)
			_log_expense_change(
				request=request,
				expense=expense,
				action=ExpenseChangeLog.ACTION_UPDATE,
				comment=comment,
				change_summary=summary,
			)
			messages.success(request, "Gasto actualizado correctamente.")
			return redirect(_build_home_url(scenario=expense.scenario, year=expense.year, month=expense.month, anchor="#expensePanel"))
	else:
		form = ExpenseForm(instance=expense)

	return render(
		request,
		"dashboard/expense_form.html",
		{
			"form": form,
			"expense": expense,
			"scenario_id": expense.scenario_id,
			"cancel_url": _build_home_url(scenario=expense.scenario, year=expense.year, month=expense.month, anchor="#expensePanel"),
		},
	)


@login_required
@permission_required("dashboard.delete_expense", raise_exception=True)
@require_POST
def expense_delete(request, pk):
	expense = get_object_or_404(Expense.objects.select_related("provider", "scenario"), pk=pk)
	comment = (request.POST.get("change_comment") or "").strip()
	if not comment:
		messages.error(request, "Debés agregar un comentario para registrar la eliminación.")
		next_url = request.POST.get("next") or reverse("dashboard:home")
		if not next_url.startswith("/"):
			next_url = reverse("dashboard:home")
		return redirect(next_url)

	summary = (
		f"Eliminado gasto {expense.payment_label or '—'} | "
		f"Proveedor: {_format_expense_value('provider', expense.provider)} | "
		f"Fecha: {_format_expense_value('payment_date', expense.payment_date)} | "
		f"Monto: {_format_expense_value('amount', expense.amount)}"
	)
	_log_expense_change(
		request=request,
		expense=expense,
		action=ExpenseChangeLog.ACTION_DELETE,
		comment=comment,
		change_summary=summary,
	)
	expense.delete()
	messages.success(request, "Gasto eliminado correctamente.")
	next_url = request.POST.get("next") or reverse("dashboard:home")
	if not next_url.startswith("/"):
		next_url = reverse("dashboard:home")
	return redirect(next_url)


@login_required
@permission_required("dashboard.add_expense", raise_exception=True)
def expense_create(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "Primero importá un Excel para crear gastos.")
		return redirect("dashboard:home")

	if request.method == "POST":
		form = ManualExpenseForm(request.POST)
		if form.is_valid():
			expense = form.save(commit=False)
			expense.scenario = scenario
			expense.source_tag = form.cleaned_data.get("source_tag") or Expense.SOURCE_MANUAL
			expense.save()
			comment = form.cleaned_data["change_comment"].strip()
			summary = (
				f"Creado gasto {expense.payment_label or '—'} | "
				f"Proveedor: {_format_expense_value('provider', expense.provider)} | "
				f"Fecha: {_format_expense_value('payment_date', expense.payment_date)} | "
				f"Monto: {_format_expense_value('amount', expense.amount)}"
			)
			_log_expense_change(
				request=request,
				expense=expense,
				action=ExpenseChangeLog.ACTION_CREATE,
				comment=comment,
				change_summary=summary,
			)
			messages.success(request, "Gasto cargado correctamente.")
			return redirect(
				_build_home_url(
					scenario=expense.scenario,
					year=expense.year,
					month=expense.month,
					provider=expense.provider_id,
					payment_date=expense.payment_date,
					anchor="#expensePanel",
				)
			)
	else:
		form = ManualExpenseForm(
			initial={
				"year": request.GET.get("year") or scenario.year,
				"month": request.GET.get("month") or scenario.start_month,
				"payment_date": request.GET.get("payment_date") or date.today(),
				"source_tag": Expense.SOURCE_MANUAL,
			}
		)

	return render(
		request,
		"dashboard/expense_form.html",
		{
			"form": form,
			"title": "Nuevo gasto",
			"is_create": True,
			"scenario_id": scenario.id,
			"cancel_url": _build_home_url(
				scenario=scenario,
				year=request.GET.get("year") or scenario.year,
				month=request.GET.get("month") or scenario.start_month,
				anchor="#expensePanel",
			),
		},
	)


@login_required
def expense_export_excel(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "No hay escenario activo para exportar gastos.")
		return redirect("dashboard:home")

	provider_qs = scenario.expenses.values_list("provider_id", flat=True).distinct()
	expense_filter_form = ExpenseFilterForm(
		request.GET or None,
		provider_queryset=Provider.objects.filter(id__in=provider_qs),
	)

	selected_year = int(request.GET.get("year") or scenario.year)
	selected_month = int(request.GET.get("month") or scenario.start_month)
	selected_provider = None
	selected_payment_date = None

	if expense_filter_form.is_valid():
		selected_provider = expense_filter_form.cleaned_data.get("provider")
		selected_payment_date = expense_filter_form.cleaned_data.get("payment_date")

	expense_qs, _ = filtered_expenses(
		scenario=scenario,
		year=selected_year,
		month=selected_month,
		provider=selected_provider,
		payment_date=selected_payment_date,
	)

	excel_bytes = export_expenses_to_excel(expense_qs)
	filename = f"gastos_{selected_year}_{selected_month:02d}.xlsx"
	response = HttpResponse(
		excel_bytes,
		content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	)
	response["Content-Disposition"] = f'attachment; filename="{filename}"'
	return response


@login_required
@permission_required("dashboard.add_expense", raise_exception=True)
def expense_import_excel(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "No hay escenario activo para importar gastos.")
		return redirect("dashboard:home")

	result = None
	if request.method == "POST":
		form = ExpenseExcelImportForm(request.POST, request.FILES)
		if form.is_valid():
			try:
				result = import_expenses_from_excel(
					excel_bytes=form.cleaned_data["excel_file"].read(),
					scenario=scenario,
				)
			except ValueError as exc:
				messages.error(request, str(exc))
			else:
				ok_rows = result.created + result.updated
				if ok_rows:
					messages.success(
						request,
						f"Importación finalizada. Nuevos: {result.created} · Actualizados: {result.updated} · Errores: {len(result.errors)}",
					)
				elif result.errors:
					messages.error(request, "No se importaron filas válidas. Revisá los errores listados.")
	else:
		form = ExpenseExcelImportForm()

	return render(
		request,
		"dashboard/import_expenses.html",
		{
			"form": form,
			"result": result,
			"back_query": request.GET.urlencode(),
			"scenario_id": scenario.id,
		},
	)


@login_required
@permission_required("dashboard.add_incomeentry", raise_exception=True)
def income_import_excel(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "No hay escenario activo para importar ingresos.")
		return redirect("dashboard:home")

	result = None
	if request.method == "POST":
		form = IncomeExcelImportForm(request.POST, request.FILES)
		if form.is_valid():
			try:
				result = import_incomes_from_excel(
					excel_bytes=form.cleaned_data["excel_file"].read(),
					scenario=scenario,
				)
			except ValueError as exc:
				messages.error(request, str(exc))
			else:
				ok_rows = result.created + result.updated
				if ok_rows:
					messages.success(
						request,
						f"Importación de ingresos finalizada. Nuevos: {result.created} · Actualizados: {result.updated} · Errores: {len(result.errors)}",
					)
				elif result.errors:
					messages.error(request, "No se importaron filas válidas de ingresos. Revisá los errores listados.")
	else:
		form = IncomeExcelImportForm()

	return render(
		request,
		"dashboard/import_incomes.html",
		{
			"form": form,
			"result": result,
			"back_query": request.GET.urlencode(),
			"scenario_id": scenario.id,
		},
	)


@login_required
@permission_required("dashboard.add_expense", raise_exception=True)
def investment_import_excel(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "No hay escenario activo para importar inversiones.")
		return redirect("dashboard:home")

	result = None
	if request.method == "POST":
		form = InvestmentExcelImportForm(request.POST, request.FILES)
		if form.is_valid():
			try:
				result = import_investment_snapshots_from_excel(
					excel_bytes=form.cleaned_data["excel_file"].read(),
					scenario=scenario,
					year=scenario.year,
					daily_rate=scenario.daily_interest_rate,
				)
			except ValueError as exc:
				messages.error(request, str(exc))
			else:
				messages.success(
					request,
					"Importación de inversiones finalizada. "
					f"Días: {result.processed_days} · Corte por neteo: {result.cuts_count} · "
					f"Rango: {result.first_date} a {result.last_date}",
				)
	else:
		form = InvestmentExcelImportForm()

	return render(
		request,
		"dashboard/import_investments.html",
		{
			"form": form,
			"result": result,
			"scenario_id": scenario.id,
			"back_query": request.GET.urlencode(),
		},
	)


@login_required
@permission_required("dashboard.add_incomeentry", raise_exception=True)
def income_create(request):
	scenario = _resolve_request_scenario(request)
	if not scenario:
		messages.error(request, "Primero importá un Excel para crear ingresos.")
		return redirect("dashboard:home")

	if request.method == "POST":
		form = IncomeEntryForm(request.POST)
		if form.is_valid():
			obj = form.save(commit=False)
			obj.scenario = scenario
			obj.source_tag = "manual"
			obj.save()
			messages.success(request, "Ingreso cargado correctamente.")
			return redirect(_build_home_url(scenario=scenario, year=obj.entry_date.year, month=obj.entry_date.month, anchor="#expensePanel"))
	else:
		form = IncomeEntryForm(initial={"entry_date": date.today()})

	return render(
		request,
		"dashboard/income_form.html",
		{
			"form": form,
			"title": "Nuevo ingreso",
			"scenario_id": scenario.id,
			"cancel_url": _build_home_url(scenario=scenario, anchor="#expensePanel"),
		},
	)


@login_required
@permission_required("dashboard.change_incomeentry", raise_exception=True)
def income_edit(request, pk):
	income = get_object_or_404(IncomeEntry, pk=pk)
	if request.method == "POST":
		form = IncomeEntryForm(request.POST, instance=income)
		if form.is_valid():
			obj = form.save(commit=False)
			if obj.source_tag == "excel":
				obj.source_tag = "manual"
			obj.save()
			messages.success(request, "Ingreso actualizado correctamente.")
			return redirect(_build_home_url(scenario=obj.scenario, year=obj.entry_date.year, month=obj.entry_date.month, anchor="#expensePanel"))
	else:
		form = IncomeEntryForm(instance=income)

	return render(
		request,
		"dashboard/income_form.html",
		{
			"form": form,
			"title": "Editar ingreso",
			"scenario_id": income.scenario_id,
			"cancel_url": _build_home_url(scenario=income.scenario, year=income.entry_date.year, month=income.entry_date.month, anchor="#expensePanel"),
		},
	)


@login_required
@user_passes_test(lambda u: u.is_staff)
def import_excel_view(request):
	if request.method == "POST":
		form = ExcelImportForm(request.POST, request.FILES)
		if form.is_valid():
			result = import_excel_bytes(
				excel_bytes=form.cleaned_data["excel_file"].read(),
				scenario_name=form.cleaned_data["scenario_name"],
				year=form.cleaned_data["year"],
				start_month=form.cleaned_data["start_month"],
				replace_existing=form.cleaned_data["replace_existing"],
			)
			messages.success(
				request,
				"Importación finalizada. "
				f"Proyecciones: {result['daily_projections']} · Ingresos: {result['income_entries']} · "
				f"Reglas: {result['payment_rules']} · Gastos: {result['expenses']}",
			)
			return HttpResponseRedirect(reverse("dashboard:home"))
	else:
		form = ExcelImportForm()

	return render(request, "dashboard/import_excel.html", {"form": form})


@login_required
@user_passes_test(lambda u: u.is_staff)
def cafci_manual_history(request):
	"""Allow staff to submit up to 7 historical (date, cuotaparte) points for the target fund.

	The form accepts inputs named `date_1..date_7` and `value_1..value_7` (POST).
	Each valid pair is persisted with `update_or_create` into `FundCuotaparteHistory`.
	"""
	if request.method == "POST":
		created = 0
		updated = 0
		errors = []
		for i in range(1, 8):
			raw_date = (request.POST.get(f"date_{i}") or "").strip()
			raw_value = (request.POST.get(f"value_{i}") or "").strip()
			if not raw_date or not raw_value:
				continue
			parsed_date = _parse_history_date(raw_date)
			if parsed_date is None:
				errors.append(f"Fecha inválida: {raw_date}")
				continue
			try:
				parsed_value = Decimal(raw_value.replace(",", "."))
			except (InvalidOperation, ValueError):
				errors.append(f"Valor inválido: {raw_value}")
				continue
			try:
				obj, created_flag = FundCuotaparteHistory.objects.update_or_create(
					fund_name=CAFCI_CALCULATOR_FUND_NAME,
					quote_date=parsed_date,
					defaults={"cuotaparte": parsed_value},
				)
				if created_flag:
					created += 1
				else:
					updated += 1
			except Exception as exc:
				errors.append(str(exc))

		if errors:
			messages.error(request, "Errores: " + "; ".join(errors))
		else:
			messages.success(request, f"Historial guardado. Nuevos: {created} · Actualizados: {updated}")
		return redirect("dashboard:home")

	# GET: render simple form
	return render(request, "dashboard/cafci_manual_history.html", {})


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def cafci_update(request):
	"""Trigger a download+ingest of the CAFCI planilla (protected POST).

	Runs the management commands `download_cafci_planilla` and
	`ingest_cafci_planilla` and redirects back to the dashboard with a
	success/error message.
	"""
	try:
		call_command("download_cafci_planilla")
		call_command("ingest_cafci_planilla")
	except Exception as exc:
		messages.error(request, f"Error al actualizar CAFCI: {exc}")
	else:
		messages.success(request, "Actualización CAFCI completada.")
	return redirect("dashboard:home")
