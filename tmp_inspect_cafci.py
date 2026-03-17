import pandas as pd

df = pd.read_excel('data/cafci_planilla.xlsx', sheet_name=0, nrows=10)
print(df.head())
print(df.columns.tolist())
