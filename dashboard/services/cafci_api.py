from __future__ import annotations

import json
import io
import os
import ssl
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

try:
    import certifi
except Exception:  # pragma: no cover - optional dependency safeguard
    certifi = None


CAFCI_API_BASE_URL = "https://api.cafci.org.ar"
CAFCI_PB_GET_URL = "https://api.pub.cafci.org.ar/pb_get"
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
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y/%m/%d"):
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


def _normalize_label_text(value: Any) -> str:
    text = _as_text(value).lower().strip()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return " ".join(text.split())


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


def _normalize_cuotaparte_units(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    # CAFCI Planilla Diaria often publishes value as "mil cuotapartes".
    # Keep calculator history in regular cuotaparte units.
    if value >= Decimal("1000"):
        return value / Decimal("1000")
    return value


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


def _build_ssl_context() -> ssl.SSLContext:
    verify_env = os.getenv("CAFCI_SSL_VERIFY", "true").strip().lower()
    verify_ssl = verify_env not in {"0", "false", "no", "off"}
    if not verify_ssl:
        context = ssl._create_unverified_context()
    else:
        ca_bundle = os.getenv("CAFCI_CA_BUNDLE", "").strip()
        if ca_bundle:
            context = ssl.create_default_context(cafile=ca_bundle)
        else:
            context = ssl.create_default_context()

    # CAFCI endpoints can present legacy TLS/cipher settings on some days.
    # Relaxing minimums improves interoperability on newer OpenSSL runtimes.
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1
    except Exception:
        pass
    try:
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
    except Exception:
        pass
    return context


def _build_certifi_ssl_context() -> ssl.SSLContext | None:
    if certifi is None:
        return None
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            pass
        return context
    except Exception:
        return None


def _is_cert_verification_error(exc: URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    text = str(reason or "")
    return "CERTIFICATE_VERIFY_FAILED" in text.upper()


def _urlopen_with_ssl_fallback(req: Request, *, timeout: int):
    primary_context = _build_ssl_context()
    try:
        return urlopen(req, timeout=timeout, context=primary_context)
    except URLError as exc:
        # Retry with certifi bundle when system trust store fails on some machines.
        if not _is_cert_verification_error(exc):
            raise
        fallback_context = _build_certifi_ssl_context()
        if fallback_context is None:
            raise
        return urlopen(req, timeout=timeout, context=fallback_context)


def _get_json(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    req = _build_request(url)
    try:
        with _urlopen_with_ssl_fallback(req, timeout=timeout) as response:
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


def _get_bytes(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    req = _build_request(url)
    try:
        with _urlopen_with_ssl_fallback(req, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise CafciResponseError(f"Error al descargar archivo CAFCI ({exc.code}).") from exc
    except URLError as exc:
        raise CafciNetworkError(f"No se pudo conectar con CAFCI para descargar archivo: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CafciNetworkError("Tiempo de espera agotado al descargar archivo CAFCI.") from exc


def _find_planilla_header_row(raw_df: pd.DataFrame) -> int | None:
    max_scan = min(len(raw_df), 40)
    for idx in range(max_scan):
        row_text = " ".join([str(x).lower() for x in raw_df.iloc[idx].tolist() if pd.notna(x)])
        if "codigo cafci" in row_text and "valor (mil cuotapartes)" in row_text:
            return idx
    return None


def _extract_planilla_daily_row(*, fund: str, fund_class: str, fund_name: str | None = None) -> dict[str, Any] | None:
    binary = _get_bytes(CAFCI_PB_GET_URL)
    raw_df = pd.read_excel(io.BytesIO(binary), sheet_name=0, header=None)

    # The daily CAFCI sheet consistently starts data rows at index 9.
    # Avoid dynamic header detection because CAFCI changes heading text and layout frequently.
    data_df = raw_df.iloc[9:].copy()
    if data_df.empty:
        return None

    data_df = data_df.reset_index(drop=True)

    # Column positions validated against current CAFCI Planilla Diaria format.
    col_fondo = 0
    col_fecha = 4
    col_cuotaparte_actual = 5
    col_cuotaparte_anterior = 6
    col_variacion_pct = 7
    col_codigo_cafci = 20

    target_codes = [str(fund).strip(), str(fund_class).strip()]
    target_codes = [c for c in target_codes if c]

    candidates = data_df[data_df[col_codigo_cafci].notna()].copy()
    if candidates.empty:
        return None

    candidates["__codigo_cafci_str"] = candidates[col_codigo_cafci].astype(str).str.strip()

    for code in target_codes:
        matched = candidates[candidates["__codigo_cafci_str"] == code]
        if matched.empty:
            continue

        row = matched.iloc[0]
        actual = _normalize_cuotaparte_units(_normalize_decimal(row.get(col_cuotaparte_actual)))
        previous = _normalize_cuotaparte_units(_normalize_decimal(row.get(col_cuotaparte_anterior)))
        computed_daily_return = None
        if actual is not None and previous not in (None, Decimal("0")):
            computed_daily_return = ((actual - previous) / previous) * Decimal("100")
        return {
            "fundName": _as_text(row.get(col_fondo)),
            "dailyDate": _normalize_date(row.get(col_fecha)),
            "cuotaparte": actual,
            "cuotapartePrevious": previous,
            "dailyReturn": computed_daily_return if computed_daily_return is not None else _normalize_decimal(row.get(col_variacion_pct)),
            "dailyReturnSource": "formula" if computed_daily_return is not None else "variac_pct",
            "codigoCafci": code,
            "source": CAFCI_PB_GET_URL,
        }

    if fund_name:
        normalized_target = _normalize_label_text(fund_name)
        if normalized_target:
            candidates["__fondo_norm"] = candidates[col_fondo].apply(_normalize_label_text)
            by_name = candidates[candidates["__fondo_norm"].str.contains(normalized_target, na=False)]
            if by_name.empty:
                by_name = candidates[candidates["__fondo_norm"].apply(lambda x: normalized_target in x or x in normalized_target)]

            if not by_name.empty:
                row = by_name.iloc[0]
                actual = _normalize_cuotaparte_units(_normalize_decimal(row.get(col_cuotaparte_actual)))
                previous = _normalize_cuotaparte_units(_normalize_decimal(row.get(col_cuotaparte_anterior)))
                computed_daily_return = None
                if actual is not None and previous not in (None, Decimal("0")):
                    computed_daily_return = ((actual - previous) / previous) * Decimal("100")
                return {
                    "fundName": _as_text(row.get(col_fondo)),
                    "dailyDate": _normalize_date(row.get(col_fecha)),
                    "cuotaparte": actual,
                    "cuotapartePrevious": previous,
                    "dailyReturn": computed_daily_return if computed_daily_return is not None else _normalize_decimal(row.get(col_variacion_pct)),
                    "dailyReturnSource": "formula" if computed_daily_return is not None else "variac_pct",
                    "codigoCafci": _as_text(row.get(col_codigo_cafci)),
                    "source": CAFCI_PB_GET_URL,
                }

    return None


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


def build_cafci_snapshot(*, fund: str, fund_class: str, start_date: date, end_date: date, fund_name: str | None = None) -> dict[str, Any]:
    ficha: dict[str, Any] = {
        "fund": fund,
        "fundClass": fund_class,
        "dailyReturn": None,
        "dailyDate": None,
        "cuotaparte": None,
        "otherReturns": [],
        "dailyInfoItems": [],
        "lastUpdate": None,
        "source": None,
    }
    planilla_row = _extract_planilla_daily_row(fund=fund, fund_class=fund_class, fund_name=fund_name)
    if not planilla_row:
        raise CafciApiError("No se encontró la línea del fondo en la planilla diaria de CAFCI.")

    ficha["fundName"] = planilla_row.get("fundName")
    ficha["rowLoaded"] = True
    if planilla_row.get("dailyReturn") is not None:
        ficha["dailyReturn"] = planilla_row["dailyReturn"]
    if planilla_row.get("dailyDate") is not None:
        ficha["dailyDate"] = planilla_row["dailyDate"]
        ficha["lastUpdate"] = planilla_row["dailyDate"]
    if planilla_row.get("cuotaparte") is not None:
        ficha["cuotaparte"] = planilla_row["cuotaparte"]
    if planilla_row.get("cuotapartePrevious") is not None:
        ficha["cuotapartePrevious"] = planilla_row["cuotapartePrevious"]

    source_name = planilla_row.get("fundName") or "Planilla Diaria"
    ficha["source"] = f"{planilla_row['source']} (codigo {planilla_row['codigoCafci']} - {source_name})"
    daily_info = ficha.get("dailyInfoItems") or []
    daily_info.insert(0, {"campo": "planilla.fondo", "valor": _as_text(planilla_row.get("fundName"))})
    daily_info.insert(1, {"campo": "planilla.codigo_cafci", "valor": _as_text(planilla_row.get("codigoCafci"))})
    daily_info.insert(2, {"campo": "planilla.fecha", "valor": _as_text(planilla_row.get("dailyDate"))})
    daily_info.insert(3, {"campo": "planilla.cuotaparte_actual", "valor": _as_text(planilla_row.get("cuotaparte"))})
    daily_info.insert(4, {"campo": "planilla.cuotaparte_anterior", "valor": _as_text(planilla_row.get("cuotapartePrevious"))})
    daily_info.insert(5, {"campo": "planilla.rendimiento_diario_pct", "valor": _as_text(planilla_row.get("dailyReturn"))})
    daily_info.insert(6, {"campo": "planilla.rendimiento_fuente", "valor": _as_text(planilla_row.get("dailyReturnSource"))})
    ficha["dailyInfoItems"] = daily_info

    performance: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "rendimiento": None,
        "series": [],
        "source": None,
    }

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
