from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0007_scenario_interest_mode_and_seed_weekly"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestmentDailySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot_date", models.DateField()),
                ("net_flow", models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ("active_capital", models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ("daily_yield", models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ("cumulative_yield", models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ("was_cut", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "scenario",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="investment_snapshots", to="dashboard.scenario"),
                ),
            ],
            options={
                "ordering": ["snapshot_date"],
                "unique_together": {("scenario", "snapshot_date")},
            },
        ),
    ]