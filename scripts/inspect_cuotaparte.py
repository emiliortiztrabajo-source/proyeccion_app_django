from pathlib import Path
import pandas as pd

path = Path(r'c:/Users/eortiz/Documents/GitHub/fondos django/proyeccion_app_django/cuotaparte_1822 RAÍCES INVERSIÓN (1).xlsx')
df = pd.read_excel(path, sheet_name=0, engine='openpyxl')
print('shape', df.shape)
print(df.head(10).to_string(index=False))
print('\ncolumns:', df.columns.tolist())
