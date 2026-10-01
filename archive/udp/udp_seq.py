#!/usr/bin/env python3
"""UDP ペイロード連番ヘッダ（パケットロス検出用）

RTCM バイト列は一切変更せず、UDP ペイロードの先頭に 8 バイトのヘッダを
付与して欠落を検出する。ヘッダは RTCM3 プリアンブル (0xD3) と衝突しない
マジックで始めるため、受信側は自動判別できる。

ヘッダ構成 (8 bytes):
  [0:4]  マジック b"UDP1" (0x55 0x44 0x50 0x31)
  [4:8]  シーケンス番号 (uint32 big-endian、0 始まりで巡回)

受信側は data[0:4] == MAGIC なら「連番ヘッダ付き」と判定し、[4:8] の
連番から欠落（ギャップ）を検出する。ヘッダなし（旧形式・生 RTCM）も
そのまま受け付けるため、既存プロトコルを壊さない。
"""

MAGIC = b"UDP1"
HEADER_LEN = 8


def pack_seq_payload(seq: int, rtcm_frame: bytes) -> bytes:
    """連番ヘッダ + RTCM フレームの UDP ペイロードを組み立てる。

    RTCM フレーム（バイト列）はそのまま後ろに連結するだけ。
    """
    return MAGIC + (seq & 0xFFFFFFFF).to_bytes(4, "big") + rtcm_frame


def unpack_seq_payload(data):
    """UDP 受信データを解析する。

    Returns:
        (is_seq_packet, seq, rtcm_payload)
        - is_seq_packet=True : seq は連番、rtcm_payload は RTCM バイト列
        - is_seq_packet=False: seq=None、rtcm_payload は data そのまま
    """
    if len(data) >= HEADER_LEN and data[:4] == MAGIC:
        seq = int.from_bytes(data[4:8], "big")
        return True, seq, data[HEADER_LEN:]
    return False, None, data


class SeqLossTracker:
    """連番から UDP 欠落（ロス）を検出するトラッカー。

    期待連番との差分を数えることで、受信パケット数と欠落数を分離集計する。
    """

    def __init__(self):
        self.packets_received = 0
        self.packets_lost = 0
        self._last_seq = None

    def update(self, seq: int) -> None:
        """受信した連番を記録し、欠落を検出する。"""
        self.packets_received += 1
        if self._last_seq is None:
            self._last_seq = seq
            return
        delta = (seq - self._last_seq) & 0xFFFFFFFF
        if delta == 0:
            # 同一連番（重複）はロスと数えない
            self._last_seq = seq
            return
        if 1 < delta < 0x80000000:
            # 途中 delta-1 個が欠落（0x80000000 超は再起動等による異常ジャンプ）
            self.packets_lost += delta - 1
        self._last_seq = seq

    @property
    def packets_expected(self) -> int:
        """送信されたはずの総数 = 受信 + 欠落。"""
        return self.packets_received + self.packets_lost

    @property
    def loss_rate(self) -> float:
        """欠落率（0.0〜1.0）。expected が 0 なら 0.0。"""
        exp = self.packets_expected
        if exp == 0:
            return 0.0
        return self.packets_lost / exp
