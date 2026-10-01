#!/usr/bin/env python3
"""fix_monitor_lite.py — Fix 監視の軽量実装（★判定の正典は gcs/fix_metrics.py）。

GCS-UmemotoLab の ``rtk_tools/gcs_fix_monitor.py``（REST ポーリング + carrSoln
マッピング）は統合対象外。RTK Fix 判定の正典は ``gcs/fix_metrics.py``
（``fix_name`` / ``ubx_to_fix_type`` / ``compute_metrics``）である。

本モジュールは、その正典を再利用して「GCS REST API をポーリングし RTK_FIXED 到達
を待つ」最小のユーティリティを提供する（``f9p_config_all --mode full`` の Phase 8
で利用）。判定そのものは ``fix_metrics.fix_name()`` に委譲しており、fix_type の
重複マッピングを持たない。
"""

from __future__ import annotations

import time
from typing import Optional

try:
    from gcs.fix_metrics import fix_name, FIXED
except ImportError:  # 単体実行時のフォールバック
    from fix_metrics import fix_name, FIXED  # type: ignore

try:
    import requests
except ImportError:  # requests が無い環境でも import 自体は成立させる
    requests = None  # type: ignore


def fetch_fix_type(gcs_url: str, system_id: int = 1, timeout: float = 5.0) -> Optional[int]:
    """GCS REST API (/api/drones) から対象ドローンの fix_type を取得する。"""
    if requests is None:
        raise RuntimeError("requests ライブラリが必要です")
    try:
        resp = requests.get(f"{gcs_url.rstrip('/')}/api/drones", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    drones = data.get("drones", [])
    if not isinstance(drones, list):
        drones = []
    for drone in drones:
        if drone.get("system_id") == system_id:
            return drone.get("gps_fix")
    return None


def wait_for_rtk_fixed(gcs_url: str, system_id: int = 1,
                       timeout: float = 120.0, poll_interval: float = 1.0) -> bool:
    """GCS API をポーリングし fix_type=6（RTK_FIXED）到達を待つ。

    判定は ``gcs.fix_metrics`` の ``FIXED`` 定数・``fix_name`` を正典として利用する。
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        fix_type = fetch_fix_type(gcs_url, system_id=system_id)
        if fix_type == FIXED:
            return True
        if fix_type is not None:
            print(f"  t={time.monotonic() - start:5.1f}s  fix_type={fix_type}"
                  f"({fix_name(fix_type)})")
        time.sleep(poll_interval)
    return False


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="RTK FIXED wait (fix_metrics canonical)")
    parser.add_argument("--gcs-url", default="http://localhost:8000")
    parser.add_argument("--system-id", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    sys.exit(0 if wait_for_rtk_fixed(args.gcs_url, args.system_id, args.timeout) else 1)
