import os, time, hashlib, requests, threading
from copy import deepcopy
from google.oauth2 import service_account
from googleapiclient.discovery import build
from flask import Flask

# ---- Nhận JSON key qua ENV rồi ghi ra file cục bộ (KHÔNG commit) ----
CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
CREDS_PATH = "service_account.json"
if CREDS_JSON:
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        f.write(CREDS_JSON)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

# ---- Config qua ENV ----
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME     = os.environ.get("SHEET_NAME", "Sheet1")
DISCORD_WEBHOOK= os.environ["DISCORD_WEBHOOK"]
POLL_SECONDS   = int(os.environ.get("POLL_SECONDS", "2"))
QUIET_SECONDS  = int(os.environ.get("QUIET_SECONDS", "5"))
RANGE_A1       = os.environ.get("RANGE", "A1:C100")
PORT           = int(os.environ.get("PORT", "10000"))  # Render sẽ set PORT

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def build_sheets():
    creds = service_account.Credentials.from_service_account_file(
        CREDS_PATH, scopes=SCOPES
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
    # chuẩn hoá 3 cột
    for row in vals:
        while len(row) < 3: row.append("")
    # lấp dòng rỗng nếu thiếu
    import re
    m = re.search(r"[A-Z]+(\d+):[A-Z]+(\d+)", RANGE_A1, re.I)
    total = (int(m.group(2)) - int(m.group(1)) + 1) if m else 100
    while len(vals) < total: vals.append(["","",""])
    return vals

def mhash(matrix):
    import hashlib
    h = hashlib.sha256()
    for r in matrix: h.update(("||".join(r)).encode())
    return h.hexdigest()

def diffs(old, new):
    out = []
    for i in range(min(len(old), len(new))):
        a0,b0,c0 = old[i]
        a1,b1,c1 = new[i]
        if a0 != a1 or b0 != b1:
            out.append((i+1, [a0,b0,c0], [a1,b1,c1]))
    return out

def esc(s): return "(trống)" if not s else str(s).replace("`","\\`")

def send(msg):
    try: requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e: print("send error:", e)

def fmt(sheet, changes):
    lines = [f"📣 Google Sheets vừa được cập nhật:", f"• Sheet: **{sheet}**", ""]
    for row, old, new in changes:
        lines.append(
            f"• Cũ: (A{row}) `{esc(old[0])}` : (B{row}) `{esc(old[1])}`\n"
            f"• Mới: (A{row}) `{esc(new[0])}` : (B{row}) `{esc(new[1])}`\n"
            f"• Trạng thái: `{esc(new[2])}`\n"
        )
    lines.append(f"🔗 https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return "\n".join(lines)

def watcher_loop():
    service = build_sheets()
    baseline = fetch_values(service)
    h_old = mhash(baseline)
    pending = False
    last_change = 0
    pend_old = pend_new = None

    print(f"📡 Watcher started. Poll={POLL_SECONDS}s Quiet={QUIET_SECONDS}s Range={RANGE_A1}")
    while True:
        try:
            time.sleep(POLL_SECONDS)
            curr = fetch_values(service)
            h_new = mhash(curr)
            if h_new != h_old:
                pend_old = deepcopy(baseline)
                pend_new = deepcopy(curr)
                last_change = time.time()
                pending = True
                baseline = deepcopy(curr)
                h_old = h_new
            elif pending and time.time() - last_change >= QUIET_SECONDS:
                df = diffs(pend_old, pend_new)
                if df: send(fmt(SHEET_NAME, df))
                pending = False
        except Exception as e:
            print("❌ watcher error:", e)
            time.sleep(2)

# ---- Web server nhỏ để Render free không sleep (ping từ UptimeRobot) ----
app = Flask(__name__)
@app.get("/health")
def health(): return "ok", 200

if __name__ == "__main__":
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
