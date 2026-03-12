from django.core.management.base import BaseCommand, CommandError
import os

from dashboard.services.cafci_api import _extract_planilla_daily_row_local
from dashboard.models import FundCuotaparteHistory

# Import the list of target fund display names from views
try:
    from dashboard.views import CAFCI_DAILY_FUND_NAMES
except Exception:
    # Fallback: if import fails, use an empty list
    CAFCI_DAILY_FUND_NAMES = []


class Command(BaseCommand):
    help = "Ingresa en la base las cuotapartes de la planilla local para los fondos del cuadro (CAFCI_DAILY_FUND_NAMES)"

    def add_arguments(self, parser):
        parser.add_argument("--path", help="Ruta al archivo local de planilla (opcional)")

    def handle(self, *args, **options):
        path = options.get("path")
        # If path provided, set env var temporarily
        original = os.environ.get("CAFCI_LOCAL_PLANILLA_PATH")
        if path:
            os.environ["CAFCI_LOCAL_PLANILLA_PATH"] = path

        if not CAFCI_DAILY_FUND_NAMES:
            raise CommandError("No hay fondos configurados en CAFCI_DAILY_FUND_NAMES.")

        saved = 0
        skipped = 0
        errors = []

        for fund_name in CAFCI_DAILY_FUND_NAMES:
            try:
                row = _extract_planilla_daily_row_local(fund="", fund_class="", fund_name=fund_name)
            except Exception as exc:
                errors.append(f"{fund_name}: error extracción local: {exc}")
                continue

            if not row:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"No encontrada fila para: {fund_name}"))
                continue

            fecha = row.get("dailyDate")
            cuotaparte = row.get("cuotaparte")
            found_name = row.get("fundName") or fund_name

            if fecha is None or cuotaparte is None:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Datos incompletos para {fund_name}: fecha={fecha}, cuotaparte={cuotaparte}"))
                continue

            try:
                obj, created = FundCuotaparteHistory.objects.update_or_create(
                    fund_name=found_name,
                    quote_date=fecha,
                        defaults={"cuotaparte": cuotaparte, "is_from_excel": True},
                )
                saved += 1
                verb = "Creado" if created else "Actualizado"
                self.stdout.write(self.style.SUCCESS(f"{verb}: {found_name} - {fecha} -> {cuotaparte}"))
            except Exception as exc:
                errors.append(f"{fund_name}: error guardando DB: {exc}")

        # restore original env var
        if path:
            if original is None:
                os.environ.pop("CAFCI_LOCAL_PLANILLA_PATH", None)
            else:
                os.environ["CAFCI_LOCAL_PLANILLA_PATH"] = original

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Guardados: {saved}, Omitidos: {skipped}"))
        if errors:
            for e in errors:
                self.stdout.write(self.style.ERROR(e))