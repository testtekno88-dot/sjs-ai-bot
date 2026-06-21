import os
import sqlite3
import traceback
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

# ==================== CONFIGURATION ====================
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
GEMINI_KEY   = os.getenv("GEMINI_API_KEY")
BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID")

if not all([DEEPSEEK_KEY, BOT_TOKEN, CHAT_ID]):
    raise RuntimeError(
        "Environment variable belum lengkap. Set dulu di Railway: "
        "DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    )

BASE_DIR = Path(os.getenv("SJS_DATA_DIR", "./data"))
DB_PATH  = BASE_DIR / "master_brain.db"
BASE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="YansenIT Agent Server")

# ==================== UTILITIES ====================
def log_system(level, category, message, task_id="SYSTEM"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [{category}] {message}")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        log_system("ERROR", "TELEGRAM", str(e))

# ==================== AI INTEGRATION ====================
def call_deepseek(prompt: str) -> str:
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
    system_dna = "Anda adalah YansenIT, konsultan teknologi efisien. Jawaban singkat, padat, gunakan tabel jika perlu. Akhiri dengan 'Saran Auditor'."
    payload = {"model": "deepseek-chat", "messages": [{"role": "system", "content": system_dna}, {"role": "user", "content": prompt}], "max_tokens": 4000}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR DeepSeek: {e}"

# ==================== TELEGRAM POLLING ====================
def telegram_polling():
    last_update_id = 0
    print("Bot Polling aktif, siap mendengarkan pesan...")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}"
            r = requests.get(url, timeout=30)
            data = r.json()
            if data.get("result"):
                for update in data["result"]:
                    last_update_id = update["update_id"]
                    msg_obj = update.get("message", {})
                    text = msg_obj.get("text", "")
                    chat_id = msg_obj.get("chat", {}).get("id")
                    if text and str(chat_id) == str(CHAT_ID):
                        ai_res = call_deepseek(text)
                        send_telegram(ai_res)
            time.sleep(2)
        except:
            time.sleep(5)

@app.on_event("startup")
def startup_event():
    threading.Thread(target=telegram_polling, daemon=True).start()

# ==================== API ENDPOINTS ====================
class TaskRequest(BaseModel):
    project: str
    task: str
    force: bool = False

@app.post("/execute")
def execute_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = datetime.now().strftime("%Y%m%d%H%M%S")
    background_tasks.add_task(lambda: send_telegram(call_deepseek(f"Project: {req.project}\nTugas: {req.task}")))
    return {"status": "PROCESSING", "task_id": task_id}

@app.get("/health")
def health():
    return {"status": "ok"}
