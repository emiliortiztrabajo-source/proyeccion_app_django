from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd


DEFAULT_ACTIVE_INVESTMENTS_PATH = Path(__file__).resolve().parents[2] / "inversionesactivas.xlsx"


@dataclass
class ActiveInvestmentRow:
    fund_name: str
    invested_amount: Decimal
    sell_today_amount: Decimal


def _normalize_header(value) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _parse_decimal(value) -> Decimal:
    if pd.isna(value):
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        text = str(value).strip().replace("$", "").replace(" ", "")
        text = text.replace(".", "").replace(",", ".")
        if not text:
            return Decimal("0")
        return Decimal(text).quantize(Decimal("0.01"))


def load_active_investments_summary(file_path: str | Path | None = None):
    path = Path(file_path) if file_path else DEFAULT_ACTIVE_INVESTMENTS_PATH
    if not path.exists():
        return {
            "available": False,
            "file_path": str(path),
            "total_sell_today": Decimal("0"),
            "total_invested": Decimal("0"),
            "rows": [],
            "tooltip": "",
        }

    df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    normalized_columns = {_normalize_header(col): col for col in df.columns}
    fund_col = normalized_columns.get("fondo")
    invested_col = normalized_columns.get("pendiente de retiro")
    sell_today_col = normalized_columns.get("si vendes hoy")

    if not fund_col or not invested_col or not sell_today_col:
        return {
            "available": False,
            "file_path": str(path),
            "total_sell_today": Decimal("0"),
            "total_invested": Decimal("0"),
            "rows": [],
            "tooltip": "",
        }

    rows: list[ActiveInvestmentRow] = []
    for _, row in df.iterrows():
        fund_name = str(row.get(fund_col) or "").strip()
        invested_amount = _parse_decimal(row.get(invested_col))
        sell_today_amount = _parse_decimal(row.get(sell_today_col))
        if not fund_name or (invested_amount == 0 and sell_today_amount == 0):
            continue
        rows.append(
            ActiveInvestmentRow(
                fund_name=fund_name,
                invested_amount=invested_amount,
                sell_today_amount=sell_today_amount,
            )
        )

    total_sell_today = sum((row.sell_today_amount for row in rows), Decimal("0"))
    total_invested = sum((row.invested_amount for row in rows), Decimal("0"))

    tooltip_lines = [
        f"Total si vendes hoy: $ {total_sell_today:,.2f}",
        f"Total invertido: $ {total_invested:,.2f}",
        "",
        "Detalle por fondo:",
    ]
    for row in rows:
        tooltip_lines.append(
            f"{row.fund_name} | Invertido: $ {row.invested_amount:,.2f} | Si vendes hoy: $ {row.sell_today_amount:,.2f}"
        )

    return {
        "available": True,
        "file_path": str(path),
        "total_sell_today": total_sell_today,
        "total_invested": total_invested,
        "rows": rows,
        "tooltip": "\n".join(tooltip_lines),
    }
