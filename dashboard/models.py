from django.db import models


class Scenario(models.Model):
	name = models.CharField(max_length=120)
	year = models.PositiveIntegerField()
	start_month = models.PositiveSmallIntegerField(default=3)
	daily_interest_rate = models.DecimalField(max_digits=8, decimal_places=6, default=0.000967)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-year", "name"]
		unique_together = ("name", "year")

	def __str__(self):
		return f"{self.name} ({self.year})"


class Provider(models.Model):
	name = models.CharField(max_length=255, unique=True)

	class Meta:
		ordering = ["name"]

	def __str__(self):
		return self.name


class PaymentDayRule(models.Model):
	scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="payment_rules")
	label = models.CharField(max_length=255)
	month = models.PositiveSmallIntegerField()
	payment_date = models.DateField()

	class Meta:
		ordering = ["month", "label"]
		unique_together = ("scenario", "label", "month")

	def __str__(self):
		return f"{self.label} - {self.payment_date}"


class DailyProjection(models.Model):
	scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="daily_projections")
	projection_date = models.DateField()
	caja_inicial = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	gastos_proyectados_excel = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	ingresos_financieros_excel = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	rescate_fci = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	interes_diario_excel = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	inversiones_fci = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	intereses_acumulados = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	intereses_recuperado = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	total_excel = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["projection_date"]
		unique_together = ("scenario", "projection_date")

	def __str__(self):
		return f"{self.scenario} - {self.projection_date}"


class IncomeEntry(models.Model):
	scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="income_entries")
	entry_date = models.DateField()
	amount = models.DecimalField(max_digits=20, decimal_places=2)
	source_tag = models.CharField(max_length=100, default="excel")
	note = models.CharField(max_length=255, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["entry_date"]
		indexes = [models.Index(fields=["scenario", "entry_date"])]

	def __str__(self):
		return f"{self.entry_date} - {self.amount}"


class Expense(models.Model):
	scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="expenses")
	provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="expenses")
	year = models.PositiveIntegerField()
	month = models.PositiveSmallIntegerField()
	amount = models.DecimalField(max_digits=20, decimal_places=2)
	payment_date = models.DateField(null=True, blank=True)
	payment_label = models.CharField(max_length=255)
	financial_code = models.CharField(max_length=120, blank=True)
	purchase_order = models.CharField(max_length=120, blank=True)
	nueva_clasificacion = models.CharField(max_length=255, blank=True)
	clasif_cash = models.CharField(max_length=255, blank=True)
	source_tag = models.CharField(max_length=100, default="excel")
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["payment_date", "-amount"]
		indexes = [
			models.Index(fields=["scenario", "year", "month"]),
			models.Index(fields=["provider", "payment_date"]),
		]

	def __str__(self):
		return f"{self.provider} - {self.amount}"
