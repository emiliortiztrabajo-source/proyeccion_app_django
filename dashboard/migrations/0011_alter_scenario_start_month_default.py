from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0010_incomeentry_account_incomeentry_balance_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scenario",
            name="start_month",
            field=models.PositiveSmallIntegerField(default=2),
        ),
    ]
