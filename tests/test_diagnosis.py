# -*- coding: utf-8 -*-
"""app/diagnosis.py 单元测试：DiagnosisEngine.diagnose 的 P0/P1/P2/正常分级。

分级规则以 app/diagnosis.py 实际代码为准：
- P0：告警名含退服关键字 / 可用率 < 10 / RRC 请求 > 50 且成功为 0
- P1：容量（RRC>400 或 PRB 下行 > 80% 等）/ 载波噪声 > -110dBm（或无噪声列时 RSSI > -110）
      / 下行速率 < 2Mbps 且流量 > 0.5GB
- P2：掉线率 > 3% / 接通率 < 90% / 切换成功率 < 90% 等
- 正常：以上均不触发。优先级 P0 > P1 > P2。

全部数据均为人工构造的假数据。
"""

import pandas as pd
import pytest

from app.diagnosis import DiagnosisEngine


def _row(**overrides):
    """一行健康基线小区：各项指标均在正常范围内。"""
    base = {
        "cell_name": "测试小区-1",
        "site_name": "测试站",
        "cgi": "460001234567890",
        "alarm_name": "",
        "alarm_cause": "",
        "availability": 99.8,
        "rrc_conn_max": 120,
        "rrc_conn_avg": 60,
        "prb_dl_util": 35.0,
        "prb_ul_util": 20.0,
        "rrc_congestion_count": 0,
        "carrier_noise": -118.0,
        "ul_rssi": -115.0,
        "dl_user_speed": 25.0,
        "traffic_gb": 1.2,
        "drop_rate": 0.5,
        "volte_drop_rate": 0.3,
        "setup_success_rate": 99.5,
        "volte_setup_rate": 99.0,
        "handover_success_rate": 98.0,
        "rsrp_coverage_rate": 96.0,
        "cqi_good_rate": 92.0,
        "ta_avg_distance": 800,
        "rrc_setup_req": 1000,
        "rrc_setup_succ": 990,
    }
    base.update(overrides)
    return base


def _diagnose(rows):
    return DiagnosisEngine.diagnose(pd.DataFrame(rows))


class TestNormal:
    def test_healthy_cell_is_normal(self):
        df = _diagnose([_row()])
        assert df.loc[0, "diag_level"] == "正常"
        assert df.loc[0, "diag_type"] == "运行平稳"


class TestP0:
    def test_outage_alarm_keyword(self):
        """告警名含“不可用”-> P0 退服断站。"""
        df = _diagnose([_row(alarm_name="小区不可用")])
        assert df.loc[0, "diag_level"] == "P0"
        assert df.loc[0, "diag_type"] == "退服断站"

    def test_outage_alarm_keyword_sctp(self):
        df = _diagnose([_row(alarm_name="SCTP链路故障")])
        assert df.loc[0, "diag_level"] == "P0"

    def test_availability_collapse(self):
        """可用率 < 10% -> P0（无告警时也触发）。"""
        df = _diagnose([_row(availability=5.0)])
        assert df.loc[0, "diag_level"] == "P0"
        assert df.loc[0, "diag_type"] == "退服断站"

    def test_rrc_all_blocked(self):
        """RRC 请求 > 50 且成功为 0 -> P0 入网全阻断。"""
        df = _diagnose([_row(rrc_setup_req=100, rrc_setup_succ=0)])
        assert df.loc[0, "diag_level"] == "P0"


class TestP1:
    def test_rrc_overload(self):
        df = _diagnose([_row(rrc_conn_max=500)])
        assert df.loc[0, "diag_level"] == "P1"
        assert df.loc[0, "diag_type"] == "容量超限"

    def test_prb_dl_overload(self):
        df = _diagnose([_row(prb_dl_util=85.0)])
        assert df.loc[0, "diag_level"] == "P1"

    def test_prb_ul_overload(self):
        df = _diagnose([_row(prb_ul_util=80.0)])
        assert df.loc[0, "diag_level"] == "P1"

    def test_strong_interference_by_carrier_noise(self):
        """载波噪声 -105dBm（> -110 门限）-> P1 上行干扰。"""
        df = _diagnose([_row(carrier_noise=-105.0)])
        assert df.loc[0, "diag_level"] == "P1"
        assert df.loc[0, "diag_type"] == "上行干扰"

    def test_ul_rssi_used_only_when_no_carrier_noise_column(self):
        """无 carrier_noise 列时才以 ul_rssi 判定干扰。"""
        row = _row(ul_rssi=-105.0)
        del row["carrier_noise"]
        df = _diagnose([row])
        assert df.loc[0, "diag_level"] == "P1"
        assert df.loc[0, "diag_type"] == "上行干扰"

    def test_carrier_noise_takes_precedence_over_rssi(self):
        """有 carrier_noise 列时只看它：噪声 -115（正常）+ RSSI -105 也不触发 P1。"""
        df = _diagnose([_row(carrier_noise=-115.0, ul_rssi=-105.0)])
        assert df.loc[0, "diag_level"] == "正常"

    def test_low_user_speed_with_traffic(self):
        """下行速率 < 2Mbps 且流量 > 0.5GB -> P1 感知劣化。"""
        df = _diagnose([_row(dl_user_speed=1.5, traffic_gb=1.0)])
        assert df.loc[0, "diag_level"] == "P1"
        assert df.loc[0, "diag_type"] == "感知劣化"

    def test_low_speed_without_traffic_is_not_p1(self):
        df = _diagnose([_row(dl_user_speed=1.5, traffic_gb=0.1)])
        assert df.loc[0, "diag_level"] == "正常"


class TestP2:
    def test_high_drop_rate(self):
        df = _diagnose([_row(drop_rate=5.0)])
        assert df.loc[0, "diag_level"] == "P2"
        assert df.loc[0, "diag_type"] == "语音数据质差"

    def test_low_handover_rate(self):
        df = _diagnose([_row(handover_success_rate=85.0)])
        assert df.loc[0, "diag_level"] == "P2"

    def test_low_setup_rate(self):
        df = _diagnose([_row(setup_success_rate=88.0)])
        assert df.loc[0, "diag_level"] == "P2"

    def test_low_coverage_rate(self):
        df = _diagnose([_row(rsrp_coverage_rate=80.0)])
        assert df.loc[0, "diag_level"] == "P2"


class TestPriority:
    def test_p0_beats_p1(self):
        """同时触发 P0（退服告警）和 P1（RRC 过载）-> 取 P0。"""
        df = _diagnose([_row(alarm_name="小区不可用", rrc_conn_max=500)])
        assert df.loc[0, "diag_level"] == "P0"

    def test_p1_beats_p2(self):
        """同时触发 P1（PRB 过载）和 P2（掉线率高）-> 取 P1。"""
        df = _diagnose([_row(prb_dl_util=85.0, drop_rate=5.0)])
        assert df.loc[0, "diag_level"] == "P1"


class TestSummary:
    def test_mixed_summary_counts(self):
        rows = [
            _row(cell_name="小区-P0", alarm_name="小区不可用"),
            _row(cell_name="小区-P1", rrc_conn_max=500),
            _row(cell_name="小区-P2", drop_rate=5.0),
            _row(cell_name="小区-正常"),
        ]
        diagnosed = _diagnose(rows)
        summary = DiagnosisEngine.get_summary(diagnosed)
        assert summary["total_cells"] == 4
        assert summary["p0_count"] == 1
        assert summary["p1_count"] == 1
        assert summary["p2_count"] == 1
        assert summary["normal_count"] == 1
        assert summary["health_score"] == 25.0
        assert "退服" in summary["overall_status"]
        assert len(summary["p0_cells"]) == 1
        assert summary["p0_cells"][0]["cell_name"] == "小区-P0"

    def test_empty_summary(self):
        diagnosed = DiagnosisEngine.diagnose(pd.DataFrame())
        summary = DiagnosisEngine.get_summary(diagnosed)
        assert summary["total_cells"] == 0
        assert summary["health_score"] == 100.0
        assert summary["overall_status"] == "保障区域网络运行良好"
