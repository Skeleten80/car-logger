"""Phase-3 end-to-end test: dashcam perception, no hardware.

1. Unit-checks the pure pieces: letterbox geometry and the
   is_interesting() snapshot heuristic.
2. Runs the real vision loop over a short video synthesized from a real
   traffic photo (ultralytics' demo bus.jpg), with the real YOLOv8n ONNX
   model, and asserts detections land in SQLite with sane labels.
3. Asserts the dash API exposes the vision summary and serves snapshots.

Requires models/yolov8n.onnx -- run `python tools/export_models.py` first.
"""
import sqlite3
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

import numpy as np
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carlogger import dash, vision  # noqa: E402
from carlogger.vision import Detection, is_interesting, letterbox  # noqa: E402

BUS_JPG_URL = "https://ultralytics.com/images/bus.jpg"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL = PROJECT_ROOT / "models" / "yolov8n.onnx"


def test_letterbox():
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    padded, r, pad_w, pad_h = letterbox(img)
    assert padded.shape == (640, 640, 3), padded.shape
    assert abs(r - 0.5) < 1e-9
    # box round-trip through the padding math
    x = (100 - pad_w) / r
    assert abs(x - 200) < 1e-9
    print("letterbox ok")


def test_is_interesting():
    cfg = {"vision": {"interesting_conf": 0.6,
                      "large_box_fraction": 0.25,
                      "decel_threshold": 4.0}}
    area = 640.0 * 480.0
    person = Detection("person", 0.8, 0, 0, 50, 50)
    car_far = Detection("car", 0.9, 0, 0, 60, 40)      # tiny box
    car_near = Detection("car", 0.9, 0, 0, 400, 300)   # big box
    assert is_interesting([person], 0.0, area, cfg)
    assert not is_interesting([Detection("person", 0.5, 0, 0, 50, 50)],
                              0.0, area, cfg)
    assert is_interesting([car_near], 0.0, area, cfg)
    assert not is_interesting([car_far], 0.0, area, cfg)
    assert is_interesting([car_far], 5.0, area, cfg)   # hard braking
    assert not is_interesting([car_far], 2.0, area, cfg)
    assert not is_interesting([], 9.0, area, cfg)
    print("is_interesting ok")


def fetch_image(tmp: Path) -> Path:
    p = tmp / "bus.jpg"
    urllib.request.urlretrieve(BUS_JPG_URL, p)
    return p


def make_clip(img_path: Path, tmp: Path) -> Path:
    """15-frame clip with a slight zoom to simulate motion."""
    import cv2
    img = cv2.imread(str(img_path))
    assert img is not None, f"could not read {img_path}"
    h, w = img.shape[:2]
    out_path = tmp / "clip.mp4"
    vw = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                         5.0, (w, h))
    for i in range(15):
        scale = 1.0 + 0.04 * (i / 14)
        nw, nh = int(w * scale), int(h * scale)
        big = cv2.resize(img, (nw, nh))
        x0, y0 = (nw - w) // 2, (nh - h) // 2
        vw.write(big[y0:y0 + h, x0:x0 + w])
    vw.release()
    return out_path


def main():
    test_letterbox()
    test_is_interesting()

    assert MODEL.exists(), \
        f"model missing: {MODEL} -- run python tools/export_models.py first"
    tmp = Path(tempfile.mkdtemp(prefix="carlogger-phase3-"))
    snap_dir = tmp / "snapshots"

    img_path = fetch_image(tmp)
    clip = make_clip(img_path, tmp)

    cfg = {
        "storage": {"path": str(tmp / "drive.db")},
        "vision": {
            "enabled": True,
            "source": str(clip),
            "model": str(MODEL),
            "providers": ["CPUExecutionProvider"],
            "conf_threshold": 0.45,
            "target_fps": 1000.0,   # process every frame of the clip
            "snapshot_dir": str(snap_dir),
            "interesting_conf": 0.6,
            "large_box_fraction": 0.25,
            "decel_threshold": 4.0,
        },
        "dash": {"host": "127.0.0.1", "port": 0},
    }

    db_path = vision.run(cfg)   # returns at end of the clip
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT label, confidence, snapshot_path, interesting "
        "FROM vision_events").fetchall()
    conn.close()

    labels = {r[0] for r in rows}
    best = max(rows, key=lambda r: r[1]) if rows else None
    print(f"vision_events: {len(rows)} rows, labels={sorted(labels)}")
    if best:
        print(f"  best: {best[0]} conf={best[1]:.2f} "
              f"interesting={bool(best[3])}")
    assert rows, "no detections logged"
    assert labels & {"bus", "truck", "car"}, \
        f"expected a vehicle label, got {sorted(labels)}"
    assert best[1] > 0.5, f"best confidence too low: {best[1]}"
    assert any(r[3] for r in rows), "no interesting events flagged"
    snaps = list(snap_dir.glob("*.jpg"))
    assert snaps, "no snapshots saved"
    assert snaps[0].read_bytes()[:2] == b"\xff\xd8", "snapshot not a JPEG"
    print(f"snapshots: {len(snaps)} files, e.g. {snaps[0].name}")

    # dash API: vision summary + snapshot serving
    server = dash.create_server(cfg)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/latest", timeout=10) as r:
            import json
            latest = json.loads(r.read())
        vis = latest["vision"]
        assert set(vis["detections"]) & {"bus", "truck", "car"}, vis
        assert vis["last_snapshot"], "no last_snapshot in API"
        print(f"/api/latest vision ok: {sorted(vis['detections'])} "
              f"last_snapshot={vis['last_snapshot']}")
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/snapshots/{vis['last_snapshot']}",
                timeout=10) as r:
            body = r.read()
        assert r.headers.get_content_type() == "image/jpeg"
        assert body[:2] == b"\xff\xd8"
        print(f"/snapshots ok: {len(body)} bytes JPEG")
        # traversal attempt must 404, not leak files
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/snapshots/..%2Fdrive.db",
                timeout=10)
            raise SystemExit("path traversal NOT blocked!")
        except urllib.error.HTTPError as e:
            assert e.code == 404, e.code
            print("snapshot path traversal blocked (404) ok")
    finally:
        server.shutdown()
        server.server_close()

    print("PHASE-3 TEST PASSED")


if __name__ == "__main__":
    main()
