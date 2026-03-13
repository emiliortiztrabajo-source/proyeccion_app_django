from django.db import migrations, models


WEEKLY_SCENARIO_BASE_NAME = "ESCENARIO 2 - PROMEDIO SEMANAL"


def seed_weekly_average_scenarios(apps, schema_editor):
    Scenario = apps.get_model("dashboard", "Scenario")

    fixed_mode = "FIXED"
    weekly_mode = "WEEKLY_AVG"

    # Existing scenarios remain fixed by default unless explicitly created as weekly.
    Scenario.objects.exclude(interest_mode=weekly_mode).update(interest_mode=fixed_mode)

    years = (
        Scenario.objects.order_by("year")
        .values_list("year", flat=True)
        .distinct()
    )

    for year in years:
        year_scenarios = Scenario.objects.filter(year=year).order_by("name", "id")
        if not year_scenarios.exists():
            continue

        if year_scenarios.filter(interest_mode=weekly_mode).exists():
            continue

        base_scenario = year_scenarios.first()
        candidate_name = WEEKLY_SCENARIO_BASE_NAME
        suffix = 2
        while Scenario.objects.filter(year=year, name=candidate_name).exists():
            suffix += 1
            candidate_name = f"ESCENARIO {suffix} - PROMEDIO SEMANAL"

        Scenario.objects.create(
            name=candidate_name,
            year=year,
            start_month=base_scenario.start_month,
            daily_interest_rate=base_scenario.daily_interest_rate,
            interest_mode=weekly_mode,
            is_active=False,
        )


def reverse_seed_weekly_average_scenarios(apps, schema_editor):
    # Reverse is intentionally a no-op to avoid deleting user-managed scenarios.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_add_is_from_excel"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenario",
            name="interest_mode",
            field=models.CharField(
                choices=[
                    ("FIXED", "Tasa fija del escenario"),
                    ("WEEKLY_AVG", "Tasa promedio semanal (real)"),
                ],
                default="FIXED",
                max_length=20,
            ),
        ),
        migrations.RunPython(seed_weekly_average_scenarios, reverse_seed_weekly_average_scenarios),
    ]
