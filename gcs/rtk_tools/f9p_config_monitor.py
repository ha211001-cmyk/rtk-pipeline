#!/usr/bin/env python3
"""
f9p_config_monitor.py — F9P 設定値 継続的差分監視ツール

f9p_config_all.py の verify モードを活用し、F9P の設定値が意図せず
変わっていないかを定期的にチェックする。

動作:
  1. 初回: 全設定キーを verify → ベースライン JSON として保存
  2. 定期監視: --interval 秒ごとに verify を再実行
  3. 差分検出: ベースラインと現在値を比較し、変化があれば警告

Usage:
  # 基地局の設定監視（60秒間隔）
  python rtk_tools/f9p_config_monitor.py --role base --port /dev/tty.usbmodemXXX

  # 移動局の設定監視（30秒間隔）
  python rtk_tools/f9p_config_monitor.py --role rover --port /dev/ttyAMA4 --interval 30

  # 単発チェック
  python rtk_tools/f9p_config_monitor.py --role base --port /dev/tty.usbmodemXXX --once

  # ベースラインをリセット（現在値を新しい基準にする）
  python rtk_tools/f9p_config_monitor.py --role rover --port /dev/ttyAMA4 --reset-baseline

  # JSON 出力
  python rtk_tools/f9p_config_monitor.py --role base --port /dev/tty.usbmodemXXX --once --json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from gcs.rtk_tools.f9p_config_all import (
        F9pAllConfigurator,
        _build_key_table,
        _get_keys_by_role,
        _ICON_OK,
        _ICON_FAIL,
        _ICON_WARN,
    )
except ImportError:  # 単体実行時（PYTHONPATH 未設定）のフォールバック
    from f9p_config_all import (  # type: ignore
        F9pAllConfigurator,
        _build_key_table,
        _get_keys_by_role,
        _ICON_OK,
        _ICON_FAIL,
        _ICON_WARN,
    )

# ==========================================================================
# Constants
# ==========================================================================

_DEFAULT_INTERVAL = 60          # デフォルト監視間隔（秒）
_BASELINE_DIR = "logs"          # ベースライン保存ディレクトリ

# 変化を検出したときに無視するキー（例: 動的に変化しうる値）
_IGNORE_CHANGE_KEYS: set = set()  # 例: {"CFG-RATE-MEAS", "CFG-RATE-NAV"}


# ==========================================================================
# Baseline helpers
# ==========================================================================


def _sanitize_port(port: str) -> str:
    """Convert a device path like /dev/tty.usbmodem114301 to a safe filename slug."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", port.strip("/"))


def _baseline_path(role: str, port: str, custom_dir: Optional[str] = None) -> str:
    """Generate the baseline file path for a given role + port."""
    base_dir = custom_dir or _BASELINE_DIR
    slug = _sanitize_port(port)
    filename = f"f9p_config_baseline_{role}_{slug}.json"
    return os.path.join(base_dir, filename)


def _load_baseline(path: str) -> Optional[dict]:
    """Load baseline JSON file. Returns None if not found or corrupt."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "keys" in data:
            return data
        return None
    except (json.JSONDecodeError, OSError) as e:
        logging.getLogger("f9p_config_monitor").warning(
            f"Failed to load baseline {path}: {e}"
        )
        return None


def _save_baseline(path: str, verify_result: dict, port: str, role: str) -> None:
    """Save a verify result as a baseline JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    keys_map: Dict[str, dict] = {}
    for check in verify_result.get("checks", []):
        key_name = check.get("key", "")
        keys_map[key_name] = {
            "id": check.get("id"),
            "key": key_name,
            "description": check.get("description", ""),
            "expected": check.get("expected"),
            "actual": check.get("actual"),
            "status": check.get("status"),
        }

    baseline = {
        "role": role,
        "port": port,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "saved_at_local": datetime.now().isoformat(),
        "device_alive": verify_result.get("device_alive", False),
        "all_verified": verify_result.get("all_verified", False),
        "ok_count": verify_result.get("ok_count", 0),
        "fail_count": verify_result.get("fail_count", 0),
        "warn_count": verify_result.get("warn_count", 0),
        "keys": keys_map,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)

    logging.getLogger("f9p_config_monitor").info(
        f"Baseline saved: {path} ({len(keys_map)} keys)")

# ==========================================================================
# Diff engine
# ==========================================================================


def _diff_against_baseline(
    current_verify: dict,
    baseline: dict,
) -> dict:
    """Compare current verify result against baseline.

    Returns a diff summary dict with:
      - role, port, timestamp
      - changed: list of keys where actual value differs from baseline
      - missing: keys present in baseline but not in current
      - new: keys present in current but not in baseline
      - unchanged_count: count of matching keys
      - has_changes: bool
      - warnings: human-readable warning messages
    """
    baseline_keys: Dict[str, dict] = baseline.get("keys", {})
    current_checks: List[dict] = current_verify.get("checks", [])

    current_keys: Dict[str, dict] = {}
    for c in current_checks:
        current_keys[c.get("key", "")] = c

    changed: List[dict] = []
    missing: List[dict] = []
    unchanged_count = 0
    warnings: List[str] = []

    all_baseline_key_names = set(baseline_keys.keys())
    all_current_key_names = set(current_keys.keys())

    for key_name in sorted(all_baseline_key_names & all_current_key_names):
        if key_name in _IGNORE_CHANGE_KEYS:
            unchanged_count += 1
            continue

        bl_val = baseline_keys[key_name].get("actual")
        cur_check = current_keys[key_name]
        cur_val = cur_check.get("actual")
        cur_status = cur_check.get("status", "fail")

        if cur_val != bl_val or cur_status != "ok":
            entry = {
                "key": key_name,
                "description": cur_check.get("description", ""),
                "baseline_actual": bl_val,
                "current_actual": cur_val,
                "baseline_status": baseline_keys[key_name].get("status"),
                "current_status": cur_status,
            }
            changed.append(entry)
            msg = (
                f"[CHANGED] {key_name}: "
                f"baseline={bl_val!r} -> current={cur_val!r}"
            )
            warnings.append(msg)
        else:
            unchanged_count += 1

    for key_name in sorted(all_baseline_key_names - all_current_key_names):
        entry = {
            "key": key_name,
            "description": baseline_keys[key_name].get("description", ""),
            "baseline_actual": baseline_keys[key_name].get("actual"),
            "current_actual": "(missing)",
            "baseline_status": baseline_keys[key_name].get("status"),
            "current_status": "missing",
        }
        missing.append(entry)
        msg = (
            f"[MISSING] {key_name}: "
            f"was {baseline_keys[key_name].get('actual')!r}, now not in response"
        )
        warnings.append(msg)

    new_keys: List[dict] = []
    for key_name in sorted(all_current_key_names - all_baseline_key_names):
        cur_check = current_keys[key_name]
        entry = {
            "key": key_name,
            "description": cur_check.get("description", ""),
            "baseline_actual": "(not in baseline)",
            "current_actual": cur_check.get("actual"),
            "baseline_status": "n/a",
            "current_status": cur_check.get("status", "?"),
        }
        new_keys.append(entry)
        msg = (
            f"[NEW] {key_name}: "
            f"not in baseline, current={cur_check.get('actual')!r}"
        )
        warnings.append(msg)

    has_changes = bool(changed or missing or new_keys)

    return {
        "role": current_verify.get("role", baseline.get("role", "?")),
        "port": current_verify.get("port", baseline.get("port", "?")),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "timestamp_local": datetime.now().isoformat(),
        "device_alive": current_verify.get("device_alive", False),
        "changed": changed,
        "missing": missing,
        "new": new_keys,
        "unchanged_count": unchanged_count,
        "total_keys_current": len(current_keys),
        "total_keys_baseline": len(baseline_keys),
        "has_changes": has_changes,
        "warnings": warnings,
    }



# ==========================================================================
# Display helpers
# ==========================================================================


def _print_diff_summary(diff: dict, check_number: int, is_first: bool) -> None:
    """Print a human-readable diff summary to stdout."""
    ts = diff.get("timestamp_local", "?")
    role = diff.get("role", "?").upper()
    alive = "YES" if diff.get("device_alive") else "NO"

    if is_first:
        print()
        print("=" * 70)
        print(f"  F9P Config Monitor — {role}")
        print(f"  Port: {diff.get('port', '?')}")
        print("=" * 70)

    print()
    print(f"--- Check #{check_number}  [{ts}] ---")
    print(f"  Device alive: {alive}")
    print(f"  Keys unchanged: {diff['unchanged_count']}")

    changed = diff.get("changed", [])
    missing = diff.get("missing", [])
    new_keys = diff.get("new", [])

    if not diff.get("has_changes"):
        print(f"  {_ICON_OK} No changes detected — all keys match baseline.")
        return

    print(f"  {_ICON_WARN} CONFIG CHANGES DETECTED!")
    print(f"  Changed: {len(changed)} key(s)")
    print(f"  Missing: {len(missing)} key(s)")
    print(f"  New:     {len(new_keys)} key(s)")

    if changed:
        print()
        print(f"  {_ICON_FAIL} Changed keys:")
        for entry in changed:
            print(f"    - {entry['key']}")
            print(f"        Baseline: {entry['baseline_actual']!r}")
            print(f"        Current:  {entry['current_actual']!r}")

    if missing:
        print()
        print(f"  {_ICON_WARN} Missing keys (in baseline but not in current):")
        for entry in missing:
            print(f"    - {entry['key']}  (was: {entry['baseline_actual']!r})")

    if new_keys:
        print()
        print(f"  {_ICON_WARN} New keys (not in baseline):")
        for entry in new_keys:
            print(f"    - {entry['key']}  (current: {entry['current_actual']!r})")



# ==========================================================================
# Core monitor class
# ==========================================================================


class F9pConfigMonitor:
    """F9P 設定値の継続的監視を行う。

    f9p_config_all.F9pAllConfigurator の verify モードを使い、
    定期的に全設定キーをポーリングしてベースラインと比較する。
    """

    def __init__(
        self,
        role: str,
        port: str,
        baudrate: int = 38400,
        baseline_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.role = role
        self.port = port
        self.baudrate = baudrate
        self.logger = logger or logging.getLogger("F9pConfigMonitor")
        self._baseline_path = baseline_path or _baseline_path(role, port)
        self._configurator = F9pAllConfigurator(
            serial_port=port, baudrate=baudrate, logger=self.logger,
            port_type="both"
        )

    @property
    def baseline_path(self) -> str:
        return self._baseline_path

    def has_baseline(self) -> bool:
        return os.path.exists(self._baseline_path)

    def load_baseline(self) -> Optional[dict]:
        return _load_baseline(self._baseline_path)

    def save_baseline(self, verify_result: dict) -> None:
        _save_baseline(self._baseline_path, verify_result, self.port, self.role)

    def reset_baseline(self, lat: float = 0, lon: float = 0, alt: float = 0) -> dict:
        """Run verify and save as new baseline."""
        self.logger.info(f"Resetting baseline for {self.role} on {self.port}")
        key_table = _build_key_table(lat, lon, alt)
        verify_result = self._configurator.verify_role(self.role, key_table)
        self.save_baseline(verify_result)
        return verify_result

    def run_verify(self, lat: float = 0, lon: float = 0, alt: float = 0) -> dict:
        """Run a single verify pass."""
        key_table = _build_key_table(lat, lon, alt)
        return self._configurator.verify_role(self.role, key_table)

    def check_once(
        self, lat: float = 0, lon: float = 0, alt: float = 0
    ) -> dict:
        """Run verify and diff against baseline (or create baseline if none)."""
        verify_result = self.run_verify(lat, lon, alt)
        baseline = self.load_baseline()

        result: Dict[str, Any] = {
            "verify": verify_result,
            "baseline_loaded": baseline is not None,
        }

        if baseline is None:
            self.save_baseline(verify_result)
            result["baseline_created"] = True
            result["diff"] = None
            self.logger.info(
                f"No baseline found; created new baseline with "
                f"{verify_result.get('ok_count', 0)} keys."
            )
        else:
            diff = _diff_against_baseline(verify_result, baseline)
            result["diff"] = diff
            result["baseline_created"] = False

            if diff.get("has_changes"):
                self.logger.warning(
                    f"Config changes detected! "
                    f"changed={len(diff.get('changed', []))}, "
                    f"missing={len(diff.get('missing', []))}, "
                    f"new={len(diff.get('new', []))}"
                )

        return result

    def monitor_loop(
        self,
        interval: float = _DEFAULT_INTERVAL,
        max_checks: Optional[int] = None,
        lat: float = 0,
        lon: float = 0,
        alt: float = 0,
    ) -> None:
        """Run continuous monitoring loop."""
        self.logger.info(
            f"Starting monitor loop: {self.role} on {self.port} "
            f"(interval={interval}s)"
        )

        check_number = 0
        first_print = True

        while max_checks is None or check_number < max_checks:
            check_number += 1
            self.logger.debug(f"Check #{check_number} starting...")

            try:
                result = self.check_once(lat, lon, alt)
            except Exception as e:
                self.logger.error(f"Check #{check_number} failed: {e}")
                time.sleep(interval)
                continue

            diff = result.get("diff")

            if result.get("baseline_created"):
                print()
                print("=" * 70)
                print(f"  F9P Config Monitor — {self.role.upper()}")
                print(f"  Port: {self.port}")
                print("=" * 70)
                print(f"  {_ICON_OK} Baseline created successfully.")
                verify = result["verify"]
                print(f"  Keys verified: {verify.get('ok_count', 0)} OK, "
                      f"{verify.get('fail_count', 0)} FAIL, "
                      f"{verify.get('warn_count', 0)} WARN")
                print("  Starting monitoring...")
                first_print = False
            elif diff is not None:
                _print_diff_summary(diff, check_number, first_print)
                first_print = False

            if max_checks is not None and check_number >= max_checks:
                break

            time.sleep(interval)

        self.logger.info(
            f"Monitor loop ended after {check_number} check(s)."
        )



# ==========================================================================
# CLI Entry Point
# ==========================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="F9P 設定値 継続的差分監視ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --role base --port /dev/tty.usbmodem114301\n"
            "  %(prog)s --role rover --port /dev/ttyAMA4 --interval 30\n"
            "  %(prog)s --role base --port /dev/tty.usbmodemXXX --once --json\n"
            "  %(prog)s --role rover --port /dev/ttyAMA4 --reset-baseline\n"
            "  %(prog)s --role both --base-port /dev/tty.X --rover-port /dev/tty.Y --once\n"
        ),
    )
    parser.add_argument("--role", required=True,
                        choices=["base", "rover", "both"],
                        help="Target role (基地局=base, 移動局=rover, 両方=both)")
    parser.add_argument("--port", default=None, help="Serial port (single role)")
    parser.add_argument("--base-port", default="/dev/tty.usbmodem114301",
                        help="Base port (--role both)")
    parser.add_argument("--rover-port", default="/dev/ttyAMA4",
                        help="Rover port (--role both)")
    parser.add_argument("--baud", type=int, default=None,
                        help="Baudrate (single; defaults: base=38400 rover=115200)")
    parser.add_argument("--base-baud", type=int, default=38400,
                        help="Base baudrate (default: 38400)")
    parser.add_argument("--rover-baud", type=int, default=115200,
                        help="Rover baudrate (default: 115200)")
    parser.add_argument("--interval", type=float, default=_DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {_DEFAULT_INTERVAL})")
    parser.add_argument("--once", action="store_true",
                        help="Single check only (no continuous loop)")
    parser.add_argument("--max-checks", type=int, default=None,
                        help="Max number of checks before exiting (default: unlimited)")
    parser.add_argument("--reset-baseline", action="store_true",
                        help="Reset baseline to current values before monitoring")
    parser.add_argument("--baseline-dir", default=None,
                        help="Custom directory for baseline files (default: logs/)")
    parser.add_argument("--lat", type=float, default=35.1234567,
                        help="Base latitude (default: 35.1234567)")
    parser.add_argument("--lon", type=float, default=139.1234567,
                        help="Base longitude (default: 139.1234567)")
    parser.add_argument("--alt", type=float, default=100.0,
                        help="Base altitude in meters (default: 100.0)")
    parser.add_argument("--json", action="store_true",
                        help="Output diff as JSON (single check mode)")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: WARNING)")


    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("f9p_config_monitor")

    base_baud = args.base_baud
    rover_baud = args.rover_baud
    if args.baud is not None:
        if args.role == "base":
            base_baud = args.baud
        elif args.role == "rover":
            rover_baud = args.baud

    roles_to_monitor: List[Tuple[str, str, int]] = []
    if args.role in ("base", "both"):
        port = args.port if args.role == "base" else args.base_port
        roles_to_monitor.append(("base", port, base_baud))
    if args.role in ("rover", "both"):
        port = args.port if args.role == "rover" else args.rover_port
        roles_to_monitor.append(("rover", port, rover_baud))

    if not roles_to_monitor:
        print("Error: No roles to monitor.", file=sys.stderr)
        return 1

    def _make_monitor(role: str, port: str, baud: int) -> F9pConfigMonitor:
        bp = _baseline_path(role, port, args.baseline_dir)
        return F9pConfigMonitor(
            role=role, port=port, baudrate=baud,
            baseline_path=bp, logger=logger,
        )

    # -- Once mode (single check) --
    if args.once:
        all_results: Dict[str, Any] = {}
        exit_code = 0

        for role, port, baud in roles_to_monitor:
            monitor = _make_monitor(role, port, baud)

            if args.reset_baseline:
                verify = monitor.reset_baseline(args.lat, args.lon, args.alt)
                all_results[role] = {
                    "baseline_reset": True,
                    "verify": {
                        "device_alive": verify.get("device_alive"),
                        "all_verified": verify.get("all_verified"),
                        "ok_count": verify.get("ok_count"),
                        "fail_count": verify.get("fail_count"),
                        "warn_count": verify.get("warn_count"),
                    },
                }
                continue

            result = monitor.check_once(args.lat, args.lon, args.alt)
            all_results[role] = result

            if result.get("diff") and result["diff"].get("has_changes"):
                exit_code = 1

        if args.json:
            output = {}
            for role, r in all_results.items():
                if r.get("baseline_reset"):
                    output[role] = r
                else:
                    output[role] = {
                        "baseline_created": r.get("baseline_created"),
                        "baseline_loaded": r.get("baseline_loaded"),
                        "device_alive": r["verify"].get("device_alive"),
                        "all_verified": r["verify"].get("all_verified"),
                        "diff": r.get("diff"),
                    }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            for role, r in all_results.items():
                if r.get("baseline_reset"):
                    v = r["verify"]
                    print()
                    print("=" * 70)
                    print(f"  F9P Config Monitor — {role.upper()}")
                    print("=" * 70)
                    print(f"  {_ICON_OK} Baseline reset successfully.")
                    print(f"  Keys verified: {v.get('ok_count', 0)} OK, "
                          f"{v.get('fail_count', 0)} FAIL, "
                          f"{v.get('warn_count', 0)} WARN")
                elif r.get("baseline_created"):
                    print()
                    print("=" * 70)
                    print(f"  F9P Config Monitor — {role.upper()}")
                    print("=" * 70)
                    print(f"  {_ICON_OK} Baseline created (first run).")
                    v = r["verify"]
                    print(f"  Keys verified: {v.get('ok_count', 0)} OK, "
                          f"{v.get('fail_count', 0)} FAIL, "
                          f"{v.get('warn_count', 0)} WARN")
                elif r.get("diff"):
                    _print_diff_summary(r["diff"], 1, True)
                    diff = r["diff"]
                    icon = _ICON_OK if not diff.get("has_changes") else _ICON_WARN
                    print(f"  {icon} Overall: "
                          f"{'NO CHANGES' if not diff.get('has_changes') else 'CHANGES DETECTED'}")

        return exit_code

    # -- Continuous monitoring mode --
    if args.role == "both" and len(roles_to_monitor) == 2:
        print("Error: Continuous monitoring with --role both is not supported.",
              file=sys.stderr)
        print("Run two separate instances for base and rover.", file=sys.stderr)
        return 1

    role, port, baud = roles_to_monitor[0]
    monitor = _make_monitor(role, port, baud)

    if args.reset_baseline:
        monitor.reset_baseline(args.lat, args.lon, args.alt)
        print(f"  {_ICON_OK} Baseline reset successfully for {role.upper()}.")
        print(f"  Port: {port}")

    try:
        monitor.monitor_loop(
            interval=args.interval,
            max_checks=args.max_checks,
            lat=args.lat,
            lon=args.lon,
            alt=args.alt,
        )
    except KeyboardInterrupt:
        print()
        print("Monitoring stopped by user.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
