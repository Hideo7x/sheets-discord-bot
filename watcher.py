import os, time, hashlib, requests
from copy import deepcopy
from typing import List, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = os.environ.get("SHEET_NAME", "Sheet1")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "2"))
QUIET_SECONDS = int(os.environ.get("QUIET_SECONDS", "5"))
RANGE_A1 = os.environ.get("RANGE", "A1:C100")
CREDENTIALS = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def build_sheets():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def fetch_values(service):
    rng = f"{SHEET_NAME}!{RANGE_A1}"
    res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=rng,
        valueRenderOption="FORMATTED_VALUE",
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute()
    vals = res.get("values", [])
    for row in vals:
        while len(row) < 3:
            row.append("")
    return vals + [["", "", ""]] * (100 - len(vals))

def matrix_hash(m):
    h = hashlib.sha256()
    for r in m:
        h.update(("||".join(r)).encode())
    return h.hexdigest()

def diff_rows(old, new):
    out = []
    for i in range(len(old)):
        a_old, b_old, c_old = old[i]
        a_new, b_new, c_new = new[i]
        if a_old != a_new or b_old != b_new:
            out.append((i + 1, [a_old, b_old, c_old], [a_new, b_new, c_new]))
    return out

def esc(s): return "(trống)" if not s else str(s).replace("`", "\\`")

def send_discord(msg):
    requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)

def format_msg(sheet_name, changes):
    lines = [f"📣 Google Sheets vừa được cập nhật:", f"• Sheet: **{sheet_name}**", ""]
    for row, old, new in changes:
        lines.append(
            f"• Cũ: (A{row}) `{esc(old[0])}` : (B{row}) `{esc(old[1])}`\n"
            f"• Mới: (A{row}) `{esc(new[0])}` : (B{row}) `{esc(new[1])}`\n"
            f"• Trạng thái: `{esc(new[2])}`\n"
        )
    lines.append(f"🔗 https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return "\n".join(lines)

def main():
    service = build_sheets()
    baseline = fetch_values(service)
    h_old = matrix_hash(baseline)
    last_change = 0
    pending_old = None
    pending_new = None
    pending = False
    print("📡 Watcher started. Poll =", POLL_SECONDS, "s; Quiet =", QUIET_SECONDS, "s")
    while True:
        try:
            time.sleep(POLL_SECONDS)
            curr = fetch_values(service)
            h_new = matrix_hash(curr)
            if h_new != h_old:
                pending_old = deepcopy(baseline)
                pending_new = deepcopy(curr)
                last_change = time.time()
                pending = True
                baseline = deepcopy(curr)
                h_old = h_new
            elif pending and time.time() - last_change >= QUIET_SECONDS:
                diffs = diff_rows(pending_old, pending_new)
                if diffs:
                    send_discord(format_msg(SHEET_NAME, diffs))
                pending = False
        except Exception as e:
            print("❌ Error:", e)
            time.sleep(2)

if __name__ == "__main__":
    main()
