from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_expense_source_tag_choices"),
    ]

    operations = [
        migrations.AlterField(
            model_name="expense",
            name="source_tag",
            field=models.CharField(
                choices=[("EXCEL", "EXCEL"), ("MANUAL", "MANUAL"), ("IMPORTADO", "IMPORTADO")],
                default="EXCEL",
                max_length=20,
            ),
        ),
    ]
