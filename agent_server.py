import os
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path

import requests
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

# ==================== CONFIGURATION ====================
# PENTING: Semua secret WAJIB diisi lewat Environment Variable di Railway.
# TIDAK ADA lagi nilai rahasia yang ditulis langsung di kode.
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", )
GEMINI_KEY   = os.getenv("GEMINI_API_KEY", )
BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", )
CHAT_ID      = os.getenv("8960086795")

if not all([DEEPSEEK_KEY, BOT_TOKEN, CHAT_ID]):
    raise RuntimeError(
        "Environment variable belum lengkap. Set dulu di Railway: "
        "DEEPSEEK_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    )

# Path sekarang relatif & lintas-platform (aman di Railway/Linux maupun lokal Windows)
BASE_DIR = Path(os.getenv("SJS_DATA_DIR", "./data"))
DB_PATH  = BASE_DIR / "master_brain.db"
BASE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="YansenIT Agent Server")

# ==================== UTILITIES ====================

def log_system(level, category, message, task_id="SYSTEM"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [{category}] {message}")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS system_logs "
                "(id INTEGER PRIMARY KEY, timestamp TEXT, level TEXT, "
                "category TEXT, task_id TEXT, message TEXT)"
            )
            conn.execute(
                "INSERT INTO system_logs "
                "(timestamp, level, category, task_id, message) VALUES (?, ?, ?, ?, ?)",
                (timestamp, level, category, task_id, message),
            )
    except Exception as e:
        print(f"⚠️ Gagal log: {e}")


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log_system("ERROR", "TELEGRAM", str(e))


# ==================== AI INTEGRATION ====================

def call_deepseek(prompt: str) -> str:
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
    system_dna = (
        "Anda adalah YansenIT, konsultan teknologi efisien. "
        "PRINSIP: Jawaban langsung (1+1=2), hemat kata, tidak bertele-tele. "
        "Jika riset: Gunakan Tabel Markdown. "
        "Selalu akhiri dengan 'Saran Auditor' yang tegas. "
        "Jangan berikan penjelasan teknis kecuali diminta."
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_dna},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR DeepSeek: {e}"


# ==================== CORE WORKFLOW ====================

SENSITIVE_WORDS = ["pajak", "keuangan", "transfer", "bayar", "hapus", "db"]


def run_task_in_background(task_id: str, project_name: str, task_desc: str):
    """Jalan di background -> pemanggil (Hookdeck/n8n) tidak perlu menunggu, jadi tidak timeout."""
    try:
        log_system("INFO", "AI", "Mengontak DeepSeek...", task_id)
        prompt = f"Project: {project_name}\nTugas: {task_desc}\nBerikan hasil/riset/kode."
        ai_res = call_deepseek(prompt)
        send_telegram(f"✅ *HASIL EKSEKUSI*\n\n{ai_res}")
        log_system("INFO", "WORKFLOW", "Selesai", task_id)
    except Exception:
        log_system("ERROR", "WORKFLOW", traceback.format_exc(), task_id)
        send_telegram("❌ *ERROR* saat memproses tugas. Cek log sistem.")


class TaskRequest(BaseModel):
    project: str
    task: str
    force: bool = False


@app.post("/execute")
def execute_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = datetime.now().strftime("%Y%m%d%H%M%S")
    log_system("INFO", "WORKFLOW", f"Memulai: {req.project}", task_id)

    # 1. RISK ASSESSMENT -- dijawab langsung, tanpa nunggu AI
    if any(w in req.task.lower() for w in SENSITIVE_WORDS) and not req.force:
        send_telegram("🛑 *RISK GUARD TRIGGERED!*\nKonfirmasi via force=true diperlukan.")
        return {"status": "WAITING_APPROVAL", "task_id": task_id}

    # 2. Proses berat (panggil DeepSeek) dilempar ke background
    background_tasks.add_task(run_task_in_background, task_id, req.project, req.task)
    return {"status": "PROCESSING", "task_id": task_id}


@app.get("/health")
def health():
    return {"status": "ok"}
