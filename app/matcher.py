# -*- coding: utf-8 -*-
"""
多源数据匹配引擎 - matches alarm and KPI data to base parameter cells.

Provides fuzzy column-name resolution (Chinese/English aliases),
CGI normalisation, and a two-pass join strategy (CGI → site_id+cell_id fallback).
"""

import io
import re
from typing import Dict, List, Optional, Union

import pandas as pd


class DataMatcher:
    """Match alarm / KPI data to the base-parameter cell table."""

    # ------------------------------------------------------------------ #
    #  Column alias mappings                                              #
    # ------------------------------------------------------------------ #

    ALARM_COLUMN_ALIASES: Dict[str, List[str]] = {
        "cell_name": ["告警对象名称", "AU", "小区名称", "小区中文名", "CELL_NAME", "Cell Name", "小区名"],
        "cgi": ["CGI", "ECGI", "NCGI", "E-CGI", "N-CGI", "全球小区标识"],
        "cell_id": ["小区编号", "小区ID", "Cell ID", "CellID", "CELL_ID", "本地小区标识"],
        "site_id": ["基站编号", "基站ID", "eNodeB ID", "eNodeBID", "gNB ID", "ENODEB_ID", "GNB_ID"],
        "site_name": ["网元", "网元名称", "基站名称", "ME", "基站", "ME_NAME"],
        "alarm_name": ["告警码名称", "告警名称", "告警标题", "Alarm Name", "ALARM_NAME", "告警描述", "告警内容"],
        "alarm_level": ["告警级别", "严重程度", "Alarm Level", "ALARM_LEVEL", "告警等级"],
        "alarm_cause": ["告警原因", "根因", "故障原因", "Alarm Cause", "ALARM_CAUSE", "可能原因"],
        "start_time": ["发生时间", "告警开始时间", "Start Time", "START_TIME", "产生时间", "首次发生时间"],
    }

    KPI_COLUMN_ALIASES: Dict[str, List[str]] = {
        "cell_name": [
            "小区名称", "DU物理小区名称", "NR物理小区名称", "5G物理小区名称",
            "DU小区名称", "NR小区名称", "5G小区名称", "CELL_NAME", "小区中文名", "小区名", "Cell Name",
        ],
        "site_id": [
            "duMeMoId", "gNodeBId", "gNBId", "eNodeBId", "ENBFunctionID",
            "网元ID", "基站编号", "基站ID", "eNodeB ID", "eNodeBID", "gNB ID", "ENODEB_ID", "GNB_ID",
        ],
        "cell_id": [
            "cellId", "DU物理小区ID", "nrPhysicalCellDUId", "NR物理小区ID",
            "小区ID", "小区编号", "Cell ID", "CellID", "CELL_ID",
        ],
        "site_name": ["管理网元", "ENBFunction名称", "网元名称", "基站名称", "ME_NAME", "网元"],
        "cgi": ["CGI", "ECGI", "NCGI", "全球小区标识"],
        "availability": ["小区的可用率(%)", "小区的可用率", "无线可用率", "小区可用率", "可用率", "AVAILABILITY", "Cell Availability"],
        "traffic_gb": [
            "空口4G业务量(上行+下行)GB-重庆", "空口4G业务量(上行+下行)GB",
            "RLC流量(DU)-重庆(GB)", "RLC流量(DU)(GB)", "RLC流量(GB)",
            "4G业务量(GB)", "5G业务量(GB)", "5G流量(GB)", "NR业务量(GB)",
            "总业务量(GB)", "总流量(GB)", "业务量(GB)",
        ],
        "traffic_ul_gb": [
            "空口上行业务量(GB)-重庆", "空口上行业务量(GB)", "上行业务量(GB)", "RLC上行流量(GB)",
        ],
        "traffic_dl_gb": [
            "空口下行业务量(GB)-重庆", "空口下行业务量(GB)", "下行业务量(GB)", "RLC下行流量(GB)",
        ],
        "volte_traffic": [
            "VoNR话务量(Erl)-重庆", "VoNR话务量(Erl)", "VoNR话务量", "5G话务量(Erl)",
            "VOLTE话务量(Erl)-重庆", "VOLTE话务量(Erl)", "VOLTE话务量", "话务量(Erl)",
        ],
        "prb_dl_util": [
            "小区下行PRB平均占用率(%)", "小区下行PRB平均占用率", "5G下行PRB利用率",
            "下行信道PRB资源利用率(%)", "下行信道PRB资源利用率", "下行PRB利用率", "PRB利用率(下行)", "下行PRB占用率",
            "DL PRB Usage", "DL_PRB_UTIL", "PRB_DL_UTIL", "下行PRB平均利用率",
        ],
        "prb_ul_util": [
            "小区上行PRB平均占用率(%)", "小区上行PRB平均占用率", "5G上行PRB利用率",
            "上行信道PRB资源利用率(%)", "上行信道PRB资源利用率", "上行PRB利用率", "PRB利用率(上行)", "上行PRB占用率",
            "UL PRB Usage", "UL_PRB_UTIL", "PRB_UL_UTIL",
        ],
        "rrc_conn_max": [
            "RRC连接最大连接用户数", "RRC最大连接用户数",
            "最大的RRC连接建立个数", "最大RRC连接数", "最大RRC用户数",
            "MAX_RRC_CONN", "RRC Connected Max", "最大连接用户数",
        ],
        "rrc_conn_avg": [
            "平均的RRC连接建立个数", "平均RRC连接数", "平均RRC用户数", "RRC平均连接用户数",
        ],
        "ul_rssi": [
            "小区平均RSSI(dBm)", "小区平均RSSI", "平均PRB干扰电平", "RSSI(dBm)",
            "UL RSSI", "UL_RSSI", "上行RSSI", "上行底噪", "上行干扰电平", "IOT",
            "小区上行平均干扰电平(dBm)", "小区上行平均干扰电平",
        ],
        "carrier_noise": [
            "载波平均噪声干扰(dBm)", "载波平均噪声干扰", "平均噪声干扰",
            "小区上行平均干扰电平(dBm)", "小区上行平均干扰电平",
        ],
        "setup_success_rate": [
            "无线接入成功率(%)", "无线接入成功率", "5G无线接通率", "5G接通率",
            "无线接通率(%)-重庆", "无线接通率(%)", "无线接通率", "接通率",
            "RRC建立成功率", "SETUP_SUCCESS_RATE", "RRC Setup Success Rate", "连接建立成功率",
        ],
        "drop_rate": [
            "UE上下文异常掉线率(质差)-重庆", "UE上下文异常掉线率", "5G掉线率", "5G掉话率", "NR掉线率",
            "无线掉线率(%)", "无线掉线率", "无线掉话率(%)", "无线掉话率", "掉线率", "DROP_RATE",
            "掉话率", "E-RAB掉线率", "异常释放率",
        ],
        "volte_setup_rate": [
            "VoNR语音接通率-重庆", "VoNR语音接通率", "VoNR接通率",
            "VOLTE无线接通率-重庆", "VOLTE无线接通率", "VOLTE接通率",
        ],
        "volte_drop_rate": [
            "VoNR语音掉话率-重庆", "VoNR语音掉话率", "VoNR掉话率",
            "VOLTE无线掉话率-重庆", "VOLTE无线掉话率", "VOLTE掉话率", "VOLTE掉线率",
        ],
        "handover_success_rate": [
            "切换出成功率(%)", "切换出成功率", "切换成功率", "HO Success Rate",
            "HO_SUCCESS_RATE", "切换成功率(%)",
        ],
        "handover_in_success_rate": [
            "系统内切换入成功率(%)", "系统内切换入成功率",
        ],
        "rsrp_coverage_rate": [
            "服务小区RSRP良好覆盖率(≥-110)-重庆", "服务小区RSRP良好覆盖率(≥-110)", "服务小区RSRP良好覆盖率", "RSRP良好覆盖率",
        ],
        "cqi_good_rate": [
            "CQI优良率-重庆", "CQI优良率",
        ],
        "dl_user_speed": [
            "小区级下行单用户平均感知速率-重庆", "小区级下行单用户平均感知速率", "下行感知速率",
            "下行吞吐率", "下行吞吐量", "DL Throughput", "DL_THROUGHPUT", "小区下行吞吐率",
        ],
        "ul_user_speed": [
            "小区级上行单用户平均感知速率-重庆", "小区级上行单用户平均感知速率", "上行感知速率",
            "上行吞吐率", "上行吞吐量", "UL Throughput", "UL_THROUGHPUT", "小区上行吞吐率",
        ],
        "tcp_rtt_ms": [
            "小区下行TCP采样报文RTT平均时延(毫秒)-重庆", "TCP时延(毫秒)", "TCP时延",
        ],
        "ta_avg_distance": [
            "TA平均接入距离-重庆", "TA平均接入距离", "TA接入距离",
        ],
        "ta_max_distance": [
            "TA最大接入距离-重庆", "TA最大接入距离",
        ],
        "rrc_congestion_count": [
            "RRC拥塞次数-重庆", "RRC拥塞次数",
        ],
        "rrc_setup_req": [
            "RRC建立请求数目", "RRC建立尝试次数", "RRC_SETUP_ATT", "RRC Setup Attempts",
        ],
        "rrc_setup_succ": [
            "RRC建立成功数目", "RRC建立成功次数",
        ],
        "rrc_setup_fail": [
            "RRC建立失败数目", "RRC建立失败次数",
        ],
        "erab_setup_succ": [
            "E-RAB建立成功数目",
        ],
        "erab_setup_req": [
            "E-RAB建立请求数目",
        ],
        "start_time": [
            "开始时间", "START_TIME", "StartTime", "开始时间(Start Time)",
            "采样时间", "时间", "TIME", "起始时间", "粒度开始时间",
        ],
        "end_time": ["结束时间", "END_TIME"],
        "granularity": ["粒度"],
    }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _standardize_columns(
        df: pd.DataFrame,
        aliases: Dict[str, List[str]],
    ) -> pd.DataFrame:
        """Rename columns using fuzzy alias matching.

        For every standard name → alias list pair, the *first* alias found
        among the DataFrame columns wins and is renamed to the standard name.
        Matching is case-insensitive and strips surrounding whitespace.
        """
        df = df.copy()
        # Build a lookup: lowered-and-stripped original col → actual col name
        col_lookup = {c.strip().lower(): c for c in df.columns}

        rename_map: Dict[str, str] = {}
        used_targets: set = set()

        for std_name, candidates in aliases.items():
            for candidate in candidates:
                key = candidate.strip().lower()
                if key in col_lookup:
                    original = col_lookup[key]
                    if original not in used_targets:
                        rename_map[original] = std_name
                        used_targets.add(original)
                    break  # first match wins

        df.rename(columns=rename_map, inplace=True)
        return df

    @staticmethod
    def _normalize_cgi(cgi_str) -> Optional[str]:
        """Normalise a CGI string for matching.

        * Strips common MCC-MNC prefixes such as ``460-00-``, ``460-01-``.
        * Removes dashes, dots, and whitespace.
        * Returns ``None`` for null / empty values.
        """
        if pd.isna(cgi_str):
            return None
        s = str(cgi_str).strip()
        if not s:
            return None
        # Remove common MCC-MNC prefixes (e.g. 460-00-, 460-01-, 46000-, 46001-)
        s = re.sub(r"^460[\-\.]?0[0-9][\-\.]?", "", s)
        # Remove remaining separators
        s = re.sub(r"[\-\.\s]", "", s)
        return s if s else None

    # ------------------------------------------------------------------ #
    #  File loaders                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def _load_file(
        cls,
        filepath_or_bytes,
        filename: str,
    ) -> pd.DataFrame:
        """Read a .csv or .xlsx file and return a raw DataFrame."""
        if isinstance(filepath_or_bytes, pd.DataFrame):
            df = filepath_or_bytes.copy()
            df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
            return df

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "csv" or not ext:
            if isinstance(filepath_or_bytes, (bytes, bytearray)):
                buf = io.BytesIO(filepath_or_bytes)
            else:
                buf = filepath_or_bytes
            df = None
            for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
                try:
                    if isinstance(buf, io.BytesIO):
                        buf.seek(0)
                    df = pd.read_csv(buf, encoding=enc, dtype=str)
                    break
                except Exception:
                    continue
            if df is None:
                if isinstance(buf, io.BytesIO):
                    buf.seek(0)
                df = pd.read_csv(buf, encoding="utf-8", errors="ignore", dtype=str)
        elif ext in ("xlsx", "xls"):
            if isinstance(filepath_or_bytes, (bytes, bytearray)):
                buf = io.BytesIO(filepath_or_bytes)
            else:
                buf = filepath_or_bytes
            df = pd.read_excel(buf, dtype=str)
        else:
            if isinstance(filepath_or_bytes, (bytes, bytearray)):
                buf = io.BytesIO(filepath_or_bytes)
            else:
                buf = filepath_or_bytes
            df = pd.read_csv(buf, encoding="utf-8-sig", dtype=str)

        # Strip whitespace and BOM from column names
        df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
        return df

    @classmethod
    def load_alarm_file(
        cls,
        filepath_or_bytes,
        filename: str,
    ) -> pd.DataFrame:
        """Load an alarm file (.csv / .xlsx), standardise columns, return DataFrame."""
        df = cls._load_file(filepath_or_bytes, filename)
        # 兼容原始网管导出模板：若第47列(AU)为告警对象名称，或列名含 AU/告警对象，将其规范为 cell_name
        if "cell_name" not in df.columns:
            if len(df.columns) > 46 and ("告警对象" in str(df.columns[46]) or "AU" in str(df.columns[46])):
                df.rename(columns={df.columns[46]: "cell_name"}, inplace=True)
            elif "告警对象名称" in df.columns:
                df.rename(columns={"告警对象名称": "cell_name"}, inplace=True)
        df = cls._standardize_columns(df, cls.ALARM_COLUMN_ALIASES)
        if "site_name" in df.columns and "site_id" not in df.columns:
            df["site_id"] = df["site_name"].astype(str).str.extract(r'\((\d+)\)')[0]
        return df

    @classmethod
    def load_kpi_file(
        cls,
        filepath_or_bytes,
        filename: str,
    ) -> pd.DataFrame:
        """Load a KPI file (.csv / .xlsx), standardise columns, return DataFrame."""
        df = cls._load_file(filepath_or_bytes, filename)
        raw_cols_str = " ".join([str(c) for c in df.columns]).upper()
        df = cls._standardize_columns(df, cls.KPI_COLUMN_ALIASES)

        # 过滤完全空行与无小区名称的脏数据
        if "cell_name" in df.columns:
            df = df[df["cell_name"].notna() & (df["cell_name"].astype(str).str.strip() != "") & (df["cell_name"].astype(str).str.strip() != "nan")]
        else:
            df = df.dropna(how="all")

        # 同步干扰指标：上行干扰电平 / 噪声电平
        if "carrier_noise" in df.columns and "ul_rssi" not in df.columns:
            df["ul_rssi"] = df["carrier_noise"]
        elif "ul_rssi" in df.columns and "carrier_noise" not in df.columns:
            df["carrier_noise"] = df["ul_rssi"]

        # 规范化 site_id（如去除 460-01_ 等网管前缀，统一为纯网元号）
        if "site_id" in df.columns:
            df["site_id"] = df["site_id"].astype(str).str.strip().str.replace(r'^[A-Za-z0-9\-]+_', '', regex=True)

        # 智能量纲自适应检测与归一化（将 0~1 的小数比率转化为 0~100 百分制）
        rate_cols = [
            "setup_success_rate", "drop_rate", "prb_dl_util", "prb_ul_util",
            "availability", "volte_setup_rate", "volte_drop_rate",
            "handover_success_rate", "rsrp_coverage_rate", "cqi_good_rate"
        ]
        for col in rate_cols:
            if col in df.columns:
                num_s = pd.to_numeric(df[col], errors="coerce")
                valid_vals = num_s.dropna()
                if not valid_vals.empty and valid_vals.max() <= 1.0 and valid_vals.max() > 0:
                    df[col] = (num_s * 100).round(2).astype(str)

        # 制式识别严格通过文件名识别（避免 4G 表头或小区名称中含 RLC/NR/5G反开 等字段导致误判为 5G）
        filename_upper = filename.upper()
        if any(k in filename_upper for k in ["5G", "NR", "VONR"]):
            df["rat"] = "5G"
        else:
            df["rat"] = "4G"

        # 智能判定运营商 (联通 / 电信)
        if "operator" not in df.columns:
            df["operator"] = None

        if "masterOperatorId" in df.columns:
            op_series = df["masterOperatorId"].astype(str)
            df.loc[op_series.str.contains("46001", na=False), "operator"] = "联通"
            df.loc[op_series.str.contains("46011|46003", na=False), "operator"] = "电信"

        fname_default_op = None
        if any(k in filename_upper for k in ["-DX-", "_DX_", "DX", "电信", "TELECOM", "-CT-", "_CT_"]):
            fname_default_op = "电信"
        elif any(k in filename_upper for k in ["-LT-", "_LT_", "LT", "联通", "UNICOM", "CULTE"]):
            fname_default_op = "联通"

        if fname_default_op:
            df["operator"] = df["operator"].fillna(fname_default_op)
        else:
            df["operator"] = df["operator"].fillna("联通")

        # 确保 KPI 开始时间明确可用
        if "start_time" in df.columns:
            df["kpi_start_time"] = df["start_time"]

        return df.reset_index(drop=True)

    @classmethod
    def aggregate_kpi_files(
        cls,
        files: List[Union[str, io.BytesIO, bytes]],
        filenames: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """多网管指标文件智能汇总：支持 1~6 个 4G/5G 网管导出的指标文件，标准化并合并去重。

        Parameters
        ----------
        files : List[Union[str, io.BytesIO, bytes]]
            指标文件列表（最多 6 个）。
        filenames : Optional[List[str]]
            对应的文件名列表。

        Returns
        -------
        pd.DataFrame
            汇总后的全量指标 DataFrame。
        """
        if not files:
            return pd.DataFrame()

        # 限制最多6个文件
        files = files[:6]
        if filenames is None:
            filenames = [f"kpi_file_{i+1}.csv" for i in range(len(files))]
        else:
            filenames = filenames[:len(files)]

        dfs = []
        for file_item, fname in zip(files, filenames):
            try:
                sub_df = cls.load_kpi_file(file_item, fname)
                if sub_df is not None and not sub_df.empty:
                    sub_df["kpi_source_file"] = fname
                    fname_upper = fname.upper()
                    if any(k in fname_upper for k in ["5G", "NR", "VONR"]):
                        sub_df["rat"] = "5G"
                    else:
                        sub_df["rat"] = "4G"
                    dfs.append(sub_df)
            except Exception as e:
                print(f"Warning: Failed to load KPI file {fname}: {e}")

        if not dfs:
            return pd.DataFrame()

        # 纵向拼接
        combined = pd.concat(dfs, ignore_index=True)

        # 智能去重与聚合：以小区名称与制式为联合主键
        if "cell_name" in combined.columns:
            combined = combined[combined["cell_name"].notna() & (combined["cell_name"].astype(str).str.strip() != "") & (combined["cell_name"].astype(str).str.strip() != "nan")]

            # 若有 start_time，优先排序让最新的排在前面
            if "start_time" in combined.columns:
                try:
                    combined["_sort_time"] = pd.to_datetime(combined["start_time"].astype(str).str.replace("/", "-"), errors="coerce")
                    combined.sort_values(by="_sort_time", ascending=False, inplace=True)
                    combined.drop(columns=["_sort_time"], inplace=True, errors="ignore")
                except Exception:
                    pass

            dedup_keys = ["cell_name"]
            if "rat" in combined.columns:
                dedup_keys.append("rat")
            combined.drop_duplicates(subset=dedup_keys, keep="first", inplace=True)
        elif "site_id" in combined.columns and "cell_id" in combined.columns:
            combined = combined[combined["site_id"].notna() & combined["cell_id"].notna()]
            dedup_keys = ["site_id", "cell_id"]
            if "rat" in combined.columns:
                dedup_keys.append("rat")
            combined.drop_duplicates(subset=dedup_keys, keep="first", inplace=True)

        return combined.reset_index(drop=True)

    # ------------------------------------------------------------------ #
    #  Matching engine                                                    #
    # ------------------------------------------------------------------ #

    @classmethod
    def aggregate_alarms(cls, df: pd.DataFrame) -> pd.DataFrame:
        """多重告警聚合：同一小区聚合为单行，保留最高级别、合并告警名称与网管根因"""
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        if "site_name" in df.columns and "site_id" not in df.columns:
            df["site_id"] = df["site_name"].astype(str).str.extract(r'\((\d+)\)')[0]

        severity_map = {"严重": 4, "主要": 3, "次要": 2, "警告": 1}

        if "cell_name" in df.columns:
            grouped = []
            for cname, g in df.groupby("cell_name"):
                names = [str(x).strip() for x in g["alarm_name"].dropna().unique() if str(x).strip()]
                levels = [str(x).strip() for x in g.get("alarm_level", pd.Series()).dropna() if str(x).strip()]
                best_lvl = max(levels, key=lambda x: severity_map.get(x, 0)) if levels else "一般"
                causes = []
                if "alarm_cause" in g.columns:
                    for c in g["alarm_cause"].dropna():
                        s = str(c).strip().replace("\r\n", " ").replace("\n", " ")
                        if s and s not in causes:
                            causes.append(s)
                times = [str(x).strip() for x in g.get("start_time", pd.Series()).dropna() if str(x).strip()]
                site_ids = g.get("site_id", pd.Series()).dropna().tolist()
                site_names = g.get("site_name", pd.Series()).dropna().tolist()
                cgis = g.get("cgi", pd.Series()).dropna().tolist()
                grouped.append({
                    "cell_name": str(cname).strip(),
                    "alarm_name": " | ".join(names) if names else "活动告警",
                    "alarm_level": best_lvl,
                    "alarm_cause": " ; ".join(causes[:3]) if causes else "",
                    "start_time": max(times) if times else "",
                    "alarm_count": len(g),
                    "site_id": site_ids[0] if site_ids else None,
                    "site_name": site_names[0] if site_names else None,
                    "cgi": cgis[0] if cgis else None,
                })
            return pd.DataFrame(grouped)
        return df

    @classmethod
    def match_data(
        cls,
        cells_df: pd.DataFrame,
        alarm_df: Optional[pd.DataFrame] = None,
        kpi_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Match alarm and KPI data to the base-parameter cell table.

        Join strategy for alarm_df:
          1. Exact match on cell_name (Column AU from network management).
          2. Fallback on normalised CGI.
          3. Fallback on [site_id, cell_id] composite key.
          4. Fallback site-level outage (matches cells under a site if ME has power outage / link fault).

        Join strategy for kpi_df:
          1. Left-join on normalised CGI.
          2. Fallback on [site_id, cell_id] composite key.
          3. Fallback on cell_name.
        """
        result = cells_df.copy()
        result_idx = result.index

        has_alarm_match = pd.Series(False, index=result_idx)
        has_kpi_match = pd.Series(False, index=result_idx)

        # ----------------- 1. ALARM JOIN ----------------- #
        if alarm_df is not None and not alarm_df.empty:
            agg_alarm = cls.aggregate_alarms(alarm_df)

            result["alarm_name"] = None
            result["alarm_level"] = None
            result["alarm_cause"] = None
            result["start_time"] = None
            result["alarm_count"] = 0

            # Pass 1: cell_name 优先对齐（原始网管 AU 列精确匹配）
            if "cell_name" in result.columns and "cell_name" in agg_alarm.columns:
                result["_cn"] = result["cell_name"].astype(str).str.strip()
                agg_alarm["_cn"] = agg_alarm["cell_name"].astype(str).str.strip()
                agg_map = agg_alarm.set_index("_cn")

                for idx in result.index:
                    cn = result.at[idx, "_cn"]
                    if cn in agg_map.index:
                        matched_row = agg_map.loc[cn]
                        if isinstance(matched_row, pd.DataFrame):
                            matched_row = matched_row.iloc[0]
                        result.at[idx, "alarm_name"] = matched_row["alarm_name"]
                        result.at[idx, "alarm_level"] = matched_row["alarm_level"]
                        result.at[idx, "alarm_cause"] = matched_row["alarm_cause"]
                        result.at[idx, "start_time"] = matched_row["start_time"]
                        result.at[idx, "alarm_count"] = matched_row["alarm_count"]
                        has_alarm_match.at[idx] = True

                result.drop(columns=["_cn"], inplace=True, errors="ignore")

            # Pass 2: CGI 辅助对齐（针对仍未匹配的小区）
            unmatched = result.index[~has_alarm_match]
            if len(unmatched) > 0 and "cgi" in result.columns and "cgi" in agg_alarm.columns:
                result["_cgi_norm"] = result["cgi"].apply(cls._normalize_cgi)
                agg_alarm["_cgi_norm"] = agg_alarm["cgi"].apply(cls._normalize_cgi)
                cgi_map = agg_alarm[agg_alarm["_cgi_norm"].notna()].drop_duplicates(subset=["_cgi_norm"]).set_index("_cgi_norm")

                for idx in unmatched:
                    cg = result.at[idx, "_cgi_norm"]
                    if cg and cg in cgi_map.index:
                        matched_row = cgi_map.loc[cg]
                        result.at[idx, "alarm_name"] = matched_row["alarm_name"]
                        result.at[idx, "alarm_level"] = matched_row["alarm_level"]
                        result.at[idx, "alarm_cause"] = matched_row["alarm_cause"]
                        result.at[idx, "start_time"] = matched_row["start_time"]
                        result.at[idx, "alarm_count"] = matched_row["alarm_count"]
                        has_alarm_match.at[idx] = True

                result.drop(columns=["_cgi_norm"], inplace=True, errors="ignore")

            # Pass 3: [site_id, cell_id] 对齐
            unmatched = result.index[~has_alarm_match]
            if len(unmatched) > 0 and "site_id" in result.columns and "cell_id" in result.columns and "site_id" in agg_alarm.columns and "cell_id" in agg_alarm.columns:
                result["_sk"] = result["site_id"].astype(str).str.strip() + "||" + result["cell_id"].astype(str).str.strip()
                agg_alarm["_sk"] = agg_alarm["site_id"].astype(str).str.strip() + "||" + agg_alarm["cell_id"].astype(str).str.strip()
                sk_map = agg_alarm.drop_duplicates(subset=["_sk"]).set_index("_sk")

                for idx in unmatched:
                    sk = result.at[idx, "_sk"]
                    if sk in sk_map.index:
                        matched_row = sk_map.loc[sk]
                        result.at[idx, "alarm_name"] = matched_row["alarm_name"]
                        result.at[idx, "alarm_level"] = matched_row["alarm_level"]
                        result.at[idx, "alarm_cause"] = matched_row["alarm_cause"]
                        result.at[idx, "start_time"] = matched_row["start_time"]
                        result.at[idx, "alarm_count"] = matched_row["alarm_count"]
                        has_alarm_match.at[idx] = True

                result.drop(columns=["_sk"], inplace=True, errors="ignore")

            # Pass 4: 局向/整站级告警穿透（例如设备掉电、输入电源断、S1链路断等整网元告警）
            unmatched = result.index[~has_alarm_match]
            if len(unmatched) > 0 and "site_id" in result.columns and "site_id" in agg_alarm.columns:
                site_level_alarms = agg_alarm[agg_alarm["site_id"].notna()].drop_duplicates(subset=["site_id"]).set_index("site_id")
                for idx in unmatched:
                    sid = str(result.at[idx, "site_id"]).strip()
                    if sid and sid in site_level_alarms.index:
                        salarm = site_level_alarms.loc[sid]
                        result.at[idx, "alarm_name"] = salarm["alarm_name"]
                        result.at[idx, "alarm_level"] = salarm["alarm_level"]
                        result.at[idx, "alarm_cause"] = salarm["alarm_cause"]
                        result.at[idx, "start_time"] = salarm["start_time"]
                        result.at[idx, "alarm_count"] = salarm["alarm_count"]
                        has_alarm_match.at[idx] = True

        # ----------------- 2. KPI JOIN ----------------- #
        if kpi_df is not None and not kpi_df.empty:
            kpi = kpi_df.copy()
            kpi_cols = [c for c in kpi.columns if c not in result.columns]
            for c in kpi_cols:
                result[c] = pd.Series([None] * len(result), index=result.index, dtype=object)

            if "kpi_start_time" not in result.columns:
                result["kpi_start_time"] = pd.Series([None] * len(result), index=result.index, dtype=object)
            if "kpi_rat" not in result.columns:
                result["kpi_rat"] = pd.Series([None] * len(result), index=result.index, dtype=object)

            def _apply_kpi_row(target_idx, kpi_row):
                for col in kpi_cols:
                    result.at[target_idx, col] = kpi_row[col]
                # 记录指标来源文件名与制式
                if "kpi_source_file" in kpi_row and pd.notna(kpi_row["kpi_source_file"]):
                    result.at[target_idx, "kpi_source_file"] = str(kpi_row["kpi_source_file"]).strip()
                if "rat" in kpi_row and pd.notna(kpi_row["rat"]):
                    result.at[target_idx, "kpi_rat"] = str(kpi_row["rat"]).strip()
                # 明确保存指标开始时间，并同步补充给 start_time
                t_val = kpi_row.get("kpi_start_time") if "kpi_start_time" in kpi_row else None
                if pd.isna(t_val) or not t_val:
                    t_val = kpi_row.get("start_time") if "start_time" in kpi_row else None
                if pd.isna(t_val) or not t_val:
                    t_val = kpi_row.get("开始时间") if "开始时间" in kpi_row else None
                if pd.notna(t_val) and str(t_val).strip() and str(t_val).strip().lower() not in ["none", "nan"]:
                    result.at[target_idx, "kpi_start_time"] = str(t_val).strip()
                    curr_st = result.at[target_idx, "start_time"] if "start_time" in result.columns else None
                    if pd.isna(curr_st) or not str(curr_st).strip() or str(curr_st).strip().lower() in ["none", "nan"]:
                        result.at[target_idx, "start_time"] = str(t_val).strip()

            # Pass 1: cell_name 优先对齐（原始网管表头小区名称）
            if "cell_name" in result.columns and "cell_name" in kpi.columns:
                result["_cn"] = result["cell_name"].astype(str).str.strip()
                kpi["_cn"] = kpi["cell_name"].astype(str).str.strip()
                cn_map = kpi.drop_duplicates(subset=["_cn"]).set_index("_cn")

                for idx in result.index:
                    cn = result.at[idx, "_cn"]
                    if cn in cn_map.index:
                        krow = cn_map.loc[cn]
                        _apply_kpi_row(idx, krow)
                        has_kpi_match.at[idx] = True

                result.drop(columns=["_cn"], inplace=True, errors="ignore")

            # Pass 2: [site_id, cell_id] 对齐
            unmatched_kpi = result.index[~has_kpi_match]
            if len(unmatched_kpi) > 0 and "site_id" in result.columns and "cell_id" in result.columns and "site_id" in kpi.columns and "cell_id" in kpi.columns:
                result["_sk"] = result["site_id"].astype(str).str.strip() + "||" + result["cell_id"].astype(str).str.strip()
                kpi["_sk"] = kpi["site_id"].astype(str).str.strip() + "||" + kpi["cell_id"].astype(str).str.strip()
                sk_map = kpi.drop_duplicates(subset=["_sk"]).set_index("_sk")

                for idx in unmatched_kpi:
                    sk = result.at[idx, "_sk"]
                    if sk in sk_map.index:
                        krow = sk_map.loc[sk]
                        _apply_kpi_row(idx, krow)
                        has_kpi_match.at[idx] = True

                result.drop(columns=["_sk"], inplace=True, errors="ignore")

            # Pass 3: CGI 对齐
            unmatched_kpi = result.index[~has_kpi_match]
            if len(unmatched_kpi) > 0 and "cgi" in result.columns and "cgi" in kpi.columns:
                result["_cgi_norm"] = result["cgi"].apply(cls._normalize_cgi)
                kpi["_cgi_norm"] = kpi["cgi"].apply(cls._normalize_cgi)
                kpi_dedup = kpi.drop_duplicates(subset=["_cgi_norm"]).set_index("_cgi_norm")

                for idx in unmatched_kpi:
                    cg = result.at[idx, "_cgi_norm"]
                    if cg and cg in kpi_dedup.index:
                        krow = kpi_dedup.loc[cg]
                        _apply_kpi_row(idx, krow)
                        has_kpi_match.at[idx] = True

                result.drop(columns=["_cgi_norm"], inplace=True, errors="ignore")

        # ----------------- 3. MATCH STATUS ----------------- #
        def _status(alarm_ok: bool, kpi_ok: bool) -> str:
            if alarm_ok and kpi_ok:
                return "告警+性能已匹配"
            elif alarm_ok:
                return "仅告警匹配"
            elif kpi_ok:
                return "仅性能匹配"
            else:
                return "无活动告警/未出话务"

        has_alarm_match = has_alarm_match.reindex(result.index, fill_value=False)
        has_kpi_match = has_kpi_match.reindex(result.index, fill_value=False)

        result["match_status"] = [
            _status(a, k)
            for a, k in zip(has_alarm_match, has_kpi_match)
        ]

        return result
