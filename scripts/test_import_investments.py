import os
import sys
from pathlib import Path

# Ensure project is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proyeccion_app.settings")

import django
django.setup()

from dashboard.models import Scenario, InvestmentDailySnapshot
from dashboard.services.investment_excel_io import import_investment_snapshots_from_excel

scenario = Scenario.objects.filter(name__icontains="REAL").order_by("id").first()
if not scenario:
    raise SystemExit("No REAL scenario found")

path = Path(r"c:/Users/eortiz/Documents/GitHub/fondos django/proyeccion_app_django/GASTOS.xlsx")
result = import_investment_snapshots_from_excel(excel_bytes=path.read_bytes(), scenario=scenario, year=scenario.year, daily_rate=scenario.daily_interest_rate)
print('Imported:', result.processed_days, 'days; cuts:', result.cuts_count)

# Print some snapshot values for first few days
for snap in InvestmentDailySnapshot.objects.filter(scenario=scenario).order_by('snapshot_date')[:10]:
    print(snap.snapshot_date, 'net_flow', snap.net_flow, 'active', snap.active_capital, 'daily_yield', snap.daily_yield)
