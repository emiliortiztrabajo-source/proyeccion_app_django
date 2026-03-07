from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea grupos base de permisos (administrador y operador)"

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name="administrador_finanzas")
        operador_group, _ = Group.objects.get_or_create(name="operador_finanzas")

        model_permissions = Permission.objects.filter(content_type__app_label="dashboard")
        admin_group.permissions.set(model_permissions)

        operador_codenames = {
            "view_scenario",
            "view_dailyprojection",
            "view_incomeentry",
            "view_expense",
            "view_provider",
            "view_paymentdayrule",
            "add_incomeentry",
            "change_incomeentry",
            "change_expense",
        }
        operador_perms = Permission.objects.filter(content_type__app_label="dashboard", codename__in=operador_codenames)
        operador_group.permissions.set(operador_perms)

        self.stdout.write(self.style.SUCCESS("Grupos y permisos creados/actualizados."))
