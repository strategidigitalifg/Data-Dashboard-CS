import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import pandas as pd
import numpy as np
from datetime import time, timedelta

# ===================== CONFIG =====================
SPREADSHEET_ID = "1nBu4i90879LP-ieaG9SoPPFngAHK6mlItUs1iJpI3as"

SOURCE_SHEET = "Data Source CS"
OLD_DATA_SHEET = "Old Data"
WA_COSTER = "Data WA Coster"
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

def combine_date_hour(date_col, hour_col):
    if pd.isna(date_col) or pd.isna(hour_col):
        return pd.NaT
    return pd.to_datetime(
        f"{date_col} {hour_col}",
        dayfirst=True,
        errors="coerce"
    )

WORK_START = time(9, 0)
WORK_END = time(21, 0)

def is_outside_working_hours(dt):
    return (
        dt.weekday() >= 5 or
        dt.time() < WORK_START or
        dt.time() >= WORK_END
    )

def diff_hours(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan
    diff = (end - start).total_seconds() / 60
    return round(max(diff, 0), 5)

# 🔥 RULE BARU
def diff_hours_business(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan

    if end <= start:
        return 0

    total_seconds = 0
    current = start

    while current < end:
        # 🔥 RULE BERDASARKAN TANGGAL
        if current.date() >= pd.to_datetime("2026-04-13").date():
            work_start_hour = 8
            work_end_hour = 22
            is_workday = True
        else:
            work_start_hour = 9
            work_end_hour = 21
            is_workday = current.weekday() < 5

        # skip weekend hanya sebelum 13 April
        if not is_workday:
            current = (current + timedelta(days=1)).replace(hour=work_start_hour, minute=0, second=0)
            continue

        work_start_dt = current.replace(hour=work_start_hour, minute=0, second=0)
        work_end_dt = current.replace(hour=work_end_hour, minute=0, second=0)

        effective_start = max(current, work_start_dt)
        effective_end = min(end, work_end_dt)

        if effective_start < effective_end:
            total_seconds += (effective_end - effective_start).total_seconds()

        # next day
        current = (current + timedelta(days=1)).replace(hour=work_start_hour, minute=0, second=0)

    return round(total_seconds / 60, 5)


def classify_business_hour(dt):
    if pd.isna(dt):
        return np.nan

    if dt.date() >= pd.to_datetime("2026-04-13").date():
        # setelah 13 April (weekend masuk)
        work_start = time(9, 0)
        work_end = time(22, 0)
        is_workday = True
    else:
        # sebelum 13 April (weekend tidak masuk)
        work_start = time(9, 0)
        work_end = time(21, 0)
        is_workday = dt.weekday() < 5

    is_worktime = work_start <= dt.time() < work_end

    if is_workday and is_worktime:
        return "business hour"
    else:
        return "non business hour"
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
df_raw["Created_ts"] = pd.to_datetime(
    df_raw["Created_at"].astype(str) + " " + df_raw["Created_hours"].astype(str),
    errors="coerce"
)
df_raw["Closed_ts"] = pd.to_datetime(
    df_raw["Closed_at"].astype(str) + " " + df_raw["Closed_hours"].astype(str),
    errors="coerce"
)
# Remove timezone (kalau ada)
df_raw["Created_ts"] = df_raw["Created_ts"].dt.tz_localize(None)
df_raw["Closed_ts"] = df_raw["Closed_ts"].dt.tz_localize(None)

df_raw["Created_ts"] = pd.to_datetime(df_raw["Created_ts"])
df_raw["Closed_ts"] = pd.to_datetime(df_raw["Closed_ts"])

# Coster
cols = [
    "Ticket Number",
    "Created At",
    "Assigned At",
    "First Response At",
    "Closed At"
]
df_coster = read_sheet(WA_COSTER)
df_coster = df_coster[cols].rename(columns={
    "Created At": "Created At Coster",
    "Closed At": "Closed At Coster"
})

df_coster["Created At Coster"] = pd.to_datetime(
    df_coster["Created At Coster"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
)

df_coster["First Response At"] = pd.to_datetime(
    df_coster["First Response At"],
    errors="coerce"
)

df_coster["Closed At Coster"] = pd.to_datetime(
    df_coster["Closed At Coster"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
)

df_raw = df_raw.merge(
    df_coster,
    left_on="Nomor Ticket Coster",
    right_on="Ticket Number",
    how="left"   # bisa diganti "inner" kalau mau hanya yang match saja
)
# ganti Created_at untuk whatsapp-cloud
df_raw["Created_ts"] = np.where(
    (df_raw["Channel"] == "Whatsapp-cloud") & (df_raw["Created At Coster"].notna()),
    df_raw["Created At Coster"],
    df_raw["Created_ts"]
)

df_raw["Closed_ts"] = np.where(
    (df_raw["Channel"] == "Whatsapp-cloud") & (df_raw["Closed At Coster"].notna()),
    df_raw["Closed At Coster"],
    df_raw["Closed_ts"]
)

# Hitung selisih jam
df_raw["Solved_hours"] = df_raw.apply(
    lambda r: diff_hours(r["Created_ts"], r["Closed_ts"]),
    axis=1
)
df_raw["Solved_hours"] = df_raw["Solved_hours"].astype(float)

# Hitung First_time_response 
def diff_first_time(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan 
    diff = (end - start).total_seconds() / 60
    return max(diff, 0)

df_raw["First_time_response"] = df_raw.apply(
    lambda r: diff_first_time(r["Created_ts"], r["First Response At"]),
    axis=1
)
df_raw["First_time_response"] = df_raw["First_time_response"].astype(float)

df_raw["Solved_hours_business_hours"] = df_raw.apply(
    lambda r: diff_hours_business(r["Created_ts"], r["Closed_ts"]),
    axis=1
)

df_raw["First_time_business_hours"] = df_raw.apply(
    lambda r: diff_hours_business(r["Created_ts"], r["First Response At"]),
    axis=1
)

df_raw["Created_weekday"] = df_raw["Created_ts"].dt.day_name()

df_raw["Created_hour_type"] = df_raw["Created_ts"].apply(classify_business_hour)

# FORMAT DATE
df_raw["Created_at"] = df_raw["Created_at"].dt.strftime("%d/%m/%Y").fillna("")
df_raw["Closed_at"] = df_raw["Closed_at"].dt.strftime("%d/%m/%Y").fillna("")

df_raw["Solved_hours"] = df_raw["Solved_hours"] / 60
df_raw["Solved_hours_business_hours"] = df_raw["Solved_hours_business_hours"] / 60

# FINAL COLUMNS
final_columns = [
    "Channel","Created_at","Created_hours","Nomor Tiket",
    "Nomor Ticket Coster","Email","Nama","Nomor KTP",
    "No Kartu Asuransi","No Telp","Alamat",
    "Nama Badan Usaha","PIC","Pengaduan","Type",
    "Category","Sub Category","Product","Eskalasi",
    "Status","Solusi","Closed_at","Closed_hours",
    "Keterangan","Created_weekday", "Created_hour_type" ,"Solved_hours", "Solved_hours_business_hours", "First_time_response", "First_time_business_hours"
]
df_raw = df_raw.reindex(columns=final_columns)
# ===================== MERGE AFTER PROCESS =====================
df_old["Solved_hours_business_hours"] = np.nan
df_old["Created_hour_type"] = np.nan
df_old["First_time_response"] = np.nan
df_old["First_time_business_hours"] = np.nan
df_old["Solved_hours"] = df_old["Solved_hours"].astype(float)

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
