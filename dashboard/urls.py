from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("gastos/", views.expense_list, name="expense_list"),
    path("gastos/nuevo/", views.expense_create, name="expense_create"),
    path("gastos/exportar-excel/", views.expense_export_excel, name="expense_export_excel"),
    path("gastos/importar-excel/", views.expense_import_excel, name="expense_import_excel"),
    path("gastos/<int:pk>/editar/", views.expense_edit, name="expense_edit"),
    path("gastos/<int:pk>/eliminar/", views.expense_delete, name="expense_delete"),
    path("ingresos/nuevo/", views.income_create, name="income_create"),
    path("ingresos/<int:pk>/editar/", views.income_edit, name="income_edit"),
    path("ingresos/importar-excel/", views.income_import_excel, name="income_import_excel"),
    path("inversiones/importar-excel/", views.investment_import_excel, name="investment_import_excel"),
    path("importar-excel/", views.import_excel_view, name="import_excel"),
    path("cafci/update/", views.cafci_update, name="cafci_update"),
    path("cafci/manual-history/", views.cafci_manual_history, name="cafci_manual_history"),
]
