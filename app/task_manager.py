# -*- coding: utf-8 -*-
"""应急保障任务历史记录持久化管理器
负责将空间圈选、故障诊断、报告导出等完整任务元数据落盘至本地 JSON 文件。
支持任务创建、增量更新、最近列表查询、搜索、单条读取与删除。
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "tasks_history.json"


class TaskManager:
    """应急保障任务历史管理器（线程安全单例/实例）"""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or HISTORY_FILE
        self._lock = threading.Lock()
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储目录及文件存在"""
        if not self.storage_path.parent.exists():
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            with self._lock:
                self.storage_path.write_text("[]", encoding="utf-8")

    def _read_all(self) -> List[Dict[str, Any]]:
        """读取全部任务记录"""
        try:
            if not self.storage_path.exists():
                return []
            content = self.storage_path.read_text(encoding="utf-8").strip()
            if not content:
                return []
            return json.loads(content)
        except Exception as e:
            print(f"[TaskManager] 读取任务文件异常: {e}")
            return []

    def _write_all(self, tasks: List[Dict[str, Any]]):
        """原子覆写全部任务记录"""
        tmp_file = self.storage_path.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(self.storage_path)

    def create_task(
        self,
        event_name: str,
        address: str,
        shape_type: str,
        shape_params: Dict[str, Any],
        metrics: Dict[str, Any],
        cells: Optional[List[Dict[str, Any]]] = None,
        diagnosis: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """创建一条新的应急任务记录

        Parameters
        ----------
        event_name : str
            事件/任务名称，如"南川水江应急保障"
        address : str
            保障地标或详细地址
        shape_type : str
            "circle" 或 "polygon"
        shape_params : dict
            圈选具体参数（圆心、半径米数、多边形经纬度坐标串等）
        metrics : dict
            总基站数、小区数、4G/5G分布、覆盖面积
        cells : list, optional
            圈选出的小区与基站完整工参快照列表
        diagnosis : dict, optional
            诊断与指标告警统计数据及异常小区明细快照
        artifacts : dict, optional
            输出文档路径（word/excel）
        """
        with self._lock:
            tasks = self._read_all()
            now_dt = datetime.now()
            time_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            # 唯一任务 ID
            task_id = f"TASK_{now_dt.strftime('%Y%m%d_%H%M%S')}_{os.urandom(2).hex().upper()}"

            new_task = {
                "task_id": task_id,
                "create_time": time_str,
                "update_time": time_str,
                "event_name": event_name.strip() or "应急保障任务",
                "address": address.strip() or "自定义保障区域",
                "shape_type": shape_type,
                "shape_params": shape_params or {},
                "metrics": metrics or {},
                "cells": cells or [],
                "diagnosis": diagnosis or {"status": "pending", "p0_count": 0, "p1_count": 0, "p2_count": 0, "normal_count": 0, "diagnosed_cells": []},
                "artifacts": artifacts or {"excel_path": "", "word_path": ""},
                "status": "已完成",
            }

            # 插入首位（按创建时间倒序）
            tasks.insert(0, new_task)
            # 保持最多保留 200 条归档记录，避免文件无限膨胀
            if len(tasks) > 200:
                tasks = tasks[:200]

            self._write_all(tasks)
            return new_task

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新指定任务字段（如补充诊断结果、报告路径等）"""
        with self._lock:
            tasks = self._read_all()
            target_idx = None
            for idx, t in enumerate(tasks):
                if t.get("task_id") == task_id:
                    target_idx = idx
                    break

            if target_idx is None:
                return None

            cur = tasks[target_idx]
            cur["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for k, v in updates.items():
                if isinstance(v, dict) and isinstance(cur.get(k), dict):
                    cur[k].update(v)
                else:
                    cur[k] = v

            self._write_all(tasks)
            return cur

    def get_recent_tasks(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近 N 条任务记录"""
        with self._lock:
            tasks = self._read_all()
            return tasks[:limit]

    def get_all_tasks(self, keyword: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """获取任务列表，支持关键字（事件名称、地址）模糊搜索"""
        with self._lock:
            tasks = self._read_all()
            if not keyword:
                return tasks[:limit]
            kw = keyword.strip().lower()
            filtered = [
                t for t in tasks
                if kw in t.get("event_name", "").lower() or kw in t.get("address", "").lower()
            ]
            return filtered[:limit]

    def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查询单个任务详情"""
        with self._lock:
            tasks = self._read_all()
            for t in tasks:
                if t.get("task_id") == task_id:
                    return t
            return None

    def delete_task(self, task_id: str) -> bool:
        """删除指定 ID 任务"""
        with self._lock:
            tasks = self._read_all()
            initial_len = len(tasks)
            tasks = [t for t in tasks if t.get("task_id") != task_id]
            if len(tasks) < initial_len:
                self._write_all(tasks)
                return True
            return False

    def clear_all(self) -> int:
        """清空所有历史任务"""
        with self._lock:
            tasks = self._read_all()
            count = len(tasks)
            self._write_all([])
            return count
