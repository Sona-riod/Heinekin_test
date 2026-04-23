# Top Camera — Debug Report & Checklist

**Reviewed:** 2026-04-22  ·  **Files:** `config.py`, `camera.py`, `detector.py`, `pallet_controller.py`, `hmi.py`, `main.py`, `ws_client.py`, `api_sender.py`, `database.py`, `printer.py`, `gpu_utils.py`

Logs from `top_camera.log` show the app now boots cleanly on Windows (PC mode, `/dev/video0` at 1280×720, YOLO + QReader on CPU, WebSocket connected). No crashes in the last few runs. Below are real issues, ordered by impact.

---

## 🔴 Correctness bugs (worth fixing soon)

- [ ] **1. Dummy camera frame never reaches the UI**
  In [camera.py:82](top_camera_final/camera.py#L82), real init sets `is_active = True`; dummy init leaves `is_active = False` ([camera.py:131](top_camera_final/camera.py#L131)).
  But [hmi.py:533-534](top_camera_final/hmi.py#L533-L534) early-returns from `_tick_camera` when `is_active` is False. So when the camera fails, the dummy's "CAMERA CONNECT FAIL" frame is drawn into the queue and immediately discarded — the operator sees a black panel instead of the diagnostic text.
  **Fix:** let `_tick_camera` render dummy frames (they're explicitly made for UI feedback) or set `is_active = True` with a separate `self.is_real` flag.

- [ ] **2. Reset leaks "assembling" pallets into the DB forever**
  `_reset_session` ([pallet_controller.py:126](top_camera_final/pallet_controller.py#L126)) creates a *new* `pallet_id` but never updates the old one's status. Every RESET (or fresh launch without a submit) leaves an orphaned `status='assembling'` row. [main.py:182](top_camera_final/main.py#L182) `--recover` mode picks the first one it sees — it'll resurrect stale sessions forever.
  **Fix:** before creating the new pallet, call `self.db.update_pallet_status(self.current_pallet_id, 'abandoned')` if a pallet is already in flight.

- [ ] **3. `test_mode` flag is wired to nothing**
  [config.py:49](top_camera_final/config.py#L49) sets `'test_mode': True`, comment says it "skips real API calls". Grep finds zero readers. Either wire it (`api_sender.py` should early-return a stub dispatch response when set) or delete the flag — right now it lies to whoever sets it.

- [ ] **4. `detector.device` can be `None` after a failed model load**
  [detector.py:50-52](top_camera_final/detector.py#L50-L52): if `YOLO(...)` raises, the `except` only logs — `self.device` stays `None`. Later, `self.model(frame, ..., device=None)` gets called. Ultralytics silently falls back to CPU, but the detector now has `self.model = None` and will silently return empty results on every frame. No alarm, no UI hint. Raise or propagate a hard failure here, or at minimum push a notification to the HMI.

---

## 🟠 Architecture & performance

- [ ] **5. IoU product tracker double-counts on a moving forklift**
  [pallet_controller.py:270-334](top_camera_final/pallet_controller.py#L270-L334) uses `IOU_THRESHOLD = 0.30` and `PRODUCT_MAX_AGE = 300` frames (~10 s at 30 fps). The comment assumes bottles are static. In reality, when the forklift accelerates, the bbox of the same bottle between frames 1 and 5 may have <30 % overlap → tracker starts a new `_TrackedProduct` and counts it again.
  This is exactly what motivated the "freeze on location confirm" band-aid. Consider:
  - Dropping `IOU_THRESHOLD` to ~0.10, **or**
  - Using a velocity-aware tracker (ByteTrack / BoT-SORT — ultralytics ships with them: `model.track(...)` instead of `model(...)`).

- [ ] **6. `_gpu_preprocess` is slower than CPU for `BGR2GRAY`**
  [detector.py:78-99](top_camera_final/detector.py#L78-L99) uploads to GPU, converts one color space, downloads back. The PCIe round-trip dwarfs the kernel cost. Either drop the GPU path for this op or run the whole crop→gray→decode pipeline on-GPU.

- [ ] **7. QReader is being fed grayscale, not RGB**
  [detector.py:168, 199, 219](top_camera_final/detector.py#L168) — the crop is converted to grayscale then passed to `self.reader.detect_and_decode(image=gray)`. QReader's internal YOLOv7 expects a 3-channel image; handing it a 2-D array either hurts accuracy or forces an implicit conversion inside the library. Pass the color `crop_opt` directly — Pyzbar is the one that wants grayscale.

- [ ] **8. Log file grows without bound**
  [config.py:238-242](top_camera_final/config.py#L238-L242) uses `FileHandler`, not `RotatingFileHandler`. The current log is 70 KB after a few days. A Jetson running 24/7 will fill its eMMC. Swap for `RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)`.

- [ ] **9. `ThreadPoolExecutor` is never shut down on app exit**
  [hmi.py:216](top_camera_final/hmi.py#L216) creates `self._executor`; nothing calls `shutdown()`. Daemon threads get killed when the process dies, so it doesn't leak in practice, but a clean `on_stop()` path should `self._executor.shutdown(wait=False, cancel_futures=True)`.

- [ ] **10. `cv2.VideoCapture.read()` is not guaranteed thread-safe**
  The capture thread ([camera.py:156](top_camera_final/camera.py#L156)) and `reinitialize()` both touch `self.cap`. `reinitialize()` calls `release()` on one thread and immediately re-initialises — if the capture loop was mid-`read()` on a now-released capture, you can get segfaults on Linux. Add a `threading.Lock` around `self.cap` assignment/access, or have the capture loop own all cap operations and post a "reinit" event to itself.

---

## 🟡 Cross-platform & environment

- [ ] **11. Linux-isms leak into PC mode**
  - [camera.py:52](top_camera_final/camera.py#L52) logs "Initializing ICAM-540 at /dev/video0" even on Windows — confusing.
  - [camera.py:39](top_camera_final/camera.py#L39) `_list_available_devices` only scans `/dev/video*` — on Windows, the "Available video devices: []" message is a lie; OpenCV sees them by index.
  Gate both on `os.name == 'nt'` or read `TOP_CAMERA_CONFIG['type']`.

- [ ] **12. Printer won't work on Windows without extra setup**
  [printer.py:9](top_camera_final/printer.py#L9) hardcodes `/dev/usb/lp0`. PyUSB fallback needs libusb + a Zadig-replaced driver on Windows. Document this in README or gate printer init behind `DEPLOY_MODE`.

- [ ] **13. `start_app.sh` is Jetson-only**
  No Windows `.bat` or PowerShell equivalent. If PC mode is intended for development, add one or document "just run `python main.py`".

- [ ] **14. KivyMD 1.2.0 is deprecated**
  The log warning at startup says it literally. Upgrade plan: `pip install https://github.com/kivymd/KivyMD/archive/master.zip` (KivyMD 2.0). This is a breaking change — plan the migration, don't do it mid-sprint.

---

## 🟢 Nice-to-have / polish

- [ ] **15. `_submit_btn` uses `on_press` while every other button uses `on_release`**
  [hmi.py:520](top_camera_final/hmi.py#L520). `on_press` fires immediately on tap-down; a user dragging off the button still triggers submit. Change to `on_release` for consistency.

- [ ] **16. MAC address + forklift ID are hardcoded in `config.py`**
  Fine for a single unit; risky once you have >1 forklift. Read from an env var (`FORKLIFT_ID`, `FORKLIFT_MAC`) or a small `device.json` next to the config.

- [ ] **17. `datetime.now().strftime('%d%m%y_…')` pallet IDs are not monotonic across years**
  `311299_235959` > `010100_000001`. With the `uuid4` suffix it doesn't matter for uniqueness, but any code sorting pallets lexicographically will get wrong results on New Year's Day. Use `%Y%m%d_%H%M%S`.

- [ ] **18. `signal.SIGTERM` handler in [main.py:273](top_camera_final/main.py#L273)**
  On Windows, `signal.SIGTERM` exists but the OS doesn't actually deliver it the way it does on Linux. Not a bug, just dead code in PC mode.

---

## ✅ Things you got right

- Heartbeat file + crash log pattern — good for watchdog-driven uptime.
- `threading.Event` for `_counts_frozen` — clean, atomic, cross-thread.
- `_keg_lock` guarding the three keg sets.
- WebSocket exponential backoff with stop-event.
- DB migrations are additive (`ALTER ... ADD COLUMN` swallowed if exists).
- Freezing product counts on location confirm is a clever workaround for the IoU-tracker weakness (see #5).

---

## Info that would sharpen this review

Optional things you could send me that'd let me give sharper answers:

1. **A real camera frame** (one `.jpg` from `top_camera_frames/`) — I could sanity-check the YOLO confidence thresholds against a realistic input.
2. **A sample cloud dispatch response** — the `paletteId` / `palletId` / `id` fallback chain in [hmi.py:972-974](top_camera_final/hmi.py#L972-L974) is guessing; let's pin it down.
3. **Answer to my question**: is Windows just for dev, or do you ship on PC too? That decides whether #11–13 are cosmetic or blockers.
4. **Crash log** (`crash.log` if it exists) — would tell me about unhandled exceptions not captured in `top_camera.log`.

---

## Suggested fix order

1. **#1 dummy-frame visibility** (1-line change, unblocks on-site debugging when camera fails)
2. **#2 abandoned pallet status** (5-line change, stops recovery from loading stale sessions)
3. **#8 log rotation** (1-line change, prevents disk-fill on Jetson)
4. **#4 detector hard-fail surface** (small change, avoids silent "no detections ever")
5. **#5 tracker upgrade to ultralytics ByteTrack** (bigger change, real quality win on product counts)
6. **#10 capture thread lock** (medium change, prevents rare Jetson crashes)
7. Everything else on a rainy day.
