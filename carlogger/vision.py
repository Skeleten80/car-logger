"""Phase-3 dashcam perception.

Capture -> YOLOv8n object detection -> SQLite vision_events, timestamped on
the same wall clock as the CAN logger so video and bus traffic can be
correlated after a drive ("what did the camera see when the bus did X?").

One runtime everywhere: onnxruntime. The execution providers come from
config, so the *same* model file runs on:
  - the M6 Mac Mini with ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    (the CoreML EP dispatches eligible ops to the Neural Engine), and
  - a Linux dev box with ["CPUExecutionProvider"].

Usage:
    python -m carlogger.vision [--config config.local.toml] [--duration 60]

Enable it first: [vision] enabled = true, source = 0 (USB dashcam index)
or a video file path for testing.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import load_config
from .db import Store

_stop = False

IMG_SIZE = 640

COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]

PERSON_LABEL = "person"
VEHICLE_LABELS = frozenset({"car", "motorcycle", "bus", "truck", "bicycle"})


@dataclass
class Detection:
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def _handle_signal(signum, frame):
    global _stop
    _stop = True


def letterbox(img: np.ndarray, size: int = IMG_SIZE):
    """Resize + pad to size x size (ultralytics letterbox convention)."""
    h, w = img.shape[:2]
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    import cv2
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_w, pad_h = (size - nw) / 2, (size - nh) / 2
    padded = cv2.copyMakeBorder(
        resized, int(round(pad_h - 0.1)), int(round(pad_h + 0.1)),
        int(round(pad_w - 0.1)), int(round(pad_w + 0.1)),
        cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return padded, r, pad_w, pad_h


class Detector:
    """YOLOv8n ONNX (NMS baked in) via onnxruntime."""

    def __init__(self, model_path: str | Path,
                 providers: list[str] | None = None,
                 conf_threshold: float = 0.45):
        try:
            import onnxruntime as ort
        except ImportError:
            raise RuntimeError(
                "onnxruntime is required for vision: pip install onnxruntime")
        self._ort = ort
        p = Path(model_path).expanduser()
        if not p.exists():
            # also try relative to the project root
            alt = Path(__file__).resolve().parent.parent / model_path
            p = alt if alt.exists() else p
        if not p.exists():
            raise FileNotFoundError(
                f"vision model not found: {model_path} "
                f"(run python tools/export_models.py)")
        available = set(ort.get_available_providers())
        wanted = providers or ["CPUExecutionProvider"]
        use = [pr for pr in wanted if pr in available]
        if "CPUExecutionProvider" not in use:
            use.append("CPUExecutionProvider")
        self.session = ort.InferenceSession(str(p), providers=use)
        self.providers = use
        self.conf_threshold = conf_threshold
        self.input_name = self.session.get_inputs()[0].name
        print(f"vision model: {p.name} providers={use}", flush=True)

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        import cv2
        h, w = bgr.shape[:2]
        padded, r, pad_w, pad_h = letterbox(bgr)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        inp = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        rows = self.session.run(None, {self.input_name: inp})[0]
        if rows.ndim == 3:
            rows = rows[0]  # NMS-baked export pads to a fixed (300, 6)
        out: list[Detection] = []
        for row in rows:
            x1, y1, x2, y2, conf, cls = (float(v) for v in row)
            if conf < self.conf_threshold:
                continue  # also skips the zero padding rows
            label = COCO_LABELS[int(cls)] \
                if 0 <= int(cls) < len(COCO_LABELS) else f"class_{int(cls)}"
            # back to original pixel coordinates
            out.append(Detection(
                label, float(conf),
                (x1 - pad_w) / r, (y1 - pad_h) / r,
                (x2 - pad_w) / r, (y2 - pad_h) / r))
        return out


def is_interesting(dets: list[Detection], decel_ms2: float,
                   frame_area: float, cfg: dict) -> bool:
    """Pure heuristic, unit-testable: is this frame worth a snapshot?"""
    if not dets:
        return False
    v = cfg["vision"]
    for d in dets:
        if d.label == PERSON_LABEL and d.confidence >= v["interesting_conf"]:
            return True
        if d.label in VEHICLE_LABELS:
            area = max(0.0, d.x2 - d.x1) * max(0.0, d.y2 - d.y1)
            if frame_area > 0 and area / frame_area >= v["large_box_fraction"]:
                return True
    # hard braking + anything detected in front of the car
    return decel_ms2 >= v["decel_threshold"]


def _annotate(bgr: np.ndarray, dets: list[Detection]) -> np.ndarray:
    import cv2
    img = bgr.copy()
    for d in dets:
        cv2.rectangle(img, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)),
                      (0, 255, 0), 2)
        cv2.putText(img, f"{d.label} {d.confidence:.2f}",
                    (int(d.x1), max(0, int(d.y1) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return img


def _latest_speed(store: Store) -> tuple[float | None, float | None]:
    row = store.conn.execute(
        "SELECT value, ts FROM obd2 WHERE name='speed' "
        "ORDER BY ts DESC LIMIT 1").fetchone()
    return (row[0], row[1]) if row else (None, None)


def run(cfg: dict, duration: float | None = None) -> Path:
    global _stop
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        import cv2  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "opencv is required for vision: pip install opencv-python-headless")

    v = cfg["vision"]
    if not v.get("enabled", False):
        raise RuntimeError(
            "vision is disabled: set [vision] enabled = true in config")

    store = Store(cfg["storage"]["path"], note="mode=vision")
    detector = Detector(v["model"], v.get("providers"),
                        v.get("conf_threshold", 0.45))
    snap_dir = Path(v.get("snapshot_dir",
                          "~/car-logger-data/snapshots")).expanduser()
    snap_dir.mkdir(parents=True, exist_ok=True)

    src = v.get("source", 0)
    cap = cv2.VideoCapture(int(src) if str(src).isdigit() else str(src))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video source: {src!r}")

    target_fps = float(v.get("target_fps", 4.0))
    min_dt = 1.0 / target_fps if target_fps > 0 else 0.0
    print(f"vision running: source={src} target_fps={target_fps} "
          f"-> {store.path} (session {store.session_id})", flush=True)

    t_end = time.time() + duration if duration else None
    last_proc = 0.0
    prev_speed: tuple[float | None, float | None] = (None, None)
    frames = events = snaps = 0
    try:
        while not _stop and (t_end is None or time.time() < t_end):
            ok, frame = cap.read()
            if not ok:
                break  # end of file / camera lost
            now = time.time()
            if now - last_proc < min_dt:
                continue
            last_proc = now
            frames += 1

            dets = detector.detect(frame)
            ts = time.time()
            h, w = frame.shape[:2]

            # deceleration from OBD-II speed (km/h -> m/s^2), same DB
            speed, sts = _latest_speed(store)
            decel = 0.0
            if (speed is not None and prev_speed[0] is not None
                    and sts and prev_speed[1]):
                dt = sts - prev_speed[1]
                if dt > 0:
                    decel = -((speed - prev_speed[0]) / 3.6) / dt
            prev_speed = (speed, sts)

            interesting = is_interesting(dets, decel, float(w * h), cfg)
            snap_path = ""
            if interesting:
                snap_path = str(
                    snap_dir / f"snap_{store.session_id}_{frames:06d}.jpg")
                cv2.imwrite(snap_path, _annotate(frame, dets))
                snaps += 1

            if dets:
                store.log_vision(ts, [
                    (d.label, d.confidence, d.x1, d.y1, d.x2, d.y2,
                     snap_path, interesting) for d in dets])
                events += len(dets)
    finally:
        cap.release()
        store.close()
    print(f"vision done: {frames} frames, {events} detections, "
          f"{snaps} snapshots", flush=True)
    return store.path


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-3 dashcam perception")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--duration", type=float, default=None,
                    help="stop after N seconds (default: run until signal)")
    args = ap.parse_args()
    cfg, cfg_path = load_config(args.config)
    print(f"using config: {cfg_path}", flush=True)
    run(cfg, args.duration)


if __name__ == "__main__":
    main()
