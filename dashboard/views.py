from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import DashboardFilterForm, ExcelImportForm, ExpenseForm, IncomeEntryForm
from .models import Expense, IncomeEntry, Provider, Scenario
from .services.dashboard_logic import (
	build_year_cash_projection,
	filtered_expenses,
	get_month_calendar_payload,
	monthly_interest_summary,
	resolve_default_scenario,
)
from .services.parsing import MONTH_NAME_ES
from .services.excel_importer import import_excel_bytes


def _sum_interest(rows):
	total = Decimal("0")
	for row in rows:
		if row["interes_diario"] is not None:
			total += row["interes_diario"]
	return total


@login_required
def dashboard_home(request):
	scenario = resolve_default_scenario()

	if not scenario:
		return render(request, "dashboard/home.html", {"no_data": True})

	provider_qs = scenario.expenses.values_list("provider_id", flat=True).distinct()
	form = DashboardFilterForm(
		request.GET or None,
		year=scenario.year,
		start_month=scenario.start_month,
		provider_queryset=Provider.objects.filter(id__in=provider_qs),
	)

	selected_year = scenario.year
	selected_month = scenario.start_month
	selected_provider = None
	selected_payment_date = None

	if form.is_valid():
		selected_year = form.cleaned_data["year"]
		selected_month = int(form.cleaned_data["month"])
		selected_provider = form.cleaned_data.get("provider")
		selected_payment_date = form.cleaned_data.get("payment_date")

	cash_rows = build_year_cash_projection(scenario=scenario, year=selected_year)
	month_rows = [row for row in cash_rows if row["mes"] == selected_month]
	monthly_summary = monthly_interest_summary(cash_rows, scenario.start_month)
	calendar_payload = get_month_calendar_payload(cash_rows, selected_year, selected_month)

	expense_qs, expense_total = filtered_expenses(
		scenario=scenario,
		year=selected_year,
		month=selected_month,
		provider=selected_provider,
		payment_date=selected_payment_date,
	)

	monthly_incomes = IncomeEntry.objects.filter(
		scenario=scenario,
		entry_date__year=selected_year,
		entry_date__month=selected_month,
	).order_by("entry_date")
	income_total = monthly_incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0")

	chart_labels = [x["mes_nombre"] for x in monthly_summary]
	chart_values = [float(x["interes_mes"] or 0) for x in monthly_summary]

	context = {
		"scenario": scenario,
		"filter_form": form,
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
		"income_rows": monthly_incomes[:250],
		"income_total": income_total,
		"total_mes": _sum_interest(month_rows),
		"total_anual": _sum_interest(cash_rows),
		"daily_rate_pct": float(scenario.daily_interest_rate * Decimal("100")),
		"today": date.today(),
	}
	return render(request, "dashboard/home.html", context)


@login_required
def expense_list(request):
	scenario = resolve_default_scenario()
	qs = Expense.objects.none() if scenario is None else Expense.objects.filter(scenario=scenario).select_related("provider").order_by("-year", "month", "payment_date")
	return render(request, "dashboard/expense_list.html", {"scenario": scenario, "expenses": qs[:400]})


@login_required
@permission_required("dashboard.change_expense", raise_exception=True)
def expense_edit(request, pk):
	expense = get_object_or_404(Expense.objects.select_related("scenario"), pk=pk)
	if request.method == "POST":
		form = ExpenseForm(request.POST, instance=expense)
		if form.is_valid():
			form.save()
			messages.success(request, "Gasto actualizado correctamente.")
			return redirect("dashboard:home")
	else:
		form = ExpenseForm(instance=expense)

	return render(request, "dashboard/expense_form.html", {"form": form, "expense": expense})


@login_required
@permission_required("dashboard.add_incomeentry", raise_exception=True)
def income_create(request):
	scenario = resolve_default_scenario()
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
			return redirect("dashboard:home")
	else:
		form = IncomeEntryForm(initial={"entry_date": date.today()})

	return render(request, "dashboard/income_form.html", {"form": form, "title": "Nuevo ingreso"})


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
			return redirect("dashboard:home")
	else:
		form = IncomeEntryForm(instance=income)

	return render(request, "dashboard/income_form.html", {"form": form, "title": "Editar ingreso"})


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
