import re
from datetime import date, datetime
from decimal import Decimal

import pandas as pd


MONTH_ABBR_ES = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}

MONTH_NAME_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}

DIAS_COL_ES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SEPTIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}

MESES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def parse_monto(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))

    text = str(value).strip()
    if text in ("", "-", "$-", "$ -", "—", "None", "nan", "NaN"):
        return None
    if "REF" in text.upper():
        return None

    neg = text.startswith("-")
    text = text.replace("$", "").replace(" ", "").lstrip("-")
    text = text.replace(".", "").replace(",", ".")
    text = re.sub(r"[^0-9.]", "", text)
    if text in ("", "."):
        return None

    val = Decimal(text)
    return -val if neg else val


def parse_header_fecha(col_name: str, year: int):
    source = str(col_name).strip().lower()
    match = re.match(r"^(\d{1,2})[-/ ]([a-záéíóúñ]+)$", source)
    if not match:
        return None

    day = int(match.group(1))
    month_text = (
        match.group(2)
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    month = MESES.get(month_text[:3])
    if not month:
        return None

    return date(year, month, day)


def list_escenario_cols(df: pd.DataFrame):
    cols = [c for c in df.columns if re.match(r"(?i)^escenario\b", str(c).strip())]

    def scen_num(col_name):
        match = re.search(r"(\d+)", str(col_name).strip().lower())
        return int(match.group(1)) if match else 9999

    return sorted(cols, key=scen_num)


def extract_rate_from_label(label: str) -> Decimal:
    match = re.search(r"\(([\d.,]+)\s*%\)", str(label))
    if not match:
        return Decimal("0")
    value = match.group(1).replace(",", ".")
    try:
        return Decimal(value) / Decimal("100")
    except Exception:
        return Decimal("0")


def month_amount_col(year: int, month: int):
    return f"{MONTH_ABBR_ES[month]} {year}"


def format_money_ar(value):
    if value is None:
        return "—"
    rendered = f"{float(value):,.2f}"
    return rendered.replace(",", "X").replace(".", ",").replace("X", ".")
