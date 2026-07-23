"""
ShortGen — 제품 코어 파이프라인
주제/대본 -> 완성된 9:16 쇼츠 mp4.

배경 2모드:
  - "gradient" (무료 티어, 기본): 애니 그래디언트+그레인+비네트. 키/GPU 0.
  - "footage"  (유료 티어): Pexels 무료 API로 문장 키워드별 실사 B롤 합성. pexels_key 필요.

무료 스택: edge-tts(음성)·ffmpeg(합성). COGS ~0.
"""
import os, re, json, subprocess, tempfile, shutil, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

def _bin(name):
    """번들 exe(윈도우) 우선, 없으면 시스템 PATH(리눅스 배포)."""
    local = os.path.join(HERE, name + ".exe")
    if os.name == "nt" and os.path.exists(local):
        return local
    return shutil.which(name) or shutil.which(name + ".exe") or local

FFMPEG = _bin("ffmpeg")
FFPROBE = _bin("ffprobe")
WM_FONT = os.path.join(HERE, "wm.ttf")


def _wm_filter():
    """무료 티어 워터마크 (drawtext). fontfile 콜론 이스케이프(ffmpeg 필터 규칙)."""
    ff = WM_FONT.replace("\\", "/").replace(":", "\\:")
    return (f"drawtext=fontfile='{ff}':text='ShortGen.app':x=(w-text_w)/2:y=48:"
            f"fontsize=24:fontcolor=white@0.6:box=1:boxcolor=black@0.28:boxborderw=8,")

DEFAULT_VOICE = "en-US-AndrewNeural"          # Warm, Confident, Honest
VOICE_ALT = {"male": "en-US-AndrewNeural", "female": "en-US-AvaNeural"}

# 자막: 하단중앙, 굵은 흰+검은외곽. Shadow=0(잔상 제거).
CAPTION_STYLE = ("Fontname=Arial,Fontsize=16,Bold=1,PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,BorderStyle=1,Outline=4,Shadow=0,"
                 "Alignment=2,MarginV=118")

_STOP = set("the a an and or but of to in on for with your you i it is are be as at "
            "this that these those from by so if then than into out up down not no do "
            "does did just now here there what which who how why when where can will "
            "one two three them they we he she his her its our their my me".split())


# ── 유틸 ──────────────────────────────────────────────────────────────────
def _ts(sec):
    if sec < 0:
        sec = 0
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s += 1; ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_to_sec(t):
    t = t.replace(",", ".")
    hh, mm, ss = t.split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def _tts(script, voice, audio_path, vtt_path):
    subprocess.run(["python", "-m", "edge_tts", "--voice", voice, "--text", script,
                    "--write-media", audio_path, "--write-subtitles", vtt_path],
                   check=True, capture_output=True)


def _parse_sentences(vtt_path):
    raw = open(vtt_path, encoding="utf-8").read()
    out = []
    for m in re.finditer(
            r"(\d\d:\d\d:\d\d[.,]\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d[.,]\d\d\d)\s*\n(.+)", raw):
        out.append((_vtt_to_sec(m.group(1)), _vtt_to_sec(m.group(2)), m.group(3).strip()))
    return out


def _build_srt(sentences, srt_path, words_per_cue=4):
    lines, idx = [], 1
    for cs, ce, text in sentences:
        ws = text.split()
        if not ws:
            continue
        n, span = len(ws), max(ce - cs, 0.001)
        for j in range(0, n, words_per_cue):
            grp = ws[j:j + words_per_cue]
            s = cs + span * (j / n)
            e = cs + span * (min(j + words_per_cue, n) / n)
            lines.append(f"{idx}\n{_ts(s)} --> {_ts(e)}\n{' '.join(grp)}\n")
            idx += 1
    open(srt_path, "w", encoding="utf-8").write("\n".join(lines))
    return idx - 1


def _duration(audio_path):
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path])
    return float(out.decode().strip())


def _keywords(script, k=5):
    freq = {}
    for w in re.findall(r"[a-zA-Z]{4,}", script.lower()):
        if w in _STOP:
            continue
        freq[w] = freq.get(w, 0) + 1
    top = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])][:k]
    return top or ["technology", "abstract", "working", "laptop", "city night"]


# ── 배경: 그래디언트 (무료) ────────────────────────────────────────────────
def _gradient_inputs(dur):
    grad = (f"gradients=s=540x960:c0=#0e0a1f:c1=#241c46:c2=#12183a:c3=#1a1030:"
            f"nb_colors=3:x0=60:y0=100:x1=480:y1=860:speed=0.012:duration={dur:.2f}:rate=24")
    pre = "vignette=PI/5,"                     # noise(그레인) 제거 = 메모리 대폭 절감
    return ["-f", "lavfi", "-i", grad], pre


# ── 배경: 실사 B롤 (유료, Pexels) ─────────────────────────────────────────
def _pexels_search_download(keyword, key, dest):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": keyword, "orientation": "portrait", "per_page": 3, "size": "medium"})
    req = urllib.request.Request(url, headers={"Authorization": key})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    for vid in data.get("videos", []):
        files = sorted(vid.get("video_files", []),
                       key=lambda f: abs((f.get("height") or 0) - 1920))
        for f in files:
            if (f.get("height") or 0) >= 1080 and f.get("link"):
                urllib.request.urlretrieve(f["link"], dest)
                return True
    return False


def _footage_bg(script, dur, key, work):
    kws = _keywords(script, k=6)
    seg = max(dur / max(len(kws), 1), 3.0)
    segs = []
    for i, kw in enumerate(kws):
        raw = os.path.join(work, f"clip{i}.mp4")
        if not _pexels_search_download(kw, key, raw):
            continue
        seg_path = os.path.join(work, f"seg{i}.mp4")
        r = subprocess.run([FFMPEG, "-y", "-t", f"{seg:.2f}", "-i", raw,
            "-vf", "scale=540:960:force_original_aspect_ratio=increase,"
                   "crop=540:960,setsar=1", "-an", "-r", "24",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
            "-pix_fmt", "yuv420p", seg_path],
            capture_output=True)
        if r.returncode == 0:
            segs.append(seg_path)
        if sum_dur(segs) >= dur + seg:
            break
    if not segs:
        raise RuntimeError("Pexels 클립 수급 실패 (키/쿼터 확인)")
    # concat (부족하면 반복해서 dur 채움)
    listf = os.path.join(work, "list.txt")
    total, order = 0.0, []
    while total < dur:
        for s in segs:
            order.append(s); total += seg
            if total >= dur:
                break
    with open(listf, "w", encoding="utf-8") as f:
        for s in order:
            f.write(f"file '{s.replace(os.sep, '/')}'\n")
    bg = os.path.join(work, "bg.mp4")
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listf,
        "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", bg], check=True, capture_output=True)
    return bg


def sum_dur(paths):
    t = 0.0
    for p in paths:
        try:
            t += _duration(p)
        except Exception:
            pass
    return t


# ── 공개 API ──────────────────────────────────────────────────────────────
def generate_short(script, out_path, voice=None, background="gradient",
                   pexels_key=None, words_per_cue=4, watermark=False):
    """
    script -> 9:16 mp4.
    background: "gradient"(무료·기본) | "footage"(유료·Pexels, pexels_key 필요).
    watermark: True 면 'ShortGen.app' 워터마크(무료 티어).
    """
    voice = VOICE_ALT.get(voice, voice) if voice else DEFAULT_VOICE
    work = tempfile.mkdtemp(prefix="shortgen_")
    try:
        audio = os.path.join(work, "audio.mp3")
        vtt = os.path.join(work, "subs.vtt")
        srt = os.path.join(work, "subs.srt")
        _tts(script, voice, audio, vtt)
        sents = _parse_sentences(vtt)
        ncues = _build_srt(sents, srt, words_per_cue)
        dur = _duration(audio)
        sub = f"subtitles=subs.srt:force_style='{CAPTION_STYLE}'"
        wm = _wm_filter() if watermark else ""

        if background == "footage":
            if not pexels_key:
                raise ValueError("footage 모드는 pexels_key 필요")
            bg = _footage_bg(script, dur, pexels_key, work)
            inputs = ["-i", os.path.basename(bg)]
            vf = f"[0:v]{wm}{sub}[v]"
        else:  # gradient
            inputs, pre = _gradient_inputs(dur)
            vf = f"[0:v]{pre}{wm}{sub}[v]"

        cmd = ([FFMPEG, "-y"] + inputs + ["-i", "audio.mp3",
               "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
               "-t", f"{dur:.2f}", "-r", "24", "-c:v", "libx264", "-preset", "ultrafast",
               "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "out.mp4"])
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg 실패:\n" + r.stderr[-1200:])
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.move(os.path.join(work, "out.mp4"), out_path)
        return {"out": out_path, "duration": round(dur, 1), "cues": ncues,
                "voice": voice, "background": background}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    demo = ("Most people use A-I like a search box. One question, one answer. "
            "Tell it to ask you questions first. Now it gives back something you'd use.")
    res = generate_short(demo, os.path.join(HERE, "..", "out", "core_gradient.mp4"),
                         background="gradient")
    print("OK:", res)
