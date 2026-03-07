from django.contrib import admin
from .models import DailyProjection, Expense, IncomeEntry, PaymentDayRule, Provider, Scenario


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
	list_display = ("name", "year", "start_month", "daily_interest_rate", "is_active")
	list_filter = ("year", "is_active")
	search_fields = ("name",)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
	search_fields = ("name",)


@admin.register(PaymentDayRule)
class PaymentDayRuleAdmin(admin.ModelAdmin):
	list_display = ("scenario", "label", "month", "payment_date")
	list_filter = ("scenario", "month")
	search_fields = ("label",)


@admin.register(DailyProjection)
class DailyProjectionAdmin(admin.ModelAdmin):
	list_display = ("scenario", "projection_date", "caja_inicial", "interes_diario_excel", "total_excel")
	list_filter = ("scenario", "projection_date")
	search_fields = ("scenario__name",)


@admin.register(IncomeEntry)
class IncomeEntryAdmin(admin.ModelAdmin):
	list_display = ("scenario", "entry_date", "amount", "source_tag")
	list_filter = ("scenario", "entry_date", "source_tag")
	search_fields = ("note",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
	list_display = (
		"scenario",
		"provider",
		"year",
		"month",
		"payment_date",
		"amount",
		"payment_label",
	)
	list_filter = ("scenario", "year", "month", "payment_date", "provider")
	search_fields = ("provider__name", "payment_label", "financial_code", "purchase_order")
