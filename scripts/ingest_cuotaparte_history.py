import os
import sys
from pathlib import Path

# Ensure project is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proyeccion_app.settings")

import django
from decimal import Decimal
from datetime import datetime

django.setup()

import pandas as pd
from dashboard.models import FundCuotaparteHistory

# Adjust as needed
FILE_PATH = Path(r"c:/Users/eortiz/Documents/GitHub/fondos django/proyeccion_app_django/cuotaparte_1822 RAÍCES INVERSIÓN (1).xlsx")
FUND_NAME = "1822 RAICES INVERSION"

if not FILE_PATH.exists():
    raise SystemExit(f"File not found: {FILE_PATH}")

# Read the sheet
# Expected columns: Fecha, Número fondo, Nombre fondo, Valor Cuota Parte
# Fecha should be parsed as date, and Valor Cuota Parte as Decimal.
df = pd.read_excel(FILE_PATH, sheet_name=0, engine="openpyxl")

created = 0
updated = 0
skipped = 0

for idx, row in df.iterrows():
    raw_date = row.get("Fecha")
    raw_value = row.get("Valor Cuota Parte")

    if pd.isna(raw_date) or pd.isna(raw_value):
        skipped += 1
        continue

    if isinstance(raw_date, str):
        raw_date = raw_date.strip()
    try:
        if isinstance(raw_date, str):
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
        elif isinstance(raw_date, (datetime,)):
            parsed_date = raw_date.date()
        else:
            parsed_date = raw_date
    except Exception:
        skipped += 1
        continue

    try:
        cuotaparte = Decimal(str(raw_value)).quantize(Decimal("0.000001"))
    except Exception:
        skipped += 1
        continue

    obj, created_flag = FundCuotaparteHistory.objects.update_or_create(
        fund_name=FUND_NAME,
        quote_date=parsed_date,
        defaults={"cuotaparte": cuotaparte, "is_from_excel": True},
    )
    if created_flag:
        created += 1
    else:
        updated += 1

print(f"Done. Created: {created}, Updated: {updated}, Skipped: {skipped}")
