from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0003_expense_source_tag_importado"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("CREATE", "Alta"), ("UPDATE", "Edición"), ("DELETE", "Eliminación")], max_length=12)),
                ("comment", models.TextField(blank=True)),
                ("change_summary", models.TextField(blank=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="expense_change_logs", to="auth.user")),
                ("expense", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="change_logs", to="dashboard.expense")),
                ("scenario", models.ForeignKey(on_delete=models.CASCADE, related_name="expense_change_logs", to="dashboard.scenario")),
            ],
            options={
                "ordering": ["-changed_at", "-id"],
            },
        ),
    ]
