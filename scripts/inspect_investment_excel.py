import os
import sys
from pathlib import Path

# Ensure our Django project is importable when running this script directly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure Django settings are configured for standalone script.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "proyeccion_app.settings")

import django
django.setup()

import pandas as pd
from dashboard.services.investment_excel_io import SOURCE_SHEET

path = Path(r'c:/Users/eortiz/Documents/GitHub/fondos django/proyeccion_app_django/GASTOS.xlsx')
df = pd.read_excel(path, sheet_name=SOURCE_SHEET, engine='openpyxl', header=0)
print('Columns:', df.columns.tolist())
label_col = df.columns[0]
print('label column name:', label_col)
print('First 20 labels:')
print(df[label_col].head(20).to_string(index=False))
print('--- Total row (full) ---')
total_row = df[df[label_col].astype(str).str.strip().str.lower().str.contains('total', na=False)]
if not total_row.empty:
    print(total_row.to_string(index=False))
else:
    print('No total row found')
