from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / "AppData/Local/Temp/rolerun-opencv"))
import cv2
import numpy as np

video = Path(r"C:\Users\PC\Videos\2026-08-24 19-58-31.mp4")
out = Path.home() / "AppData/Local/Temp/alpha127_drag_video_frames"
out.mkdir(parents=True, exist_ok=True)
capture = cv2.VideoCapture(str(video))
fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
duration = count / fps
frames = []
for index, second in enumerate(np.arange(0.0, duration + 0.001, 0.5)):
    capture.set(cv2.CAP_PROP_POS_MSEC, float(second * 1000.0))
    ok, frame = capture.read()
    if not ok:
        continue
    frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
    cv2.putText(frame, f"{second:05.1f}s", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2, cv2.LINE_AA)
    frames.append(frame)
capture.release()
for sheet_index in range(0, len(frames), 12):
    page = frames[sheet_index:sheet_index + 12]
    while len(page) < 12:
        page.append(np.zeros_like(frames[0]))
    rows = [np.hstack(page[row:row + 4]) for row in range(0, 12, 4)]
    cv2.imwrite(str(out / f"sheet_{sheet_index // 12 + 1:02d}.jpg"), np.vstack(rows))
print(f"fps={fps} frames={count} duration={duration:.3f}s sheets={(len(frames)+11)//12}")
