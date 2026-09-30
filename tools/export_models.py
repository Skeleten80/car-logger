"""Export the phase-3 perception model.

Downloads YOLOv8n (nano, ~6 MB weights) and exports it to ONNX *with NMS
baked into the graph*, so inference is a single session run returning final
detections as rows of [x1, y1, x2, y2, confidence, class_id].

The same .onnx runs on both targets:
  - Linux dev/test box: onnxruntime CPUExecutionProvider
  - M6 Mac Mini:      onnxruntime CoreMLExecutionProvider -> Neural Engine

Run:  python tools/export_models.py [--models-dir models]

Verifies the export by loading it in onnxruntime and running one inference.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser(description="Export YOLOv8n to ONNX+NMS")
    ap.add_argument("--models-dir", default="models")
    ap.add_argument("--img-size", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO

    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    print("loading yolov8n (downloads weights on first run)...", flush=True)
    model = YOLO("yolov8n.pt")

    out = models_dir / "yolov8n.onnx"
    print(f"exporting -> {out} ...", flush=True)
    exported = model.export(format="onnx", nms=True, dynamic=False,
                            simplify=True, imgsz=args.img_size)
    # ultralytics saves next to the weights by default; move into models/
    exported_path = Path(exported)
    if exported_path.resolve() != out.resolve():
        out.write_bytes(exported_path.read_bytes())
        print(f"moved {exported_path} -> {out}", flush=True)

    # Verify: load in onnxruntime, run a blank-frame inference.
    import onnxruntime as ort

    sess = ort.InferenceSession(str(out),
                                providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    print(f"input: {inp.name} {inp.shape}, "
          f"outputs: {[o.name for o in sess.get_outputs()]}", flush=True)
    dummy = np.zeros((1, 3, args.img_size, args.img_size), dtype=np.float32)
    det = sess.run(None, {inp.name: dummy})[0]
    # NMS-baked export pads to a fixed count: (1, 300, 6). Squeeze the batch
    # dim; what matters is rows of [x1 y1 x2 y2 conf class].
    if det.ndim == 3:
        det = det[0]
    print(f"verify inference ok: output shape {det.shape} "
          f"(rows of [x1 y1 x2 y2 conf class])", flush=True)
    assert det.ndim == 2 and det.shape[1] == 6, \
        f"unexpected NMS output shape {det.shape}"
    print("EXPORT OK")


if __name__ == "__main__":
    sys.exit(main())
