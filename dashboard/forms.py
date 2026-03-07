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
    year = forms.IntegerField(label="Año")
    month = forms.ChoiceField(label="Mes", choices=[])
    provider = forms.ModelChoiceField(label="Proveedor", queryset=Provider.objects.none(), required=False)
    payment_date = forms.DateField(label="Fecha de pago", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, year=2026, start_month=3, provider_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["month"].choices = [(m, MONTH_NAME_ES[m]) for m in range(start_month, 13)]
        self.fields["year"].initial = year
        self.fields["month"].initial = start_month
        self.fields["provider"].queryset = provider_queryset if provider_queryset is not None else Provider.objects.all()


class ExpenseForm(forms.ModelForm):
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


class IncomeEntryForm(forms.ModelForm):
    class Meta:
        model = IncomeEntry
        fields = ["entry_date", "amount", "note"]
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
        }


class ExcelImportForm(forms.Form):
    excel_file = forms.FileField(label="Archivo Excel (.xlsx)")
    scenario_name = forms.CharField(label="Escenario", initial="ESCENARIO 1", max_length=120)
    year = forms.IntegerField(label="Año", initial=2026)
    start_month = forms.IntegerField(label="Mes de inicio", initial=3, min_value=1, max_value=12)
    replace_existing = forms.BooleanField(label="Reemplazar datos existentes del escenario", initial=True, required=False)
