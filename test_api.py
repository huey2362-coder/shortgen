import urllib.request, json, time, os
BASE = "http://127.0.0.1:8099"

def post(path, obj):
    req = urllib.request.Request(BASE+path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

def get(path):
    return json.load(urllib.request.urlopen(BASE+path, timeout=30))

body = {"script": ("Most people use AI like a search box. One question, one answer. "
                   "Here is the shift. Tell it to ask you questions first. "
                   "Now it gives back something you would actually use."),
        "voice": "male", "background": "gradient"}
print("1) generate 요청...")
j = post("/api/generate", body)
jid = j["job_id"]; print("   job_id:", jid)

print("2) 폴링...")
for _ in range(60):
    time.sleep(1.5)
    s = get("/api/status/"+jid)
    print("   status:", s["status"])
    if s["status"] == "done":
        print("   meta:", s["meta"]); break
    if s["status"] == "error":
        print("   ERROR:", s["error"]); raise SystemExit(1)

print("3) 다운로드 확인...")
data = urllib.request.urlopen(BASE+"/api/download/"+jid, timeout=30).read()
out = os.path.join(os.path.dirname(__file__), "out", "api_result.mp4")
open(out, "wb").write(data)
print("   다운로드 OK:", len(data)//1024, "KB ->", out)
