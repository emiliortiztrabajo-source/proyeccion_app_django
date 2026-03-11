from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0004_expensechangelog"),
    ]

    operations = [
        migrations.CreateModel(
            name="FundCuotaparteHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fund_name", models.CharField(max_length=255)),
                ("quote_date", models.DateField()),
                ("cuotaparte", models.DecimalField(decimal_places=6, max_digits=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["fund_name", "quote_date"],
                "unique_together": {("fund_name", "quote_date")},
            },
        ),
        migrations.AddIndex(
            model_name="fundcuotapartehistory",
            index=models.Index(fields=["fund_name", "quote_date"], name="dashboard_fund_name_653a94_idx"),
        ),
    ]
