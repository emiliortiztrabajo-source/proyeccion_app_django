from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from dashboard.models import DailyProjection, Expense, FundCuotaparteHistory, IncomeEntry, InvestmentDailyFlow, InvestmentDailySnapshot, Provider, Scenario
from dashboard.services.dashboard_logic import build_real_projection_snapshot, get_dashboard_scenarios, resolve_default_scenario
from dashboard.services.expense_excel_io import import_expenses_from_excel
from dashboard.services.income_excel_io import import_incomes_from_excel
from dashboard.services.investment_excel_io import import_investment_snapshots_from_excel


class RealProjectionSnapshotTests(TestCase):
	def test_build_real_projection_snapshot_separates_real_and_projected_totals(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))
		provider = Provider.objects.create(name="Proveedor Uno")
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 3, 17),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)
		IncomeEntry.objects.create(scenario=scenario, entry_date=date(2026, 3, 17), amount=Decimal("220.00"), source_tag="importado")
		Expense.objects.create(
			scenario=scenario,
			provider=provider,
			year=2026,
			month=3,
			amount=Decimal("80.00"),
			payment_date=date(2026, 3, 17),
			payment_label="PAGO 17",
			source_tag=Expense.SOURCE_IMPORTADO,
		)

		snapshot = build_real_projection_snapshot(scenario=scenario, year=2026, month=3)

		self.assertEqual(snapshot["projected_income_total"], Decimal("250.00"))
		self.assertEqual(snapshot["actual_income_total"], Decimal("220.00"))
		self.assertEqual(snapshot["projected_expense_total"], Decimal("100.00"))
		self.assertEqual(snapshot["actual_expense_total"], Decimal("80.00"))
		self.assertEqual(snapshot["net_variance_total"], Decimal("-10.00"))
		self.assertEqual(snapshot["days_with_real_data"], 1)


class DashboardScenarioVisibilityTests(TestCase):
	def test_dashboard_scenarios_exclude_optimistic(self):
		Scenario.objects.create(name="ESCENARIO 1 - PROYECCION CONSERVADORA", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=True)
		Scenario.objects.create(name="ESCENARIO 2 - PROYECCION OPTIMISTA", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=False)
		Scenario.objects.create(name="ESCENARIO 3 - PROYECCION REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=False)

		visible_names = [scenario.name for scenario in get_dashboard_scenarios()]

		self.assertEqual(visible_names, [
			"ESCENARIO 1 - PROYECCION CONSERVADORA",
			"ESCENARIO 3 - PROYECCION REAL",
		])

	def test_resolve_default_scenario_ignores_active_optimistic(self):
		Scenario.objects.create(name="ESCENARIO 1 - PROYECCION CONSERVADORA", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=False)
		Scenario.objects.create(name="ESCENARIO 2 - PROYECCION OPTIMISTA", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=True)
		Scenario.objects.create(name="ESCENARIO 3 - PROYECCION REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"), is_active=False)

		default_scenario = resolve_default_scenario()

		self.assertEqual(default_scenario.name, "ESCENARIO 1 - PROYECCION CONSERVADORA")


class DashboardHomeCalculatorContextTests(TestCase):
	def test_dashboard_home_builds_calc_expense_options_independent_from_expense_filter(self):
		user = get_user_model().objects.create_user(username="tester", password="secret123")
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO REAL",
			year=2026,
			start_month=1,
			daily_interest_rate=Decimal("0.001"),
		)
		provider_a = Provider.objects.create(name="Proveedor A")
		provider_b = Provider.objects.create(name="Proveedor B")

		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 1, 5),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)
		Expense.objects.create(
			scenario=scenario,
			provider=provider_a,
			year=2026,
			month=1,
			amount=Decimal("1500.00"),
			payment_date=date(2026, 1, 20),
			payment_label="PAGO A",
			source_tag=Expense.SOURCE_MANUAL,
		)
		Expense.objects.create(
			scenario=scenario,
			provider=provider_b,
			year=2026,
			month=1,
			amount=Decimal("2200.00"),
			payment_date=date(2026, 1, 22),
			payment_label="PAGO B",
			source_tag=Expense.SOURCE_MANUAL,
		)
		Expense.objects.create(
			scenario=scenario,
			provider=provider_b,
			year=2026,
			month=1,
			amount=Decimal("0.00"),
			payment_date=date(2026, 1, 23),
			payment_label="PAGO CERO",
			source_tag=Expense.SOURCE_MANUAL,
		)
		Expense.objects.create(
			scenario=scenario,
			provider=provider_b,
			year=2026,
			month=1,
			amount=Decimal("999.00"),
			payment_date=None,
			payment_label="SIN FECHA",
			source_tag=Expense.SOURCE_MANUAL,
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{
				"scenario_id": scenario.id,
				"year": 2026,
				"month": 1,
				"provider": provider_a.id,
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertIn("calc_expense_options", response.context)
		self.assertEqual(
			response.context["calc_expense_options"],
			[
				{
					"id": Expense.objects.get(payment_label="PAGO A").id,
					"provider": "Proveedor A",
					"payment_date": date(2026, 1, 20),
					"payment_label": "PAGO A",
					"amount": 1500.0,
				},
				{
					"id": Expense.objects.get(payment_label="PAGO B").id,
					"provider": "Proveedor B",
					"payment_date": date(2026, 1, 22),
					"payment_label": "PAGO B",
					"amount": 2200.0,
				},
			],
		)

	def test_dashboard_home_defaults_to_current_month_and_marks_today(self):
		user = get_user_model().objects.create_user(username="todaytester", password="secret123")
		self.client.force_login(user)

		today = date.today()
		scenario = Scenario.objects.create(
			name="ESCENARIO 1 - PROYECCION CONSERVADORA",
			year=today.year,
			start_month=1,
			daily_interest_rate=Decimal("0.001"),
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["selected_year"], today.year)
		self.assertEqual(response.context["selected_month"], today.month)

		today_cell = None
		for week in response.context["calendar_payload"]["weeks"]:
			for day in week:
				if day["date"] == today:
					today_cell = day
					break
			if today_cell:
				break

		self.assertIsNotNone(today_cell)
		self.assertTrue(today_cell["is_today"])
		self.assertContains(response, 'class="mini-badge">Hoy</div>', html=False)

	def test_dashboard_home_real_scenario_shows_today_date_in_yield_labels(self):
		user = get_user_model().objects.create_user(username="yielddatetester", password="secret123")
		self.client.force_login(user)

		today = date.today()
		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=today.year,
			start_month=today.month,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=today,
			gastos_proyectados_excel=Decimal("0.00"),
			ingresos_financieros_excel=Decimal("0.00"),
		)
		FundCuotaparteHistory.objects.create(
			fund_name="1822 RAICES INVERSION",
			quote_date=today,
			cuotaparte=Decimal("120.000000"),
		)
		snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=today,
			net_flow=Decimal("100.00"),
			active_capital=Decimal("100.00"),
			daily_yield=Decimal("5.00"),
			cumulative_yield=Decimal("5.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=snapshot, label="Lote Hoy", amount=Decimal("100.00"))

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": today.year, "month": today.month},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, f"Rendimiento total al {today.day}-{today.month}")
		self.assertContains(response, f"Rendimiento del día {today.day}-{today.month}")

	def test_dashboard_home_non_real_chart_stays_annual_when_month_changes(self):
		user = get_user_model().objects.create_user(username="charttester", password="secret123")
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 1 - PROYECCION CONSERVADORA",
			year=2026,
			start_month=1,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.bulk_create(
			[
				DailyProjection(
					scenario=scenario,
					projection_date=date(2026, 1, 5),
					interes_diario_excel=Decimal("10.00"),
				),
				DailyProjection(
					scenario=scenario,
					projection_date=date(2026, 2, 10),
					interes_diario_excel=Decimal("20.00"),
				),
				DailyProjection(
					scenario=scenario,
					projection_date=date(2026, 3, 15),
					interes_diario_excel=Decimal("30.00"),
				),
			]
		)

		january_response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 1},
		)
		march_response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 3},
		)

		self.assertEqual(january_response.status_code, 200)
		self.assertEqual(march_response.status_code, 200)
		self.assertEqual(january_response.context["chart_labels"], march_response.context["chart_labels"])
		self.assertEqual(january_response.context["chart_values"], march_response.context["chart_values"])
		self.assertEqual(january_response.context["total_mes"], Decimal("10.00"))
		self.assertEqual(march_response.context["total_mes"], Decimal("30.00"))

	def test_dashboard_home_non_real_shows_total_interest_until_today(self):
		user = get_user_model().objects.create_user(username="todayinteresttester", password="secret123")
		self.client.force_login(user)

		today = date.today()
		scenario = Scenario.objects.create(
			name="ESCENARIO 1 - PROYECCION CONSERVADORA",
			year=today.year,
			start_month=today.month,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.bulk_create(
			[
				DailyProjection(
					scenario=scenario,
					projection_date=today - timedelta(days=1),
					interes_diario_excel=Decimal("10.00"),
				),
				DailyProjection(
					scenario=scenario,
					projection_date=today,
					interes_diario_excel=Decimal("20.00"),
				),
				DailyProjection(
					scenario=scenario,
					projection_date=today + timedelta(days=1),
					interes_diario_excel=Decimal("30.00"),
				),
			]
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": today.year, "month": today.month},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["total_hasta_hoy"], Decimal("30.00"))
		self.assertContains(response, f"Rendimiento al {today.day}-{today.month}")

	def test_dashboard_home_non_real_expense_panel_is_not_rendered_twice(self):
		user = get_user_model().objects.create_user(username="expensetester", password="secret123")
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 1 - PROYECCION CONSERVADORA",
			year=2026,
			start_month=5,
			daily_interest_rate=Decimal("0.001"),
		)
		provider = Provider.objects.create(name="Proveedor Test")
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 5, 5),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)
		Expense.objects.create(
			scenario=scenario,
			provider=provider,
			year=2026,
			month=5,
			amount=Decimal("1500.00"),
			payment_date=date(2026, 5, 20),
			payment_label="PAGO A",
			source_tag=Expense.SOURCE_MANUAL,
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 5},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Total gastos (filtrado)", count=1)
		self.assertNotContains(response, 'data-real-panel="expenses"')

	def test_dashboard_home_real_actions_show_only_import_buttons_and_toggle(self):
		user = get_user_model().objects.create_superuser(
			username="realactiontester",
			email="realactiontester@example.com",
			password="secret123",
		)
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=2026,
			start_month=3,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 3, 5),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 3},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Importar gastos reales")
		self.assertContains(response, "Importar ingresos reales")
		self.assertContains(response, "Ver gastos")
		self.assertNotContains(response, "Agregar gasto")
		self.assertNotContains(response, "Agregar ingreso real")
		self.assertNotContains(response, "Exportar gastos")
		self.assertNotContains(response, "Importar inversiones activas")

	def test_dashboard_home_real_panel_shows_monthly_incomes_table(self):
		user = get_user_model().objects.create_superuser(
			username="realincometester",
			email="realincometester@example.com",
			password="secret123",
		)
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=2026,
			start_month=3,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 3, 5),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)
		IncomeEntry.objects.create(
			scenario=scenario,
			entry_date=date(2026, 3, 17),
			amount=Decimal("1500.00"),
			source_tag="importado",
			classification="LIBRE",
			account="Cuenta: 7185-4056/1",
			description="Ingreso diario",
			remarks="Ingresos",
			note="Ingreso diario",
		)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 3},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Gastos e ingresos")
		self.assertContains(response, 'data-real-tab="expenses"')
		self.assertContains(response, 'data-real-tab="incomes"')
		self.assertContains(response, 'data-real-tab="tracking"')
		self.assertContains(response, "Ingresos del mes")
		self.assertContains(response, "Clasificacion")
		self.assertContains(response, "Cuenta: 7185-4056/1")
		self.assertContains(response, "Ingreso diario")
		self.assertContains(response, "$ 1.500,00")

	def test_dashboard_home_real_incomes_tab_paginates_results(self):
		user = get_user_model().objects.create_superuser(
			username="realincomepagination",
			email="realincomepagination@example.com",
			password="secret123",
		)
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=2026,
			start_month=3,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 3, 5),
			gastos_proyectados_excel=Decimal("100.00"),
			ingresos_financieros_excel=Decimal("250.00"),
		)
		for idx in range(105):
			IncomeEntry.objects.create(
				scenario=scenario,
				entry_date=date(2026, 3, 17),
				amount=Decimal("100.00"),
				source_tag="movimientos",
				classification="LIBRE",
				account="Cuenta prueba",
				description=f"Ingreso {idx}",
				remarks="Ingresos",
			)

		response = self.client.get(
			reverse("dashboard:home"),
			{"scenario_id": scenario.id, "year": 2026, "month": 3, "real_tab": "incomes", "income_page": 2},
		)

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Pagina")
		self.assertContains(response, "2</strong> de <strong>2")
		self.assertContains(response, "Ingreso 104")
		self.assertNotContains(response, "Ingreso 94")

	def test_dashboard_home_real_scenario_uses_current_active_metrics_and_breakdown_tooltip(self):
		user = get_user_model().objects.create_user(username="realtester", password="secret123")
		self.client.force_login(user)

		today = date.today()
		first_investment_date = today - timedelta(days=60)
		second_investment_date = today - timedelta(days=12)

		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=today.year,
			start_month=first_investment_date.month,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=first_investment_date,
			gastos_proyectados_excel=Decimal("0.00"),
			ingresos_financieros_excel=Decimal("0.00"),
		)

		FundCuotaparteHistory.objects.bulk_create(
			[
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=first_investment_date,
					cuotaparte=Decimal("100.000000"),
				),
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=second_investment_date,
					cuotaparte=Decimal("110.000000"),
				),
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=today,
					cuotaparte=Decimal("120.000000"),
				),
			]
		)

		first_snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=first_investment_date,
			net_flow=Decimal("1000.00"),
			active_capital=Decimal("1000.00"),
			daily_yield=Decimal("10.00"),
			cumulative_yield=Decimal("10.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=first_snapshot, label="Lote A", amount=Decimal("1000.00"))

		second_snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=second_investment_date,
			net_flow=Decimal("200.00"),
			active_capital=Decimal("1200.00"),
			daily_yield=Decimal("12.00"),
			cumulative_yield=Decimal("22.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=second_snapshot, label="Lote B", amount=Decimal("200.00"))

		response = self.client.get(
			reverse("dashboard:home"),
			{
				"scenario_id": scenario.id,
				"year": today.year,
				"month": first_investment_date.month,
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["investment_active_capital"], Decimal("1200.00"))
		self.assertEqual(response.context["investment_last_date"], second_investment_date)

		first_return = (Decimal("120.000000") / Decimal("100.000000")) - Decimal("1")
		second_return = (Decimal("120.000000") / Decimal("110.000000")) - Decimal("1")
		expected_interest = (Decimal("1000.00") * first_return) + (Decimal("200.00") * second_return)
		self.assertEqual(
			response.context["investment_active_interest_total"].quantize(Decimal("0.000001")),
			expected_interest.quantize(Decimal("0.000001")),
		)

		first_days = Decimal(str(max((today - first_investment_date).days, 1)))
		second_days = Decimal(str(max((today - second_investment_date).days, 1)))
		expected_daily_rate_pct = (
			(
				(Decimal("1000.00") * (first_return / first_days))
				+ (Decimal("200.00") * (second_return / second_days))
			)
			/ Decimal("1200.00")
		) * Decimal("100")
		self.assertEqual(
			response.context["investment_daily_rate_pct"].quantize(Decimal("0.000001")),
			expected_daily_rate_pct.quantize(Decimal("0.000001")),
		)

		tooltip = ""
		for week in response.context["calendar_payload"]["weeks"]:
			for day in week:
				if day["in_month"] and day["date"] == first_investment_date:
					tooltip = day["investment_tooltip"]
					break
			if tooltip:
				break

		self.assertIn("Desglose activo", tooltip)
		self.assertIn("Lote A", tooltip)
		self.assertNotIn("Evolución", tooltip)
		self.assertNotContains(response, 'data-real-tab="expenses"')
		self.assertNotContains(response, 'data-real-tab="tracking"')
		self.assertContains(response, 'data-real-panel="tracking"')

	def test_dashboard_home_real_scenario_excludes_netted_outflows_from_active_total_and_calendar(self):
		user = get_user_model().objects.create_user(username="nettester", password="secret123")
		self.client.force_login(user)

		scenario = Scenario.objects.create(
			name="ESCENARIO 3 - PROYECCION REAL",
			year=2026,
			start_month=3,
			daily_interest_rate=Decimal("0.001"),
		)
		DailyProjection.objects.create(
			scenario=scenario,
			projection_date=date(2026, 3, 1),
			gastos_proyectados_excel=Decimal("0.00"),
			ingresos_financieros_excel=Decimal("0.00"),
		)

		FundCuotaparteHistory.objects.bulk_create(
			[
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=date(2026, 3, 1),
					cuotaparte=Decimal("100.000000"),
				),
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=date(2026, 3, 10),
					cuotaparte=Decimal("110.000000"),
				),
				FundCuotaparteHistory(
					fund_name="1822 RAICES INVERSION",
					quote_date=date(2026, 3, 16),
					cuotaparte=Decimal("120.000000"),
				),
			]
		)

		first_snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=date(2026, 3, 1),
			net_flow=Decimal("1000.00"),
			active_capital=Decimal("1000.00"),
			daily_yield=Decimal("10.00"),
			cumulative_yield=Decimal("10.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=first_snapshot, label="Lote A", amount=Decimal("1000.00"))

		withdraw_snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=date(2026, 3, 5),
			net_flow=Decimal("-1000.00"),
			active_capital=Decimal("0.00"),
			daily_yield=Decimal("0.00"),
			cumulative_yield=Decimal("10.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=withdraw_snapshot, label="Lote A", amount=Decimal("-1000.00"))

		active_snapshot = InvestmentDailySnapshot.objects.create(
			scenario=scenario,
			snapshot_date=date(2026, 3, 10),
			net_flow=Decimal("200.00"),
			active_capital=Decimal("200.00"),
			daily_yield=Decimal("5.00"),
			cumulative_yield=Decimal("15.00"),
		)
		InvestmentDailyFlow.objects.create(snapshot=active_snapshot, label="Lote B", amount=Decimal("200.00"))

		response = self.client.get(
			reverse("dashboard:home"),
			{
				"scenario_id": scenario.id,
				"year": 2026,
				"month": 3,
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["investment_active_capital"], Decimal("200.00"))

		expected_interest = Decimal("200.00") * ((Decimal("120.000000") / Decimal("110.000000")) - Decimal("1"))
		self.assertEqual(
			response.context["investment_active_interest_total"].quantize(Decimal("0.000001")),
			expected_interest.quantize(Decimal("0.000001")),
		)

		march_1 = None
		march_5 = None
		march_10 = None
		for week in response.context["calendar_payload"]["weeks"]:
			for day in week:
				if day["in_month"] and day["date"] == date(2026, 3, 1):
					march_1 = day
				if day["in_month"] and day["date"] == date(2026, 3, 5):
					march_5 = day
				if day["in_month"] and day["date"] == date(2026, 3, 10):
					march_10 = day

		self.assertIsNotNone(march_1)
		self.assertIsNotNone(march_5)
		self.assertIsNotNone(march_10)
		self.assertIsNone(march_1["net_flow"])
		self.assertEqual(march_1["investment_tooltip"], "")
		self.assertIsNone(march_5["net_flow"])
		self.assertEqual(march_5["investment_tooltip"], "")
		self.assertEqual(march_10["net_flow"], Decimal("200.00"))
		self.assertIn("Desglose activo", march_10["investment_tooltip"])
		self.assertIn("Lote B", march_10["investment_tooltip"])


class IncomeExcelImportTests(TestCase):
	def test_import_incomes_from_tabular_excel_updates_same_date(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))
		IncomeEntry.objects.create(
			scenario=scenario,
			entry_date=date(2026, 3, 17),
			amount=Decimal("100.00"),
			source_tag="excel",
			note="anterior",
		)

		df = pd.DataFrame(
			[
				{"Fecha": date(2026, 3, 17), "Monto": 1500, "Nota": "real", "Origen": "importado"},
				{"Fecha": date(2026, 3, 18), "Monto": 2000, "Nota": "nuevo", "Origen": "importado"},
			]
		)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, index=False)

		result = import_incomes_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario)

		self.assertEqual(result.created, 1)
		self.assertEqual(result.updated, 1)
		self.assertEqual(result.errors, [])
		self.assertEqual(IncomeEntry.objects.filter(scenario=scenario).count(), 2)
		updated_entry = IncomeEntry.objects.get(scenario=scenario, entry_date=date(2026, 3, 17))
		self.assertEqual(updated_entry.amount, Decimal("1500.00"))
		self.assertEqual(updated_entry.note, "real")

	def test_import_incomes_from_movimientos_workbook_keeps_each_income_row(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))

		df = pd.DataFrame(
			[
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "02/03/2026",
					"Descripción": "Cobro 1",
					"Importe": 1000,
					"Saldo": 5000,
					"Aclaraciones": "Ingresos",
				},
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "02/03/2026",
					"Descripción": "Cobro 2",
					"Importe": 2500.5,
					"Saldo": 7500.5,
					"Aclaraciones": "Ingresos",
				},
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "02/03/2026",
					"Descripción": "Pago",
					"Importe": -400,
					"Saldo": 7100.5,
					"Aclaraciones": "Gastos",
				},
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "03/03/2026",
					"Descripción": "Cobro 3",
					"Importe": 900,
					"Saldo": 8000.5,
					"Aclaraciones": "Ingresos",
				},
			]
		)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, sheet_name="Movimientos", index=False)

		result = import_incomes_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario)

		self.assertEqual(result.created, 3)
		self.assertEqual(result.updated, 0)
		self.assertEqual(result.errors, [])
		self.assertEqual(IncomeEntry.objects.filter(scenario=scenario).count(), 3)
		first_income = IncomeEntry.objects.get(scenario=scenario, entry_date=date(2026, 3, 2), description="Cobro 1")
		second_income = IncomeEntry.objects.get(scenario=scenario, entry_date=date(2026, 3, 2), description="Cobro 2")
		march_3 = IncomeEntry.objects.get(scenario=scenario, entry_date=date(2026, 3, 3), description="Cobro 3")
		self.assertEqual(first_income.amount, Decimal("1000.00"))
		self.assertEqual(second_income.amount, Decimal("2500.50"))
		self.assertEqual(march_3.amount, Decimal("900.00"))
		self.assertEqual(first_income.source_tag, "movimientos")
		self.assertEqual(first_income.classification, "LIBRE")
		self.assertEqual(first_income.account, "Cuenta: 7185-4056/1")
		self.assertEqual(first_income.remarks, "Ingresos")

	def test_import_incomes_from_movimientos_replaces_only_dates_present_in_file(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))
		IncomeEntry.objects.create(
			scenario=scenario,
			entry_date=date(2026, 3, 2),
			amount=Decimal("100.00"),
			source_tag="movimientos",
			description="Viejo 2",
			remarks="Ingresos",
		)
		IncomeEntry.objects.create(
			scenario=scenario,
			entry_date=date(2026, 3, 4),
			amount=Decimal("400.00"),
			source_tag="movimientos",
			description="Viejo 4",
			remarks="Ingresos",
		)

		df = pd.DataFrame(
			[
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "02/03/2026",
					"DescripciÃ³n": "Nuevo 2",
					"Importe": 200,
					"Saldo": 1200,
					"Aclaraciones": "Ingresos",
				},
				{
					"CLASIFICACION": "LIBRE",
					"CTA": "Cuenta: 7185-4056/1",
					"Fecha": "03/03/2026",
					"DescripciÃ³n": "Nuevo 3",
					"Importe": 300,
					"Saldo": 1500,
					"Aclaraciones": "Ingresos",
				},
			]
		)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, sheet_name="Movimientos", index=False)

		result = import_incomes_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario)

		self.assertEqual(result.created, 2)
		self.assertEqual(result.updated, 1)
		self.assertEqual(IncomeEntry.objects.filter(scenario=scenario).count(), 3)
		self.assertFalse(IncomeEntry.objects.filter(scenario=scenario, description="Viejo 2").exists())
		self.assertTrue(IncomeEntry.objects.filter(scenario=scenario, description="Viejo 4").exists())
		self.assertTrue(IncomeEntry.objects.filter(scenario=scenario, description="Nuevo 2").exists())
		self.assertTrue(IncomeEntry.objects.filter(scenario=scenario, description="Nuevo 3").exists())


class ExpenseExcelImportTests(TestCase):
	def test_import_expenses_from_real_expense_workbook_format(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))

		rows = [
			["TOTALES", None, None, None, 1000],
			[
				"PROVEEDOR",
				"COD. FINAN.",
				"CLASIF. CASH",
				"FECHA",
				"IMPORTE TOTAL",
				"ENE-26",
				"FEB-26",
				"MAR-26",
				"PRIORIDAD",
				"TIPO GASTO",
				"FF",
				"FONDO AFECTADO",
				"CLASIF. LMR",
				"NRO PAGADO",
				"NUEVA CLASIF.",
				"VENC. CHEQUE",
				"U. EJECUTORA",
				"NRO OBJ.",
				"OBJ. GASTO",
				"COMENTARIO",
			],
			[
				"Proveedor Test",
				"FFC001",
				"SERVICIOS",
				date(2026, 3, 17),
				2500,
				0,
				0,
				2500,
				"PRIORIDAD 1",
				"",
				"1.1.0",
				"0 -",
				"",
				"PAGO-123",
				"SERVICIOS ESPECIALES",
				"",
				"",
				"",
				"",
				"",
			],
		]
		df = pd.DataFrame(rows)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, index=False, header=False, sheet_name="Gastos Reales")

		result = import_expenses_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario)

		self.assertEqual(result.created, 1)
		self.assertEqual(result.updated, 0)
		self.assertEqual(result.errors, [])
		expense = Expense.objects.get(scenario=scenario)
		self.assertEqual(expense.amount, Decimal("2500.00"))
		self.assertEqual(expense.source_tag, Expense.SOURCE_IMPORTADO)
		self.assertEqual(expense.payment_label, "PAGO-123")
		self.assertEqual(expense.nueva_clasificacion, "SERVICIOS ESPECIALES")


class InvestmentExcelImportTests(TestCase):
	def test_import_investments_from_excel_creates_flows_per_day(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))

		# Create a minimal Hoja6 (2) with a Total row and two investment lines.
		rows = [
			["Total", None, None, None, 300],
			["Aporte 1", 100, 100, 100, 0],
			["Aporte 2", 200, 200, 200, 0],
		]
		df = pd.DataFrame(rows, columns=["Label", "8-ene", "9-ene", "10-ene", "Extra"])
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, index=False, sheet_name="Hoja6 (2)")

		result = import_investment_snapshots_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario, year=2026)

		self.assertEqual(result.processed_days, 3)
		self.assertEqual(InvestmentDailySnapshot.objects.filter(scenario=scenario).count(), 3)
		self.assertEqual(InvestmentDailyFlow.objects.filter(snapshot__scenario=scenario).count(), 4)

		# Validate that flows are tied to the correct date.
		snapshot_8 = InvestmentDailySnapshot.objects.get(scenario=scenario, snapshot_date=date(2026, 1, 8))
		flows_8 = list(snapshot_8.flows.order_by("label"))
		self.assertEqual(flows_8[0].label, "Aporte 1")
		self.assertEqual(flows_8[0].amount, Decimal("100.00"))
		self.assertEqual(flows_8[1].label, "Aporte 2")
		self.assertEqual(flows_8[1].amount, Decimal("200.00"))

	def test_import_expenses_from_real_expense_workbook_keeps_negative_amounts(self):
		scenario = Scenario.objects.create(name="ESCENARIO REAL 2", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))

		rows = [
			["TOTALES", None, None, None, -100],
			[
				"PROVEEDOR",
				"COD. FINAN.",
				"CLASIF. CASH",
				"FECHA",
				"IMPORTE TOTAL",
				"ENE-26",
				"FEB-26",
				"MAR-26",
				"PRIORIDAD",
				"TIPO GASTO",
				"FF",
				"FONDO AFECTADO",
				"CLASIF. LMR",
				"NRO PAGADO",
				"NUEVA CLASIF.",
				"VENC. CHEQUE",
				"U. EJECUTORA",
				"NRO OBJ.",
				"OBJ. GASTO",
				"COMENTARIO",
			],
			[
				"Proveedor Ajuste",
				"FFC002",
				"S-SUELDOS",
				date(2026, 3, 17),
				-100,
				0,
				0,
				-100,
				"PRIORIDAD 1",
				"",
				"1.1.0",
				"0 -",
				"",
				"AJ-1",
				"",
				"",
				"",
				"",
				"",
				"",
			],
		]
		df = pd.DataFrame(rows)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, index=False, header=False, sheet_name="Gastos Reales")

		result = import_expenses_from_excel(excel_bytes=buffer.getvalue(), scenario=scenario)

		self.assertEqual(result.created, 1)
		self.assertEqual(result.errors, [])
		expense = Expense.objects.get(scenario=scenario)
		self.assertEqual(expense.amount, Decimal("-100.00"))
		self.assertEqual(expense.nueva_clasificacion, "S-SUELDOS")


class InvestmentExcelImportTests(TestCase):
	def test_import_investment_snapshots_builds_active_capital_and_yield(self):
		scenario = Scenario.objects.create(name="ESCENARIO 3 - PROYECCION REAL", year=2026, start_month=3, daily_interest_rate=Decimal("0.001"))
		rows = [
			["Etiquetas de fila", "07-ene", "08-ene", "09-ene", "10-ene"],
			["LIBRE DISPONIBILIDAD", 1000, 0, 0, 0],
			["Total", 1000, 500, -2000, 400],
		]
		df = pd.DataFrame(rows)
		buffer = BytesIO()
		with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
			df.to_excel(writer, index=False, header=False, sheet_name="Hoja6 (2)")

		result = import_investment_snapshots_from_excel(
			excel_bytes=buffer.getvalue(),
			scenario=scenario,
			year=2026,
		)

		self.assertEqual(result.processed_days, 4)
		self.assertEqual(result.cuts_count, 1)
		snapshots = list(InvestmentDailySnapshot.objects.filter(scenario=scenario).order_by("snapshot_date"))
		self.assertEqual(len(snapshots), 4)
		self.assertEqual(snapshots[0].active_capital, Decimal("1000.00"))
		self.assertEqual(snapshots[1].active_capital, Decimal("1500.00"))
		self.assertEqual(snapshots[2].active_capital, Decimal("0.00"))
		self.assertTrue(snapshots[2].was_cut)
		self.assertEqual(snapshots[3].active_capital, Decimal("400.00"))
