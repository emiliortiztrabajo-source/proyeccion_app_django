from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_fundcuotapartehistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="fundcuotapartehistory",
            name="is_from_excel",
            field=models.BooleanField(default=False),
        ),
    ]
