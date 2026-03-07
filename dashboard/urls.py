from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("gastos/", views.expense_list, name="expense_list"),
    path("gastos/<int:pk>/editar/", views.expense_edit, name="expense_edit"),
    path("ingresos/nuevo/", views.income_create, name="income_create"),
    path("ingresos/<int:pk>/editar/", views.income_edit, name="income_edit"),
    path("importar-excel/", views.import_excel_view, name="import_excel"),
]
