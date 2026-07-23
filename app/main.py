"""
ShortGen — 웹 백엔드 (FastAPI)
주제/대본 입력 -> 백그라운드 생성 -> 상태 폴링 -> 다운로드/미리보기.
로컬 실행: uvicorn app.main:app  (프로젝트 루트에서)
"""
import os, sys, uuid, threading, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

from core.pipeline import generate_short
from app import billing

app = FastAPI(title="ShortGen")

JOBDIR = os.path.join(ROOT, "out", "jobs")
os.makedirs(JOBDIR, exist_ok=True)
JOBS = {}                      # job_id -> {status, out, meta, error}
_LOCK = threading.Lock()

# 데모용 무료 사용 한도(계정/결제 붙기 전 임시)
DEMO_LIMIT = int(os.environ.get("SHORTGEN_DEMO_LIMIT", "9999"))


class GenReq(BaseModel):
    script: str
    voice: str = "male"                 # male | female
    background: str = "gradient"        # gradient(무료) | footage(유료)
    pexels_key: str | None = None       # footage 모드용


def _run(job_id: str, req: GenReq):
    with _LOCK:
        JOBS[job_id] = {"status": "running"}
    try:
        out = os.path.join(JOBDIR, f"{job_id}.mp4")
        # 무료(gradient)=워터마크 / 유료(footage)=제거
        is_free = req.background != "footage"
        res = generate_short(
            req.script, out, voice=req.voice,
            background=req.background, pexels_key=req.pexels_key or None,
            watermark=is_free)
        with _LOCK:
            JOBS[job_id] = {"status": "done", "out": out, "meta": {
                "duration": res["duration"], "cues": res["cues"],
                "voice": res["voice"], "background": res["background"]}}
    except Exception as e:
        with _LOCK:
            JOBS[job_id] = {"status": "error", "error": str(e)}
        traceback.print_exc()


@app.post("/api/generate")
def api_generate(req: GenReq, bg: BackgroundTasks):
    if not req.script or len(req.script.split()) < 5:
        return JSONResponse({"error": "대본이 너무 짧다 (최소 몇 문장)"}, status_code=400)
    if req.background == "footage" and not req.pexels_key:
        return JSONResponse(
            {"error": "footage(실사 B롤)는 Pexels 무료 키가 필요. 무료는 gradient."},
            status_code=400)
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        JOBS[job_id] = {"status": "queued"}
    bg.add_task(_run, job_id, req)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def api_status(job_id: str):
    with _LOCK:
        j = JOBS.get(job_id)
    if not j:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return {"status": j["status"], "meta": j.get("meta"), "error": j.get("error")}


@app.get("/api/download/{job_id}")
def api_download(job_id: str):
    with _LOCK:
        j = JOBS.get(job_id)
    if not j or j.get("status") != "done":
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(j["out"], media_type="video/mp4",
                        filename=f"shortgen_{job_id}.mp4")


@app.get("/api/config")
def api_config():
    return {"paid_enabled": billing.ENABLED,
            "price": os.environ.get("STRIPE_PRICE_DISPLAY", "$9/mo")}


@app.post("/api/checkout")
def api_checkout(payload: dict):
    email = (payload or {}).get("email", "")
    try:
        return {"url": billing.create_checkout(email)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/webhook")
async def api_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        return billing.handle_webhook(payload, sig)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()
