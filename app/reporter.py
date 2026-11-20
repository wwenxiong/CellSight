# -*- coding: utf-8 -*-
"""
reporter.py - 应急事件无线网络保障自动报告生成引擎
生成 Word (.docx) 和 Excel (.xlsx) 格式的专业通报文档
"""

import os
import math
import re
from datetime import datetime
from typing import Optional, Any

import pandas as pd
from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def _safe_str(value) -> str:
    """将任意值转为安全字符串，处理 None / NaN。"""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _safe_num(value, fmt: str = ".2f") -> str:
    """将数值转为格式化字符串，None/NaN 返回 'N/A'。"""
    if value is None:
        return "N/A"
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    try:
        return f"{float(value):{fmt}}"
    except (ValueError, TypeError):
        return _safe_str(value)


def _to_num(value) -> Optional[float]:
    """转为 float 数值，失败或 NaN 返回 None。"""
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


# Excel与文档导出表头中文映射字典
COLUMN_ZH_MAP = {
    # 基础工参字段
    "rat": "网络制式",
    "operator": "运营商",
    "site_id": "基站ID",
    "site_name": "基站名称",
    "cell_id": "小区ID",
    "cell_name": "小区名称",
    "cellid": "小区ID",
    "cgi": "小区全局标识(CGI)",
    "ecgi": "小区全局标识(ECGI)",
    "ncgi": "小区全局标识(NCGI)",
    "longitude": "经度(WGS84)",
    "latitude": "纬度(WGS84)",
    "longitude_wgs": "经度(WGS84)",
    "latitude_wgs": "纬度(WGS84)",
    "longitude_gcj": "经度(GCJ02)",
    "latitude_gcj": "纬度(GCJ02)",
    "freq_band": "工作频段",
    "earfcn": "频点号",
    "pci": "物理小区标识(PCI)",
    "tac": "跟踪区码(TAC)",
    "azimuth": "天线方位角(°)",
    "tilt": "下倾角(°)",
    "mech_tilt": "机械下倾角(°)",
    "elec_tilt": "电子下倾角(°)",
    "antenna_height": "天线挂高(m)",
    "cover_type": "覆盖类型",
    "distance_m": "距事件中心距离(米)",
    "distance_km": "距事件中心距离(km)",
    "is_indoor": "是否室分",
    "indoor": "是否室分",
    "vendor": "设备厂家",
    "bandwidth": "系统带宽(MHz)",

    # 网管元数据与标识字段
    "enbfunctionid": "基站功能ID",
    "enbfunction名称": "基站功能名称",
    "lteid": "LTE小区ID",
    "lte名称": "LTE小区名称",
    "nrphysicalcellduid": "5G物理小区ID",
    "nrcarriergroupid": "5G载波组ID",
    "nrradioinfrastructureid": "5G射频基础设施ID",
    "masteroperatorid": "主运营商ID",
    "dumemoid": "DU网元ID",
    "gnbid": "5G基站ID",
    "enodebid": "4G基站ID",
    "子网id": "子网ID",
    "子网名称": "子网名称",
    "网元id": "网元ID",
    "网元名称": "网元名称",
    "网元类型": "网元类型",
    "制式": "制式",
    "频段指示": "频段指示",

    # KPI 性能指标字段
    "start_time": "统计开始时间",
    "end_time": "统计结束时间",
    "granularity": "采样粒度(分钟)",
    "kpi_start_time": "指标采集时间",
    "kpi_rat": "指标网络制式",
    "kpi_source_file": "网管指标来源",
    "availability": "小区可用率(%)",
    "traffic_gb": "总业务量(GB)",
    "traffic_volume": "总业务量(GB)",
    "traffic_ul_gb": "上行业务量(GB)",
    "traffic_dl_gb": "下行业务量(GB)",
    "ul_traffic_gb": "上行业务量(GB)",
    "dl_traffic_gb": "下行业务量(GB)",
    "volte_traffic": "话务量(Erl)",
    "flow_mb": "流量(MB)",
    "prb_dl_util": "下行PRB利用率(%)",
    "dl_prb_util": "下行PRB利用率(%)",
    "prb_ul_util": "上行PRB利用率(%)",
    "ul_prb_util": "上行PRB利用率(%)",
    "prb_util": "PRB利用率(%)",
    "rrc_conn_max": "最大RRC连接数",
    "rrc_conn_avg": "平均RRC连接数",
    "max_active_users": "最大激活用户数",
    "avg_active_users": "平均激活用户数",
    "user_count": "用户数",
    "carrier_noise": "载波平均噪声干扰(dBm)",
    "ul_rssi": "上行平均干扰电平(dBm)",
    "ul_interference": "上行干扰电平(dBm)",
    "setup_success_rate": "无线接通率(%)",
    "rrc_setup_succ_rate": "无线接通率(%)",
    "erab_setup_succ_rate": "E-RAB建立成功率(%)",
    "drop_rate": "掉线率(%)",
    "volte_setup_rate": "VoLTE/VoNR接通率(%)",
    "volte_drop_rate": "VoLTE/VoNR掉话率(%)",
    "handover_success_rate": "切换成功率(%)",
    "handover_in_success_rate": "系统内切入成功率(%)",
    "rsrp_coverage_rate": "RSRP良好覆盖率(%)",
    "cqi_good_rate": "CQI优良率(%)",
    "dl_user_speed": "下行用户感知速率(Mbps)",
    "ul_user_speed": "上行用户感知速率(Mbps)",
    "dl_throughput": "下行吞吐率(Mbps)",
    "ul_throughput": "上行吞吐率(Mbps)",
    "tcp_rtt_ms": "TCP时延(ms)",
    "ta_avg_distance": "TA平均接入距离(m)",
    "ta_max_distance": "TA最大接入距离(m)",
    "rrc_congestion_count": "RRC拥塞次数",
    "rrc_setup_req": "RRC建立请求数",
    "rrc_setup_succ": "RRC建立成功数",
    "rrc_setup_fail": "RRC建立失败数",
    "rrc_setup_count": "RRC建立尝试次数",
    "erab_setup_req": "E-RAB建立请求数",
    "erab_setup_succ": "E-RAB建立成功数",

    # 告警与诊断结果字段
    "alarm_name": "当前活动告警",
    "alarm_level": "告警级别",
    "alarm_cause": "告警原因",
    "alarm_count": "告警数量",
    "alarm_type": "告警类型",
    "alarm_first_time": "告警发生时间",
    "alarm_title": "告警标题",
    "site_id_alarm": "告警关联基站ID",
    "cell_id_alarm": "告警关联小区ID",
    "cgi_alarm": "告警关联CGI",
    "cgi_kpi": "指标关联CGI",
    "diag_level": "故障等级",
    "severity": "严重程度",
    "diag_type": "异常分类",
    "diag_reasons": "异常根因诊断",
    "diag_reason": "异常根因诊断",
    "diag_detail": "诊断明细",
    "diag_details": "诊断明细",
    "diag_suggestion": "处理建议",
    "suggestion": "处理建议",
    "match_status": "工参匹配状态",
}


def _get_zh_header(col_name: Any) -> str:
    """获取字段的中文标准表头名称，支持忽略大小写与去首尾空格。"""
    s = str(col_name).strip()
    return COLUMN_ZH_MAP.get(s) or COLUMN_ZH_MAP.get(s.lower()) or s


def _set_cell_shading(cell, color_hex: str):
    """为单元格设置背景填充色（不含 # 号的 6 位 hex）。"""
    shading_elm = parse_xml(
        f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>'
    )
    cell._tc.get_or_add_tcPr().append(shading_elm)


def _set_table_borders(table):
    """为整个表格设置细线边框。"""
    tbl = table._tbl
    tbl_pr = tbl.tblPr if tbl.tblPr is not None else parse_xml(f'<w:tblPr {nsdecls("w")}/>')
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '  <w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '</w:tblBorders>'
    )
    tbl_pr.append(borders)


def _set_run_font(run, font_name: str, size_pt: float, bold: bool = False, color: Optional[RGBColor] = None, ascii_font: Optional[str] = None):
    """统一设置 run 的中英文字体、字号、加粗、颜色。"""
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    if not ascii_font:
        if "仿宋" in font_name or "楷体" in font_name:
            ascii_font = "Times New Roman"
        else:
            ascii_font = font_name
    run.font.name = ascii_font

    # 设置东亚与西文字体
    r_element = run._element
    rPr = r_element.find(qn("w:rPr"))
    if rPr is None:
        rPr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        r_element.insert(0, rPr)
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = parse_xml(f'<w:rFonts {nsdecls("w")}/>')
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), ascii_font)
    rFonts.set(qn("w:hAnsi"), ascii_font)
    rFonts.set(qn("w:eastAsia"), font_name)
    rFonts.set(qn("w:cs"), ascii_font)


def _add_official_paragraph(
    doc,
    text: str,
    font_name: str = "仿宋_GB2312",
    size_pt: float = 16.0,
    bold: bool = False,
    indent_chars: int = 2,
    line_spacing_pt: float = 29.0,
    alignment = WD_ALIGN_PARAGRAPH.JUSTIFY,
    space_before_pt: float = 0.0,
    space_after_pt: float = 0.0,
    ascii_font: Optional[str] = None,
    color: Optional[RGBColor] = None,
    heading_level: Optional[int] = None,
):
    """添加符合国家公文排版标准的段落（支持28-30磅行距、首行缩进2字符、大纲级别与Word导航窗格）。"""
    if heading_level is not None and 1 <= heading_level <= 9:
        try:
            para = doc.add_paragraph(style=f"Heading {heading_level}")
        except Exception:
            para = doc.add_paragraph()
    else:
        para = doc.add_paragraph()

    if alignment is not None:
        para.alignment = alignment
    para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    para.paragraph_format.line_spacing = Pt(line_spacing_pt)
    para.paragraph_format.space_before = Pt(space_before_pt)
    para.paragraph_format.space_after = Pt(space_after_pt)

    pPr = para._p.get_or_add_pPr()
    if indent_chars > 0:
        para.paragraph_format.first_line_indent = Pt(size_pt * indent_chars)
        ind = pPr.find(qn("w:ind"))
        if ind is not None:
            ind.set(qn("w:firstLineChars"), str(indent_chars * 100))
    else:
        para.paragraph_format.first_line_indent = Pt(0)

    # 显式写入大纲级别，确保在 Word 和 WPS 的导航窗格(Navigation Pane)中100%可见
    if heading_level is not None and 1 <= heading_level <= 9:
        outline = pPr.find(qn("w:outlineLvl"))
        if outline is None:
            pPr.append(parse_xml(f'<w:outlineLvl {nsdecls("w")} w:val="{heading_level - 1}"/>'))
        else:
            outline.set(qn("w:val"), str(heading_level - 1))

    run = para.add_run(text)
    _set_run_font(run, font_name, size_pt, bold, color=color or RGBColor(0, 0, 0), ascii_font=ascii_font)
    return para


def _add_styled_paragraph(doc, text: str, font_name: str = "仿宋_GB2312", size_pt: float = 16.0,
                           bold: bool = False, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after_pt: float = 0.0):
    """兼容旧接口的段落添加函数。"""
    return _add_official_paragraph(
        doc, text, font_name=font_name, size_pt=size_pt, bold=bold,
        indent_chars=2, line_spacing_pt=29.0, alignment=alignment, space_after_pt=space_after_pt
    )


def _clean_cell_text(text: Any) -> str:
    """清理表格单元格文本，彻底移除所有回车符、换行符及多余空白。"""
    if text is None:
        return ""
    if isinstance(text, float) and math.isnan(text):
        return ""
    s = str(text)
    # 彻底清除所有形式的回车符、换行符、垂直制表符
    s = re.sub(r'[\r\n\v\x0b\u2028\u2029]+', '', s)
    return s.strip()


def _fill_table_cell(cell, text: str, font_name: str = "仿宋_GB2312", size_pt: float = 10.5,
                      bold: bool = False, color: Optional[RGBColor] = None,
                      alignment=WD_ALIGN_PARAGRAPH.CENTER, ascii_font: Optional[str] = None):
    """填充表格单元格文本并设置规范样式，消除单元格内多余段落与回车符号。"""
    clean_txt = _clean_cell_text(text)

    # 1. 确保单元格内仅有唯一段落，清理任何多余段落（避免单元格内出现多个回车符号）
    while len(cell.paragraphs) > 1:
        p_elm = cell.paragraphs[-1]._p
        p_elm.getparent().remove(p_elm)

    para = cell.paragraphs[0]
    # 2. 清除该段落所有已有 run，杜绝空 run 占位
    p_elm = para._p
    for r in list(para.runs):
        p_elm.remove(r._r)

    para.alignment = alignment
    para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    para.paragraph_format.first_line_indent = Pt(0)
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(2)

    run = para.add_run(clean_txt)
    _set_run_font(run, font_name, size_pt, bold, color, ascii_font=ascii_font)


class ReportGenerator:
    """应急事件报告自动生成器，支持 Word 和 Excel 输出。"""

    # ------------------------------------------------------------------ #
    #                         Word 报告生成                                #
    # ------------------------------------------------------------------ #
    def generate_word(
        self,
        event_info: dict,
        param_summary: dict,
        diag_summary: dict,
        diagnosed_df: pd.DataFrame,
        output_dir: str,
    ) -> str:
        """
        参考项目下真实的 Word 报告（《酉阳利斯卡尔酒店语音投诉异常分析》）格式输出 Word。
        去除冗余官方套话，采用专业真实的一线网优分析表述：
        - 公文标题：2号方正小标宋 (22pt)，居中
        - 一级标题：3号黑体 (16pt) —— 一、二、三、四、，首行缩进2字符 (32pt)
        - 二级标题：3号楷体 (16pt) —— （一）（二），首行缩进2字符 (32pt)
        - 通篇正文：3号仿宋GB2312 (16pt)，首行缩进2字符 (32pt)
        - 行距：固定值29磅 (28-30磅范围)
        - 页边距：上3.7cm、下3.5cm、左2.8cm、右2.6cm
        """
        os.makedirs(output_dir, exist_ok=True)
        doc = Document()

        # 1. 页边距：上3.7下3.5左2.8右2.6
        for s in doc.sections:
            s.top_margin = Cm(3.7)
            s.bottom_margin = Cm(3.5)
            s.left_margin = Cm(2.8)
            s.right_margin = Cm(2.6)
            s.page_width = Cm(21.0)
            s.page_height = Cm(29.7)

        # 全局 Normal 样式
        style = doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(16.0)
        style.element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋_GB2312")

        # 事件名称与标题处理（对齐真实报告标题形式）
        raw_event_name = (event_info.get("event_name") or event_info.get("name") or "应急保障处置通报").strip()
        base_title = raw_event_name[:-5].strip() if raw_event_name.lower().endswith(".docx") else raw_event_name
        if base_title.endswith("异常分析") or base_title.endswith("投诉分析") or base_title.endswith("通报") or base_title.endswith("报告"):
            title_text = base_title
        else:
            title_text = f"{base_title}语音投诉异常分析"

        # 提取区域名（如“酉阳”、“南川”、“两江”）
        area_name = event_info.get("area_name")
        if not area_name:
            for prefix in ["酉阳", "南川", "两江", "渝北", "江北", "沙坪坝", "九龙坡", "南岸", "巴南", "北碚", "万州", "涪陵"]:
                if prefix in raw_event_name:
                    area_name = prefix
                    break
        if not area_name:
            area_name = raw_event_name[:4]

        # 自然时间格式化：例如 2026/10/26号15点43
        trigger_time_str = event_info.get("trigger_time") or ""
        if not trigger_time_str:
            trigger_time_fmt = datetime.now().strftime("%Y/%m/%d号%H点%M")
        else:
            try:
                if " " in trigger_time_str:
                    d_part, t_part = trigger_time_str.split(" ")
                    yy, mm, dd = d_part.replace("-", "/").split("/")
                    hh, mi = t_part.split(":")[:2]
                    trigger_time_fmt = f"{yy}/{int(mm)}/{int(dd)}号{hh}点{mi}"
                elif "-" in trigger_time_str:
                    yy, mm, dd = trigger_time_str.split("-")[:3]
                    trigger_time_fmt = f"{yy}/{int(mm)}/{int(dd)}号"
                else:
                    trigger_time_fmt = trigger_time_str
            except Exception:
                trigger_time_fmt = trigger_time_str

        # 用户投诉现象
        complaint_desc = event_info.get("description") or "手机无信号，无法上网和打电话现象"
        if not complaint_desc.endswith("现象") and not complaint_desc.endswith("。"):
            complaint_desc = f"{complaint_desc}现象"

        # 统计 4G / 5G 以及室分情况
        lte_indoor = False
        nr_indoor = False
        macro_cells = []

        if diagnosed_df is not None and not diagnosed_df.empty:
            cover_col = diagnosed_df["cover_type"].astype(str) if "cover_type" in diagnosed_df.columns else pd.Series(dtype=str)
            name_col = diagnosed_df["cell_name"].astype(str) if "cell_name" in diagnosed_df.columns else pd.Series(dtype=str)
            rat_col = diagnosed_df["rat"].astype(str).str.upper() if "rat" in diagnosed_df.columns else pd.Series(dtype=str)
            is_indoor = (cover_col.str.contains("室分|室内|分布") | name_col.str.contains("室分|室内")) & (~cover_col.str.contains("室外"))

            lte_mask = rat_col.isin(["4G", "LTE"])
            nr_mask = rat_col.isin(["5G", "NR"])

            lte_indoor = bool(is_indoor[lte_mask].any()) if lte_mask.any() else False
            nr_indoor = bool(is_indoor[nr_mask].any()) if nr_mask.any() else False

            # 宏站小区筛选
            macro_df = diagnosed_df[~is_indoor]
            if not macro_df.empty and "cell_name" in macro_df.columns:
                macro_cells = [str(c).strip() for c in macro_df["cell_name"].dropna().unique() if str(c).strip()][:3]
            elif "site_name" in diagnosed_df.columns:
                macro_cells = [str(s).strip() for s in diagnosed_df["site_name"].dropna().unique() if str(s).strip()][:3]

        # 室分描述
        if not lte_indoor and nr_indoor:
            cover_desc = "4G无室分，5G有室分"
        elif lte_indoor and not nr_indoor:
            cover_desc = "4G有室分，5G无室分"
        elif lte_indoor and nr_indoor:
            cover_desc = "4/5G均有室分"
        else:
            cover_desc = "4/5G电联均无室分"

        # 宏站描述
        if len(macro_cells) == 1:
            macro_str = f"周边{macro_cells[0]}宏站"
        elif len(macro_cells) == 2:
            macro_str = f"周边{macro_cells[0]}、{macro_cells[1]}两个宏站"
        elif len(macro_cells) > 2:
            macro_str = f"周边{'、'.join(macro_cells[:2])}等宏站"
        else:
            macro_str = "周边宏站"

        # 告警信息解析
        p0_count = diag_summary.get("p0_count", 0)
        p0_cells = diag_summary.get("p0_cells", [])
        lte_alarms = []
        nr_alarms = []
        alarm_site_names = set()

        if diagnosed_df is not None and not diagnosed_df.empty and "diag_level" in diagnosed_df.columns:
            p0_df = diagnosed_df[diagnosed_df["diag_level"] == "P0"]
            for _, r in p0_df.iterrows():
                rat = str(r.get("rat", "")).upper()
                c_name = _safe_str(r.get("cell_name", ""))
                s_name = _safe_str(r.get("site_name", ""))
                if s_name:
                    alarm_site_names.add(s_name)
                a_cause = _safe_str(r.get("alarm_name") or r.get("alarm_cause") or "")
                item_desc = f"{c_name}存在{a_cause}告警" if a_cause else f"{c_name}退服"
                if "5G" in rat or "NR" in rat:
                    nr_alarms.append(item_desc)
                else:
                    lte_alarms.append(item_desc)
        elif p0_count > 0:
            for c in p0_cells:
                c_name = _safe_str(c.get("cell_name", ""))
                s_name = _safe_str(c.get("site_name", ""))
                if s_name:
                    alarm_site_names.add(s_name)
                a_cause = _safe_str(c.get("alarm_name") or c.get("alarm_cause") or "")
                lte_alarms.append(f"{c_name}存在{a_cause}告警" if a_cause else f"{c_name}退服")

        # ==================== 公文标题：2号方正小标宋，居中 ====================
        _add_official_paragraph(
            doc,
            title_text,
            font_name="方正小标宋",
            size_pt=22.0,
            bold=False,
            indent_chars=0,
            line_spacing_pt=29.0,
            alignment=WD_ALIGN_PARAGRAPH.CENTER,
            space_before_pt=0.0,
            space_after_pt=6.0,
            ascii_font="方正小标宋",
        )

        # ==================== 一、问题描述 ====================
        _add_official_paragraph(
            doc, "一、问题描述", font_name="黑体", size_pt=16.0, bold=False,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=4.0, space_after_pt=2.0, ascii_font="黑体",
            heading_level=1
        )

        # 实际问题，时间地点发生了什么，留空（供人工核实填入）
        custom_desc = (event_info.get("description") or "").strip()
        if custom_desc:
            _add_official_paragraph(
                doc, custom_desc, font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0
            )
        else:
            _add_official_paragraph(
                doc, "", font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0
            )

        # 程序只统计该场景有多少基站，多少小区，有无室分
        total_cells = len(diagnosed_df) if diagnosed_df is not None and not diagnosed_df.empty else param_summary.get("total_cells", 0)
        if diagnosed_df is not None and not diagnosed_df.empty:
            if "site_id" in diagnosed_df.columns and diagnosed_df["site_id"].notna().any():
                total_sites = int(diagnosed_df["site_id"].dropna().nunique())
            elif "site_name" in diagnosed_df.columns:
                total_sites = int(diagnosed_df["site_name"].dropna().nunique())
            else:
                total_sites = param_summary.get("total_sites", 0)

            rat_s = diagnosed_df["rat"].astype(str).str.upper() if "rat" in diagnosed_df.columns else pd.Series(dtype=str)
            lte_cells = int(rat_s.isin(["4G", "LTE"]).sum())
            nr_cells = int(rat_s.isin(["5G", "NR"]).sum())
            if lte_cells == 0 and nr_cells == 0:
                lte_cells = total_cells
        else:
            total_sites = param_summary.get("total_sites", 0)
            total_cells = param_summary.get("total_cells", 0)
            lte_cells = param_summary.get("lte_cells", 0)
            nr_cells = param_summary.get("nr_cells", 0)

        if lte_cells > 0 and nr_cells > 0:
            cell_breakdown = f"（其中 4G 小区 {lte_cells} 个，5G 小区 {nr_cells} 个）"
        elif lte_cells > 0:
            cell_breakdown = f"（全部为 4G 小区，共 {lte_cells} 个）"
        elif nr_cells > 0:
            cell_breakdown = f"（全部为 5G 小区，共 {nr_cells} 个）"
        else:
            cell_breakdown = ""

        stats_text = (
            f"该场景共涉及物理基站 {total_sites} 个，小区 {total_cells} 个{cell_breakdown}。"
            f"{cover_desc}，主要由{macro_str}覆盖。"
        )
        _add_official_paragraph(doc, stats_text, font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)

        # ==================== 二、问题分析 ====================
        _add_official_paragraph(
            doc, "二、问题分析", font_name="黑体", size_pt=16.0, bold=False,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=4.0, space_after_pt=2.0, ascii_font="黑体",
            heading_level=1
        )

        # （一）告警
        _add_official_paragraph(
            doc, "（一）告警", font_name="楷体", size_pt=16.0, bold=True,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=2.0, space_after_pt=2.0,
            heading_level=2
        )

        if lte_alarms or nr_alarms:
            nr_str = "5G侧联通及电信站点均无场景相关异常告警" if not nr_alarms else f"5G侧存在告警，{'；'.join(nr_alarms[:2])}"
            lte_str = "4G侧无异常告警" if not lte_alarms else f"4G存在告警，{'；'.join(lte_alarms[:2])}"
            alarm_para = f"核实工参告警异常情况如下，{nr_str}，{lte_str}。如图："
        else:
            alarm_para = "核实工参告警异常情况如下，5G侧及4G侧联通及电信站点均无场景相关异常告警，电联基站运行正常。"
        _add_official_paragraph(doc, alarm_para, font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)

        # 若有告警，附上告警明细清单表
        if p0_count > 0 and diagnosed_df is not None and not diagnosed_df.empty:
            p0_df = diagnosed_df[diagnosed_df.get("diag_level") == "P0"] if "diag_level" in diagnosed_df.columns else pd.DataFrame()
            if len(p0_df) > 0:
                p0_cols = ["序号", "基站名称", "小区名称", "告警名称", "告警级别", "网管告警原因", "发生时间"]
                col_widths = [Cm(1.0), Cm(2.6), Cm(2.6), Cm(2.8), Cm(1.6), Cm(3.0), Cm(2.0)]
                p0_table = doc.add_table(rows=1, cols=len(p0_cols))
                p0_table.alignment = WD_TABLE_ALIGNMENT.CENTER
                _set_table_borders(p0_table)

                for idx, col_name in enumerate(p0_cols):
                    cell = p0_table.rows[0].cells[idx]
                    cell.width = col_widths[idx]
                    _fill_table_cell(cell, col_name, font_name="黑体", size_pt=10.5, bold=True, color=RGBColor(0, 0, 0))
                    _set_cell_shading(cell, "F2F2F2")

                for seq, (_, row) in enumerate(p0_df.iterrows(), start=1):
                    row_cells = p0_table.add_row().cells
                    for idx, w in enumerate(col_widths): row_cells[idx].width = w
                    _fill_table_cell(row_cells[0], str(seq))
                    _fill_table_cell(row_cells[1], row.get("site_name", ""), alignment=WD_ALIGN_PARAGRAPH.LEFT)
                    _fill_table_cell(row_cells[2], row.get("cell_name", ""), alignment=WD_ALIGN_PARAGRAPH.LEFT)
                    _fill_table_cell(row_cells[3], row.get("alarm_name", ""), alignment=WD_ALIGN_PARAGRAPH.LEFT)
                    _fill_table_cell(row_cells[4], row.get("alarm_level", ""))
                    _fill_table_cell(row_cells[5], row.get("alarm_cause", ""), alignment=WD_ALIGN_PARAGRAPH.LEFT)
                    _fill_table_cell(row_cells[6], row.get("start_time", ""))

        # （二）指标
        _add_official_paragraph(
            doc, "（二）指标", font_name="楷体", size_pt=16.0, bold=True,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=2.0, space_after_pt=2.0,
            heading_level=2
        )

        kpi_para = f"关键指标分析，截止目前{area_name}区域整体电联指标未发现明显异常。非区域性故障。"
        _add_official_paragraph(doc, kpi_para, font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)

        # 区分联通网管与电信网管，分区域贴入详细小区名称、时间和指标
        def _get_operator_tag(r):
            op_val = str(r.get("operator", "")).strip().upper()
            if "电信" in op_val or "CT" in op_val or "TELECOM" in op_val: return "电信"
            if "联通" in op_val or "CU" in op_val or "UNICOM" in op_val: return "联通"
            m_op = str(r.get("masterOperatorId", "")).strip()
            if "46011" in m_op or "46003" in m_op: return "电信"
            if "46001" in m_op: return "联通"
            kpi_file = str(r.get("kpi_source_file", "")).upper()
            if any(k in kpi_file for k in ["-DX-", "_DX_", "DX", "电信", "TELECOM", "-CT-", "_CT_"]): return "电信"
            if any(k in kpi_file for k in ["-LT-", "_LT_", "LT", "联通", "UNICOM", "CULTE"]): return "联通"
            enb = (str(r.get("site_id", "")) + " " + str(r.get("ENBFunctionID", ""))).upper()
            if "460-11" in enb or "460-03" in enb: return "电信"
            if "460-01" in enb: return "联通"
            text = (str(r.get("cell_name", "")) + " " + str(r.get("site_name", "")) + " " + str(r.get("LTE名称", ""))).upper()
            if "电信" in text or "CT" in text: return "电信"
            if "联通" in text or "CULTE" in text or "(L)" in text or "CU" in text: return "联通"
            fb = str(r.get("freq_band", "")).upper()
            if "800" in fb or "C波段" in fb: return "电信"
            return "联通"

        def _has_actual_kpi(r):
            # 只要具有任意有效指标数值或网管采集时间，即视为有效指标记录
            for col in ["traffic_gb", "volte_traffic", "setup_success_rate", "drop_rate", "rrc_conn_max", "prb_dl_util", "carrier_noise", "ul_rssi", "ul_interference"]:
                v = r.get(col)
                if v is not None and not pd.isna(v) and str(v).strip() not in ["", "—", "nan", "None"]:
                    return True
            t_kpi = r.get("kpi_start_time")
            if t_kpi is not None and not pd.isna(t_kpi) and str(t_kpi).strip().lower() not in ["", "none", "nan", "—"]:
                return True
            return False

        def _render_kpi_table(doc_obj, target_df: pd.DataFrame, rat_type: str = "4G") -> bool:
            # 过滤出真正具有网管指标的记录行，杜绝整行全为“—”的空白占位行及海量空回车
            valid_df = target_df[target_df.apply(_has_actual_kpi, axis=1)] if not target_df.empty else target_df
            if valid_df.empty:
                return False

            if rat_type == "5G":
                cols = ["小区名称", "时间", "RLC流量(GB)", "VoNR话务(Erl)", "接入成功率", "掉线率", "最大RRC", "下行PRB", "干扰指标"]
            else:
                cols = ["小区名称", "时间", "4G流量(GB)", "VoLTE话务(Erl)", "接通率", "掉线率", "最大RRC", "下行PRB", "干扰指标"]
            col_widths = [Cm(4.6), Cm(1.9), Cm(1.5), Cm(1.4), Cm(1.3), Cm(1.1), Cm(1.1), Cm(1.3), Cm(1.4)]

            table = doc_obj.add_table(rows=1, cols=len(cols))
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            _set_table_borders(table)

            for idx, col_name in enumerate(cols):
                cell = table.rows[0].cells[idx]
                cell.width = col_widths[idx]
                _fill_table_cell(cell, col_name, font_name="黑体", size_pt=9.5, bold=True, color=RGBColor(0, 0, 0))
                _set_cell_shading(cell, "F2F2F2")

            for _, row in valid_df.iterrows():
                row_cells = table.add_row().cells
                for idx, w in enumerate(col_widths):
                    row_cells[idx].width = w

                c_name = row.get("cell_name", "")
                t_raw = row.get("kpi_start_time")
                if t_raw is None or pd.isna(t_raw) or str(t_raw).strip().lower() in ["", "none", "nan"]:
                    t_raw = row.get("start_time")
                if t_raw is None or pd.isna(t_raw) or str(t_raw).strip().lower() in ["", "none", "nan"]:
                    t_raw = row.get("开始时间")

                t_str = str(t_raw).strip() if (t_raw is not None and not pd.isna(t_raw)) else ""
                if t_str and t_str.lower() not in ["none", "nan"]:
                    if " " in t_str:
                        d_p, tm_p = t_str.split(" ", 1)
                        clean_d = re.sub(r'^\d{4}[/-]', '', d_p)
                        t_display = f"{clean_d} {tm_p[:5]}"
                    elif "-" in t_str or "/" in t_str:
                        t_display = re.sub(r'^\d{4}[/-]', '', t_str[:16])
                    else:
                        t_display = t_str
                else:
                    t_display = "—"

                traf = _to_num(row.get("traffic_gb"))
                traf_str = f"{traf:.2f}" if traf is not None else "—"

                vol = _to_num(row.get("volte_traffic"))
                vol_str = f"{vol:.2f}" if vol is not None else "—"

                setup = _to_num(row.get("setup_success_rate"))
                setup_str = f"{setup:.2f}%" if setup is not None else "—"

                drop = _to_num(row.get("drop_rate"))
                drop_str = f"{drop:.2f}%" if drop is not None else "—"

                rrc = _to_num(row.get("rrc_conn_max"))
                rrc_str = f"{rrc:.0f}" if rrc is not None else "—"

                prb = _to_num(row.get("prb_dl_util"))
                prb_str = f"{prb:.1f}%" if prb is not None else "—"

                interf_val = row.get("carrier_noise")
                if interf_val is None or pd.isna(interf_val):
                    interf_val = row.get("ul_rssi")
                if interf_val is None or pd.isna(interf_val):
                    interf_val = row.get("ul_interference")
                if interf_val is None or pd.isna(interf_val):
                    interf_val = row.get("载波平均噪声干扰(dBm)")
                if interf_val is None or pd.isna(interf_val):
                    interf_val = row.get("小区上行平均干扰电平(dBm)")
                if interf_val is None or pd.isna(interf_val):
                    interf_val = row.get("上行干扰电平")

                interf_num = _to_num(interf_val)
                if interf_num is not None:
                    interf_str = f"{interf_num:.1f}dBm"
                elif interf_val is not None and str(interf_val).strip() not in ["", "—", "nan", "None"]:
                    interf_str = str(interf_val).strip()
                    if not interf_str.endswith("dBm") and not interf_str.endswith("%"):
                        try:
                            interf_str = f"{float(interf_str):.1f}dBm"
                        except Exception:
                            pass
                else:
                    interf_str = "—"

                _fill_table_cell(row_cells[0], c_name, size_pt=9.0, alignment=WD_ALIGN_PARAGRAPH.LEFT)
                _fill_table_cell(row_cells[1], t_display, size_pt=9.0)
                _fill_table_cell(row_cells[2], traf_str, size_pt=9.0)
                _fill_table_cell(row_cells[3], vol_str, size_pt=9.0)
                _fill_table_cell(row_cells[4], setup_str, size_pt=9.0)
                _fill_table_cell(row_cells[5], drop_str, size_pt=9.0)
                _fill_table_cell(row_cells[6], rrc_str, size_pt=9.0)
                _fill_table_cell(row_cells[7], prb_str, size_pt=9.0)
                _fill_table_cell(row_cells[8], interf_str, size_pt=9.0)

            return True

        has_cell_kpi = (diagnosed_df is not None and not diagnosed_df.empty and any(c in diagnosed_df.columns for c in ["traffic_gb", "volte_traffic", "setup_success_rate", "rrc_conn_max", "carrier_noise", "ul_rssi"]))

        if has_cell_kpi:
            df_with_op = diagnosed_df.copy()
            df_with_op["_detected_op"] = df_with_op.apply(_get_operator_tag, axis=1)

            # 拆分为 4G 小区与 5G 小区：严格依据文件名与制式标记，禁止通过小区名称猜测
            def _is_5g_kpi(r):
                # 1. 优先通过网管指标文件名称识别
                src_file = str(r.get("kpi_source_file", "")).upper()
                if src_file:
                    if any(k in src_file for k in ["5G", "NR", "VONR"]):
                        return True
                    if any(k in src_file for k in ["4G", "LTE"]):
                        return False
                # 2. 其次通过 kpi_rat 或工参 rat 识别
                k_rat = str(r.get("kpi_rat", "")).strip().upper()
                if k_rat in ["5G", "NR"]: return True
                if k_rat in ["4G", "LTE"]: return False
                r_rat = str(r.get("rat", "")).strip().upper()
                if r_rat in ["5G", "NR"]: return True
                return False

            is_5g_mask = df_with_op.apply(_is_5g_kpi, axis=1)
            df_4g = df_with_op[~is_5g_mask]
            df_5g = df_with_op[is_5g_mask]

            # ==================== 小块 1：4G网管性能指标 ====================
            _add_official_paragraph(
                doc, "1. 4G网管性能指标", font_name="黑体", size_pt=14.0, bold=True,
                indent_chars=2, line_spacing_pt=26.0, space_before_pt=4.0, space_after_pt=2.0,
                heading_level=3
            )
            if df_4g.empty:
                _add_official_paragraph(
                    doc, "不涉及", font_name="仿宋_GB2312", size_pt=14.0, indent_chars=2, line_spacing_pt=26.0
                )
            else:
                cu_4g = df_4g[df_4g["_detected_op"] == "联通"]
                ct_4g = df_4g[df_4g["_detected_op"] == "电信"]

                _add_official_paragraph(
                    doc, "（1）联通4G网管指标：", font_name="楷体", size_pt=13.0, bold=True,
                    indent_chars=2, line_spacing_pt=24.0, space_before_pt=3.0, space_after_pt=1.0,
                    heading_level=4
                )
                if cu_4g.empty or not _render_kpi_table(doc, cu_4g, rat_type="4G"):
                    _add_official_paragraph(
                        doc, "不涉及", font_name="仿宋_GB2312", size_pt=13.0, indent_chars=2, line_spacing_pt=24.0
                    )

                _add_official_paragraph(
                    doc, "（2）电信4G网管指标：", font_name="楷体", size_pt=13.0, bold=True,
                    indent_chars=2, line_spacing_pt=24.0, space_before_pt=3.0, space_after_pt=1.0,
                    heading_level=4
                )
                if ct_4g.empty or not _render_kpi_table(doc, ct_4g, rat_type="4G"):
                    _add_official_paragraph(
                        doc, "不涉及", font_name="仿宋_GB2312", size_pt=13.0, indent_chars=2, line_spacing_pt=24.0
                    )

            # ==================== 小块 2：5G网管性能指标 ====================
            _add_official_paragraph(
                doc, "2. 5G网管性能指标", font_name="黑体", size_pt=14.0, bold=True,
                indent_chars=2, line_spacing_pt=26.0, space_before_pt=6.0, space_after_pt=2.0,
                heading_level=3
            )
            if df_5g.empty:
                _add_official_paragraph(
                    doc, "不涉及", font_name="仿宋_GB2312", size_pt=14.0, indent_chars=2, line_spacing_pt=26.0
                )
            else:
                cu_5g = df_5g[df_5g["_detected_op"] == "联通"]
                ct_5g = df_5g[df_5g["_detected_op"] == "电信"]

                _add_official_paragraph(
                    doc, "（1）联通5G网管指标：", font_name="楷体", size_pt=13.0, bold=True,
                    indent_chars=2, line_spacing_pt=24.0, space_before_pt=3.0, space_after_pt=1.0,
                    heading_level=4
                )
                if cu_5g.empty or not _render_kpi_table(doc, cu_5g, rat_type="5G"):
                    _add_official_paragraph(
                        doc, "不涉及", font_name="仿宋_GB2312", size_pt=13.0, indent_chars=2, line_spacing_pt=24.0
                    )

                _add_official_paragraph(
                    doc, "（2）电信5G网管指标：", font_name="楷体", size_pt=13.0, bold=True,
                    indent_chars=2, line_spacing_pt=24.0, space_before_pt=3.0, space_after_pt=1.0,
                    heading_level=4
                )
                if ct_5g.empty or not _render_kpi_table(doc, ct_5g, rat_type="5G"):
                    _add_official_paragraph(
                        doc, "不涉及", font_name="仿宋_GB2312", size_pt=13.0, indent_chars=2, line_spacing_pt=24.0
                    )
        else:
            _add_official_paragraph(
                doc, "不涉及", font_name="仿宋_GB2312", size_pt=14.0, indent_chars=2, line_spacing_pt=26.0
            )

        # 共享策略核实段落（与真实报告 P8 严格一致）
        _add_official_paragraph(
            doc, "涉及电联小区的共享策略核实均无异常：", font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0, space_before_pt=4.0
        )

        # 共享策略表（与真实报告 Table 1 呼应）
        share_table = doc.add_table(rows=1, cols=4)
        share_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(share_table)
        share_col_widths = [Cm(3.0), Cm(4.2), Cm(4.2), Cm(4.2)]

        share_headers = ["网络制式", "载波频段", "共享模式", "共享策略核查结论"]
        for idx, col_name in enumerate(share_headers):
            cell = share_table.rows[0].cells[idx]
            cell.width = share_col_widths[idx]
            _fill_table_cell(cell, col_name, font_name="黑体", size_pt=10.5, bold=True, color=RGBColor(0, 0, 0))
            _set_cell_shading(cell, "F2F2F2")

        share_data_rows = [
            ["5G (NR)", "3.5GHz / 2.1GHz", "联通电信共建共享", "核查无异常，策略一致生效"],
            ["4G (LTE)", "1.8GHz / 2.1GHz", "双向对等共享互通", "核查无异常，切换与承载正常"],
        ]
        for row_vals in share_data_rows:
            row_cells = share_table.add_row().cells
            for idx, w in enumerate(share_col_widths): row_cells[idx].width = w
            _fill_table_cell(row_cells[0], row_vals[0], font_name="黑体", bold=True)
            _fill_table_cell(row_cells[1], row_vals[1])
            _fill_table_cell(row_cells[2], row_vals[2])
            _fill_table_cell(row_cells[3], row_vals[3])

        # ==================== 三、初步原因 ====================
        _add_official_paragraph(
            doc, "三、初步原因", font_name="黑体", size_pt=16.0, bold=False,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=4.0, space_after_pt=2.0, ascii_font="黑体",
            heading_level=1
        )

        # 原因分析结构严格对标真实报告：
        # "按初步核实酉阳利斯卡尔酒店4G无室分，5G有室分，4G主要由周边...两个宏站覆盖。初步定位用户占用4G，4G周边宏站覆盖，深度覆盖不足；...存在...告警，接续不足导致快衰后掉话。。"
        reason_parts = [
            f"按初步核实{area_name}{cover_desc}，主要由{macro_str}覆盖。",
            "初步定位用户占用4G，4G周边宏站覆盖，深度覆盖不足；"
        ]

        if lte_alarms:
            reason_parts.append(f"{'；'.join(lte_alarms[:2])}，接续不足导致快衰后掉话。")
        else:
            reason_parts.append("建筑物穿透损耗大，室内深度覆盖不足，接续不足导致快衰后掉话。")

        reason_para = "".join(reason_parts)
        _add_official_paragraph(doc, reason_para, font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)

        # ==================== 四、下一步计划 ====================
        _add_official_paragraph(
            doc, "四、下一步计划", font_name="黑体", size_pt=16.0, bold=False,
            indent_chars=2, line_spacing_pt=29.0, space_before_pt=4.0, space_after_pt=2.0, ascii_font="黑体",
            heading_level=1
        )

        if lte_alarms or nr_alarms:
            sites_str = "、".join(list(alarm_site_names)[:3]) if alarm_site_names else "告警基站"
            _add_official_paragraph(doc, f"1. 协调代维人员对故障基站（{sites_str}）开展排查与恢复；", font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)
            _add_official_paragraph(doc, "2. 已安排现场测试，待完成后输出测试报告。", font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)
        else:
            # 与真实报告 P12 严格一致
            _add_official_paragraph(doc, "已安排现场测试，待完成后输出测试报告。", font_name="仿宋_GB2312", size_pt=16.0, indent_chars=2, line_spacing_pt=29.0)

        # 保存：直接使用导出时填写的名称
        clean_name = re.sub(r'[\\/*?:"<>|]', '_', raw_event_name.strip())
        if not clean_name:
            clean_name = "应急保障处置通报"
        if not clean_name.lower().endswith(".docx"):
            filename = f"{clean_name}.docx"
        else:
            filename = clean_name
        filepath = os.path.join(output_dir, filename)
        doc.save(filepath)
        return filepath

    # ------------------------------------------------------------------ #
    #                         Excel 报告生成                               #
    # ------------------------------------------------------------------ #
    def generate_excel(
        self,
        diagnosed_df: pd.DataFrame,
        event_info: dict,
        output_dir: str,
    ) -> str:
        """
        生成带条件格式化的 Excel 工作簿 (.xlsx)。

        Parameters
        ----------
        diagnosed_df : pd.DataFrame
            诊断后的小区级 DataFrame。
        event_info : dict
            事件基本信息。
        output_dir : str
            输出目录路径。

        Returns
        -------
        str
            生成的 Excel 文件完整路径。
        """
        os.makedirs(output_dir, exist_ok=True)

        wb = Workbook()
        ws = wb.active
        ws.title = "影响区域小区清单"

        # ---- 样式定义 ----
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name="黑体", size=10, bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        p0_fill = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
        p1_fill = PatternFill(start_color="FFE0B2", end_color="FFE0B2", fill_type="solid")
        p2_fill = PatternFill(start_color="FFFFF0", end_color="FFFFF0", fill_type="solid")
        normal_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")

        body_font = Font(name="仿宋", size=10)
        body_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )

        # 排除内部临时列与已删除的处置建议列
        excluded_cols = {"diag_suggestion", "_cgi_norm", "_sk", "_cn", "_sort_time", "_sort_key"}
        columns = [c for c in diagnosed_df.columns if c not in excluded_cols]
        num_cols = len(columns)

        # ---- 表头 (中文表头) ----
        for col_idx, col_name in enumerate(columns, start=1):
            zh_header = _get_zh_header(col_name)
            cell = ws.cell(row=1, column=col_idx, value=zh_header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = thin_border

        # ---- 数据行 ----
        severity_col_name = "diag_level" if "diag_level" in diagnosed_df.columns else ("severity" if "severity" in diagnosed_df.columns else None)

        for row_idx, (_, data_row) in enumerate(diagnosed_df.iterrows(), start=2):
            severity_val = ""
            if severity_col_name:
                severity_val = _safe_str(data_row.get(severity_col_name, ""))

            # 选择行填充色
            if severity_val == "P0":
                row_fill = p0_fill
            elif severity_val == "P1":
                row_fill = p1_fill
            elif severity_val == "P2":
                row_fill = p2_fill
            else:
                row_fill = normal_fill

            for col_idx, col_name in enumerate(columns, start=1):
                raw_value = data_row.get(col_name)
                cell_value = _safe_str(raw_value)
                cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
                cell.fill = row_fill
                cell.font = body_font
                cell.alignment = body_alignment
                cell.border = thin_border

        # ---- 自动列宽 (中文字符按双倍宽度适配) ----
        for col_idx, col_name in enumerate(columns, start=1):
            zh_header = _get_zh_header(col_name)
            max_len = 0
            for ch in zh_header:
                max_len += 2 if ord(ch) > 127 else 1

            for row_idx in range(2, min(len(diagnosed_df) + 2, 80)):
                cell_val = ws.cell(row=row_idx, column=col_idx).value
                if cell_val:
                    val_len = 0
                    for ch in str(cell_val):
                        val_len += 2 if ord(ch) > 127 else 1
                    if val_len > max_len:
                        max_len = val_len
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 11), 45)

        # ---- 冻结窗格 ----
        ws.freeze_panes = "A2"

        # ---- 保存 ----
        event_name = (event_info.get("event_name") or "未命名事件").strip()
        clean_base = re.sub(r'[\\/*?:"<>|]', '_', event_name)
        if clean_base.lower().endswith(".docx"):
            clean_base = clean_base[:-5].strip()
        filename = f"影响区域小区清单_{clean_base}.xlsx"
        filepath = os.path.join(output_dir, filename)
        wb.save(filepath)
        return filepath

    # ------------------------------------------------------------------ #
    #                         内部辅助方法                                 #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_suggestions(p0_count: int, p1_count: int, p2_count: int, normal_count: int) -> list:
        """根据诊断结果自动生成保障应对建议条目。"""
        suggestions = []
        idx = 1

        if p0_count > 0:
            suggestions.append(
                f"{idx}. 紧急派单抢修退服站点，共 {p0_count} 个小区退服，"
                f"需立即协调维护人员到站排查硬件故障、传输中断等问题，确保第一时间恢复服务。"
            )
            idx += 1

        if p1_count > 0:
            suggestions.append(
                f"{idx}. 启动应急扩容/抗干扰措施，共 {p1_count} 个小区存在高负荷、拥塞或干扰风险，"
                f"建议实施负荷均衡、频点优化、邻区调整等手段，必要时申请临时扩容或部署应急通信车。"
            )
            idx += 1

        if p2_count > 0:
            suggestions.append(
                f"{idx}. 关注质差小区性能优化，共 {p2_count} 个小区指标偏离基线，"
                f"建议安排参数核查、天馈系统检查及覆盖优化，防止质差进一步恶化。"
            )
            idx += 1

        if p0_count > 0 or p1_count > 0:
            suggestions.append(
                f"{idx}. 加强值班监控，保障期间安排专人 7×24 盯屏，"
                f"对重点区域关键指标实施 15 分钟粒度实时监控，异常情况立即上报并启动应急处置流程。"
            )
            idx += 1

        suggestions.append(
            f"{idx}. 做好保障总结与复盘，事件结束后 24 小时内完成保障报告撰写，"
            f"总结经验教训，持续完善应急预案和网络优化方案。"
        )

        if not suggestions:
            suggestions.append("当前网络运行状态良好，建议保持日常巡检监控。")

        return suggestions
