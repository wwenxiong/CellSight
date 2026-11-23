# -*- coding: utf-8 -*-
"""
LTE/NR 应急事件无线保障处置系统 - FastAPI 主入口
"""

import os
import io
import re
import json
import traceback
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

import math
import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.param_loader import ParamLoader
from app.matcher import DataMatcher
from app.diagnosis import DiagnosisEngine
from app.reporter import ReportGenerator, COLUMN_ZH_MAP
from app.coord_utils import wgs84_to_gcj02, gcj02_to_wgs84, parse_coordinates
from app.boundary_parser import parse_boundary_content
from app.amap_client import AmapClient
from app.task_manager import TaskManager
from app.smart_importer import SmartImporter
from app.project_manager import ProjectManager
from app.pci_checker import check_pci_conflicts
import urllib.request
import urllib.parse

from typing import Optional, List

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"

OUTPUT_DIR.mkdir(exist_ok=True)

# 最近工程存档（服务端保存 .wyp 副本，供工程菜单“最近工程”一键打开）
RECENT_PROJECTS_DIR = DATA_DIR / "recent_projects"
RECENT_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
RECENT_PROJECTS_META = DATA_DIR / "recent_projects.json"
MAX_RECENT_PROJECTS = 5


def _load_recent_projects_meta() -> list:
    try:
        if RECENT_PROJECTS_META.exists():
            data = json.loads(RECENT_PROJECTS_META.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_recent_projects_meta(items: list):
    RECENT_PROJECTS_META.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_recent_project(proj_name: str, wyp_bytes: bytes, cell_count: int) -> dict:
    """保存一份 .wyp 副本并记入最近工程列表（最多保留 5 个）。"""
    proj_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    safe_name = re.sub(r'[\\/*?:"<>|]', "", proj_name) or "Wmap工程"
    filename = f"{proj_id}.wyp"
    (RECENT_PROJECTS_DIR / filename).write_bytes(wyp_bytes)
    entry = {
        "id": proj_id,
        "name": safe_name,
        "filename": filename,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cell_count": cell_count,
    }
    items = [e for e in _load_recent_projects_meta() if e.get("name") != safe_name]
    items.insert(0, entry)
    # 清理超出上限的旧副本
    for stale in items[MAX_RECENT_PROJECTS:]:
        stale_path = RECENT_PROJECTS_DIR / stale.get("filename", "")
        if stale_path.exists():
            stale_path.unlink()
    items = items[:MAX_RECENT_PROJECTS]
    _save_recent_projects_meta(items)
    return entry


def _apply_project_cells_to_session(project_data: dict):
    """将工程内的工参同步至全局 param_loader 与 SQLite 数据库。"""
    from app.cell_db import CellDB, DEFAULT_DB_PATH
    cells = project_data.get("layers", {}).get("param_cells", [])
    if cells:
        df = pd.DataFrame(cells)
        param_loader.all_cells = df
        param_loader.df_all = df
        CellDB.save_dataframe(df, db_path=DEFAULT_DB_PATH)
    elif DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
        param_loader.load_from_sqlite(str(DEFAULT_DB_PATH))
    session_state["params_loaded"] = True
    session_state["param_summary"] = param_loader.get_summary()

app = FastAPI(title="LTE/NR 应急事件无线保障处置系统", version="1.0.0")

@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误: {str(exc)}"},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

def sanitize_cell_records(df: pd.DataFrame) -> list:
    """安全清洗 DataFrame 小区列表，彻底剔除 NaN/Inf 并计算 GCJ-02 渲染坐标"""
    records = []
    if df is None or df.empty:
        return records
    raw_records = df.to_dict(orient="records")
    for row in raw_records:
        clean = {}
        for k, v in row.items():
            if v is None:
                clean[k] = None
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            elif pd.isna(v):
                clean[k] = None
            elif isinstance(v, (np.integer, np.int64, np.int32)):
                clean[k] = int(v)
            elif isinstance(v, (np.floating, np.float64, np.float32)):
                clean[k] = None if (np.isnan(v) or np.isinf(v)) else float(v)
            elif isinstance(v, (bool, np.bool_)):
                clean[k] = bool(v)
            elif isinstance(v, (pd.Timestamp, datetime)):
                clean[k] = str(v)
            else:
                clean[k] = str(v) if not isinstance(v, (str, int, float)) else v
        # GCJ-02 坐标安全解析与转换
        try:
            raw_w_lng = clean.get("longitude")
            w_lng = float(raw_w_lng) if (raw_w_lng is not None and not (isinstance(raw_w_lng, float) and (math.isnan(raw_w_lng) or math.isinf(raw_w_lng)))) else 0.0
        except (ValueError, TypeError):
            w_lng = 0.0

        try:
            raw_w_lat = clean.get("latitude")
            w_lat = float(raw_w_lat) if (raw_w_lat is not None and not (isinstance(raw_w_lat, float) and (math.isnan(raw_w_lat) or math.isinf(raw_w_lat)))) else 0.0
        except (ValueError, TypeError):
            w_lat = 0.0

        g_lng, g_lat = wgs84_to_gcj02(w_lng, w_lat)
        clean["longitude_wgs"] = w_lng
        clean["latitude_wgs"] = w_lat
        clean["longitude_gcj"] = g_lng
        clean["latitude_gcj"] = g_lat
        records.append(clean)
    return records

# 静态文件挂载
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# 全局配置与高德地图客户端
# ---------------------------------------------------------------------------
CONFIG_FILE = BASE_DIR / "config.json"
LOCAL_CONFIG_FILE = BASE_DIR / "config.local.json"  # 本地密钥文件，不进仓库

def load_app_config() -> dict:
    default_cfg = {
        "amap_api_key": os.environ.get("AMAP_API_KEY", ""),
        "default_city": "广州市",
        "inferred_city": "广州市",
        "user_customized_city": False
    }
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            default_cfg.update(cfg)
        except Exception:
            pass
    # 本地配置优先（密钥只放这里，不进仓库）
    if LOCAL_CONFIG_FILE.exists():
        try:
            local_cfg = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
            default_cfg.update({k: v for k, v in local_cfg.items() if v})
        except Exception:
            pass
    return default_cfg

def save_app_config(cfg: dict):
    # 密钥只写本地文件（不进仓库），其余写 config.json
    local_cfg = {}
    if cfg.get("amap_api_key"):
        local_cfg["amap_api_key"] = cfg["amap_api_key"]
    LOCAL_CONFIG_FILE.write_text(json.dumps(local_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    public_cfg = {k: v for k, v in cfg.items() if k != "amap_api_key"}
    CONFIG_FILE.write_text(json.dumps(public_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

app_config = load_app_config()
amap_client = AmapClient(
    api_key=app_config.get("amap_api_key", ""),
    default_city=app_config.get("default_city", "广州市")
)

def update_inferred_city_from_params() -> str:
    """根据已加载工参的平均经纬度，自动推断出所在城市并更新默认检索城市"""
    summary = param_loader.get_summary()
    clng = summary.get("center_lng", 113.33)
    clat = summary.get("center_lat", 23.13)
    inferred_city = amap_client.reverse_geocode_city(clng, clat, is_wgs84=True)
    if inferred_city:
        app_config["inferred_city"] = inferred_city
        # 若用户尚未手动锁定城市，默认城市跟随工参自动更新
        if not app_config.get("user_customized_city"):
            app_config["default_city"] = inferred_city
            amap_client.default_city = inferred_city
        save_app_config(app_config)
    return inferred_city

# 全局对象
param_loader = ParamLoader()
data_matcher = DataMatcher()
diagnosis_engine = DiagnosisEngine()
report_generator = ReportGenerator()
task_manager = TaskManager()

# 全局状态（内存缓存当前会话）
session_state = {
    "params_loaded": False,
    "selected_cells": None,       # pd.DataFrame
    "alarm_df": None,
    "kpi_df": None,
    "merged_df": None,
    "diagnosed_df": None,
    "event_info": None,
    "param_summary": None,
    "diag_summary": None,
    "current_task_id": None,
}


# ---------------------------------------------------------------------------
# 主页
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>系统正在初始化...</h1>")


# ---------------------------------------------------------------------------
# 健康检查与工参管理接口
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/params/status")
async def get_param_status():
    """获取工参加载状态并同步返回全量小区数据用于地图扇区渲染（默认启动不主动加载任何工参或图层）"""
    if session_state.get("params_loaded"):
        summary = dict(session_state["param_summary"])
        summary["loaded"] = True
        if param_loader.all_cells is not None and not param_loader.all_cells.empty:
            summary["cells"] = sanitize_cell_records(param_loader.all_cells)
        return summary
    return {"loaded": False, "message": "工参尚未加载", "total_sites": 0, "total_cells": 0, "lte_cells": 0, "nr_cells": 0}


@app.post("/api/params/load")
async def load_params(
    lte_file: UploadFile = File(None),
    nr_file: UploadFile = File(None),
    use_default: bool = Form(False),
):
    """加载工参文件（上传或使用默认内置数据）"""
    try:
        lte_path = None
        nr_path = None

        if use_default:
            from app.cell_db import DEFAULT_DB_PATH
            if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
                param_loader.load_from_sqlite(str(DEFAULT_DB_PATH))
                summary = param_loader.get_summary()
                summary["loaded"] = True
                inferred_city = update_inferred_city_from_params()
                summary["inferred_city"] = inferred_city
                summary["default_city"] = app_config.get("default_city", inferred_city)
                session_state["params_loaded"] = True
                session_state["param_summary"] = summary
                if param_loader.all_cells is not None and not param_loader.all_cells.empty:
                    summary["cells"] = sanitize_cell_records(param_loader.all_cells)
                return summary
            return param_loader.get_summary()
        else:
            # 保存上传文件到临时位置
            if lte_file and lte_file.filename:
                lte_tmp = DATA_DIR / f"_uploaded_lte_{lte_file.filename}"
                content = await lte_file.read()
                lte_tmp.write_bytes(content)
                lte_path = str(lte_tmp)
            if nr_file and nr_file.filename:
                nr_tmp = DATA_DIR / f"_uploaded_nr_{nr_file.filename}"
                content = await nr_file.read()
                nr_tmp.write_bytes(content)
                nr_path = str(nr_tmp)

        if not lte_path and not nr_path:
            raise HTTPException(status_code=400, detail="未提供任何工参文件")

        param_loader.load_all(lte_path=lte_path, nr_path=nr_path)
        summary = param_loader.get_summary()
        summary["loaded"] = True

        # 从工参经纬度自动推断所属城市
        inferred_city = update_inferred_city_from_params()
        summary["inferred_city"] = inferred_city
        summary["default_city"] = app_config.get("default_city", inferred_city)

        session_state["params_loaded"] = True
        session_state["param_summary"] = summary

        return summary
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"工参加载失败: {str(e)}")

@app.get("/api/params/template")


async def download_param_template(rat: Optional[str] = None):
    """导出标准工参模板 Excel (含 4G 和 5G 工作表及示例数据)"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        wb.remove(wb.active)

        columns_zh = [
            "制式", "基站编号", "基站名称", "小区编号", "小区名称", "CGI",
            "经度", "纬度", "频段", "方位角", "下倾角", "覆盖类型"
        ]

        lte_samples = [
            ["4G", "634357", "示例江津珞璜站", "183", "示例江津珞璜1小区", "162395575", 106.443518, 29.271463, "1850", 340, 6, "室外"],
            ["4G", "634357", "示例江津珞璜站", "185", "示例江津珞璜2小区", "162395577", 106.443518, 29.271463, "1650", 120, 6, "室内"],
        ]
        nr_samples = [
            ["5G", "10092545", "示例南岸放牛村站", "256", "示例放牛村1小区", "41339064576", 106.64771, 29.58152, "3.5G", 140, 6, "室外"],
            ["5G", "10092545", "示例南岸放牛村站", "257", "示例放牛村2小区", "41339064577", 106.64771, 29.58152, "3.5G", 20, 6, "室外"],
        ]

        sheets_to_create = []
        if rat == "4G":
            sheets_to_create.append(("4G工参模板", lte_samples))
        elif rat == "5G":
            sheets_to_create.append(("5G工参模板", nr_samples))
        else:
            sheets_to_create.append(("4G (LTE) 工参模板", lte_samples))
            sheets_to_create.append(("5G (NR) 工参模板", nr_samples))

        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name="黑体", size=10, bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center")
        body_font = Font(name="宋体", size=10)
        body_alignment = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9")
        )

        for sheet_title, samples in sheets_to_create:
            ws = wb.create_sheet(title=sheet_title)
            ws.views.sheetView[0].showGridLines = True
            ws.row_dimensions[1].height = 26

            ws.append(columns_zh)
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_alignment
                cell.border = thin_border

            for r_idx, row in enumerate(samples, start=2):
                ws.row_dimensions[r_idx].height = 20
                ws.append(row)
                for c_idx in range(1, len(row) + 1):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.font = body_font
                    cell.alignment = body_alignment
                    cell.border = thin_border

            for col_idx in range(1, len(columns_zh) + 1):
                col_letter = get_column_letter(col_idx)
                header_val = columns_zh[col_idx - 1]
                max_len = 0
                for ch in header_val:
                    max_len += 2 if ord(ch) > 127 else 1
                for row_data in samples:
                    val_str = str(row_data[col_idx - 1])
                    v_len = sum(2 if ord(c) > 127 else 1 for c in val_str)
                    if v_len > max_len:
                        max_len = v_len
                ws.column_dimensions[col_letter].width = max(max_len + 5, 12)

        fname = "工参导入标准模板.xlsx" if not rat else f"{rat}工参标准模板.xlsx"
        fpath = OUTPUT_DIR / fname
        wb.save(str(fpath))

        return FileResponse(
            str(fpath),
            filename=fname,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"生成工参模板失败: {str(e)}")


# ---------------------------------------------------------------------------
# 高德地图配置接口 (API Key 与 默认城市)
# ---------------------------------------------------------------------------
@app.get("/api/config/amap")
async def get_amap_config():
    """获取当前高德 API 配置与工参推断城市"""
    key = app_config.get("amap_api_key", "")
    masked_key = ""
    if key:
        if len(key) >= 12:
            masked_key = key[:4] + "*" * (len(key) - 8) + key[-4:]
        else:
            masked_key = "****"
            
    return {
        "configured": bool(key),
        "api_key_masked": masked_key,
        "default_city": app_config.get("default_city", "广州市"),
        "inferred_city": app_config.get("inferred_city", "广州市"),
        "user_customized_city": app_config.get("user_customized_city", False)
    }


@app.post("/api/config/amap")
async def save_amap_config(
    api_key: str = Form(""),
    city: str = Form(""),
    test_now: bool = Form(True)
):
    """保存高德 API Key 与 优先检索城市配置"""
    api_key = api_key.strip()
    city = city.strip()

    # 若输入为掩码字符且已有有效 key，则沿用原 key
    if "*" in api_key:
        api_key = app_config.get("amap_api_key", "")

    if api_key and test_now:
        valid, msg = amap_client.test_key(api_key)
        if not valid:
            return JSONResponse(status_code=400, content={"success": False, "message": msg})

    app_config["amap_api_key"] = api_key
    if city:
        app_config["default_city"] = city
        app_config["user_customized_city"] = True
    else:
        app_config["user_customized_city"] = False

    amap_client.set_config(api_key, app_config["default_city"])
    save_app_config(app_config)

    return {
        "success": True,
        "message": "高德地图 API Key 已成功生效！已启用高精度检索服务。",
        "default_city": app_config["default_city"]
    }


@app.post("/api/config/amap/test")
async def test_amap_key(api_key: str = Form(...)):
    """单次测试指定的 API Key 连通性"""
    api_key = api_key.strip()
    if "*" in api_key:
        api_key = app_config.get("amap_api_key", "")
    valid, msg = amap_client.test_key(api_key)
    return {"valid": valid, "message": msg}


# ---------------------------------------------------------------------------
# 空间与地理编码搜索接口
# ---------------------------------------------------------------------------
PRESET_LANDMARKS = [
    {"name": "大坪", "address": "重庆市渝中区大坪正街", "lng": 106.5165, "lat": 29.5394},
    {"name": "大坪街道", "address": "重庆市渝中区大坪街道", "lng": 106.5165, "lat": 29.5394},
    {"name": "重庆市渝中区大坪街道", "address": "重庆市渝中区大坪正街", "lng": 106.5165, "lat": 29.5394},
    {"name": "解放碑步行街", "address": "重庆市渝中区民族路177号", "lng": 106.5771, "lat": 29.5572},
    {"name": "观音桥步行街", "address": "重庆市江北区观音桥北城天街", "lng": 106.5332, "lat": 29.5768},
    {"name": "南坪步行街", "address": "重庆市南岸区南坪东路", "lng": 106.5684, "lat": 29.5262},
    {"name": "沙坪坝三峡广场", "address": "重庆市沙坪坝区小新街", "lng": 106.4578, "lat": 29.5539},
    {"name": "重庆北站", "address": "重庆市渝北区昆仑大道51号", "lng": 106.5513, "lat": 29.6053},
    {"name": "重庆西站", "address": "重庆市沙坪坝区凤中路168号", "lng": 106.4294, "lat": 29.5074},
    {"name": "江北国际机场", "address": "重庆市渝北区机场路", "lng": 106.6439, "lat": 29.7188},
    {"name": "南川水江", "address": "重庆市南川区水江镇", "lng": 107.3821, "lat": 29.2842},
    {"name": "水江交通医院", "address": "重庆市南川区水江镇交通医院", "lng": 107.3825, "lat": 29.2846},
    {"name": "水江监狱", "address": "重庆市南川区水江镇监狱", "lng": 107.3830, "lat": 29.2850},
    {"name": "天河体育中心", "address": "广东省广州市天河区天河路299号", "lng": 113.3196, "lat": 23.1401},
    {"name": "珠江新城", "address": "广东省广州市天河区华夏路/花城广场", "lng": 113.3158, "lat": 23.1220},
    {"name": "广州塔 (小蛮腰)", "address": "广东省广州市海珠区阅江西路222号", "lng": 113.3191, "lat": 23.1090},
]

@app.get("/api/spatial/geocode")
@app.get("/api/search/geocode")
async def search_address(
    keyword: str = "",
    address: str = "",
    coord_sys: str = "wgs84"
):
    """地址与地标地理编码精准搜索（优先使用高德开放平台Web服务精准检索）"""
    kw = (keyword or address or "").strip()
    if not kw:
        return {"results": [], "provider": "empty"}

    results = []
    seen = set()

    # 0. 优先检测经纬度文本输入直接定位（如 "113.32, 23.13"、"113.32 23.13"、"23.13, 113.32"）
    coords = parse_coordinates(kw)
    if coords:
        c_lng, c_lat = coords
        if coord_sys == "gcj02":
            gcj_lng, gcj_lat = c_lng, c_lat
            wgs_lng, wgs_lat = gcj02_to_wgs84(c_lng, c_lat)
        else:
            wgs_lng, wgs_lat = c_lng, c_lat
            gcj_lng, gcj_lat = wgs84_to_gcj02(c_lng, c_lat)

        active_lng = gcj_lng if coord_sys == "gcj02" else wgs_lng
        active_lat = gcj_lat if coord_sys == "gcj02" else wgs_lat

        city_name = amap_client.infer_city_by_coords(active_lng, active_lat) if hasattr(amap_client, "infer_city_by_coords") else "坐标直达"
        results.append({
            "name": f"坐标定位 ({c_lng}, {c_lat})",
            "address": f"经度: {c_lng}, 纬度: {c_lat}（{coord_sys.upper()} 坐标定位）",
            "district": city_name or "坐标直达",
            "lng": active_lng,
            "lat": active_lat,
            "lng_wgs": wgs_lng,
            "lat_wgs": wgs_lat,
            "lng_gcj": gcj_lng,
            "lat_gcj": gcj_lat,
            "source": "经纬度定位",
            "type": "coord",
        })
        return {"results": results, "provider": "coordinates"}

    # 1. 优先使用高德 Web 服务精准检索
    if amap_client.is_configured():
        city = app_config.get("default_city", "")
        # POI 关键字搜索
        amap_pois = amap_client.search_poi(kw, city=city)
        # 若 POI 结果较少，补充详细地址地理编码解析
        if len(amap_pois) < 3:
            amap_geos = amap_client.geocode(kw, city=city)
            amap_pois.extend(amap_geos)

        if amap_pois:
            for item in amap_pois:
                key = (round(item["lng_wgs"], 4), round(item["lat_wgs"], 4))
                if key not in seen:
                    seen.add(key)
                    active_lng = item["lng_gcj"] if coord_sys == "gcj02" else item["lng_wgs"]
                    active_lat = item["lat_gcj"] if coord_sys == "gcj02" else item["lat_wgs"]
                    results.append({
                        "name": item["name"],
                        "address": item["address"],
                        "district": item.get("district", ""),
                        "lng": active_lng,
                        "lat": active_lat,
                        "lng_wgs": item["lng_wgs"],
                        "lat_wgs": item["lat_wgs"],
                        "lng_gcj": item["lng_gcj"],
                        "lat_gcj": item["lat_gcj"],
                        "source": "高德精准检索",
                        "type": "amap",
                    })
            if results:
                return {"results": results[:10], "provider": "amap"}

    # 2. 备用容灾链 A：优先搜索已载入的工参底座（基站/小区名）
    if session_state["params_loaded"] and param_loader.all_cells is not None:
        try:
            df = param_loader.all_cells
            kw_lower = kw.lower()
            mask = (
                df["site_name"].astype(str).str.lower().str.contains(kw_lower, na=False) |
                df["cell_name"].astype(str).str.lower().str.contains(kw_lower, na=False) |
                df["site_id"].astype(str).str.lower().str.contains(kw_lower, na=False)
            )
            matched_cells = df[mask].head(4)
            for _, row in matched_cells.iterrows():
                key = (round(float(row["longitude"]), 4), round(float(row["latitude"]), 4))
                if key not in seen:
                    seen.add(key)
                    wgs_lng = float(row["longitude"])
                    wgs_lat = float(row["latitude"])
                    gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
                    active_lng = gcj_lng if coord_sys == "gcj02" else wgs_lng
                    active_lat = gcj_lat if coord_sys == "gcj02" else wgs_lat

                    results.append({
                        "name": str(row["site_name"]),
                        "address": f"基站编号: {row['site_id']} / 制式: {row['rat']} / 覆盖: {row.get('cover_type', '-')}",
                        "district": "已载入工参",
                        "lng": active_lng,
                        "lat": active_lat,
                        "lng_wgs": wgs_lng,
                        "lat_wgs": wgs_lat,
                        "lng_gcj": gcj_lng,
                        "lat_gcj": gcj_lat,
                        "source": "工参基站",
                        "type": "site",
                    })
        except Exception as e:
            print("搜索工参基站异常:", e)

    # 3. 备用容灾链 B：搜索预置应急常用地标库
    kw_lower = kw.lower()
    for item in PRESET_LANDMARKS:
        if kw_lower in item["name"].lower() or kw_lower in item["address"].lower():
            wgs_lng = item["lng"]
            wgs_lat = item["lat"]
            key = (round(wgs_lng, 4), round(wgs_lat, 4))
            if key not in seen:
                seen.add(key)
                gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
                active_lng = gcj_lng if coord_sys == "gcj02" else wgs_lng
                active_lat = gcj_lat if coord_sys == "gcj02" else wgs_lat
                results.append({
                    "name": item["name"],
                    "address": item["address"],
                    "district": "常用地标",
                    "lng": active_lng,
                    "lat": active_lat,
                    "lng_wgs": wgs_lng,
                    "lat_wgs": wgs_lat,
                    "lng_gcj": gcj_lng,
                    "lat_gcj": gcj_lat,
                    "source": "常用地标",
                    "type": "landmark",
                })

    # 4. 备用容灾链 C：在线公共地图 POI 服务 (Nominatim)
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": kw,
            "format": "json",
            "limit": 6,
            "countrycodes": "cn"
        })
        req = urllib.request.Request(url, headers={"User-Agent": "EmergencyWirelessAssurance/1.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data:
                wgs_lng = float(item["lon"])
                wgs_lat = float(item["lat"])
                key = (round(wgs_lng, 4), round(wgs_lat, 4))
                if key not in seen:
                    seen.add(key)
                    gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
                    active_lng = gcj_lng if coord_sys == "gcj02" else wgs_lng
                    active_lat = gcj_lat if coord_sys == "gcj02" else wgs_lat
                    name = item.get("name") or item["display_name"].split(",")[0]
                    results.append({
                        "name": name,
                        "address": item["display_name"],
                        "district": "在线公共POI",
                        "lng": active_lng,
                        "lat": active_lat,
                        "lng_wgs": wgs_lng,
                        "lat_wgs": wgs_lat,
                        "lng_gcj": gcj_lng,
                        "lat_gcj": gcj_lat,
                        "source": "在线POI",
                        "type": "online",
                    })
    except Exception as e:
        print("公共地理编码服务请求略过:", e)

    return {"results": results[:10], "provider": "fallback"}


def ensure_params_loaded():
    """若工参尚未载入，自动尝试从 SQLite 数据库加载已有工参"""
    if session_state.get("params_loaded") and param_loader.all_cells is not None and not param_loader.all_cells.empty:
        return
    from app.cell_db import DEFAULT_DB_PATH
    if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
        try:
            param_loader.load_from_sqlite(str(DEFAULT_DB_PATH))
            summary = param_loader.get_summary()
            summary["loaded"] = True
            inferred_city = update_inferred_city_from_params()
            summary["inferred_city"] = inferred_city
            summary["default_city"] = app_config.get("default_city", inferred_city)
            session_state["params_loaded"] = True
            session_state["param_summary"] = summary
        except Exception as e:
            logger.warning("从 SQLite 自动载入工参异常: %s", e)

# ---------------------------------------------------------------------------
# 空间圈选接口
# ---------------------------------------------------------------------------
@app.post("/api/spatial/circle")
async def query_circle(
    center_lng: float = Form(...),
    center_lat: float = Form(...),
    radius_m: float = Form(1000),
    coord_sys: str = Form("wgs84"),
    event_name: str = Form(""),
    address: str = Form(""),
):
    """圆形圈选"""
    ensure_params_loaded()
    if not session_state.get("params_loaded"):
        raise HTTPException(status_code=400, detail="工参尚未载入，请先加载工参数据")

    try:
        result_df = param_loader.query_circle(center_lng, center_lat, radius_m, coord_sys)
        session_state["selected_cells"] = result_df
        session_state["event_info"] = {
            "center_lng": center_lng,
            "center_lat": center_lat,
            "radius": radius_m,
            "coord_sys": coord_sys,
            "area_desc": f"以({center_lng:.6f}, {center_lat:.6f})为中心, 半径{radius_m}m",
            "event_name": event_name,
            "address": address,
        }

        # 频段分布统计
        freq_dist = {}
        if "freq_band" in result_df.columns:
            freq_dist = result_df["freq_band"].value_counts().to_dict()

        records = sanitize_cell_records(result_df.head(2000))
        total_sites = int(result_df["site_id"].nunique()) if "site_id" in result_df.columns else 0
        lte_cells = int((result_df["rat"] == "4G").sum()) if "rat" in result_df.columns else 0
        nr_cells = int((result_df["rat"] == "5G").sum()) if "rat" in result_df.columns else 0
        r_km = radius_m / 1000.0
        area_km2 = round(math.pi * r_km * r_km, 2)

        resolved_name = (event_name or address or "").strip() or f"圆形圈选保障({int(radius_m)}米)"
        resolved_address = (address or "").strip() or f"{center_lat:.4f}°N, {center_lng:.4f}°E"

        task_record = task_manager.create_task(
            event_name=resolved_name,
            address=resolved_address,
            shape_type="circle",
            shape_params={
                "center_lng": center_lng,
                "center_lat": center_lat,
                "radius_m": radius_m,
                "coord_sys": coord_sys,
            },
            metrics={
                "total_sites": total_sites,
                "total_cells": len(result_df),
                "lte_cells": lte_cells,
                "nr_cells": nr_cells,
                "area_km2": area_km2,
            },
            cells=records
        )
        session_state["current_task_id"] = task_record["task_id"]

        return {
            "task_id": task_record["task_id"],
            "total_cells": len(result_df),
            "total_sites": total_sites,
            "lte_cells": lte_cells,
            "nr_cells": nr_cells,
            "freq_distribution": {str(k): int(v) for k, v in freq_dist.items() if not pd.isna(k)},
            "cells": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"圈选失败: {str(e)}")


@app.post("/api/spatial/polygon")
async def query_polygon(
    polygon: str = Form(...),
    coord_sys: str = Form("wgs84"),
    event_name: str = Form(""),
    address: str = Form(""),
):
    """多边形圈选。polygon 是 JSON 数组 [[lng,lat], ...]"""
    ensure_params_loaded()
    if not session_state.get("params_loaded"):
        raise HTTPException(status_code=400, detail="工参尚未载入，请先加载工参数据")

    try:
        polygon_coords = json.loads(polygon)
    except Exception:
        raise HTTPException(status_code=400, detail="多边形坐标格式错误")

    if not isinstance(polygon_coords, list):
        raise HTTPException(status_code=400, detail="多边形必须是坐标点列表")

    clean_pts = []
    for p in polygon_coords:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                px = float(p[0])
                py = float(p[1])
                if not (math.isnan(px) or math.isnan(py) or math.isinf(px) or math.isinf(py)):
                    clean_pts.append([px, py])
            except (ValueError, TypeError):
                continue

    if len(clean_pts) < 3:
        raise HTTPException(status_code=400, detail="多边形必须至少包含 3 个有效顶点坐标")

    try:
        result_df = param_loader.query_polygon(clean_pts, coord_sys)
        session_state["selected_cells"] = result_df

        c_lng = sum(p[0] for p in clean_pts) / len(clean_pts)
        c_lat = sum(p[1] for p in clean_pts) / len(clean_pts)

        session_state["event_info"] = {
            "center_lng": c_lng,
            "center_lat": c_lat,
            "radius": None,
            "coord_sys": coord_sys,
            "area_desc": f"自定义多边形区域({len(clean_pts)}个顶点)",
            "event_name": event_name,
            "address": address,
        }

        freq_dist = {}
        if "freq_band" in result_df.columns:
            freq_dist = result_df["freq_band"].value_counts().to_dict()

        records = sanitize_cell_records(result_df.head(2000))
        total_sites = int(result_df["site_id"].nunique()) if "site_id" in result_df.columns else 0
        lte_cells = int((result_df["rat"] == "4G").sum()) if "rat" in result_df.columns else 0
        nr_cells = int((result_df["rat"] == "5G").sum()) if "rat" in result_df.columns else 0
        area_km2 = round(len(clean_pts) * 3.5, 2)

        resolved_name = (event_name or address or "").strip() or f"多边形圈选({len(clean_pts)}顶点)"
        resolved_address = (address or "").strip() or f"{c_lat:.4f}°N, {c_lng:.4f}°E"

        task_record = task_manager.create_task(
            event_name=resolved_name,
            address=resolved_address,
            shape_type="polygon",
            shape_params={
                "center_lng": c_lng,
                "center_lat": c_lat,
                "polygon_coords": clean_pts,
                "coord_sys": coord_sys,
            },
            metrics={
                "total_sites": total_sites,
                "total_cells": len(result_df),
                "lte_cells": lte_cells,
                "nr_cells": nr_cells,
                "area_km2": area_km2,
            },
            cells=records
        )
        session_state["current_task_id"] = task_record["task_id"]

        return {
            "task_id": task_record["task_id"],
            "total_cells": len(result_df),
            "total_sites": total_sites,
            "lte_cells": lte_cells,
            "nr_cells": nr_cells,
            "freq_distribution": {str(k): int(v) for k, v in freq_dist.items() if not pd.isna(k)},
            "cells": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"多边形圈选执行失败: {str(e)}")


@app.post("/api/spatial/import_boundary")
async def import_boundary_endpoint(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    coord_sys: str = Form("wgs84"),
):
    """解析经纬度边界文件或文本，提取活动名称、起止时间与所有多边形区域边界"""
    content = ""
    if file:
        raw_bytes = await file.read()
        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw_bytes.decode("gbk")
            except Exception:
                content = raw_bytes.decode("utf-8", errors="ignore")
    elif text:
        content = text

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="未接收到有效的边界文件或文本内容")

    res = parse_boundary_content(content, coord_sys=coord_sys)
    if res["total_regions"] == 0:
        raise HTTPException(
            status_code=400,
            detail="未能从输入内容中识别出有效的经纬度多边形边界，请检查格式是否包含“事件区域”及“经纬度范围: {...}”或标准 GeoJSON"
        )

    res["coord_sys"] = coord_sys
    return res


@app.post("/api/spatial/multipolygon")
async def query_multipolygon(
    multipolygon: str = Form(...),
    coord_sys: str = Form("wgs84"),
    event_name: str = Form(""),
    address: str = Form(""),
):
    """多个多边形联合圈选"""
    ensure_params_loaded()
    if not session_state.get("params_loaded"):
        raise HTTPException(status_code=400, detail="工参尚未载入，请先加载工参数据")

    try:
        polygons_coords = json.loads(multipolygon)
    except Exception:
        raise HTTPException(status_code=400, detail="多边形组合坐标格式错误")

    if not isinstance(polygons_coords, list) or len(polygons_coords) == 0:
        raise HTTPException(status_code=400, detail="多边形列表不能为空")

    try:
        result_df = param_loader.query_multipolygon(polygons_coords, coord_sys)
        session_state["selected_cells"] = result_df

        # 计算所有多边形的综合质心
        all_pts = [pt for poly in polygons_coords for pt in poly if len(pt) >= 2]
        c_lng = sum(p[0] for p in all_pts) / len(all_pts) if all_pts else 106.5
        c_lat = sum(p[1] for p in all_pts) / len(all_pts) if all_pts else 29.5

        session_state["event_info"] = {
            "center_lng": c_lng,
            "center_lat": c_lat,
            "radius": None,
            "coord_sys": coord_sys,
            "area_desc": f"组合多边形区域({len(polygons_coords)}个多边形/共{len(all_pts)}个顶点)",
            "event_name": event_name,
            "address": address,
        }

        freq_dist = {}
        if "freq_band" in result_df.columns:
            freq_dist = result_df["freq_band"].value_counts().to_dict()

        records = sanitize_cell_records(result_df.head(2000))
        total_sites = int(result_df["site_id"].nunique()) if "site_id" in result_df.columns else 0
        lte_cells = int((result_df["rat"] == "4G").sum()) if "rat" in result_df.columns else 0
        nr_cells = int((result_df["rat"] == "5G").sum()) if "rat" in result_df.columns else 0
        area_km2 = round(len(all_pts) * 3.5, 2)

        resolved_name = (event_name or address or "").strip() or f"多区域联合圈选({len(polygons_coords)}个区域)"
        resolved_address = (address or "").strip() or f"{c_lat:.4f}°N, {c_lng:.4f}°E"

        task_record = task_manager.create_task(
            event_name=resolved_name,
            address=resolved_address,
            shape_type="multipolygon",
            shape_params={
                "center_lng": c_lng,
                "center_lat": c_lat,
                "polygons_coords": polygons_coords,
                "coord_sys": coord_sys,
            },
            metrics={
                "total_sites": total_sites,
                "total_cells": len(result_df),
                "lte_cells": lte_cells,
                "nr_cells": nr_cells,
                "area_km2": area_km2,
            },
            cells=records
        )
        session_state["current_task_id"] = task_record["task_id"]

        return {
            "task_id": task_record["task_id"],
            "total_cells": len(result_df),
            "total_sites": total_sites,
            "lte_cells": lte_cells,
            "nr_cells": nr_cells,
            "freq_distribution": {str(k): int(v) for k, v in freq_dist.items() if not pd.isna(k)},
            "cells": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"组合多边形圈选执行失败: {str(e)}")


@app.get("/api/spatial/export")
async def export_selected_cells():
    """导出当前圈选的工参清单为 Excel (中文表头并自适应排版)"""
    if session_state["selected_cells"] is None or session_state["selected_cells"].empty:
        raise HTTPException(status_code=400, detail="暂无圈选结果")

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"圈选工参清单_{ts}.xlsx"
        fpath = OUTPUT_DIR / fname

        export_df = session_state["selected_cells"].copy()

        # 排除内部临时列
        internal_cols = [c for c in export_df.columns if str(c).startswith("_")]
        if internal_cols:
            export_df.drop(columns=internal_cols, inplace=True, errors="ignore")

        # 将列名替换为中文
        rename_map = {col: COLUMN_ZH_MAP.get(str(col), str(col)) for col in export_df.columns}
        export_df.rename(columns=rename_map, inplace=True)

        export_df.to_excel(str(fpath), index=False, engine="openpyxl")

        # 美化格式（深蓝表头与自适应列宽）
        try:
            from openpyxl import load_workbook
            from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
            from openpyxl.utils import get_column_letter

            wb = load_workbook(str(fpath))
            ws = wb.active
            header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            header_font = Font(name="黑体", size=10, bold=True, color="FFFFFF")
            header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            body_font = Font(name="宋体", size=10)
            body_alignment = Alignment(horizontal="center", vertical="center")
            thin_border = Border(
                left=Side(style="thin", color="D9D9D9"),
                right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"),
                bottom=Side(style="thin", color="D9D9D9")
            )

            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_alignment

            for col_idx in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_idx)
                header_val = str(ws.cell(row=1, column=col_idx).value or "")
                max_len = 0
                for ch in header_val:
                    max_len += 2 if ord(ch) > 127 else 1

                for row_idx in range(2, min(ws.max_row + 1, 80)):
                    c = ws.cell(row=row_idx, column=col_idx)
                    c.font = body_font
                    c.alignment = body_alignment
                    c.border = thin_border
                    val_str = str(c.value or "")
                    if val_str:
                        val_len = sum(2 if ord(ch) > 127 else 1 for ch in val_str)
                        if val_len > max_len:
                            max_len = val_len

                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 11), 40)

            wb.save(str(fpath))
        except Exception as style_err:
            print(f"[Export] 美化 Excel 异常，保留默认表: {style_err}")

        if session_state.get("current_task_id"):
            task_manager.update_task(session_state["current_task_id"], {
                "artifacts": {"excel_path": fname}
            })

        return FileResponse(str(fpath), filename=fname,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


# ---------------------------------------------------------------------------
# 数据匹配接口
# ---------------------------------------------------------------------------
@app.post("/api/match/upload")
async def upload_match_data(
    alarm_file: UploadFile = File(None),
    kpi_file: UploadFile = File(None),
    kpi_files: List[UploadFile] = File(None),
    use_default: bool = Form(False),
):
    """上传网管告警和性能指标文件并执行匹配（支持汇总最多6个4G/5G多网管指标文件）"""
    if session_state["selected_cells"] is None or session_state["selected_cells"].empty:
        raise HTTPException(status_code=400, detail="请先完成空间圈选")

    try:
        alarm_df = None
        kpi_df = None
        kpi_file_names = []

        if use_default:
            alarm_default = BASE_DIR / "故障模板.csv"
            if not alarm_default.exists():
                alarm_default = DATA_DIR / "sample_alarms.csv"
            if alarm_default.exists():
                alarm_df = data_matcher.load_alarm_file(str(alarm_default), alarm_default.name)

            # 默认优先寻找项目下的《应急查询4G》和《应急查询5G》多网管导出文件
            default_kpi_paths = list(BASE_DIR.glob("*应急查询4G*.csv")) + list(BASE_DIR.glob("*应急查询5G*.csv"))
            default_kpi_paths = default_kpi_paths[:6]
            if not default_kpi_paths:
                single_default = BASE_DIR / "性能指标.csv"
                if not single_default.exists():
                    single_default = DATA_DIR / "sample_kpi.csv"
                if single_default.exists():
                    default_kpi_paths = [single_default]

            if default_kpi_paths:
                kpi_df = data_matcher.aggregate_kpi_files(
                    [str(p) for p in default_kpi_paths],
                    [p.name for p in default_kpi_paths],
                )
                kpi_file_names = [p.name for p in default_kpi_paths]
        else:
            if alarm_file and alarm_file.filename:
                content = await alarm_file.read()
                alarm_df = data_matcher.load_alarm_file(
                    io.BytesIO(content), alarm_file.filename
                )

            # 收集所有上传的 KPI 指标文件（兼容单文件与多文件，支持4G/5G多网管）
            all_kpi_uploads = []
            if kpi_files:
                all_kpi_uploads.extend([f for f in kpi_files if f and f.filename])
            if kpi_file and kpi_file.filename:
                if not any(f.filename == kpi_file.filename for f in all_kpi_uploads):
                    all_kpi_uploads.append(kpi_file)

            if len(all_kpi_uploads) > 6:
                raise HTTPException(status_code=400, detail="网管指标文件最多支持上传 6 个文件（含4G/5G）")

            if all_kpi_uploads:
                kpi_file_streams = []
                for upload in all_kpi_uploads[:6]:
                    c = await upload.read()
                    kpi_file_streams.append(io.BytesIO(c))
                    kpi_file_names.append(upload.filename)

                kpi_df = data_matcher.aggregate_kpi_files(
                    kpi_file_streams, kpi_file_names
                )

        if alarm_df is None and kpi_df is None:
            raise HTTPException(status_code=400, detail="未提供任何网管数据文件")

        session_state["alarm_df"] = alarm_df
        session_state["kpi_df"] = kpi_df

        # 执行匹配
        merged_df = data_matcher.match_data(
            session_state["selected_cells"], alarm_df, kpi_df
        )
        session_state["merged_df"] = merged_df

        # 统计匹配情况
        match_stats = merged_df["match_status"].value_counts().to_dict() if "match_status" in merged_df.columns else {}

        msg = "数据匹配完成"
        if kpi_file_names:
            msg = f"数据匹配完成，已汇总 {len(kpi_file_names)} 个网管指标文件（共 {len(kpi_df) if kpi_df is not None else 0} 个小区指标）"

        return {
            "total_matched": len(merged_df),
            "match_statistics": {str(k): int(v) for k, v in match_stats.items()},
            "alarm_count": len(alarm_df) if alarm_df is not None else 0,
            "kpi_count": len(kpi_df) if kpi_df is not None else 0,
            "kpi_file_count": len(kpi_file_names),
            "kpi_file_names": kpi_file_names,
            "message": msg,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据匹配失败: {str(e)}")


# ---------------------------------------------------------------------------
# 智能诊断接口
# ---------------------------------------------------------------------------
@app.post("/api/diagnosis/run")
async def run_diagnosis():
    """执行智能诊断"""
    if session_state["merged_df"] is None or session_state["merged_df"].empty:
        raise HTTPException(status_code=400, detail="请先完成数据匹配")

    try:
        diagnosed_df = diagnosis_engine.diagnose(session_state["merged_df"])
        session_state["diagnosed_df"] = diagnosed_df

        diag_summary = diagnosis_engine.get_summary(diagnosed_df)
        
        # 组装完整的异常小区清单，并补齐级别标识
        p0 = diag_summary.get("p0_cells", [])
        for c in p0: c["diag_level"] = c.get("diag_level") or "P0"
        p1 = diag_summary.get("p1_cells", [])
        for c in p1: c["diag_level"] = c.get("diag_level") or "P1"
        p2 = diag_summary.get("p2_cells", [])
        for c in p2: c["diag_level"] = c.get("diag_level") or "P2"
        diag_summary["diagnosed_cells"] = p0 + p1 + p2
        session_state["diag_summary"] = diag_summary

        if session_state.get("current_task_id"):
            task_manager.update_task(session_state["current_task_id"], {
                "diagnosis": {
                    "status": "completed",
                    "p0_count": diag_summary.get("p0_count", 0),
                    "p1_count": diag_summary.get("p1_count", 0),
                    "p2_count": diag_summary.get("p2_count", 0),
                    "normal_count": diag_summary.get("normal_count", 0),
                    "diagnosed_cells": diag_summary.get("diagnosed_cells", []),
                    "summary_text": diag_summary.get("summary_text", "")
                }
            })

        return diag_summary
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"诊断执行失败: {str(e)}")


# ---------------------------------------------------------------------------
# 报告生成接口
# ---------------------------------------------------------------------------
@app.post("/api/report/generate")
async def generate_report(
    event_name: str = Form("应急通信保障事件"),
):
    """生成 Word 报告和 Excel 清单"""
    if session_state["diagnosed_df"] is None or session_state["diagnosed_df"].empty:
        raise HTTPException(status_code=400, detail="请先导入告警或性能表比对指标")

    try:
        diagnosed_df = session_state["diagnosed_df"]
        event_info = session_state.get("event_info", {})
        event_info["event_name"] = event_name
        event_info["trigger_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 仅针对圈选边框范围内的小区与基站进行现状统计
        rat_col = diagnosed_df["rat"].astype(str).str.upper() if "rat" in diagnosed_df.columns else pd.Series([], dtype=str)
        if "site_id" in diagnosed_df.columns and diagnosed_df["site_id"].notna().any():
            bounded_sites = int(diagnosed_df["site_id"].nunique())
        elif "site_name" in diagnosed_df.columns:
            bounded_sites = int(diagnosed_df["site_name"].nunique())
        else:
            bounded_sites = 0

        bounded_lte = int(rat_col.isin(["4G", "LTE"]).sum())
        bounded_nr = int(rat_col.isin(["5G", "NR"]).sum())
        bounded_freq = diagnosed_df["freq_band"].dropna().astype(str).value_counts().to_dict() if "freq_band" in diagnosed_df.columns else {}

        bounded_param_summary = {
            "total_sites": bounded_sites,
            "total_cells": len(diagnosed_df),
            "lte_cells": bounded_lte,
            "nr_cells": bounded_nr,
            "freq_band_dist": bounded_freq,
        }

        diag_summary = session_state.get("diag_summary", {})

        word_path = report_generator.generate_word(
            event_info, bounded_param_summary, diag_summary,
            diagnosed_df, str(OUTPUT_DIR),
        )
        excel_path = report_generator.generate_excel(
            diagnosed_df, event_info, str(OUTPUT_DIR),
        )

        word_filename = os.path.basename(word_path)
        excel_filename = os.path.basename(excel_path)

        if session_state.get("current_task_id"):
            task_manager.update_task(session_state["current_task_id"], {
                "event_name": event_name,
                "artifacts": {
                    "word_path": word_filename,
                    "excel_path": excel_filename,
                }
            })

        return {
            "word_file": word_filename,
            "excel_file": excel_filename,
            "message": "报告生成完成",
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"报告生成失败: {str(e)}")


@app.get("/api/report/download/{filename}")
async def download_report(filename: str):
    """下载生成的报告文件"""
    fpath = OUTPUT_DIR / filename
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    media_type = "application/octet-stream"
    if filename.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(str(fpath), filename=filename, media_type=media_type)


# ---------------------------------------------------------------------------
# 任务历史记录管理接口
# ---------------------------------------------------------------------------
@app.get("/api/tasks/recent")
async def get_recent_tasks(limit: int = 5):
    """获取最近 N 条历史保障任务"""
    tasks = task_manager.get_recent_tasks(limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/list")
async def list_tasks(keyword: str = "", limit: int = 50):
    """查询历史保障任务档案列表"""
    tasks = task_manager.get_all_tasks(keyword=keyword, limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """获取指定任务的完整信息"""
    task = task_manager.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该任务记录")
    return task


@app.post("/api/tasks/{task_id}/activate")
async def activate_task(task_id: str):
    """调阅历史任务快照，恢复后端会话上下文（无需重新执行分析）"""
    task = task_manager.get_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该任务记录")

    session_state["current_task_id"] = task["task_id"]
    if task.get("cells"):
        session_state["selected_cells"] = pd.DataFrame(task["cells"])
    if task.get("diagnosis", {}).get("diagnosed_cells"):
        session_state["diagnosed_df"] = pd.DataFrame(task["diagnosis"]["diagnosed_cells"])
    session_state["event_info"] = {
        "event_name": task.get("event_name"),
        "address": task.get("address"),
    }
    return {"success": True, "message": "历史任务档案已成功载入上下文", "task": task}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除单条历史任务"""
    success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在或已删除")
    return {"success": True, "message": "任务记录已删除"}


@app.post("/api/tasks/clear")
async def clear_tasks():
    """清空所有历史任务"""
    count = task_manager.clear_all()
    return {"success": True, "message": f"已清空 {count} 条历史任务"}


# ---------------------------------------------------------------------------
# 一键演示（加载默认数据 + 圈选 + 匹配 + 诊断）
# ---------------------------------------------------------------------------
@app.post("/api/demo/run")
async def run_demo():
    """一键演示：加载内置测试数据并执行全流程"""
    try:
        steps_completed = []

        # Step 1: 加载工参 (从 SQLite 数据库)
        from app.cell_db import DEFAULT_DB_PATH
        if DEFAULT_DB_PATH.exists() and DEFAULT_DB_PATH.stat().st_size > 0:
            param_loader.load_from_sqlite(str(DEFAULT_DB_PATH))
        elif param_loader.all_cells is not None and not param_loader.all_cells.empty:
            pass
        else:
            raise HTTPException(status_code=400, detail="未检测到工参数据库，请先通过顶部「导入工参」导入表格")
        summary = param_loader.get_summary()
        summary["loaded"] = True
        inferred_city = update_inferred_city_from_params()
        summary["inferred_city"] = inferred_city
        summary["default_city"] = app_config.get("default_city", inferred_city)

        session_state["params_loaded"] = True
        session_state["param_summary"] = summary
        steps_completed.append(f"工参加载完成 (所在地市: {inferred_city})")

        # Step 2: 圆形圈选（自适应使用工参代表中心点）
        if getattr(param_loader, "all_cells", None) is not None and not param_loader.all_cells.empty:
            center_lng = round(float(param_loader.all_cells["longitude"].median()), 4)
            center_lat = round(float(param_loader.all_cells["latitude"].median()), 4)
        else:
            center_lng = 106.48
            center_lat = 29.27
        radius_m = 5000
        result_df = param_loader.query_circle(center_lng, center_lat, radius_m, "wgs84")
        session_state["selected_cells"] = result_df
        session_state["event_info"] = {
            "event_name": "天河区暴雨内涝应急保障",
            "trigger_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "center_lng": center_lng,
            "center_lat": center_lat,
            "radius": radius_m,
            "coord_sys": "wgs84",
            "area_desc": f"以({center_lng}, {center_lat})为中心, 半径{radius_m}m",
        }
        steps_completed.append(f"圈选完成: {len(result_df)}个小区")

        # Step 3: 匹配告警与性能数据
        alarm_df = None
        kpi_df = None
        alarm_path = DATA_DIR / "sample_alarms.csv"
        kpi_path = DATA_DIR / "sample_kpi.csv"
        if alarm_path.exists():
            alarm_df = data_matcher.load_alarm_file(str(alarm_path), "sample_alarms.csv")
        if kpi_path.exists():
            kpi_df = data_matcher.load_kpi_file(str(kpi_path), "sample_kpi.csv")

        merged_df = data_matcher.match_data(result_df, alarm_df, kpi_df)
        session_state["merged_df"] = merged_df
        session_state["alarm_df"] = alarm_df
        session_state["kpi_df"] = kpi_df
        steps_completed.append(f"数据匹配完成: {len(merged_df)}条记录")

        # Step 4: 诊断
        diagnosed_df = diagnosis_engine.diagnose(merged_df)
        session_state["diagnosed_df"] = diagnosed_df
        diag_summary = diagnosis_engine.get_summary(diagnosed_df)
        
        # 组装完整的异常小区清单，并补齐级别标识
        p0 = diag_summary.get("p0_cells", [])
        for c in p0: c["diag_level"] = c.get("diag_level") or "P0"
        p1 = diag_summary.get("p1_cells", [])
        for c in p1: c["diag_level"] = c.get("diag_level") or "P1"
        p2 = diag_summary.get("p2_cells", [])
        for c in p2: c["diag_level"] = c.get("diag_level") or "P2"
        diag_summary["diagnosed_cells"] = p0 + p1 + p2
        session_state["diag_summary"] = diag_summary
        steps_completed.append(
            f"诊断完成: P0={diag_summary['p0_count']}, P1={diag_summary['p1_count']}, "
            f"P2={diag_summary['p2_count']}, 正常={diag_summary['normal_count']}"
        )

        # 频段分布
        freq_dist = {}
        if "freq_band" in result_df.columns:
            freq_dist = result_df["freq_band"].value_counts().to_dict()

        return {
            "steps": steps_completed,
            "param_summary": summary,
            "circle": {
                "center_lng": center_lng,
                "center_lat": center_lat,
                "radius": radius_m,
            },
            "selection": {
                "total_cells": len(result_df),
                "total_sites": result_df["site_id"].nunique() if "site_id" in result_df.columns else 0,
                "lte_cells": int((result_df["rat"] == "4G").sum()) if "rat" in result_df.columns else 0,
                "nr_cells": int((result_df["rat"] == "5G").sum()) if "rat" in result_df.columns else 0,
                "freq_distribution": {str(k): int(v) for k, v in freq_dist.items()},
                "cells": json.loads(result_df.to_json(orient="records", force_ascii=False)),
            },
            "diagnosis": diag_summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"演示执行失败: {str(e)}")


# ---------------------------------------------------------------------------
# Wmap 专业网优地图桌面系统核心 API
# ---------------------------------------------------------------------------

TEMP_IMPORT_DIR = BASE_DIR / "data" / "temp_imports"
TEMP_IMPORT_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/wmap/importer/analyze")
async def wmap_importer_analyze(file: UploadFile = File(...)):
    """分析上传的工参表格文件（CSV/XLSX/XLS），返回识别字段与数据预览"""
    try:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in [".csv", ".xlsx", ".xls"]:
            raise HTTPException(status_code=400, detail="仅支持上传 CSV 或 Excel (.xlsx/.xls) 格式文件")

        temp_path = TEMP_IMPORT_DIR / f"upload_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        analysis = SmartImporter.analyze_file(str(temp_path))
        analysis["temp_file_id"] = temp_path.name
        analysis["original_filename"] = file.filename
        return analysis
    except Exception as e:
        logger.error(f"分析工参文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分析工参文件失败: {str(e)}")

@app.post("/api/wmap/importer/apply")
async def wmap_importer_apply(request: Request):
    """应用用户确认的映射规则，清洗并导入工参至 SQLite 数据库（单一工参入口）"""
    try:
        data = await request.json()
        temp_file_id = data.get("temp_file_id")
        field_mapping = data.get("field_mapping", {})
        coord_sys = data.get("coord_sys", "WGS-84")
        rat = data.get("rat", "4G")
        layer_name = data.get("layer_name", "").strip() or "工参图层"
        import_mode = data.get("import_mode", "replace")
        template_name = data.get("template_name")
        save_as_template = data.get("save_as_template", False)

        if not temp_file_id:
            raise HTTPException(status_code=400, detail="缺少 temp_file_id 参数")

        temp_path = TEMP_IMPORT_DIR / temp_file_id
        if not temp_path.exists():
            raise HTTPException(status_code=404, detail="上传的临时文件已过期，请重新上传")

        if save_as_template and template_name:
            SmartImporter.save_template(template_name, field_mapping)

        # 解析并标准化工参为自定义图层
        df = SmartImporter.process_and_standardize(
            str(temp_path), 
            field_mapping, 
            coord_sys=coord_sys,
            rat=rat,
            layer_name=layer_name
        )

        # 写入 SQLite 数据库持久化存储（支持覆盖或追加合并）
        from app.cell_db import CellDB, DEFAULT_DB_PATH
        CellDB.save_dataframe(df, db_path=DEFAULT_DB_PATH, field_mapping=field_mapping, mode=import_mode)

        # 从 SQLite 读出当前全量工参（确保包含追加合并的历史工参与动态列）
        full_df = CellDB.load_dataframe(DEFAULT_DB_PATH)
        if full_df.empty:
            full_df = df

        # 注入现有 param_loader
        param_loader.all_cells = full_df
        param_loader.df_all = full_df
        
        # 更新 session_state
        session_state["params_loaded"] = True
        session_state["param_summary"] = param_loader.get_summary()

        # 转换为安全传输的前端列表
        cell_records = sanitize_cell_records(full_df)
        
        return {
            "success": True,
            "message": f"成功导入图层「{layer_name}」，当前共计 {len(cell_records)} 个小区工参",
            "summary": session_state["param_summary"],
            "cells": cell_records,
            "layer_name": layer_name
        }
    except Exception as e:
        logger.error(f"导入工参失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入工参失败: {str(e)}")

@app.get("/api/wmap/project/new")
async def wmap_project_new(name: str = "未命名网优工程"):
    """创建全新空白工程结构"""
    return ProjectManager.create_empty_project(name=name)

@app.post("/api/wmap/project/export")
async def wmap_project_export(request: Request):
    """将前端工程数据打包导出为 .wyp 工程文件"""
    try:
        project_data = await request.json()
        proj_name = project_data.get("meta", {}).get("name", "未命名网优工程")
        custom_save_path = project_data.get("custom_save_path", "")
        # 清理文件名非法字符
        safe_name = re.sub(r'[\\/*?:"<>|]', "", proj_name) or "Wmap工程"
        
        from app.cell_db import DEFAULT_DB_PATH
        wyp_bytes = ProjectManager.pack_project_to_bytes(project_data, db_path=str(DEFAULT_DB_PATH))
        
        out_filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wyp"
        out_path = OUTPUT_DIR / out_filename
        with open(out_path, "wb") as f:
            f.write(wyp_bytes)

        # 若指定了自定义磁盘保存路径，直接写入目标文件
        if custom_save_path:
            try:
                dest = Path(custom_save_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(wyp_bytes)
                logger.info(f"工程文件已成功另存至指定路径: {dest}")
            except Exception as e_custom:
                logger.warning(f"写入自定义另存路径失败: {e_custom}")

        # 记入最近工程（服务端存一份副本，工程菜单可一键打开）
        cell_count = len(project_data.get("layers", {}).get("param_cells", []))
        _record_recent_project(safe_name, wyp_bytes, cell_count)

        return FileResponse(
            str(out_path),
            filename=f"{safe_name}.wyp",
            media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error(f"导出工程文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出工程文件失败: {str(e)}")

@app.get("/api/wmap/project/pick_save_path")
async def wmap_project_pick_save_path(suggested_name: str = "网优工程.wyp"):
    """调起桌面系统原生另存为文件对话框（辅助不支持 showSaveFilePicker 的环境）"""
    import asyncio
    import concurrent.futures

    def _ask_path():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            clean_name = suggested_name if suggested_name.endswith(".wyp") else f"{suggested_name}.wyp"
            path = filedialog.asksaveasfilename(
                title="选择工程文件另存为路径",
                defaultextension=".wyp",
                filetypes=[("Wmap 网优工程文件", "*.wyp"), ("所有文件", "*.*")],
                initialfile=clean_name
            )
            root.destroy()
            return path
        except Exception as e:
            logger.warning(f"调用系统另存为对话框失败: {e}")
            return ""

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        path = await loop.run_in_executor(pool, _ask_path)
    return {"path": path or ""}

@app.post("/api/wmap/project/import")
async def wmap_project_import(file: UploadFile = File(...)):
    """解包并恢复上传的 .wyp 工程文件"""
    try:
        content = await file.read()
        from app.cell_db import DEFAULT_DB_PATH
        project_data = ProjectManager.unpack_project_from_bytes(content, extract_db_path=str(DEFAULT_DB_PATH))

        # 同步将工程内的工参同步至全局 param_loader（如有）
        _apply_project_cells_to_session(project_data)

        return {
            "success": True,
            "project": project_data
        }
    except Exception as e:
        logger.error(f"解包工程文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"解析工程文件失败: {str(e)}")


@app.get("/api/wmap/project/recent")
async def wmap_project_recent():
    """最近保存的工程列表（最多 5 个，按保存时间倒序）"""
    items = _load_recent_projects_meta()
    # 只返回仍有副本文件的条目
    items = [e for e in items if (RECENT_PROJECTS_DIR / e.get("filename", "")).exists()]
    return {"projects": items}


@app.post("/api/wmap/project/recent/{project_id}/open")
async def wmap_project_recent_open(project_id: str):
    """打开服务端存档的最近工程（无需再选文件）"""
    items = _load_recent_projects_meta()
    entry = next((e for e in items if e.get("id") == project_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="未找到该工程")
    wyp_path = RECENT_PROJECTS_DIR / entry.get("filename", "")
    if not wyp_path.exists():
        raise HTTPException(status_code=404, detail="工程文件已不存在")
    try:
        from app.cell_db import DEFAULT_DB_PATH
        project_data = ProjectManager.unpack_project_from_bytes(wyp_path.read_bytes(), extract_db_path=str(DEFAULT_DB_PATH))
        _apply_project_cells_to_session(project_data)
        return {"success": True, "project": project_data}
    except Exception as e:
        logger.error(f"打开最近工程失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"打开工程失败: {str(e)}")

@app.post("/api/wmap/pci/check")
async def wmap_pci_check(request: Request):
    """执行 PCI 冲突与混淆智能检测"""
    try:
        body = await request.json()
        cells = body.get("cells", [])
        threshold = float(body.get("distance_threshold_m", 6000.0))
        if not cells and param_loader.all_cells is not None and not param_loader.all_cells.empty:
            cells = sanitize_cell_records(param_loader.all_cells)
            
        result = check_pci_conflicts(cells, distance_threshold_m=threshold)
        return result
    except Exception as e:
        logger.error(f"PCI检测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PCI检测异常: {str(e)}")



# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  LTE/NR 应急事件无线保障处置系统")
    print("  访问地址: http://localhost:8080")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8080)
