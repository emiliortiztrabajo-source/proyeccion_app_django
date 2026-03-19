from django.core.management.base import BaseCommand, CommandError

from dashboard.services.excel_importer import import_excel_file


class Command(BaseCommand):
    help = "Importa datos desde el Excel de proyección a la base de datos"

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True, help="Ruta al archivo Excel")
        parser.add_argument("--scenario", default="ESCENARIO 1", help="Nombre del escenario")
        parser.add_argument("--year", type=int, default=2026, help="Año de proyección")
        parser.add_argument("--start-month", type=int, default=2, help="Mes de inicio")
        parser.add_argument("--no-replace", action="store_true", help="No borrar datos previos")

    def handle(self, *args, **options):
        try:
            result = import_excel_file(
                file_path=options["path"],
                scenario_name=options["scenario"],
                year=options["year"],
                start_month=options["start_month"],
                replace_existing=not options["no_replace"],
            )
        except FileNotFoundError as exc:
            raise CommandError(f"No se encontró el archivo: {exc}") from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Importación completada"))
        self.stdout.write(f"Escenario: {result['scenario']}")
        self.stdout.write(f"Proyecciones: {result['daily_projections']}")
        self.stdout.write(f"Ingresos: {result['income_entries']}")
        self.stdout.write(f"Reglas de pago: {result['payment_rules']}")
        self.stdout.write(f"Gastos: {result['expenses']}")
