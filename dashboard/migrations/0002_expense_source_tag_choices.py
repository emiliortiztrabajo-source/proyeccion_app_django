from django.db import migrations, models


def normalize_expense_source(apps, schema_editor):
    Expense = apps.get_model("dashboard", "Expense")
    Expense.objects.filter(source_tag__iexact="excel").update(source_tag="EXCEL")
    Expense.objects.filter(source_tag__iexact="manual").update(source_tag="MANUAL")


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="expense",
            name="source_tag",
            field=models.CharField(
                choices=[("EXCEL", "EXCEL"), ("MANUAL", "MANUAL")],
                default="EXCEL",
                max_length=20,
            ),
        ),
        migrations.RunPython(normalize_expense_source, migrations.RunPython.noop),
    ]
