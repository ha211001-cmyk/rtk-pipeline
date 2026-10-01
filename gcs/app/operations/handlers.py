"""gcs.app.operations.handlers — 操作カタログと各ハンドラ実装。

Phase 2 で一本化した正典ロジックを import して再利用する:

- F9P 設定        : ``gcs.rtk_tools.f9p_config_all``（``F9pAllConfigurator``）
- RTK Fix 判定    : ``gcs.fix_metrics``（``compute_metrics`` / ``ubx_to_fix_type``）
- RTCM 監視・抽出 : ``gcs.rtcm_monitor``（``CorrectionMonitor`` / ``Rtcm3StreamParser``）
- 基地局ストリーム: ``gcs.rtk_tools.verify_rtcm_tcp``（``RTCM_MSG_NAMES``）
- 注入・中継      : ``gcs.rtk_tools.rtk_forwarder_service`` / ``tcp2serial`` / ``rtk_base_station_v2``

制御系（アーム/離陸/Guided/RTL/モード切替）は ``gcs/app/api/routes.py`` が担当する。

注意:
- 認証情報・シークレットはハードコードしない（NTRIP 認証は環境変数参照で解決済み）。
- 危険操作（Flash 書き込み・基地局座標上書き・GLONASS 切替・RTCM レート変更）は
  ``dangerous=True`` でカタログに登録し、Web UI 側で確認ダイアログを表示する。
"""

from __future__ import annotations

import csv
import socket
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from gcs.app.operations.manager import JobContext, OperationStopped
from gcs.app.operations.util import (
    detect_serial_port,
    ensure_log_dir,
    load_gcs_config,
    project_root,
)


# ==========================================================================
# パラメータ定義ヘルパー
# ==========================================================================
def _p(name, label, type="string", required=False, default=None, help="", options=None):
    d = {
        "name": name,
        "label": label,
        "type": type,
        "required": required,
        "default": default,
        "help": help,
    }
    if options:
        d["options"] = options
    return d


_SERIAL_P = _p("serial_port", "シリアルポート", default=None,
               help="省略時は自動検出（/dev/cu.usbmodem* 等）")
_BAUD_P = _p("baudrate", "ボーレート", type="int", default=None,
             help="省略時は既定値（base=38400 / rover=115200）")
_HOST_P = _p("host", "ホスト", default="127.0.0.1")
_PORT_P = _p("port", "ポート", type="int", default=5001)
_DURATION_P = _p("duration", "実行秒数", type="float", default=60.0)
_SAVE_P = _p("save_to_flash", "Flash 保存", type="bool", default=True,
             help="OFF なら RAM のみ（電源再投入で復元）")


def _transport_params(default_transport="serial"):
    return [
        _p("transport", "接続", options=["serial", "tcp"], default=default_transport),
        _SERIAL_P,
        _HOST_P,
        _PORT_P,
        _BAUD_P,
    ]


def _f(value, fallback):
    """None なら fallback を返す。"""
    return value if value is not None else fallback


def _default_baud(role: str) -> int:
    return 38400 if role == "base" else 115200


def _verify_summary(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_alive": v.get("device_alive"),
        "all_verified": v.get("all_verified"),
        "ok_count": v.get("ok_count"),
        "fail_count": v.get("fail_count"),
        "warn_count": v.get("warn_count"),
    }


# ==========================================================================
# 設定系ハンドラ
# ==========================================================================
def _make_configurator(params: Dict[str, Any], role: str):
    """transport/serial/host/port/baudrate から F9pAllConfigurator を構築する。"""
    from gcs.rtk_tools.f9p_config_all import F9pAllConfigurator  # noqa: PLC0415

    transport = params.get("transport", "serial")
    baudrate = int(params.get("baudrate") or _default_baud(role))
    if transport == "tcp":
        host = params.get("host") or "127.0.0.1"
        port = int(params.get("port") or 5001)
        return F9pAllConfigurator(host=host, port=port), "%s:%d" % (host, port)
    serial_port = params.get("serial_port") or detect_serial_port()
    if not serial_port:
        raise RuntimeError("シリアルポートを検出できません。serial_port を指定してください。")
    return F9pAllConfigurator(serial_port=serial_port, baudrate=baudrate), serial_port


def _base_llh(params: Dict[str, Any]):
    """基地局座標（lat/lon/alt）を params 優先・config.yaml 補完で返す。"""
    cfg = load_gcs_config()["base_station"]
    lat = params.get("lat")
    lon = params.get("lon")
    alt = params.get("alt")
    lat = float(lat) if lat is not None else float(cfg["fixed_lat"])
    lon = float(lon) if lon is not None else float(cfg["fixed_lon"])
    alt = float(alt) if alt is not None else float(cfg["fixed_alt"])
    return lat, lon, alt


def _op_f9p_write_verify(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    role = params.get("role", "base")
    save = bool(params.get("save_to_flash", True))

    from gcs.rtk_tools.f9p_config_all import _build_key_table  # noqa: PLC0415

    configurator, target = _make_configurator(params, role)
    lat = lon = alt = 0.0
    if role == "base":
        lat, lon, alt = _base_llh(params)
    ctx.log("F9P %s write-verify → %s (save=%s)" % (role, target, save))
    key_table = _build_key_table(lat, lon, alt)
    result = configurator.write_and_verify(
        role, key_table, lat=lat, lon=lon, alt=alt, save_to_flash=save
    )
    ctx.log("write results: %s" % result.get("write"))
    v = result.get("verify", {})
    ctx.log(
        "verify: ok=%s fail=%s warn=%s all_verified=%s"
        % (v.get("ok_count"), v.get("fail_count"), v.get("warn_count"), v.get("all_verified"))
    )
    ok = bool(result.get("all_ok"))
    ctx.progress(100.0, "PASS" if ok else "FAIL")
    return {"all_ok": ok, "write": result.get("write"), "verify": _verify_summary(v)}


def _op_f9p_verify(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    role = params.get("role", "base")
    from gcs.rtk_tools.f9p_config_all import _build_key_table  # noqa: PLC0415

    configurator, target = _make_configurator(params, role)
    lat = lon = alt = 0.0
    if role == "base":
        lat, lon, alt = _base_llh(params)
    ctx.log("F9P %s verify → %s" % (role, target))
    v = configurator.verify_role(role, _build_key_table(lat, lon, alt))
    ctx.log(
        "verify: ok=%s fail=%s warn=%s all_verified=%s"
        % (v.get("ok_count"), v.get("fail_count"), v.get("warn_count"), v.get("all_verified"))
    )
    ok = bool(v.get("all_verified"))
    ctx.progress(100.0, "PASS" if ok else "FAIL")
    return {"all_verified": ok, "verify": _verify_summary(v)}


def _op_base_tmode3_set(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    save = bool(params.get("save_to_flash", True))
    do_reset = bool(params.get("reset", True))

    from gcs.rtk_tools.f9p_config_all import _build_key_table  # noqa: PLC0415

    configurator, target = _make_configurator(params, "base")
    lat, lon, alt = _base_llh(params)
    ctx.log("BASE TMODE3 座標設定 → %s (lat=%.7f lon=%.7f alt=%.1f)" % (target, lat, lon, alt))
    ok = configurator.write_base_tmode3(lat, lon, alt, save)
    if ok and do_reset:
        ctx.log("リセット送信（3 秒待機）...")
        configurator.send_reset()
        time.sleep(3)
    v = configurator.verify_role("base", _build_key_table(lat, lon, alt))
    ctx.log("verify: ok=%s fail=%s warn=%s" % (v.get("ok_count"), v.get("fail_count"), v.get("warn_count")))
    all_ok = ok and bool(v.get("all_verified"))
    ctx.progress(100.0, "PASS" if all_ok else "FAIL")
    return {"all_ok": all_ok, "tmode3_write": ok, "verify": _verify_summary(v)}


def _serial_connect(params: Dict[str, Any], default_baud: int):
    """pyserial を開いて返す（ポート自動検出対応）。"""
    import serial  # noqa: PLC0415

    port = params.get("serial_port") or detect_serial_port()
    if not port:
        raise RuntimeError("シリアルポートを検出できません。serial_port を指定してください。")
    baud = int(params.get("baudrate") or default_baud)
    ser = serial.Serial(port, baud, timeout=1.0)
    time.sleep(0.3)
    return ser, port, baud


def _op_rtcm_rate_set(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from pyubx2 import UBXMessage  # noqa: PLC0415

    rate_hz = float(params.get("rate_hz", 1.0))
    if rate_hz <= 0:
        raise ValueError("rate_hz は正の値で指定してください。")
    save = bool(params.get("save", False))
    layers = 7 if save else 1
    target_ms = int(round(1000.0 / rate_hz))

    ser, port, baud = _serial_connect(params, 38400)
    ctx.log("RTCM レート変更 → %s @ %d bps (rate=%.2f Hz, ms=%d)" % (port, baud, rate_hz, target_ms))
    try:
        cur = _read_cfg(ser, ["CFG_RATE_MEAS", "CFG_RATE_NAV"])
        ctx.log("現在値: CFG_RATE_MEAS=%s CFG_RATE_NAV=%s" % (cur.get("CFG_RATE_MEAS"), cur.get("CFG_RATE_NAV")))
        ser.write(UBXMessage.config_set(layers, 0, [("CFG_RATE_MEAS", target_ms)]).serialize())
        ser.flush()
        time.sleep(0.3)
        after = _read_cfg(ser, ["CFG_RATE_MEAS"])
        new_ms = after.get("CFG_RATE_MEAS")
        verified = new_ms is not None and int(new_ms) == target_ms
        ctx.log("設定後: CFG_RATE_MEAS=%s → %s" % (new_ms, "OK" if verified else "NG"))
        ctx.progress(100.0, "PASS" if verified else "FAIL")
        return {"rate_hz": rate_hz, "target_ms": target_ms, "verified": verified}
    finally:
        ser.close()


def _op_glonass_toggle(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from pyubx2 import UBXMessage  # noqa: PLC0415

    enable = bool(params.get("enable", False))
    save = bool(params.get("save", False))
    layers = 7 if save else 1
    val = 1 if enable else 0

    keys = [
        "CFG_MSGOUT_RTCM_3X_TYPE1087_USB",
        "CFG_MSGOUT_RTCM_3X_TYPE1087_UART1",
        "CFG_MSGOUT_RTCM_3X_TYPE1230_USB",
        "CFG_MSGOUT_RTCM_3X_TYPE1230_UART1",
    ]
    ser, port, baud = _serial_connect(params, 38400)
    ctx.log("GLONASS RTCM 出力 %s → %s @ %d bps" % ("ON" if enable else "OFF", port, baud))
    try:
        ser.write(UBXMessage.config_set(layers, 0, [(k, val) for k in keys]).serialize())
        ser.flush()
        time.sleep(0.3)
        current = _read_cfg(ser, keys)
        verified = all(current.get(k) == val for k in keys)
        for k in keys:
            ctx.log("  %s = %s" % (k.split("TYPE")[-1], current.get(k)))
        ctx.progress(100.0, "PASS" if verified else "FAIL")
        return {"enabled": enable, "verified": verified}
    finally:
        ser.close()


def _read_cfg(ser, keys: List[str]) -> Dict[str, Any]:
    """CFG-VALGET で keys の現在値を読み取る（pyubx2）。"""
    from pyubx2 import UBXMessage, UBXReader  # noqa: PLC0415

    ser.reset_input_buffer()
    ser.write(UBXMessage.config_poll(0, 0, keys).serialize())
    ser.flush()
    result: Dict[str, Any] = {}
    deadline = time.time() + 2.0
    ubr = UBXReader(ser, protfilter=3)
    while time.time() < deadline:
        try:
            _raw, parsed = ubr.read()
            if parsed is not None and parsed.identity == "CFG-VALGET":
                for k in keys:
                    try:
                        result[k] = getattr(parsed, k)
                    except AttributeError:
                        result[k] = None
                return result
        except Exception:
            time.sleep(0.05)
    return result


# ==========================================================================
# 監視系・ロギング系: RTK FIX 時系列サンプリング（fix_metrics 正典を再利用）
# ==========================================================================
def _run_fix_sampling(ctx: JobContext, params: Dict[str, Any], write_csv: bool):
    """UbxPvtReader + fix_metrics で RTK FIX をサンプリングする共通処理。"""
    from gcs.fix_metrics import compute_metrics, fix_name, ubx_to_fix_type  # noqa: PLC0415
    from gcs.fix_type_logger import UbxPvtReader  # noqa: PLC0415

    duration = float(params.get("duration", 60.0))
    interval = float(params.get("interval", 1.0))
    port = params.get("serial_port") or detect_serial_port()
    if not port:
        raise RuntimeError("シリアルポートを検出できません。serial_port を指定してください。")
    baud = int(params.get("baudrate") or 115200)

    reader = UbxPvtReader(port, baud, poll_interval=interval)
    if not reader.start():
        raise RuntimeError("UBX シリアル接続に失敗しました: %s" % port)

    csv_writer = None
    csv_fh = None
    if write_csv:
        out = ensure_log_dir("logs") / ("gps_fix_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        csv_fh = open(out, "w", newline="")
        csv_writer = csv.writer(csv_fh)
        csv_writer.writerow(["elapsed_sec", "fix_type", "fix_name", "ubx_fix_type", "carr_soln", "diff_soln"])
        ctx.log("CSV 出力: %s" % out)

    samples: List[Dict[str, Any]] = []
    start = time.time()
    try:
        while time.time() - start < duration:
            if ctx.stop_requested():
                raise OperationStopped()
            latest = reader.latest()
            if latest.get("updated"):
                merged = ubx_to_fix_type(latest["fix_type"], latest["carr_soln"], latest["diff_soln"])
                t = time.time() - start
                samples.append({"t": t, "fix_type": merged})
                ctx.log(
                    "t=%5.1fs  %s  (ubx_fix=%s carr=%s diff=%s)"
                    % (t, fix_name(merged), latest["fix_type"], latest["carr_soln"], latest["diff_soln"])
                )
                if csv_writer is not None:
                    csv_writer.writerow([round(t, 1), merged, fix_name(merged),
                                         latest["fix_type"], latest["carr_soln"], latest["diff_soln"]])
                    csv_fh.flush()
            ctx.progress(min(100.0, (time.time() - start) / duration * 100.0),
                         "サンプル %d 件" % len(samples))
            time.sleep(interval)
    finally:
        reader.close()
        if csv_fh is not None:
            csv_fh.close()

    metrics = compute_metrics(samples)
    ctx.log("集計: reached_fixed=%s fixed_rate=%.1f%% ttff=%s" % (
        metrics["reached_fixed"], metrics["fixed_rate_pct"],
        ("%.1fs" % metrics["ttff_sec"]) if metrics["ttff_sec"] is not None else "n/a"))
    return metrics


def _op_rtk_fix_monitor(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _run_fix_sampling(ctx, params, write_csv=False)
    ctx.progress(100.0, "PASS" if metrics["reached_fixed"] else "FAIL")
    return {"metrics": metrics}


def _op_gps_fix_log(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _run_fix_sampling(ctx, params, write_csv=True)
    ctx.progress(100.0, "DONE")
    return {"metrics": metrics}


# ==========================================================================
# 監視系: 基地局 RTCM ストリーム検証（rtcm_monitor 正典を再利用）
# ==========================================================================
def _op_rtcm_verify_tcp(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtcm_monitor import Rtcm3StreamParser, rtcm3_frame_msg_type  # noqa: PLC0415

    host = params.get("host") or "127.0.0.1"
    port = int(params.get("port") or 2101)
    duration = float(params.get("duration", 30.0))

    key_types = [1005, 1006, 1074, 1084, 1094, 1124, 1230]
    counter: Dict[int, int] = {}
    errors: List[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((host, port))
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        ctx.log("TCP 接続失敗 %s:%d: %s" % (host, port, e))
        raise RuntimeError("TCP 接続失敗 %s:%d: %s" % (host, port, e))
    sock.settimeout(1.0)

    parser = Rtcm3StreamParser(verify_crc=True)
    total = 0
    start = time.time()
    ctx.log("RTCM ストリーム検証 → %s:%d (%ss)" % (host, port, duration))
    try:
        while time.time() - start < duration:
            if ctx.stop_requested():
                raise OperationStopped()
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                ctx.progress(min(100.0, (time.time() - start) / duration * 100.0), "frames=%d" % total)
                continue
            except OSError as e:
                errors.append(str(e))
                break
            if not chunk:
                break
            for frame in parser.feed(chunk):
                mt = rtcm3_frame_msg_type(frame)
                if mt < 0:
                    continue
                counter[mt] = counter.get(mt, 0) + 1
                total += 1
            ctx.progress(min(100.0, (time.time() - start) / duration * 100.0), "frames=%d" % total)
    finally:
        sock.close()

    missing = [mt for mt in key_types if mt not in counter]
    ctx.log("total=%d  types=%s" % (total, dict(counter)))
    ctx.log("missing key types: %s" % missing)
    ok = total > 0 and len(missing) == 0
    ctx.progress(100.0, "PASS" if ok else "FAIL")
    return {
        "ok": ok,
        "total_frames": total,
        "type_counter": {str(mt): counter.get(mt, 0) for mt in key_types},
        "all_types": {str(k): v for k, v in counter.items()},
        "missing_types": missing,
        "errors": errors,
    }


def _op_rtcm_rover_monitor(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtcm_monitor import CorrectionMonitor  # noqa: PLC0415

    source = params.get("source", "serial")
    duration = float(params.get("duration", 60.0))
    cfg = load_gcs_config()["monitor"]
    mon = CorrectionMonitor(
        age_alert_threshold=float(cfg["age_alert_threshold"]),
        age_warn_threshold=float(cfg["age_warn_threshold"]),
        crc_alert_rate_pct=float(cfg["crc_alert_rate_pct"]),
        used_alert_ratio_pct=float(cfg["used_alert_ratio_pct"]),
    )

    sock = None
    ser = None
    if source == "tcp":
        host = params.get("host") or "127.0.0.1"
        port = int(params.get("port") or 2101)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        try:
            sock.connect((host, port))
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            raise RuntimeError("TCP 接続失敗 %s:%d: %s" % (host, port, e))
        sock.settimeout(1.0)
        ctx.log("RTCM 監視（TCP %s:%d）" % (host, port))
    else:
        import serial  # noqa: PLC0415

        port = params.get("serial_port") or detect_serial_port()
        if not port:
            raise RuntimeError("シリアルポートを検出できません。")
        baud = int(params.get("baudrate") or 115200)
        ser = serial.Serial(port, baud, timeout=1.0)
        ctx.log("RTCM 監視（UBX %s @ %d bps）" % (port, baud))

    start = time.time()
    last_snap = None
    try:
        while time.time() - start < duration:
            if ctx.stop_requested():
                raise OperationStopped()
            try:
                if source == "tcp":
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    mon.feed_rtcm3(chunk)
                else:
                    data = ser.read(4096)
                    if data:
                        mon.feed_ubx(data)
            except socket.timeout:
                pass
            snap = mon.snapshot()
            last_snap = snap
            ctx.progress(min(100.0, (time.time() - start) / duration * 100.0),
                         "age_state=%s" % snap["rtk_age"]["state"])
            time.sleep(1.0)
    finally:
        if sock is not None:
            sock.close()
        if ser is not None:
            ser.close()

    if last_snap is None:
        last_snap = mon.snapshot()
    ctx.log(mon.format_summary())
    ctx.progress(100.0, "DONE")
    return {"snapshot": last_snap}


# ==========================================================================
# ロギング系: RTCM 生フレーム記録（rtcm_monitor 正典を再利用）
# ==========================================================================
def _op_rtcm_logger(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtcm_monitor import Rtcm3StreamParser  # noqa: PLC0415

    host = params.get("host") or "127.0.0.1"
    port = int(params.get("port") or 2101)
    duration = float(params.get("duration", 60.0))

    out = ensure_log_dir("logs") / ("rtcm_%s.rtcm3" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    f = open(out, "wb")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((host, port))
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        f.close()
        raise RuntimeError("TCP 接続失敗 %s:%d: %s" % (host, port, e))
    sock.settimeout(1.0)

    parser = Rtcm3StreamParser(verify_crc=True)
    total = 0
    start = time.time()
    ctx.log("RTCM 生ログ → %s:%d → %s" % (host, port, out))
    try:
        while time.time() - start < duration:
            if ctx.stop_requested():
                raise OperationStopped()
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            for frame in parser.feed(chunk):
                f.write(frame)
                total += 1
            ctx.progress(min(100.0, (time.time() - start) / duration * 100.0), "frames=%d" % total)
    finally:
        f.close()
        sock.close()
    ctx.progress(100.0, "DONE")
    return {"frames": total, "path": str(out)}


# ==========================================================================
# ロギング系: PPK（RAWX/SFRBX）ロガー（raspberrypi/ppk_logger.py を subprocess 実行）
# ==========================================================================
def _run_subprocess(ctx: JobContext, cmd: List[str], cwd: str):
    """subprocess を起動し、stdout/stderr をジョブログへ流す。停止要求で terminate。"""
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    def _pump():
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line:
                ctx.log(line)

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    while True:
        if ctx.stop_requested():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            ctx.log("[STOP] subprocess terminated")
            raise OperationStopped()
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.wait()
    t.join(timeout=2)
    return proc.returncode


def _op_ppk_logger(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    port = params.get("serial_port") or detect_serial_port()
    if not port:
        raise RuntimeError("シリアルポートを検出できません。serial_port を指定してください。")
    baud = int(params.get("baudrate") or 38400)
    duration = int(float(params.get("duration", 0)))  # 0 = 無制限
    out = params.get("out") or str(ensure_log_dir("logs") / "ppk")

    script = str(project_root() / "raspberrypi" / "ppk_logger.py")
    cmd = ["python3", script, "--port", port, "--baud", str(baud), "--duration", str(duration), "--out", out]
    ctx.log("PPK ロガー起動: %s" % " ".join(cmd))
    rc = _run_subprocess(ctx, cmd, cwd=str(project_root()))
    ctx.progress(100.0, "PASS" if rc == 0 else "FAIL")
    return {"exit_code": rc, "out": out}


# ==========================================================================
# 基地局/注入系: サービス起動（stop 要求まで RUNNING を維持）
# ==========================================================================
def _run_service(ctx: JobContext, start_fn, stop_fn, status_fn):
    """start_fn をスレッドで起動し、stop 要求まで待つ。停止時は stop_fn を呼ぶ。"""
    thread = threading.Thread(target=start_fn, daemon=True)
    thread.start()
    try:
        while True:
            if ctx.stop_requested():
                break
            try:
                ctx.progress(None, status_fn())
            except Exception:
                pass
            time.sleep(1.0)
    finally:
        stop_fn()
        thread.join(timeout=3)
    raise OperationStopped()


def _op_forwarder_start(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtk_tools.rtk_forwarder_service import (  # noqa: PLC0415
        RtcmForwarderService, load_config, _resolve_config_path,
    )

    config = load_config(_resolve_config_path(params.get("config") or "rtk_forwarder.yml"))
    service = RtcmForwarderService(config)
    ctx.log("RTK フォワーダー起動: source=%s forward=%s"
            % (config.source.source_type, config.forward.forward_type))
    _run_service(
        ctx,
        start_fn=service.run_forever,
        stop_fn=service.stop,
        status_fn=lambda: "packets=%d bytes=%d" % (service.total_packets, service.total_bytes),
    )
    return {}


def _op_tcp2serial_start(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtk_tools.tcp2serial import Tcp2SerialBridge, load_bridge_config, _resolve_config_path  # noqa: PLC0415

    cfg = load_bridge_config(_resolve_config_path(params.get("config") or "tcp2serial.yml"))
    bridge = Tcp2SerialBridge(
        bind_host=cfg.get("bind_host", "0.0.0.0"),
        bind_port=int(cfg.get("bind_port", 2102)),
        serial_device=cfg.get("serial_device", "/dev/ttyAMA4"),
        baudrate=int(cfg.get("baudrate", 115200)),
        health_timeout_sec=float(cfg.get("health_timeout_sec", 30.0)),
        tcp_timeout_sec=float(cfg.get("tcp_timeout_sec", 5.0)),
        serial_timeout_sec=float(cfg.get("serial_timeout_sec", 1.0)),
        stats_interval_sec=float(cfg.get("stats_interval_sec", 60.0)),
    )
    ctx.log("tcp2serial 起動: tcp=%s:%d → %s" % (bridge.bind_host, bridge.bind_port, bridge.serial_device))
    _run_service(
        ctx,
        start_fn=bridge.run_forever,
        stop_fn=bridge.stop,
        status_fn=lambda: "packets=%d bytes=%d conn=%d"
                         % (bridge.stats.total_packets, bridge.stats.total_bytes, bridge.stats.connections),
    )
    return {}


def _op_base_station_start(ctx: JobContext, params: Dict[str, Any]) -> Dict[str, Any]:
    from gcs.rtk_tools.rtk_base_station_v2 import Config, RtkBaseStation  # noqa: PLC0415

    from gcs.app.operations.util import load_json_file  # noqa: PLC0415

    cfg_path = params.get("config") or "config/base_station.json"
    try:
        data = load_json_file(cfg_path)
    except FileNotFoundError:
        data = {}
    cfg = Config()
    for k in ("serial_port", "baudrate", "f9p_baudrate", "mode", "fixed_lat", "fixed_lon",
              "fixed_alt", "save_to_flash", "skip_f9p_config", "tcp_host", "tcp_port",
              "enable_udp", "udp_broadcast_host", "udp_broadcast_port", "log_level", "log_file"):
        if k in data:
            setattr(cfg, k, data[k])
    if params.get("skip_f9p_config"):
        cfg.skip_f9p_config = True

    station = RtkBaseStation(cfg)
    ctx.log("RTK 基地局 v2 起動: serial=%s tcp=%s:%d mode=%s"
            % (cfg.serial_port, cfg.tcp_host, cfg.tcp_port, cfg.mode))
    _run_service(
        ctx,
        start_fn=station.start,
        stop_fn=station.stop,
        status_fn=lambda: "serial_frames=%d tcp_clients=%d"
                         % (station.serial_reader.stats.get("frames_received", 0),
                            len(station.tcp_server.stats.get("clients", []))),
    )
    return {}


# ==========================================================================
# 操作カタログ定義
# ==========================================================================
# 分類: 設定系 / 監視系 / ロギング系 / 基地局・注入系
# （制御系は gcs/app/api/routes.py の既存 /api/* エンドポイントが担当）
OPERATIONS: List[Dict[str, Any]] = [
    {
        "id": "f9p_write_verify", "category": "設定系",
        "label": "F9P 設定 write-verify", "dangerous": True, "mode": "job",
        "description": "基地局12キー+移動局18キーの write-verify（Flash 書き込み＋リセット＋検証）",
        "params": [
            _p("role", "対象", options=["base", "rover"], default="base"),
            *_transport_params(),
            _p("lat", "緯度（base）", type="float", default=None),
            _p("lon", "経度（base）", type="float", default=None),
            _p("alt", "楕円体高[m]（base）", type="float", default=None),
            _SAVE_P,
        ],
        "handler": _op_f9p_write_verify,
    },
    {
        "id": "f9p_verify", "category": "設定系",
        "label": "F9P 設定検証（読み取り）", "dangerous": False, "mode": "job",
        "description": "全キーの現在値を CFG-VALGET で読み取り、Golden 値と照合（書き込みなし）",
        "params": [
            _p("role", "対象", options=["base", "rover"], default="base"),
            *_transport_params(),
            _p("lat", "緯度（base）", type="float", default=None),
            _p("lon", "経度（base）", type="float", default=None),
            _p("alt", "楕円体高[m]（base）", type="float", default=None),
        ],
        "handler": _op_f9p_verify,
    },
    {
        "id": "base_tmode3_set", "category": "設定系",
        "label": "基地局座標・TMODE3 設定", "dangerous": True, "mode": "job",
        "description": "基地局 F9P の固定座標を上書きし TMODE3 Fixed Mode を設定",
        "params": [
            *_transport_params(),
            _p("lat", "緯度", type="float", default=None),
            _p("lon", "経度", type="float", default=None),
            _p("alt", "楕円体高[m]", type="float", default=None),
            _SAVE_P,
            _p("reset", "リセット実行", type="bool", default=True),
        ],
        "handler": _op_base_tmode3_set,
    },
    {
        "id": "rtcm_rate_set", "category": "設定系",
        "label": "RTCM 出力レート変更", "dangerous": True, "mode": "job",
        "description": "基地局 F9P の CFG-RATE-MEAS を変更して全 RTCM 出力レートを変える",
        "params": [
            _SERIAL_P, _BAUD_P,
            _p("rate_hz", "レート [Hz]", type="float", default=1.0),
            _p("save", "Flash 保存", type="bool", default=False),
        ],
        "handler": _op_rtcm_rate_set,
    },
    {
        "id": "glonass_toggle", "category": "設定系",
        "label": "GLONASS 出力 切替", "dangerous": True, "mode": "job",
        "description": "基地局 F9P の GLONASS RTCM（1087/1230）出力を一時 ON/OFF",
        "params": [
            _SERIAL_P, _BAUD_P,
            _p("enable", "GLONASS 出力を ON にする", type="bool", default=False),
            _p("save", "Flash 保存", type="bool", default=False),
        ],
        "handler": _op_glonass_toggle,
    },
    {
        "id": "rtk_fix_monitor", "category": "監視系",
        "label": "RTK FIX 監視", "dangerous": False, "mode": "job",
        "description": "UBX-NAV-PVT をポーリングし FIXED 維持率・TTFF・遷移を定量判定（fix_metrics 正典）",
        "params": [
            _SERIAL_P, _BAUD_P, _DURATION_P,
            _p("interval", "サンプリング間隔[秒]", type="float", default=1.0),
        ],
        "handler": _op_rtk_fix_monitor,
    },
    {
        "id": "rtcm_verify_tcp", "category": "監視系",
        "label": "基地局 RTCM ストリーム検証", "dangerous": False, "mode": "job",
        "description": "基地局 TCP ストリームの RTCM3 メッセージタイプ（1005/1077/1230 等）を検証",
        "params": [
            _p("host", "ホスト", default="127.0.0.1"),
            _p("port", "ポート", type="int", default=2101),
            _p("duration", "実行秒数", type="float", default=30.0),
        ],
        "handler": _op_rtcm_verify_tcp,
    },
    {
        "id": "rtcm_rover_monitor", "category": "監視系",
        "label": "RTCM 到達・CRC・age 監視", "dangerous": False, "mode": "job",
        "description": "CorrectionMonitor で RTK age・CRC エラー率・msgUsed 比率・アラートを監視",
        "params": [
            _p("source", "入力", options=["serial", "tcp"], default="serial"),
            _SERIAL_P, _p("host", "ホスト", default="127.0.0.1"),
            _p("port", "ポート", type="int", default=2101),
            _BAUD_P, _DURATION_P,
        ],
        "handler": _op_rtcm_rover_monitor,
    },
    {
        "id": "ppk_logger", "category": "ロギング系",
        "label": "PPK ログ（RAWX/SFRBX）", "dangerous": False, "mode": "job",
        "description": "F9P から UBX-RXM-RAWX/SFRBX を CSV に記録（後処理 RTK 用）",
        "params": [
            _SERIAL_P, _p("baudrate", "ボーレート", type="int", default=38400),
            _p("duration", "実行秒数（0=無制限）", type="float", default=0),
            _p("out", "出力ディレクトリ", default=None),
        ],
        "handler": _op_ppk_logger,
    },
    {
        "id": "rtcm_logger", "category": "ロギング系",
        "label": "RTCM 生ログ", "dangerous": False, "mode": "job",
        "description": "基地局 TCP ストリームの RTCM3 フレームを .rtcm3 に記録",
        "params": [
            _p("host", "ホスト", default="127.0.0.1"),
            _p("port", "ポート", type="int", default=2101),
            _p("duration", "実行秒数", type="float", default=60.0),
        ],
        "handler": _op_rtcm_logger,
    },
    {
        "id": "gps_fix_log", "category": "ロギング系",
        "label": "GPS / RTK FIX ログ", "dangerous": False, "mode": "job",
        "description": "fix_type 時系列を CSV に記録し、FIXED 維持率等を集計",
        "params": [
            _SERIAL_P, _BAUD_P, _DURATION_P,
            _p("interval", "サンプリング間隔[秒]", type="float", default=1.0),
        ],
        "handler": _op_gps_fix_log,
    },
    {
        "id": "forwarder_start", "category": "基地局・注入系",
        "label": "RTCM 注入・中継（forwarder）", "dangerous": False, "mode": "service",
        "description": "rtk_forwarder_service を起動（tcp/ntrip/serial → serial/udp）。停止で終了",
        "params": [_p("config", "設定ファイル", default="rtk_forwarder.yml")],
        "handler": _op_forwarder_start,
    },
    {
        "id": "tcp2serial_start", "category": "基地局・注入系",
        "label": "TCP→シリアル注入（tcp2serial）", "dangerous": False, "mode": "service",
        "description": "tcp2serial を起動（TCP で受けた RTCM3 を F9P UART2 へ注入）。停止で終了",
        "params": [_p("config", "設定ファイル", default="tcp2serial.yml")],
        "handler": _op_tcp2serial_start,
    },
    {
        "id": "base_station_start", "category": "基地局・注入系",
        "label": "基地局サービス起動（v2）", "dangerous": True, "mode": "service",
        "description": "rtk_base_station_v2 を起動（F9P 設定 + TCP:2101 配信 + UDP 任意）。停止で終了",
        "params": [
            _p("config", "設定ファイル", default="config/base_station.json"),
            _p("skip_f9p_config", "F9P 設定をスキップ", type="bool", default=False),
        ],
        "handler": _op_base_station_start,
    },
]


def register_operations(manager) -> None:
    """OperationManager に全操作を登録する。"""
    for meta in OPERATIONS:
        manager.register(
            meta["id"],
            meta["handler"],
            category=meta["category"],
            label=meta["label"],
            description=meta.get("description", ""),
            params=meta.get("params", []),
            dangerous=meta.get("dangerous", False),
            mode=meta.get("mode", "job"),
        )
