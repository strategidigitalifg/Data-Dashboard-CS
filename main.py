import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import numpy as np
from datetime import time

# ===================== CONFIG =====================
SPREADSHEET_ID = "1nBu4i90879LP-ieaG9SoPPFngAHK6mlItUs1iJpI3as"

SOURCE_SHEET = "Data Source CS"
OLD_DATA_SHEET = "Old Data"
TARGET_SHEET = "Data Dashboard"

SERVICE_ACCOUNT_FILE = "service_account.json"

# ===================== AUTH =====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=SCOPES
)

gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

# ===================== HELPER =====================
def read_sheet(sheet_name):
    ws = sh.worksheet(sheet_name)
    return (
        get_as_dataframe(ws, evaluate_formulas=True, dtype=str)
        .dropna(how="all")
    )

def combine_date_hour(date_val, hour_val):
    if pd.isna(date_val) or pd.isna(hour_val):
        return pd.NaT
    try:
        return pd.Timestamp.combine(date_val.date(), hour_val)
    except:
        return pd.NaT

def diff_hours_business(start, end):
    if pd.isna(start) or pd.isna(end) or end <= start:
        return np.nan

    total_seconds = (end - start).total_seconds()
    return round(total_seconds / 3600, 2)
    # if pd.isna(start) or pd.isna(end) or end <= start:
    #     return np.nan

    # total_seconds = 0
    # current = start

    # while current < end:
    #     next_point = min(current + pd.Timedelta(minutes=1), end)
    #     if current.weekday() < 5 and time(8, 0) <= current.time() < time(22, 0):
    #         total_seconds += (next_point - current).total_seconds()
    #     current = next_point

    # return round(total_seconds / 3600, 2)

# ===================== READ DATA =====================
df_raw = read_sheet(SOURCE_SHEET)     # RAW
df_old = read_sheet(OLD_DATA_SHEET)   # SUDAH JADI

# ===================== PROCESS RAW DATA ONLY =====================
# DATETIME
df_raw["Created_at"] = pd.to_datetime(
    df_raw["Created_at"], dayfirst=True, errors="coerce"
)
df_raw["Closed_at"] = pd.to_datetime(
    df_raw["Closed_at"], dayfirst=True, errors="coerce"
)

# CLEAN & ROUND HOURS
df_raw["Created_hours_clean"] = (
    df_raw["Created_hours"]
    .astype(str)
    .str.replace(r"[^0-9:]", ":", regex=True)
    .pipe(pd.to_datetime, errors="coerce")
    .dt.floor("H")
    .dt.time
)

df_raw["Closed_hours_clean"] = (
    pd.to_datetime(
        df_raw["Created_hours_clean"].astype(str),
        errors="coerce"
    ) + pd.Timedelta(hours=1)
).dt.time

# COMBINE DATE + HOUR
df_raw["Created_ts"] = df_raw.apply(
    lambda r: combine_date_hour(
        r["Created_at"], r["Created_hours_clean"]
    ),
    axis=1
)

df_raw["Closed_ts"] = df_raw.apply(
    lambda r: combine_date_hour(
        r["Closed_at"], r["Closed_hours_clean"]
    ),
    axis=1
)

# WEEKDAY
df_raw["Created_weekday"] = (
    df_raw["Created_at"]
    .dt.day_name()
    .str.lower()
)

# SOLVED HOURS
df_raw["Solved_hours"] = df_raw.apply(
    lambda r: diff_hours_business(
        r["Created_ts"], r["Closed_ts"]
    ),
    axis=1
)

# FORMAT DATE
df_raw["Created_at"] = df_raw["Created_at"].dt.strftime("%d/%m/%Y").fillna("")
df_raw["Closed_at"] = df_raw["Closed_at"].dt.strftime("%d/%m/%Y").fillna("")

# FINAL COLUMNS
final_columns = [
    "Channel","Created_at","Created_hours","Nomor Tiket",
    "Nomor Ticket Coster","Email","Nama","Nomor KTP",
    "No Kartu Asuransi","No Telp","Alamat",
    "Nama Badan Usaha","PIC","Pengaduan","Type",
    "Category","Sub Category","Product","Eskalasi",
    "Status","Solusi","Closed_at","Closed_hours",
    "Keterangan","Created_weekday","Solved_hours"
]

df_raw = df_raw.reindex(columns=final_columns)

# ===================== MERGE AFTER PROCESS =====================
df_dashboard = pd.concat(
    [df_old, df_raw],
    ignore_index=True
)

# REMOVE DUPLICATE TICKET
df_dashboard = df_dashboard.drop_duplicates(
    subset=["Nomor Tiket"],
    keep="last"
)

df_dashboard["Created_at"] = pd.to_datetime(
    df_dashboard["Created_at"],
    dayfirst=True,
    errors="coerce"
).dt.strftime("%d/%m/%Y")

df_dashboard["Closed_at"] = pd.to_datetime(
    df_dashboard["Closed_at"],
    dayfirst=True,
    errors="coerce"
).dt.strftime("%d/%m/%Y")



# ===================== WRITE TO GSHEET =====================
try:
    ws_target = sh.worksheet(TARGET_SHEET)
except:
    ws_target = sh.add_worksheet(
        title=TARGET_SHEET,
        rows=5000,
        cols=50
    )

ws_target.clear()
set_with_dataframe(
    ws_target,
    df_dashboard,
    include_index=False,
    resize=True
)
ws_target.freeze(rows=1)

print("✅ Data Dashboard berhasil diperbarui")
