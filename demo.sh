#!/bin/bash
# Runs inside the demo container: virtual screen, screen recording, demo run, then the text overlays.
set -eu
mkdir -p /work/out/demo
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
export DISPLAY=:99 LANG=de_DE.UTF-8 LANGUAGE=de
sleep 2
REC_START=$(date +%s.%N); export REC_START
ffmpeg -loglevel error -y -f x11grab -draw_mouse 1 -framerate 25 -video_size 1920x1080 -i :99 \
    -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p /work/out/demo/raw.mp4 &
REC=$!
python3 /work/demo.py || { kill -INT $REC; wait $REC || true; echo demo failed; exit 1; }
sleep 0.5
kill -INT $REC; wait $REC || true

# overlays: one drawtext per caption, white text on a dark bar at the bottom
python3 - <<'EOF' > /work/out/demo/overlay.txt
import json
caps = json.load(open("/work/out/demo/captions.json"))
font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
parts = []
for i, (a, b, text) in enumerate(caps):
    open(f"/work/out/demo/cap{i}.txt", "w").write(text)
    parts.append(f"drawbox=x=0:y=ih-110:w=iw:h=110:color=black@0.6:t=fill:enable='between(t,{a:.2f},{b:.2f})',"
                 f"drawtext=fontfile={font}:textfile=/work/out/demo/cap{i}.txt:fontsize=40:fontcolor=white:"
                 f"x=50:y=h-78:enable='between(t,{a:.2f},{b:.2f})'")
print(",".join(parts))
EOF
ffmpeg -loglevel error -y -i /work/out/demo/raw.mp4 -filter_script:v /work/out/demo/overlay.txt \
    -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart -map_metadata -1 \
    /work/out/demo/e2e-check-demo.mp4
echo demo ok
