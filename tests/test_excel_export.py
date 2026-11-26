# -*- coding: utf-8 -*-
"""工参 Excel 导出功能测试。

验证：
1. 导出的工参 Excel 包含归属场景名称（且作为首列展示）
2. 不同的工参图层分别存放于独立的 Excel Sheet 工作表
3. 特殊字符和过长图层名称被合规清洗为合法 Sheet 名
4. ReportGenerator.generate_excel 同样支持场景名称与分 Sheet 存放
"""

from pathlib import Path
from unittest.mock import MagicMock
import openpyxl
import pandas as pd
import pytest

import main
from app.reporter import ReportGenerator


@pytest.fixture
def multi_layer_cells():
    return [
        {
            "cell_name": "电信A小区",
            "site_name": "电信A站",
            "longitude": 113.31,
            "latitude": 23.11,
            "layer_name": "电信4G",
            "scene_name": "奥体中心主场馆",
            "rat": "4G",
            "pci": "101",
        },
        {
            "cell_name": "电信B小区",
            "site_name": "电信B站",
            "longitude": 113.32,
            "latitude": 23.12,
            "layer_name": "电信4G",
            "scene_name": "奥体中心主场馆",
            "rat": "4G",
            "pci": "102",
        },
        {
            "cell_name": "移动C小区",
            "site_name": "移动C站",
            "longitude": 113.33,
            "latitude": 23.13,
            "layer_name": "移动5G",
            "scene_name": "外围交通干道",
            "rat": "5G",
            "pci": "501",
        },
        {
            "cell_name": "联通D小区",
            "site_name": "联通D站",
            "longitude": 113.34,
            "latitude": 23.14,
            "layer_name": "联通/测试[图层]*超长特殊字符图层名称测试用例超出限制",
            "scene_name": "",  # 模拟空场景名称，触发回退
            "rat": "4G",
            "pci": "201",
        },
    ]


@pytest.mark.anyio
async def test_export_selected_cells_multisheet_and_scene(tmp_path, multi_layer_cells, monkeypatch):
    """测试 /api/spatial/export 端点：多图层分 Sheet 存放且包含首列场景名称。"""
    monkeypatch.setattr("main.OUTPUT_DIR", tmp_path)

    main.session_state["selected_cells"] = pd.DataFrame(multi_layer_cells)
    main.session_state["event_info"] = {
        "event_name": "2026广州马拉松保障",
        "address": "天河体育中心",
    }

    resp = await main.export_selected_cells(request=None)
    assert resp.status_code == 200
    file_path = resp.path
    assert Path(file_path).exists()

    # 读取并验证生成的 Excel
    wb = openpyxl.load_workbook(file_path)
    sheet_names = wb.sheetnames
    assert len(sheet_names) == 3
    assert "电信4G" in sheet_names
    assert "移动5G" in sheet_names

    # 验证非法字符已被清洗，且长度不超过 31 字符
    sanitized_sheet = sheet_names[2]
    assert "/" not in sanitized_sheet
    assert "[" not in sanitized_sheet
    assert "]" not in sanitized_sheet
    assert "*" not in sanitized_sheet
    assert len(sanitized_sheet) <= 31

    # 验证「电信4G」工作表内容
    ws_telecom = wb["电信4G"]
    # 首列必须为场景名称
    assert ws_telecom.cell(row=1, column=1).value == "场景名称"
    assert ws_telecom.cell(row=2, column=1).value == "奥体中心主场馆"
    assert ws_telecom.cell(row=3, column=1).value == "奥体中心主场馆"

    # 验证空场景名称统一填为「无」
    ws_special = wb[sanitized_sheet]
    assert ws_special.cell(row=1, column=1).value == "场景名称"
    assert ws_special.cell(row=2, column=1).value == "无"

    # 验证其余表头严格保留原始/数据库列名（不被 COLUMN_ZH_MAP 强行改名）
    headers_telecom = [ws_telecom.cell(row=1, column=c).value for c in range(1, ws_telecom.max_column + 1)]
    assert headers_telecom[0] == "场景名称"
    assert "cell_name" in headers_telecom
    assert "site_name" in headers_telecom
    assert "longitude" in headers_telecom


def test_report_generator_generate_excel_multisheet_and_scene(tmp_path, multi_layer_cells):
    """测试 ReportGenerator.generate_excel：支持多图层分 Sheet 与首列场景名称。"""
    df = pd.DataFrame(multi_layer_cells)
    df["diag_level"] = ["P0", "P1", "P2", "正常"]

    event_info = {
        "event_name": "大型演习赛事",
        "address": "国际会展中心",
    }

    rep = ReportGenerator()
    out_file = rep.generate_excel(df, event_info, str(tmp_path))
    assert Path(out_file).exists()

    wb = openpyxl.load_workbook(out_file)
    assert len(wb.sheetnames) == 3
    assert "电信4G" in wb.sheetnames
    assert "移动5G" in wb.sheetnames

    # 验证首列为场景名称
    ws1 = wb["电信4G"]
    assert ws1.cell(row=1, column=1).value == "场景名称"
    assert ws1.cell(row=2, column=1).value == "奥体中心主场馆"

    # 验证第三个 Sheet 空场景名称回退
    ws3 = wb[wb.sheetnames[2]]
    assert ws3.cell(row=1, column=1).value == "场景名称"
    assert ws3.cell(row=2, column=1).value == "国际会展中心"


@pytest.mark.anyio
async def test_export_selected_cells_excel_styling_and_headers(tmp_path, multi_layer_cells, monkeypatch):
    """测试工参 Excel 样式的专业美化与响应头扩展名保障。"""
    from fastapi.testclient import TestClient
    from main import app

    monkeypatch.setattr("main.OUTPUT_DIR", tmp_path)
    client = TestClient(app)

    # 通过 POST /api/spatial/export.xlsx 直接携带 cells 导出
    resp = client.post("/api/spatial/export.xlsx", json={"cells": multi_layer_cells})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # 验证 Content-Disposition 中包含 .xlsx
    disp = resp.headers.get("content-disposition", "")
    assert ".xlsx" in disp

    # 将响应内容保存为文件以检验 openpyxl 格式
    out_file = tmp_path / "downloaded.xlsx"
    out_file.write_bytes(resp.content)

    wb = openpyxl.load_workbook(out_file)
    for ws in wb.worksheets:
        assert ws.freeze_panes == "A2"
        # 验证表头填充颜色为深蓝 1F4E79
        header_cell = ws.cell(row=1, column=1)
        assert header_cell.fill.start_color.rgb.endswith("1F4E79")
        assert header_cell.font.bold is True
        assert header_cell.font.color.rgb.endswith("FFFFFF")

        # 验证数据行存在边框
        data_cell = ws.cell(row=2, column=1)
        assert data_cell.border.left.style is not None
        assert data_cell.border.bottom.style is not None

