# 키·GPU 없는 애니메이션 그래디언트 배경 테스트
import os, subprocess
from core import pipeline as P

HERE = os.path.dirname(os.path.abspath(__file__))
work = os.path.join(HERE, "out")
os.makedirs(work, exist_ok=True)
audio = os.path.join(work, "g_audio.mp3")
vtt = os.path.join(work, "g_subs.vtt")
srt = os.path.join(work, "g_subs.srt")
out = os.path.join(work, "gradient_demo.mp4")

SCRIPT = ("Most people use A-I like a search box. One question, one answer. "
          "Here's the shift. Tell it to ask you questions first, before it answers. "
          "Now it interviews you, and gives back something you'd actually use. "
          "The tool matters less than how you talk to it.")

P._tts(SCRIPT, P.DEFAULT_VOICE, audio, vtt)
P._build_srt(vtt, srt, 4)
dur = P._duration(audio)
print(f"길이 {dur:.1f}s")

# 애니메이션 그래디언트 (다크 인디고 계열, 느린 회전) + 미세 그레인 + 자막
grad = (f"gradients=s=1080x1920:c0=#0e0a1f:c1=#241c46:c2=#12183a:c3=#1a1030:"
        f"nb_colors=4:x0=120:y0=200:x1=980:y1=1750:speed=0.012:duration={dur:.2f}:rate=30")
vf = (
    "noise=alls=6:allf=t,"                     # 미세 필름 그레인
    "vignette=PI/5,"                            # 가장자리 어둡게(집중)
    f"subtitles={os.path.basename(srt)}:force_style='{P.CAPTION_STYLE}'"
)
cmd = [P.FFMPEG, "-y", "-f", "lavfi", "-i", grad, "-i", os.path.basename(audio),
       "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
       "-t", f"{dur:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", os.path.basename(out)]
r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
if r.returncode != 0:
    print("ERR:\n", r.stderr[-1500:]); raise SystemExit(1)
print("완성:", out, os.path.getsize(out)//1024, "KB")
# QC 프레임 2장
for t in (2, dur*0.7):
    subprocess.run([P.FFMPEG, "-y", "-ss", f"{t:.1f}", "-i", os.path.basename(out),
        "-frames:v", "1", f"gq_{int(t)}.png"], cwd=work, capture_output=True)
print("프레임 gq_ 추출")
