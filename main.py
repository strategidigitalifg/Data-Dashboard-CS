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

def combine_date_hour(date_col, hour_col):
    if pd.isna(date_col) or pd.isna(hour_col):
        return pd.NaT
    return pd.to_datetime(
        f"{date_col} {hour_col}",
        dayfirst=True,
        errors="coerce"
    )
    
def diff_hours(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan
    if end < start:
        return 1
    if end == start:
        return 1
    return round((end - start).total_seconds() / 3600, 2)
    
from datetime import time, timedelta
import pandas as pd
import numpy as np

WORK_START = time(9, 0)
WORK_END = time(21, 0)

def adjust_to_working_time(dt):
    if pd.isna(dt):
        return pd.NaT

    # Kalau weekend → lompat ke Senin jam 09:00
    while dt.weekday() >= 5:  # 5=Sabtu, 6=Minggu
        dt = (dt + timedelta(days=1)).replace(hour=9, minute=0, second=0)

    # Kalau sebelum jam kerja → set ke 09:00
    if dt.time() < WORK_START:
        dt = dt.replace(hour=9, minute=0, second=0)

    # Kalau setelah jam kerja → ke besok 09:00
    elif dt.time() >= WORK_END:
        dt = (dt + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        return adjust_to_working_time(dt)  # recheck weekend

    return dt

def diff_hours_business(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan
    # Adjust start & end
    start = adjust_to_working_time(start)
    end = adjust_to_working_time(end)
    if end < start:
        return 1
    total_seconds = 0
    current = start
    while current < end:
        # End of current working day
        end_of_day = current.replace(hour=21, minute=0, second=0)
        if end <= end_of_day:
            total_seconds += (end - current).total_seconds()
            break
        else:
            total_seconds += (end_of_day - current).total_seconds()
            # Move ke next working day jam 09:00
            next_day = current + timedelta(days=1)
            current = adjust_to_working_time(
                next_day.replace(hour=9, minute=0, second=0)
            )
    hours = total_seconds / 3600
    # minimal 1 jam kalau start == end setelah adjust
    if hours == 0:
        return 1
    return round(hours, 2)

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
    pd.to_datetime(df_raw["Created_hours"], errors="coerce")
    .dt.floor("h")
    .dt.time
)

df_raw["Closed_hours_clean"] = (
    pd.to_datetime(df_raw["Closed_hours"], errors="coerce")
    .dt.floor("h")
    .dt.time
)

df_raw["Created_ts"] = pd.to_datetime(
    df_raw["Created_at"].astype(str) + " " + df_raw["Created_hours_clean"].astype(str),
    errors="coerce")

df_raw["Closed_ts"] = pd.to_datetime(
    df_raw["Closed_at"].astype(str) + " " + df_raw["Closed_hours_clean"].astype(str),
    errors="coerce")
# Remove timezone (kalau ada)
df_raw["Created_ts"] = df_raw["Created_ts"].dt.tz_localize(None)
df_raw["Closed_ts"] = df_raw["Closed_ts"].dt.tz_localize(None)

# Hitung selisih jam
df_raw["Solved_hours"] = df_raw.apply(
    lambda r: diff_hours(r["Created_ts"], r["Closed_ts"]),
    axis=1
)

df_raw["Solved_hours_business_hours"] = df_raw.apply(
    lambda r: diff_hours_business(r["Created_ts"], r["Closed_ts"]),
    axis=1
)
df_raw["Created_weekday"] = df_raw["Created_ts"].dt.day_name()

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
    "Keterangan","Created_weekday","Solved_hours", '"Solved_hours_business_hours"
]

df_raw = df_raw.reindex(columns=final_columns)

# ===================== MERGE AFTER PROCESS =====================
df_old["Solved_hours_business_hours"] = np.nan

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
