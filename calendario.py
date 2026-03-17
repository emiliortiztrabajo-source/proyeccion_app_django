import re
import io
import calendar
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

# =========================================================
# PAGE CONFIG (SOLO UNA VEZ, ARRIBA DE TODO)
# =========================================================
st.set_page_config(page_title="Caja + Proyección (KPI)", layout="wide")

# =========================================================
# HEADER / LOGO
# =========================================================
ASSETS_DIR = Path(__file__).parent / "assets"
logo_path = ASSETS_DIR / "logo_pilar.png"

if logo_path.exists():
    col_logo, col_title = st.columns([1.2, 5])
    with col_logo:
        st.image(Image.open(logo_path), use_container_width=True)
    with col_title:
        st.markdown(
            """
            <div style="padding-top: 18px;">
                <h2 style="margin-bottom: 0; font-weight: 800;">Municipio de Pilar</h2>
                <p style="opacity: 0.75; margin-top: 4px; font-size: 14px;">
                    Dirección de Contaduría — Proyección de Rendimientos
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
    st.markdown(
        "<hr style='margin: 12px 0 24px 0; border: 0; height: 1px; background: rgba(0,0,0,.12);'>",
        unsafe_allow_html=True
    )

# =========================================================
# CONFIG
# =========================================================
YEAR_DEFAULT = 2026
MONTH_ABBR_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}

SHEET_MAIN = "ESCENARIO 1"
SHEET_INGRESOS_DIARIOS = "INGRESOSXDIA-HABIL"
SHEET_GASTOS = "Gastos"
SHEET_DIAS = "DIAS"

CONCEPT_ING = "INGRESOS FINANCIEROS PROYECTADOS"
CONCEPT_GAS = "GASTOS PROYECTADOS"
CONCEPT_CAJA_BASE = "CAJA INICIAL"
CONCEPT_INTERES_DIARIO = "INTERES DIARIO (0.0967%)"

# ✅ EXCLUIR FEBRERO: arrancar desde MARZO
START_MONTH = 3

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12
}

MONTH_NAME_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

DIAS_COL_ES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL", 5: "MAYO", 6: "JUNIO",
    7: "JULIO", 8: "AGOSTO", 9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
}

# =========================================================
# HELPERS
# =========================================================
def parse_monto(x):
    if pd.isna(x):
        return float("nan")
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)

    s = str(x).strip()
    if s in ("", "-", "$-", "$ -", "—", "None", "nan", "NaN"):
        return float("nan")
    if "REF" in s.upper():
        return float("nan")

    neg = s.startswith("-")
    s = s.replace("$", "").replace(" ", "").lstrip("-")
    s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^0-9.]", "", s)
    if s in ("", "."):
        return float("nan")
    v = float(s)
    return -v if neg else v


def fmt_money_ar(v):
    if v is None or pd.isna(v):
        return "—"
    s = f"{float(v):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_money_compact_ar(v):
    if v is None or pd.isna(v):
        return "—"
    sign = "-" if float(v) < 0 else ""
    x = abs(float(v))

    def _fmt(num, decimals):
        s = f"{num:,.{decimals}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    if x >= 1_000_000_000:
        return f"{sign}{_fmt(x / 1_000_000_000, 2)}MM"
    if x >= 1_000_000:
        return f"{sign}{_fmt(x / 1_000_000, 2)}M"
    if x >= 1_000:
        return f"{sign}{_fmt(x / 1_000, 1)}K"
    return f"{sign}{_fmt(x, 0)}"


def parse_header_fecha(col):
    s = str(col).strip().lower()
    m = re.match(r"^(\d{1,2})[-/ ]([a-záéíóúñ]+)$", s)
    if not m:
        return None
    dia = int(m.group(1))
    mes_txt = (
        m.group(2)
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u")
    )
    mes = MESES.get(mes_txt[:3], None)
    if not mes:
        return None
    return datetime(YEAR_DEFAULT, mes, dia)


def list_escenario_cols(df: pd.DataFrame):
    cols = [c for c in df.columns if re.match(r"(?i)^escenario\b", str(c).strip())]

    def scen_num(colname):
        s = str(colname).strip().lower()
        m = re.search(r"(\d+)", s)
        return int(m.group(1)) if m else 9999

    return sorted(cols, key=scen_num)


def extract_date_cols(df: pd.DataFrame, scenario_col: str):
    date_cols, col_to_dt = [], {}
    for c in df.columns:
        if c == scenario_col:
            continue
        dt = parse_header_fecha(c)
        if dt:
            date_cols.append(c)
            col_to_dt[c] = dt
    if not date_cols:
        raise ValueError("No encontré columnas tipo 01-feb / 02-feb en la hoja.")
    return date_cols, col_to_dt


def get_row_value(df: pd.DataFrame, scenario_col: str, row_name: str, date_col: str | None):
    if date_col is None:
        return float("nan")
    serie = df[scenario_col].astype(str).str.strip().str.upper()
    row = df[serie == str(row_name).strip().upper()]
    if row.empty:
        return float("nan")
    return parse_monto(row.iloc[0][date_col])


def _extract_rate_from_label(label: str) -> float:
    s = str(label)
    m = re.search(r"\(([\d.,]+)\s*%\)", s)
    if not m:
        return 0.0
    num = m.group(1).replace(",", ".")
    try:
        return float(num) / 100.0
    except Exception:
        return 0.0


# =========================================================
# LOADERS (cache correcto: incluyen start_month en la key)
# =========================================================
@st.cache_data(show_spinner=False)
def load_sheet_bytes(excel_bytes: bytes, sheet_name: str) -> pd.DataFrame:
    bio = io.BytesIO(excel_bytes)
    return pd.read_excel(bio, sheet_name=sheet_name, engine="openpyxl")


@st.cache_data(show_spinner=False)
def load_ingresos_diarios_map_bytes(excel_bytes: bytes, sheet_name: str, year: int) -> dict:
    bio = io.BytesIO(excel_bytes)
    df = pd.read_excel(bio, sheet_name=sheet_name, engine="openpyxl", header=1)
    cols = list(df.columns)

    def is_dia_col(c) -> bool:
        s = str(c).strip().upper()
        if s in ("DIA HABIAL", "DIA HABIL", "%%"):
            return False
        return "DIA" in s

    pairs = []
    for i in range(len(cols) - 1):
        c, nxt = cols[i], cols[i + 1]
        if is_dia_col(c) and (not is_dia_col(nxt)):
            pairs.append((c, nxt))

    if not pairs:
        return {}

    out = []
    for dcol, vcol in pairs:
        sub = df[[dcol, vcol]].copy()
        sub.columns = ["fecha", "ingreso"]
        out.append(sub)

    long_df = pd.concat(out, ignore_index=True)
    long_df["fecha"] = pd.to_datetime(long_df["fecha"], errors="coerce")
    long_df["ingreso"] = pd.to_numeric(long_df["ingreso"], errors="coerce").fillna(0.0)
    long_df = long_df.dropna(subset=["fecha"])
    long_df = long_df[(long_df["fecha"] >= f"{year}-01-01") & (long_df["fecha"] <= f"{year}-12-31")]
    long_df["fecha_d"] = long_df["fecha"].dt.date
    grp = long_df.groupby("fecha_d", as_index=False)["ingreso"].sum()
    return dict(zip(grp["fecha_d"], grp["ingreso"]))


@st.cache_data(show_spinner=False)
def load_gastos_diarios_map_bytes(excel_bytes: bytes, year: int, start_month: int) -> dict:
    dias_df = load_sheet_bytes(excel_bytes, SHEET_DIAS)
    gastos_df = load_sheet_bytes(excel_bytes, SHEET_GASTOS)

    dias_df["ETIQUETA_N"] = dias_df["ETIQUETA"].astype(str).str.strip().str.upper()
    gastos_df["PAGO_DIA_N"] = gastos_df["PAGO DIA"].astype(str).str.strip().str.upper()

    out = {}

    for mnum in range(start_month, 13):
        dias_col = DIAS_COL_ES.get(mnum)
        if not dias_col or dias_col not in dias_df.columns:
            continue

        mon_abbr = MONTH_ABBR_ES[mnum]
        gastos_col = f"{mon_abbr} {year}"

        if gastos_col not in gastos_df.columns:
            cand = [c for c in gastos_df.columns if str(c).strip().lower() == gastos_col.lower()]
            if not cand:
                continue
            gastos_col = cand[0]

        sub_dias = dias_df[["ETIQUETA_N", dias_col]].copy()
        sub_dias[dias_col] = pd.to_datetime(sub_dias[dias_col], errors="coerce")
        map_etq_to_date = dict(zip(sub_dias["ETIQUETA_N"], sub_dias[dias_col]))

        amounts = pd.to_numeric(gastos_df[gastos_col], errors="coerce").fillna(0.0)

        for etq, amt in zip(gastos_df["PAGO_DIA_N"], amounts):
            if amt == 0 or pd.isna(amt):
                continue
            dt = map_etq_to_date.get(etq, pd.NaT)
            if pd.isna(dt):
                continue
            d = dt.date()
            out[d] = out.get(d, 0.0) + float(amt)

    return out


def build_year_cash_df(
    df: pd.DataFrame,
    scenario_col: str,
    year: int,
    date_cols: list[str],
    col_to_dt: dict,
    ingresos_map: dict,
    gastos_map: dict,
    start_month: int,
):
    dt_to_col = {col_to_dt[c].date(): c for c in date_cols}

    start = date(year, start_month, 1)
    end = date(year, 12, 31)

    caja_ini_day1 = float("nan")
    d0 = start
    while d0 <= end:
        dc0 = dt_to_col.get(d0, None)
        v = get_row_value(df, scenario_col, CONCEPT_CAJA_BASE, dc0)
        if not pd.isna(v):
            caja_ini_day1 = float(v)
            break
        d0 += timedelta(days=1)

    rows = []
    prev_total = None
    d = start

    while d <= end:
        dc = dt_to_col.get(d, None)

        ing = ingresos_map.get(d, float("nan"))
        if pd.isna(ing):
            ing = get_row_value(df, scenario_col, CONCEPT_ING, dc)
        ing = 0.0 if pd.isna(ing) else float(ing)

        gasto_pos = float(gastos_map.get(d, 0.0))
        gas = -abs(gasto_pos)

        caja_ini = caja_ini_day1 if prev_total is None else float(prev_total)
        caja_ini = float("nan") if pd.isna(caja_ini) else float(caja_ini)

        if pd.isna(caja_ini):
            remanente = float("nan")
            total = float("nan")
        else:
            neto = caja_ini + ing + gas
            remanente = neto
            total = remanente

        interes_excel = get_row_value(df, scenario_col, CONCEPT_INTERES_DIARIO, dc)
        interes = float(interes_excel) if not pd.isna(interes_excel) else float("nan")

        prev_total = total if not pd.isna(total) else prev_total

        rows.append({
            "Fecha": pd.to_datetime(d),
            "Caja base": caja_ini,
            "Ingresos proy": ing,
            "Gastos proy": gas,
            "Neto proy": (ing + gas) if not pd.isna(caja_ini) else float("nan"),
            "Remanente": remanente,
            "Interes diario": interes,
            "Total": total,
        })

        d += timedelta(days=1)

    out = pd.DataFrame(rows).sort_values("Fecha")
    out["Mes"] = out["Fecha"].dt.month
    out["MesNombre"] = out["Mes"].map(MONTH_NAME_ES)
    out["Dia"] = out["Fecha"].dt.day
    return out


# =========================================================
# APP
# =========================================================
st.markdown("## 📈 Rendimiento FCI — Interés diario")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EXCEL_REPO_PATH = DATA_DIR / "PROYECCION 2026.xlsx"

excel_bytes = None
if EXCEL_REPO_PATH.exists():
    excel_bytes = EXCEL_REPO_PATH.read_bytes()
else:
    with st.sidebar:
        st.markdown("### 📄 Cargar Excel")
        up = st.file_uploader("Subí PROYECCION 2026.xlsx", type=["xlsx"])
        if up is not None:
            excel_bytes = up.read()

with st.sidebar:
    if st.button("🧹 Limpiar cache"):
        st.cache_data.clear()
        st.success("Cache limpiado. Recargá la página (F5).")

if not excel_bytes:
    st.error("❌ No se encontró el Excel en /data y tampoco se cargó por upload.")
    st.stop()

df = load_sheet_bytes(excel_bytes, SHEET_MAIN)

esc_cols = list_escenario_cols(df)
if "ESCENARIO 1" in [str(c).strip().upper() for c in esc_cols]:
    escenario_a = next(c for c in esc_cols if str(c).strip().upper() == "ESCENARIO 1")
else:
    if not esc_cols:
        st.error("No encontré columnas tipo 'ESCENARIO' en la hoja principal.")
        st.stop()
    escenario_a = esc_cols[0]

top_controls = st.columns([1.0, 1.0, 1.0])
with top_controls[1]:
    year = st.selectbox("Año", [YEAR_DEFAULT], index=0)
with top_controls[2]:
    month = st.selectbox("Mes", list(range(START_MONTH, 13)), index=0, format_func=lambda m: MONTH_NAME_ES[m])

date_cols, col_to_dt = extract_date_cols(df, escenario_a)
ingresos_map = load_ingresos_diarios_map_bytes(excel_bytes, SHEET_INGRESOS_DIARIOS, year)
gastos_map = load_gastos_diarios_map_bytes(excel_bytes, year, START_MONTH)

cash_year = build_year_cash_df(df, escenario_a, year, date_cols, col_to_dt, ingresos_map, gastos_map, START_MONTH)
cash_mes = cash_year[cash_year["Mes"] == month].copy()

# =========================================================
# ✅ DEBUG: ver cuánto suma por mes (para comprobar que Febrero no entra)
# =========================================================
debug = st.sidebar.checkbox("🐞 Debug rendimientos", value=False)
if debug:
    by_month = (
        cash_year.groupby("Mes", as_index=False)["Interes diario"]
        .sum()
        .assign(MesNombre=lambda x: x["Mes"].map(MONTH_NAME_ES))
        .sort_values("Mes")
    )
    st.sidebar.write("Suma por mes (Interes diario):")
    st.sidebar.dataframe(by_month[["Mes", "MesNombre", "Interes diario"]], use_container_width=True, hide_index=True)
    st.sidebar.write("Meses incluidos:", sorted(cash_year["Mes"].unique().tolist()))

# =========================================================
# UI / Mini calendario
# =========================================================
first_wd_mon0, ndays = calendar.monthrange(year, month)
dow_labels = ["L", "M", "Mi", "J", "V", "S", "D"]
offset = first_wd_mon0

start_grid = date(year, month, 1) - timedelta(days=offset)
grid_dates = [start_grid + timedelta(days=i) for i in range(42)]
weeks = [grid_dates[i:i + 7] for i in range(0, 42, 7)]

daily_summary = {}
cash_mes_idx = cash_mes.set_index(cash_mes["Fecha"].dt.date)
for daynum in range(1, ndays + 1):
    d = date(year, month, daynum)
    if d in cash_mes_idx.index:
        row = cash_mes_idx.loc[d]
        daily_summary[d] = {"interes": float(row["Interes diario"])}
    else:
        daily_summary[d] = {"interes": float("nan")}

st.markdown(
    """
<style>
.mini-cal{
  border:1px solid rgba(255,255,255,.12);
  border-radius:16px;
  padding:14px;
  background:rgba(255,255,255,.03);
  position:sticky;
  top:80px;
  box-sizing:border-box;
}
.mini-cal, .mini-cal *{ box-sizing:border-box; }
.mini-dow, .mini-week{
  display:grid;
  grid-template-columns:repeat(7, minmax(0, 1fr));
  gap:8px;
  width:100%;
}
.mini-dow{
  font-size:12px;
  opacity:.85;
  margin:0 0 10px 0;
  text-align:center;
  font-weight:900;
  justify-items:center;
}
.mini-week{ margin-bottom:8px; justify-items:stretch; }
.mini-cell{
  border:1px solid rgba(255,255,255,.10);
  border-radius:16px;
  padding:8px 8px 10px 8px;
  min-height:76px;
  background:rgba(255,255,255,.02);
  width:100%;
  overflow:hidden;
  transition: transform .15s ease, box-shadow .15s ease, background .15s ease;
}
.mini-cell:hover{
  transform:scale(1.06);
  z-index:20;
  background:rgba(255,255,255,.05);
  box-shadow: 0 12px 30px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.15);
}
.mini-off{
  opacity:.18;
  background:transparent;
  border:1px solid rgba(255,255,255,.06);
}
.mini-top{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:6px;
  min-height:18px;
}
.mini-day{
  font-size:20px;
  font-weight:1000;
  opacity:.98;
  line-height:1;
}
.mini-val{ margin-top:6px; font-weight:950; width:100%; }
.mini-num{
  display:block;
  width:100%;
  font-size:11.5px;
  font-weight:950;
  line-height:1.05;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  letter-spacing:-0.2px;
  padding-left:2px;
}
.mini-sub{
  margin-top:2px;
  font-size:9.5px;
  opacity:.75;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.pos{color:#6ee7b7;}
.neg{color:#fb7185;}
</style>
""",
    unsafe_allow_html=True
)

left_panel, right_panel = st.columns([1.90, 2.02], gap="large")

with left_panel:
    dow_html = "<div class='mini-dow'>" + "".join(f"<div>{x}</div>" for x in dow_labels) + "</div>"
    weeks_html = []
    for week in weeks:
        cells = []
        for d in week:
            if d.month != month:
                cells.append("<div class='mini-cell mini-off'></div>")
                continue
            v = daily_summary.get(d, {}).get("interes", float("nan"))
            cls = "pos" if (not pd.isna(v) and v >= 0) else "neg"
            cells.append(
                f"<div class='mini-cell'>"
                f"  <div class='mini-top'><div class='mini-day'>{d.day}</div></div>"
                f"  <div class='mini-val {cls}'><span class='mini-num'>$ {fmt_money_compact_ar(v)}</span></div>"
                f"  <div class='mini-sub'>Interés día</div>"
                f"</div>"
            )
        weeks_html.append("<div class='mini-week'>" + "".join(cells) + "</div>")

    cal_html = (
        "<div class='mini-cal'>"
        f"<h3 style='margin:0 0 6px 0;font-size:13px;'>{MONTH_NAME_ES[month]} {year}</h3>"
        + dow_html
        + "".join(weeks_html)
        + "</div>"
    )
    st.markdown(cal_html, unsafe_allow_html=True)

with right_panel:
    # Show only the two summary cards (no chart, no chart title, no empty placeholder).
    total_mes = float(cash_mes["Interes diario"].fillna(0.0).sum())
    total_anual = float(cash_year["Interes diario"].fillna(0.0).sum())

    st.markdown(
        """
        <style>
        .totales-box{
          width: 100%;
          margin-top: 0;
          display:grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap:16px;
        }
        .tot-card{
          width: 100%;
          min-width: 0;
          padding: 14px 14px;
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.03);
        }
        .tot-title{
          font-size: 12px;
          opacity: .75;
          font-weight: 800;
          margin-bottom: 6px;
        }
        .tot-value{
          font-size: 26px;
          font-weight: 900;
          line-height: 1.05;
          letter-spacing: -0.3px;
        }
        .tot-sub{
          margin-top: 6px;
          font-size: 11px;
          opacity: .65;
          font-weight: 600;
        }
        @media (max-width: 900px){
          .totales-box{
            grid-template-columns: 1fr;
          }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        f"""
        <div class="totales-box">
          <div class="tot-card">
            <div class="tot-title">Total rendimientos del mes — {MONTH_NAME_ES[month]} {year}</div>
            <div class="tot-value">$ {fmt_money_ar(total_mes)}</div>
            <div class="tot-sub">Suma diaria de <b>Interes diario</b> del mes seleccionado</div>
          </div>

          <div class="tot-card">
            <div class="tot-title">Total rendimientos anual — {year}</div>
            <div class="tot-value">$ {fmt_money_ar(total_anual)}</div>
            <div class="tot-sub">Suma diaria de <b>Interes diario</b> desde {MONTH_NAME_ES[START_MONTH]} a Diciembre</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =========================================================
# 🧾 BOLSAS DE GASTOS
# =========================================================
st.markdown("### 🧾 Bolsas de gastos")

@st.cache_data(show_spinner=False)
def load_gastos_raw_bytes(excel_bytes: bytes) -> pd.DataFrame:
    bio = io.BytesIO(excel_bytes)
    return pd.read_excel(bio, sheet_name=SHEET_GASTOS, engine="openpyxl")


def _month_amount_col(year: int, month: int) -> str:
    return f"{MONTH_ABBR_ES[month]} {year}"


def _find_amount_and_date_col(gastos_df: pd.DataFrame, year: int, month: int):
    target = _month_amount_col(year, month)

    cols = list(gastos_df.columns)
    idx = None
    for i, c in enumerate(cols):
        if str(c).strip().lower() == target.lower():
            idx = i
            break

    if idx is None:
        return None, None

    amount_col = cols[idx]
    date_col = None
    if (idx + 1) < len(cols) and "escenario" in str(cols[idx + 1]).strip().lower():
        date_col = cols[idx + 1]
    return amount_col, date_col


gastos_raw = load_gastos_raw_bytes(excel_bytes)

needed_cols = ["PAGO DIA", "Proveedor"]
missing = [c for c in needed_cols if c not in gastos_raw.columns]
if missing:
    st.warning(f"No encontré columnas necesarias en 'Gastos': {', '.join(missing)}")
else:
    amount_col, date_col = _find_amount_and_date_col(gastos_raw, year, month)

    if not amount_col:
        st.info(f"No encontré la columna del mes para {MONTH_NAME_ES[month]} {year} en 'Gastos'.")
    else:
        df_g = gastos_raw.copy()
        df_g["_monto"] = pd.to_numeric(df_g[amount_col], errors="coerce").fillna(0.0)

        if date_col:
            df_g["_fecha"] = pd.to_datetime(df_g[date_col], errors="coerce")
        else:
            df_g["_fecha"] = pd.NaT

        df_g = df_g[df_g["_monto"].abs() > 0].copy()

        if df_g.empty:
            st.info(f"No hay gastos cargados en '{amount_col}'.")
        else:
            df_g["_pago"] = df_g["PAGO DIA"].astype(str).str.strip()

            df_g["_prov"] = df_g["Proveedor"].astype(str).str.strip()
            df_g["_fecha_d"] = pd.to_datetime(df_g["_fecha"], errors="coerce").dt.date

            st.session_state["df_gastos_mes"] = df_g.copy()

            if "Nueva Clasificación" in df_g.columns:
                clasif_src = "Nueva Clasificación"
            elif "Clasif. Cash" in df_g.columns:
                clasif_src = "Clasif. Cash"
            else:
                clasif_src = None

            st.caption(
                f"Mes: **{MONTH_NAME_ES[month]} {year}** — Monto: **{amount_col}**"
                + (f" — Fecha: **{date_col}**" if date_col else "")
            )

            total = float(df_g["_monto"].sum())
            cant = int(len(df_g))

            with st.expander(
                f"💼 TODOS LOS GASTOS — Total: $ {fmt_money_ar(total)} — Ítems: {cant}",
                expanded=False
            ):
                sub = df_g.copy()

                sub["_prov"] = sub["_prov"].astype(str).str.strip()
                sub["_pago"] = sub["_pago"].astype(str).str.strip()

                if clasif_src:
                    sub["_clasif"] = sub[clasif_src].astype(str).fillna("Sin clasificar").str.strip()
                else:
                    sub["_clasif"] = "—"

                c1, c2 = st.columns([1.2, 1.2])

                with c1:
                    prov_sel = st.multiselect(
                        "Filtrar por Proveedor",
                        options=sorted(sub["_prov"].unique().tolist()),
                        default=[],
                        key=f"prov_{year}_{month}"
                    )

                if prov_sel:
                    sub = sub[sub["_prov"].isin(prov_sel)].copy()

                with c2:
                    sub["_fecha_d"] = pd.to_datetime(sub["_fecha"], errors="coerce").dt.date
                    fechas_disp = (
                        sub.dropna(subset=["_fecha_d"])["_fecha_d"]
                        .drop_duplicates()
                        .sort_values()
                        .tolist()
                    )

                    if fechas_disp:
                        fechas_txt = [d.strftime("%d/%m/%Y") for d in fechas_disp]
                        fechas_sel_txt = st.multiselect(
                            "Filtrar por Fecha de pago",
                            options=fechas_txt,
                            default=[],
                            key=f"fechapago_{year}_{month}"
                        )

                        fechas_sel = set(
                            datetime.strptime(s, "%d/%m/%Y").date()
                            for s in fechas_sel_txt
                        )
                    else:
                        st.info("No hay fechas de pago disponibles para ese proveedor.")
                        fechas_sel = set()

                if fechas_sel:
                    sub = sub[sub["_fecha_d"].isin(fechas_sel)].copy()

                total_filtrado = float(sub["_monto"].sum()) if not sub.empty else 0.0
                st.metric("Total (filtrado)", f"$ {fmt_money_ar(total_filtrado)}")

                if sub.empty:
                    st.info("No hay filas con esos filtros.")
                else:
                    sub["_fecha_txt"] = sub["_fecha_d"].apply(
                        lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—"
                    )

                    sub["_monto_txt"] = sub["_monto"].map(fmt_money_ar)

                    if sub["_fecha"].notna().any():
                        sub = sub.sort_values(["_fecha", "_monto"], ascending=[True, False])
                    else:
                        sub = sub.sort_values("_monto", ascending=False)

                    sub_show = pd.DataFrame({
                        "Fecha": sub["_fecha_txt"],
                        "PAGO DIA": sub["_pago"],
                        "Proveedor": sub["_prov"],
                        "Nueva Clasificación": sub["_clasif"],
                        f"Monto ({MONTH_NAME_ES[month]})": sub["_monto_txt"],
                    })

                    st.dataframe(sub_show, use_container_width=True, hide_index=True)

# =========================================================
# ✅ CALCULADORAS
# =========================================================
rate = _extract_rate_from_label(CONCEPT_INTERES_DIARIO)

st.markdown("### 🧮 Calculadoras")

with st.expander("Abrir calculadoras", expanded=False):
    tab_adelanto, tab_fci = st.tabs(["⏩ Adelantar pago", "📈 Proyección rendimiento FCI"])

    # -------------------------
    # TAB 1 — ADELANTAR PAGO
    # -------------------------
    with tab_adelanto:
        calc_src = st.session_state.get("df_gastos_mes")

        if calc_src is None or calc_src.empty:
            st.info("No hay gastos disponibles para calcular adelantos en este mes.")
        else:
            calc_src = calc_src.copy()

            calc_src["_prov"] = calc_src["Proveedor"].astype(str).str.strip()
            calc_src["_fecha_d"] = pd.to_datetime(calc_src["_fecha"], errors="coerce").dt.date
            calc_src["_pago"] = calc_src["PAGO DIA"].astype(str).str.strip()

            calc_src = calc_src.dropna(subset=["_fecha_d"])
            calc_src = calc_src[calc_src["_monto"].abs() > 0]

            if calc_src.empty:
                st.info("No hay pagos con fecha válida para este mes.")
            else:
                col1, col2, col3 = st.columns([1.7, 1.2, 1.9])

                with col1:
                    prov_calc = st.selectbox(
                        "Proveedor",
                        options=sorted(calc_src["_prov"].unique()),
                        index=0,
                    )

                prov_df = calc_src[calc_src["_prov"] == prov_calc]

                with col2:
                    fechas_disp = sorted(prov_df["_fecha_d"].unique())
                    fecha_calc = st.selectbox(
                        "Fecha de pago",
                        options=fechas_disp,
                        format_func=lambda d: d.strftime("%d/%m/%Y"),
                        index=0,
                    )

                fecha_df = prov_df[prov_df["_fecha_d"] == fecha_calc].copy()
                fecha_df["_monto_txt"] = fecha_df["_monto"].map(fmt_money_ar)
                fecha_df["_opt"] = fecha_df["_pago"] + " — $ " + fecha_df["_monto_txt"]
                fecha_df = fecha_df.sort_values("_monto", ascending=False)

                with col3:
                    pago_opt = st.selectbox(
                        "Pago a adelantar (monto ya cargado)",
                        options=fecha_df["_opt"].tolist(),
                        index=0,
                    )

                adelanto_monto = float(fecha_df.loc[fecha_df["_opt"] == pago_opt, "_monto"].iloc[0])

                st.caption(f"Monto seleccionado: **$ {fmt_money_ar(adelanto_monto)}**")
                st.caption(f"Tasa diaria usada: **{rate*100:.4f}%**")

                hoy = date.today()
                dias_default = max(0, (fecha_calc - hoy).days)

                dias_key = f"calc_dias_{year}_{month}"
                firma_pago = (prov_calc, fecha_calc, pago_opt)

                if st.session_state.get("_firma_pago_prev") != firma_pago:
                    st.session_state["_firma_pago_prev"] = firma_pago
                    st.session_state[dias_key] = dias_default

                with st.form("calc_adelanto_form"):
                    colA, colB = st.columns([1.0, 1.0])

                    with colA:
                        adelanto_dias = st.number_input(
                            "Días de adelanto",
                            min_value=0,
                            max_value=365,
                            step=1,
                            key=dias_key,
                        )

                    with colB:
                        modo = st.selectbox(
                            "Modo cálculo",
                            ["Compuesto (capitaliza)", "Simple"],
                            index=0,
                        )

                    calcular = st.form_submit_button("✅ Calcular")

                if calcular and adelanto_monto > 0:
                    d = int(adelanto_dias)

                    if d <= 0:
                        interes_perdido = 0.0
                    elif modo.startswith("Simple"):
                        interes_perdido = adelanto_monto * rate * d
                    else:
                        interes_perdido = adelanto_monto * ((1 + rate) ** d - 1)

                    impacto_total = adelanto_monto + interes_perdido

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Monto del pago", f"$ {fmt_money_ar(adelanto_monto)}")
                    with c2:
                        st.metric("Interés que perdés por adelantar", f"$ {fmt_money_ar(interes_perdido)}")
                    with c3:
                        st.metric("Impacto total", f"$ {fmt_money_ar(impacto_total)}")

    # -------------------------
    # TAB 2 — FCI (calculadora real)
    # -------------------------
    with tab_fci:
        st.markdown("#### 📈 Proyección rendimiento FCI")

        colA, colB, colC = st.columns([1.2, 1.0, 1.2])

        with colA:
            capital = st.number_input(
                "Capital a invertir ($)",
                min_value=0.0,
                value=1_000_000.0,
                step=100_000.0,
                format="%.2f",
                key="fci_capital"
            )

        with colB:
            dias = st.number_input(
                "Días",
                min_value=0,
                max_value=3650,
                value=30,
                step=1,
                key="fci_dias"
            )

        with colC:
            tasa_pct = st.number_input(
                "Tasa diaria (%)",
                min_value=0.0,
                value=rate * 100.0,
                step=0.0001,
                format="%.4f",
                key="fci_tasa"
            )

        modo = st.radio(
            "Modo",
            ["Compuesto (capitaliza)", "Simple"],
            horizontal=True,
            key="fci_modo"
        )

        tasa = float(tasa_pct) / 100.0
        d = int(dias)
        cap = float(capital)

        if cap <= 0 or d <= 0 or tasa <= 0:
            st.info("Cargá capital, días y una tasa > 0 para ver la proyección.")
        else:
            if modo.startswith("Simple"):
                interes = cap * tasa * d
                total = cap + interes
            else:
                total = cap * ((1 + tasa) ** d)
                interes = total - cap

            a, b, c = st.columns(3)
            with a:
                st.metric("Capital inicial", f"$ {fmt_money_ar(cap)}")
            with b:
                st.metric("Rendimiento estimado", f"$ {fmt_money_ar(interes)}")
            with c:
                st.metric("Total estimado", f"$ {fmt_money_ar(total)}")

            st.caption(f"Tasa usada: **{tasa_pct:.4f}% diario** · Días: **{d}** · Modo: **{modo}**")
