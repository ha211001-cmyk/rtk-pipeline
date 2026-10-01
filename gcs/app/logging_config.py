"""gcs.app.logging_config — ロギング設定（GCS-UmemotoLab app/logging_config.py 由来）。

コンソール + ローテーティングファイル（``logs/gcs.log``）へ DEBUG ログを出力する。
ログ出力先ディレクトリは ``setup_logging(log_dir=...)`` または環境変数
``GCS_LOG_DIR`` で変更できる。
"""

from __future__ import annotations

import logging
import logging.config
import os

_DEFAULT_LOG_DIR = "logs"


def build_logging_config(log_dir: str | None = None) -> dict:
    """dictConfig 用のロギング設定 dict を構築する。"""
    log_dir = log_dir or os.environ.get("GCS_LOG_DIR", _DEFAULT_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
            },
        },
        "handlers": {
            "console": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "standard",
            },
            "file": {
                "level": "DEBUG",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(log_dir, "gcs.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "formatter": "standard",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
        },
    }


def setup_logging(log_dir: str | None = None) -> None:
    """dictConfig でロギングを初期化する。"""
    logging.config.dictConfig(build_logging_config(log_dir))

