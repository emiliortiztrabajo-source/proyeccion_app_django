from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CAFCI_API_BASE_URL = "https://api.cafci.org.ar"
DEFAULT_TIMEOUT_SECONDS = 15


class CafciApiError(Exception):
    """Base exception for CAFCI integration errors."""


class CafciNetworkError(CafciApiError):
    """Raised when CAFCI API cannot be reached."""


class CafciResponseError(CafciApiError):
    """Raised when CAFCI API returns an invalid response."""


def _normalize_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for parser in (date.fromisoformat,):
        try:
            return parser(text[:10])
        except ValueError:
            continue
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _normalize_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace(" ", "")
        # If comma appears without dots, assume decimal comma.
        if "," in value and "." not in value:
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _get_nested(data: Any, path: tuple[str, ...], default: Any = None) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def _flatten_simple_map(prefix: str, value: Any, output: list[dict[str, str]], max_depth: int = 2) -> None:
    if max_depth < 0:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            next_prefix = f"{prefix}.{k}" if prefix else str(k)
            _flatten_simple_map(next_prefix, v, output, max_depth=max_depth - 1)
        return
    if isinstance(value, list):
        output.append({"campo": prefix, "valor": f"{len(value)} elemento(s)"})
        return
    output.append({"campo": prefix, "valor": _as_text(value)})


def _extract_date_from_node(node: dict[str, Any]) -> date | None:
    for candidate in ("fecha", "date", "updatedAt", "lastUpdate", "ultimo_dia"):
        raw = node.get(candidate)
        parsed = _normalize_date(raw)
        if parsed:
            return parsed
    return None


def _extract_cuotaparte(diaria_node: dict[str, Any]) -> Decimal | None:
    candidates = (
        ("cuotaparte", "valor"),
        ("cuotaparte",),
        ("cuotapartes", "valor"),
        ("valorCuotaparte",),
        ("valor_cuotaparte",),
    )
    for path in candidates:
        raw = _get_nested(diaria_node, path)
        parsed = _normalize_decimal(raw)
        if parsed is not None:
            return parsed
    return None


def _extract_other_returns(rendimientos_node: Any) -> list[dict[str, Any]]:
    if not isinstance(rendimientos_node, dict):
        return []
    items: list[dict[str, Any]] = []
    for key, raw_value in rendimientos_node.items():
        if key == "day":
            continue
        if isinstance(raw_value, dict):
            value = _normalize_decimal(raw_value.get("rendimiento"))
            fecha = _normalize_date(raw_value.get("fecha"))
        else:
            value = _normalize_decimal(raw_value)
            fecha = None
        items.append({"periodo": key, "rendimiento": value, "fecha": fecha})
    return items


def _build_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.cafci.org.ar/",
            "Origin": "https://www.cafci.org.ar",
        },
    )


def _get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    req = _build_request(url)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except UnicodeDecodeError:
            body = ""
        detail = f"HTTP {exc.code}"
        if body:
            detail = f"{detail} - {body[:180]}"
        raise CafciResponseError(f"Error al consultar CAFCI API ({detail}).") from exc
    except URLError as exc:
        raise CafciNetworkError(f"No se pudo conectar con CAFCI API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CafciNetworkError("Tiempo de espera agotado al consultar CAFCI API.") from exc

    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise CafciResponseError("La respuesta de CAFCI API no es JSON valido.") from exc

    if not isinstance(data, dict):
        raise CafciResponseError("La respuesta de CAFCI API tiene formato inesperado.")

    return data


def get_fund_class_ficha(fund: str, fund_class: str) -> dict[str, Any]:
    url = f"{CAFCI_API_BASE_URL}/fondo/{fund}/clase/{fund_class}/ficha"
    payload = _get_json(url)
    return {"url": url, "payload": payload}


def get_fund_class_performance(fund: str, fund_class: str, start_date: date, end_date: date) -> dict[str, Any]:
    start_text = start_date.isoformat()
    end_text = end_date.isoformat()
    url = f"{CAFCI_API_BASE_URL}/fondo/{fund}/clase/{fund_class}/rendimiento/{start_text}/{end_text}"
    payload = _get_json(url)
    return {"url": url, "payload": payload}


def parse_ficha_payload(payload: dict[str, Any], *, fund: str, fund_class: str, source_url: str) -> dict[str, Any]:
    data_node = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    info_node = data_node.get("info") if isinstance(data_node.get("info"), dict) else {}
    diaria_node = info_node.get("diaria") if isinstance(info_node.get("diaria"), dict) else {}

    rendimientos_node = diaria_node.get("rendimientos") if isinstance(diaria_node.get("rendimientos"), dict) else {}
    day_node = rendimientos_node.get("day") if isinstance(rendimientos_node.get("day"), dict) else {}

    daily_return = _normalize_decimal(day_node.get("rendimiento"))
    daily_date = _normalize_date(day_node.get("fecha") or diaria_node.get("fecha") or data_node.get("fecha"))
    cuotaparte = _extract_cuotaparte(diaria_node)
    other_returns = _extract_other_returns(rendimientos_node)

    daily_info_items: list[dict[str, str]] = []
    _flatten_simple_map("diaria", diaria_node, daily_info_items, max_depth=2)

    return {
        "fund": fund,
        "fundClass": fund_class,
        "dailyReturn": daily_return,
        "dailyDate": daily_date,
        "cuotaparte": cuotaparte,
        "otherReturns": other_returns,
        "dailyInfoItems": daily_info_items,
        "lastUpdate": _extract_date_from_node(diaria_node) or _extract_date_from_node(data_node),
        "source": source_url,
    }


def parse_performance_payload(payload: dict[str, Any], *, source_url: str, start_date: date, end_date: date) -> dict[str, Any]:
    data_node = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rendimiento = _normalize_decimal(data_node.get("rendimiento"))

    rows: list[dict[str, Any]] = []
    series_node = data_node.get("series")
    if isinstance(series_node, list):
        for item in series_node:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "fecha": _normalize_date(item.get("fecha") or item.get("date")),
                    "valor": _normalize_decimal(item.get("rendimiento") or item.get("valor")),
                }
            )

    rows.sort(key=lambda x: x.get("fecha") or date.min, reverse=True)
    return {
        "startDate": start_date,
        "endDate": end_date,
        "rendimiento": rendimiento,
        "series": rows,
        "source": source_url,
    }


def build_cafci_snapshot(*, fund: str, fund_class: str, start_date: date, end_date: date) -> dict[str, Any]:
    ficha_result = get_fund_class_ficha(fund, fund_class)
    perf_result = get_fund_class_performance(fund, fund_class, start_date, end_date)

    ficha = parse_ficha_payload(ficha_result["payload"], fund=fund, fund_class=fund_class, source_url=ficha_result["url"])
    performance = parse_performance_payload(
        perf_result["payload"],
        source_url=perf_result["url"],
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "ficha": ficha,
        "performance": performance,
    }


def get_value_for_fci_calculator_candidate(*, fund: str, fund_class: str) -> dict[str, Any] | None:
    """Future hook: obtain last daily return from CAFCI for calculator integration."""
    ficha_result = get_fund_class_ficha(fund, fund_class)
    ficha = parse_ficha_payload(ficha_result["payload"], fund=fund, fund_class=fund_class, source_url=ficha_result["url"])
    if ficha.get("dailyReturn") is None:
        return None
    return {
        "fund": fund,
        "fundClass": fund_class,
        "fecha": ficha.get("dailyDate"),
        "valor": ficha.get("dailyReturn"),
        "fuente": ficha.get("source"),
    }
