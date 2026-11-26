# -*- coding: utf-8 -*-
"""
异常分析与智能诊断规则引擎 - classifies cells by P0/P1/P2 severity levels.

Applies a priority-ordered rule set to a merged cell+alarm+KPI DataFrame,
producing diagnostic columns (level, type, detail, suggestion) and a summary.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class DiagnosisEngine:
    """Rule-based diagnosis engine for LTE/NR wireless assurance."""

    # Keywords that indicate a site-level outage alarm
    _P0_ALARM_KEYWORDS: List[str] = [
        "退出服务", "退服", "不可用", "断站", "掉电", "电源断", "供电",
        "链路断", "链路故障", "SCTP", "NG接口", "S1", "光口", "光模块",
        "传输中断", "基站断电", "站点失联", "失联", "脱网",
    ]

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def diagnose(cls, merged_df: pd.DataFrame) -> pd.DataFrame:
        """Apply diagnosis rules and add diagnostic columns.

        Added columns:
          - ``diag_level``:  P0 / P1 / P2 / 正常
          - ``diag_type``:   退服断站 / 容量超限 / 上行干扰 / 语音数据质差 / 运行平稳
          - ``diag_detail``: Human-readable description of the triggered rule.
          - ``diag_suggestion``: Remediation suggestion text.

        Rules are evaluated in priority order; a cell receives the *highest*
        severity that matches.
        """
        df = merged_df.copy()

        # Pre-convert numeric columns that may still be strings
        numeric_cols = [
            "rrc_conn_max", "rrc_conn_avg", "traffic_gb", "volte_traffic", "prb_dl_util", "prb_ul_util",
            "setup_success_rate", "drop_rate", "volte_setup_rate", "volte_drop_rate",
            "handover_success_rate", "handover_in_success_rate", "ul_rssi", "carrier_noise",
            "rsrp_coverage_rate", "cqi_good_rate", "dl_user_speed", "ul_user_speed",
            "tcp_rtt_ms", "ta_avg_distance", "rrc_congestion_count", "availability",
            "rrc_setup_req", "rrc_setup_succ", "rrc_setup_fail", "erab_setup_succ", "erab_setup_req",
            "max_user", "dl_throughput", "ul_throughput",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        levels: List[str] = []
        types: List[str] = []
        details: List[str] = []
        suggestions: List[str] = []

        for _, row in df.iterrows():
            level, dtype, detail, suggestion = cls._evaluate_row(row)
            levels.append(level)
            types.append(dtype)
            details.append(detail)
            suggestions.append(suggestion)

        df["diag_level"] = levels
        df["diag_type"] = types
        df["diag_detail"] = details
        df["diag_suggestion"] = suggestions

        return df

    @classmethod
    def get_summary(cls, diagnosed_df: pd.DataFrame) -> Dict[str, Any]:
        """Return an aggregated summary of the diagnosis results.

        Returns
        -------
        dict
            Keys: total_cells, p0_count, p1_count, p2_count, normal_count,
            p0_cells, p1_cells, p2_cells, health_score,
            total_traffic_gb, total_volte_erl, max_rrc_conn, avg_prb_dl, avg_setup_rate.
        """
        df = diagnosed_df.copy()
        total = len(df)

        p0_mask = df["diag_level"] == "P0"
        p1_mask = df["diag_level"] == "P1"
        p2_mask = df["diag_level"] == "P2"
        normal_mask = df["diag_level"] == "正常"

        p0_count = int(p0_mask.sum())
        p1_count = int(p1_mask.sum())
        p2_count = int(p2_mask.sum())
        normal_count = int(normal_mask.sum())

        health_score = round(normal_count / total * 100, 2) if total > 0 else 100.0

        # 保障区域宏观性能聚合统计
        traffic_s = pd.to_numeric(df["traffic_gb"], errors="coerce").fillna(0) if "traffic_gb" in df.columns else pd.Series([0.0])
        total_traffic_gb = round(float(traffic_s.sum()), 2)

        volte_s = pd.to_numeric(df["volte_traffic"], errors="coerce").fillna(0) if "volte_traffic" in df.columns else pd.Series([0.0])
        total_volte_erl = round(float(volte_s.sum()), 2)

        rrc_s = pd.to_numeric(df["rrc_conn_max"], errors="coerce").fillna(0) if "rrc_conn_max" in df.columns else pd.Series([0])
        max_rrc = int(rrc_s.max()) if not rrc_s.empty else 0

        avg_prb_val = pd.to_numeric(df["prb_dl_util"], errors="coerce").dropna() if "prb_dl_util" in df.columns else pd.Series(dtype=float)
        avg_prb = round(float(avg_prb_val.mean()), 1) if not avg_prb_val.empty else 0.0

        avg_setup_val = pd.to_numeric(df["setup_success_rate"], errors="coerce").dropna() if "setup_success_rate" in df.columns else pd.Series(dtype=float)
        avg_setup = round(float(avg_setup_val.mean()), 1) if not avg_setup_val.empty else 100.0

        avg_drop_val = pd.to_numeric(df["drop_rate"], errors="coerce").dropna() if "drop_rate" in df.columns else pd.Series(dtype=float)
        avg_drop = round(float(avg_drop_val.mean()), 2) if not avg_drop_val.empty else 0.0

        # 统一输出字段集合
        all_metrics_fields = [
            "cell_name", "site_name", "diag_level", "diag_type", "diag_detail",
            "traffic_gb", "volte_traffic", "rrc_conn_max", "prb_dl_util",
            "setup_success_rate", "drop_rate", "carrier_noise", "ul_rssi", "rsrp_coverage_rate", "cqi_good_rate",
            "start_time", "end_time", "alarm_name", "alarm_level", "alarm_cause", "alarm_count",
        ]

        p0_cells = cls._extract_cell_dicts(df.loc[p0_mask], all_metrics_fields)
        p1_cells = cls._extract_cell_dicts(df.loc[p1_mask], all_metrics_fields)
        p2_cells = cls._extract_cell_dicts(df.loc[p2_mask], all_metrics_fields)

        overall_status = "存在紧急退服告警，需优先处置" if p0_count > 0 else (
            "存在高危拥塞/干扰隐患" if p1_count > 0 else (
                "部分小区性能质差需关注" if p2_count > 0 else "保障区域网络运行良好"
            )
        )

        return {
            "total_cells": total,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "p2_count": p2_count,
            "normal_count": normal_count,
            "p0_cells": p0_cells,
            "p1_cells": p1_cells,
            "p2_cells": p2_cells,
            "health_score": health_score,
            "overall_status": overall_status,
            "total_traffic_gb": total_traffic_gb,
            "total_volte_erl": total_volte_erl,
            "max_rrc_conn": max_rrc,
            "avg_prb_dl": avg_prb,
            "avg_setup_rate": avg_setup,
            "avg_drop_rate": avg_drop,
        }

    # ------------------------------------------------------------------ #
    #  Internal rule evaluation                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    def _evaluate_row(cls, row: pd.Series) -> tuple:
        """Evaluate a single row and return (level, type, detail, suggestion)."""

        # ---- P0: 基站退服/断站/瘫痪 ------------------------------------- #
        alarm_name = cls._safe_str(row, "alarm_name")
        alarm_cause = cls._safe_str(row, "alarm_cause")

        if alarm_name:
            for kw in cls._P0_ALARM_KEYWORDS:
                if kw in alarm_name:
                    desc = f"告警触发: [{alarm_name}]"
                    if alarm_cause:
                        desc += f" (原因: {alarm_cause[:80]})"
                    return ("P0", "退服断站", desc, "")

        if alarm_cause:
            for kw in ["市电异常", "光口通信异常", "外部供电", "电源断"]:
                if kw in alarm_cause:
                    return ("P0", "退服断站", f"告警原因触发: [{kw}] (告警: {alarm_name or '未知'})", "")

        avail = cls._safe_num(row, "availability")
        if avail is not None and avail < 10:
            return ("P0", "退服断站", f"可用率瘫痪: 小区可用率仅 {avail:.1f}%", "")

        rrc_req = cls._safe_num(row, "rrc_setup_req")
        rrc_succ = cls._safe_num(row, "rrc_setup_succ")
        if rrc_req is not None and rrc_req > 50 and (rrc_succ is not None and rrc_succ == 0):
            return ("P0", "退服断站", f"入网全阻断: 请求{rrc_req:.0f}次全部失败", "")

        # ---- P1: 容量超限/重度拥塞/强干扰 --------------------------------- #
        rrc_max = cls._safe_num(row, "rrc_conn_max")
        rrc_avg = cls._safe_num(row, "rrc_conn_avg")
        prb_dl = cls._safe_num(row, "prb_dl_util")
        prb_ul = cls._safe_num(row, "prb_ul_util")
        rrc_cong = cls._safe_num(row, "rrc_congestion_count")

        capacity_triggers: List[str] = []
        if rrc_max is not None and rrc_max > 400:
            capacity_triggers.append(f"最大RRC连接数={rrc_max:.0f}")
        elif rrc_avg is not None and rrc_avg > 200:
            capacity_triggers.append(f"平均RRC连接数={rrc_avg:.0f}")
        if prb_dl is not None and prb_dl > 70:
            capacity_triggers.append(f"下行PRB利用率={prb_dl:.1f}%")
        if prb_ul is not None and prb_ul > 70:
            capacity_triggers.append(f"上行PRB利用率={prb_ul:.1f}%")
        if rrc_cong is not None and rrc_cong > 0:
            capacity_triggers.append(f"RRC拥塞拒绝={rrc_cong:.0f}次")

        if capacity_triggers:
            return ("P1", "容量超限", "容量触发: " + ", ".join(capacity_triggers), "")

        # P1: 上行强干扰 (按用户要求：以载波平均噪声干扰(dBm)为准，且大于-110才视为是有干扰)
        noise = cls._safe_num(row, "carrier_noise")
        if noise is not None:
            if noise > -110:
                return ("P1", "上行干扰", f"干扰触发: 载波平均噪声干扰={noise:.1f}dBm (高于-110dBm门限)", "")
        else:
            ul_rssi = cls._safe_num(row, "ul_rssi")
            if ul_rssi is not None and ul_rssi > -110:
                return ("P1", "上行干扰", f"干扰触发: 上行RSSI={ul_rssi:.1f}dBm (高于-110dBm门限)", "")

        # P1: 感知速率极低
        dl_speed = cls._safe_num(row, "dl_user_speed")
        traffic = cls._safe_num(row, "traffic_gb")
        if dl_speed is not None and dl_speed < 2.0 and traffic is not None and traffic > 0.5:
            return ("P1", "感知劣化", f"速率拥塞: 下行感知速率={dl_speed:.2f}Mbps (低于2Mbps)", "")

        # ---- P2: 质差恶化/弱覆盖/切换异常 --------------------------------- #
        ho_rate = cls._safe_num(row, "handover_success_rate")
        drop = cls._safe_num(row, "drop_rate")
        volte_drop = cls._safe_num(row, "volte_drop_rate")
        setup_rate = cls._safe_num(row, "setup_success_rate")
        volte_setup = cls._safe_num(row, "volte_setup_rate")
        rsrp_cov = cls._safe_num(row, "rsrp_coverage_rate")
        cqi_good = cls._safe_num(row, "cqi_good_rate")
        ta_dist = cls._safe_num(row, "ta_avg_distance")

        quality_triggers: List[str] = []
        if drop is not None and drop > 3:
            quality_triggers.append(f"掉线率={drop:.2f}%")
        if volte_drop is not None and volte_drop > 2:
            quality_triggers.append(f"VoLTE掉话率={volte_drop:.2f}%")
        if setup_rate is not None and setup_rate < 90:
            quality_triggers.append(f"接通率={setup_rate:.1f}%")
        if volte_setup is not None and volte_setup < 90:
            quality_triggers.append(f"VoLTE接通率={volte_setup:.1f}%")
        if ho_rate is not None and ho_rate < 90:
            quality_triggers.append(f"切换成功率={ho_rate:.1f}%")
        if rsrp_cov is not None and rsrp_cov < 90:
            quality_triggers.append(f"良好覆盖率={rsrp_cov:.1f}%")
        if cqi_good is not None and cqi_good < 85:
            quality_triggers.append(f"CQI优良率={cqi_good:.1f}%")
        if ta_dist is not None and ta_dist > 1500:
            quality_triggers.append(f"TA接入距离={ta_dist:.0f}m")

        if quality_triggers:
            return ("P2", "语音数据质差", "质差触发: " + ", ".join(quality_triggers), "")

        # ---- 正常 ------------------------------------------------------- #
        return (
            "正常",
            "运行平稳",
            "各项指标在正常基线范围内",
            "",
        )

    # ------------------------------------------------------------------ #
    #  Utility helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_str(row: pd.Series, col: str) -> Optional[str]:
        """Return the string value for *col*, or ``None`` if missing / NaN."""
        if col not in row.index:
            return None
        val = row[col]
        if pd.isna(val):
            return None
        s = str(val).strip()
        return s if s else None

    @staticmethod
    def _safe_num(row: pd.Series, col: str) -> Optional[float]:
        """Return the numeric value for *col*, or ``None`` if missing / NaN."""
        if col not in row.index:
            return None
        val = row[col]
        if pd.isna(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_cell_dicts(
        sub_df: pd.DataFrame,
        fields: List[str],
    ) -> List[Dict[str, Any]]:
        """Extract a list of dicts from *sub_df*, replacing NaN with None."""
        records: List[Dict[str, Any]] = []
        for _, row in sub_df.iterrows():
            rec: Dict[str, Any] = {}
            for f in fields:
                if f in row.index:
                    val = row[f]
                    rec[f] = None if pd.isna(val) else val
                else:
                    rec[f] = None
            records.append(rec)
        return records
