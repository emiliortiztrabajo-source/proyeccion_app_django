from decimal import Decimal
from datetime import datetime

# Rows provided by user: (date, cuotaparte)
rows = [
    ("11/03/2026", "87.599659"),
    ("10/03/2026", "87.539829"),
    ("09/03/2026", "87.415505"),
    ("06/03/2026", "87.310665"),
    ("05/03/2026", "87.241441"),
    ("04/03/2026", "87.17636"),
    ("03/03/2026", "87.018081"),
]

# Use the same fund name constant the app expects
FUND_NAME = "1822 RAICES INVERSION"

from dashboard.models import FundCuotaparteHistory

created = 0
updated = 0

for raw_date, raw_value in rows:
    raw_date = raw_date.strip()
    raw_value = raw_value.strip().replace(',', '.')
    # try parsing dd/mm/YYYY then ISO
    parsed_date = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(raw_date, fmt).date()
            break
        except Exception:
            continue
    if parsed_date is None:
        print(f"Skipping invalid date: {raw_date}")
        continue
    try:
        parsed_value = Decimal(raw_value)
    except Exception:
        print(f"Skipping invalid value: {raw_value}")
        continue

    obj, created_flag = FundCuotaparteHistory.objects.update_or_create(
        fund_name=FUND_NAME,
        quote_date=parsed_date,
        defaults={"cuotaparte": parsed_value},
    )
    if created_flag:
        created += 1
    else:
        updated += 1

print(f"Done. Created: {created}, Updated: {updated}")
