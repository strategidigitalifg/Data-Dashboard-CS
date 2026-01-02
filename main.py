import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import numpy as np
from datetime import time, timedelta

# ===================== CONFIG =====================
SPREADSHEET_ID = "1nBu4i90879LP-ieaG9SoPPFngAHK6mlItUs1iJpI3as"
SOURCE_SHEET = "Data Source CS"
TARGET_SHEET = "Data Dashboard"

# ===================== AUTH =====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(
    "service_account.json",
    scopes=SCOPES
)

gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

# ===================== READ DATA =====================
ws_source = sh.worksheet(SOURCE_SHEET)
df_dashboard = (
    get_as_dataframe(ws_source, evaluate_formulas=True, dtype=str)
    .dropna(how="all")
)

# ===================== DATETIME CLEAN =====================
df_dashboard["Created_at"] = pd.to_datetime(df_dashboard["Created_at"], dayfirst=True, errors="coerce")
df_dashboard["Closed_at"] = pd.to_datetime(df_dashboard["Closed_at"], dayfirst=True, errors="coerce")

# ===================== COMBINE DATE + HOUR =====================
def combine_date_hour(date_val, hour_val):
    if pd.isna(date_val) or pd.isna(hour_val):
        return pd.NaT
    try:
        if isinstance(hour_val, time):
            return pd.Timestamp.combine(date_val.date(), hour_val)
        if isinstance(hour_val, timedelta):
            return date_val + hour_val
        return pd.Timestamp.combine(date_val.date(), pd.to_datetime(hour_val).time())
    except:
        return pd.NaT

df_dashboard["Created_ts"] = df_dashboard.apply(
    lambda r: combine_date_hour(r["Created_at"], r["Created_hours"]), axis=1
)
df_dashboard["Closed_ts"] = df_dashboard.apply(
    lambda r: combine_date_hour(r["Closed_at"], r["Closed_hours"]), axis=1
)

# ===================== WEEKDAY =====================
df_dashboard["Created_weekday"] = df_dashboard["Created_at"].dt.day_name().str.lower()

# ===================== BUSINESS HOURS DIFF =====================
def diff_hours_business(start, end):
    if pd.isna(start) or pd.isna(end) or end <= start:
        return np.nan

    total_seconds = 0
    current = start

    while current < end:
        next_point = min(current + pd.Timedelta(minutes=1), end)
        if current.weekday() < 5 and time(8, 0) <= current.time() < time(22, 0):
            total_seconds += (next_point - current).total_seconds()
        current = next_point

    return round(total_seconds / 3600, 2)

df_dashboard["Solved_hours"] = df_dashboard.apply(
    lambda r: diff_hours_business(r["Created_ts"], r["Closed_ts"]), axis=1
)

# ===================== FORMAT DATE =====================
df_dashboard["Created_at"] = df_dashboard["Created_at"].dt.strftime("%d/%m/%Y").fillna("")
df_dashboard["Closed_at"] = df_dashboard["Closed_at"].dt.strftime("%d/%m/%Y").fillna("")

# ===================== FINAL COLUMNS =====================
final_columns = [
    "Channel","Created_at","Created_hours","Nomor Tiket","Nomor Ticket Coster",
    "Email","Nama","Nomor KTP","No Kartu Asuransi","No Telp","Alamat",
    "Nama Badan Usaha","PIC","Pengaduan","Type","Category","Sub Category",
    "Product","Eskalasi","Status","Solusi","Closed_at","Closed_hours",
    "Keterangan","Created_weekday","Solved_hours"
]

df_dashboard = df_dashboard[final_columns]

# ===================== WRITE TO GSHEET =====================
try:
    ws_target = sh.worksheet(TARGET_SHEET)
except:
    ws_target = sh.add_worksheet(title=TARGET_SHEET, rows=1000, cols=50)

ws_target.clear()
set_with_dataframe(ws_target, df_dashboard, include_index=False, resize=True)
ws_target.freeze(rows=1)
