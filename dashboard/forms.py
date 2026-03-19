from datetime import date, timedelta

from django import forms

from .models import Expense, IncomeEntry, Provider


MONTH_NAME_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


class DashboardFilterForm(forms.Form):
    scenario_id = forms.ChoiceField(label="Escenario", choices=[])
    year = forms.IntegerField(label="Año")
    month = forms.ChoiceField(label="Mes", choices=[])

    def __init__(self, *args, year=2026, start_month=2, scenario_choices=None, selected_scenario_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        normalized_choices = [(str(pk), label) for pk, label in (scenario_choices or [])]
        self.fields["scenario_id"].choices = normalized_choices
        if selected_scenario_id is not None:
            self.fields["scenario_id"].initial = str(selected_scenario_id)
        elif normalized_choices:
            self.fields["scenario_id"].initial = normalized_choices[0][0]
        self.fields["month"].choices = [(m, MONTH_NAME_ES[m]) for m in range(start_month, 13)]
        self.fields["year"].initial = year
        self.fields["month"].initial = start_month


class ExpenseFilterForm(forms.Form):
    provider = forms.ModelChoiceField(label="Proveedor", queryset=Provider.objects.none(), required=False)
    payment_date = forms.DateField(label="Fecha de pago", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, provider_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].queryset = provider_queryset if provider_queryset is not None else Provider.objects.all()
        self.fields["provider"].empty_label = "Todos los proveedores"


class ExpenseForm(forms.ModelForm):
    change_comment = forms.CharField(
        label="Comentario del cambio",
        required=True,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Explicá brevemente qué cambiaste"}),
    )

    class Meta:
        model = Expense
        fields = [
            "provider",
            "payment_date",
            "payment_label",
            "amount",
            "nueva_clasificacion",
            "clasif_cash",
            "financial_code",
            "purchase_order",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }


class ManualExpenseForm(forms.ModelForm):
    month = forms.TypedChoiceField(label="Mes", choices=[(m, MONTH_NAME_ES[m]) for m in range(1, 13)], coerce=int)
    year = forms.IntegerField(label="Año", min_value=2000, max_value=2100)
    source_tag = forms.ChoiceField(label="Origen", choices=Expense.SOURCE_CHOICES)
    change_comment = forms.CharField(
        label="Comentario del cambio",
        required=True,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Explicá brevemente por qué agregás este gasto"}),
    )

    class Meta:
        model = Expense
        fields = [
            "financial_code",
            "nueva_clasificacion",
            "clasif_cash",
            "provider",
            "payment_label",
            "purchase_order",
            "month",
            "year",
            "payment_date",
            "amount",
            "source_tag",
        ]
        labels = {
            "financial_code": "Cod. Financiero",
            "nueva_clasificacion": "Nueva Clasificación",
            "clasif_cash": "Clasif. Cash",
            "payment_label": "PAGO DIA",
            "purchase_order": "OC",
            "payment_date": "Fecha de pago real",
            "amount": "Monto",
        }
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_tag"].initial = Expense.SOURCE_MANUAL
        self.fields["payment_date"].required = True


class IncomeEntryForm(forms.ModelForm):
    class Meta:
        model = IncomeEntry
        fields = ["entry_date", "amount", "classification", "account", "description", "balance", "remarks", "note"]
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
        }


class IncomeFilterForm(forms.Form):
    entry_date = forms.DateField(label="Fecha", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    classification = forms.ChoiceField(label="Clasificacion", required=False, choices=[])
    account = forms.ChoiceField(label="Cuenta", required=False, choices=[])
    remarks = forms.ChoiceField(label="Aclaraciones", required=False, choices=[])
    description_query = forms.CharField(label="Descripcion", required=False)

    def __init__(self, *args, classification_choices=None, account_choices=None, remarks_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classification"].choices = [("", "Todas las clasificaciones")] + [
            (value, value) for value in (classification_choices or [])
        ]
        self.fields["account"].choices = [("", "Todas las cuentas")] + [
            (value, value) for value in (account_choices or [])
        ]
        self.fields["remarks"].choices = [("", "Todas las aclaraciones")] + [
            (value, value) for value in (remarks_choices or [])
        ]


class IncomeExcelImportForm(forms.Form):
    excel_file = forms.FileField(label="Archivo Excel de ingresos (.xlsx)")


class InvestmentExcelImportForm(forms.Form):
    excel_file = forms.FileField(label="Archivo Excel de inversiones (.xlsx)")


class ExcelImportForm(forms.Form):
    excel_file = forms.FileField(label="Archivo Excel (.xlsx)")
    scenario_name = forms.CharField(label="Escenario", initial="ESCENARIO 1", max_length=120)
    year = forms.IntegerField(label="Año", initial=2026)
    start_month = forms.IntegerField(label="Mes de inicio", initial=2, min_value=1, max_value=12)
    replace_existing = forms.BooleanField(label="Reemplazar datos existentes del escenario", initial=True, required=False)


class ExpenseExcelImportForm(forms.Form):
    excel_file = forms.FileField(label="Archivo Excel de gastos (.xlsx)")


class CafciLookupForm(forms.Form):
    start_date = forms.DateField(label="Desde", widget=forms.DateInput(attrs={"type": "date"}), required=False)
    end_date = forms.DateField(label="Hasta", widget=forms.DateInput(attrs={"type": "date"}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = date.today()
        self.fields["start_date"].initial = today - timedelta(days=30)
        self.fields["end_date"].initial = today

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La fecha Hasta debe ser mayor o igual a Desde.")
        return cleaned_data
