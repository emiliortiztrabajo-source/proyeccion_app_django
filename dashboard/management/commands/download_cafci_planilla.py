from django.core.management.base import BaseCommand, CommandError
from dashboard.services.cafci_api import _get_bytes, CAFCI_PB_GET_URL
import os


class Command(BaseCommand):
    help = "Descarga la planilla diaria de CAFCI y la guarda en disco (ruta desde CAFCI_LOCAL_PLANILLA_PATH o ./data/cafci_planilla.xlsx)"

    def add_arguments(self, parser):
        parser.add_argument("--path", help="Ruta destino del archivo (opcional)")

    def handle(self, *args, **options):
        dest = options.get("path") or os.getenv("CAFCI_LOCAL_PLANILLA_PATH") or os.path.join(os.getcwd(), "data", "cafci_planilla.xlsx")
        dest_dir = os.path.dirname(dest)
        if dest_dir and not os.path.exists(dest_dir):
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except Exception as exc:
                raise CommandError(f"No se pudo crear directorio {dest_dir}: {exc}") from exc

        try:
            data = _get_bytes(CAFCI_PB_GET_URL)
        except Exception as exc:
            raise CommandError(f"Error descargando planilla CAFCI: {exc}") from exc

        try:
            with open(dest, "wb") as fh:
                fh.write(data)
        except Exception as exc:
            raise CommandError(f"No se pudo escribir el archivo {dest}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Planilla guardada en: {dest}"))
