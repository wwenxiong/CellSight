# CellSight 测试说明

## 运行方法

```bash
cd ~/workspace/wmap
.venv/bin/python -m pytest tests/ -v
```

只跑某一模块：

```bash
.venv/bin/python -m pytest tests/test_coord_utils.py -v
.venv/bin/python -m pytest tests/test_wyp_roundtrip.py -v
```

## 测试文件一览

| 文件 | 覆盖内容 |
|---|---|
| `test_wyp_roundtrip.py` | P1-7：`.wyp` 工程打包/解包往返（字节流 + 磁盘 + 纯 JSON 兼容 + 非法输入） |
| `test_coord_utils.py` | WGS-84 ↔ GCJ-02 互转、境外判定、大圆距离/方位角、目标点、坐标解析 |
| `test_pci_checker.py` | PCI 冲突检出 / 不检出、严重度、门限、排序、无效小区跳过 |
| `test_diagnosis.py` | P0/P1/P2/正常分级、优先级、汇总统计 |
| `test_smart_importer.py` | 表头智能映射、标准化处理（WGS-84/GCJ-02）、缺列行为、映射模板 |

## 约定

- 全部测试数据均为人工构造的假数据，**不使用 `data/` 下的真实工参 CSV**。
- 不访问网络；不读写业务数据目录（模板测试用 `monkeypatch` 重定向到 `tmp_path`）。
- 业务代码有缺陷时，测试不私自修代码：能断言当前行为的就如实断言并注释，
  不能通过的用 `@pytest.mark.xfail(strict=True)` 标记并在原因里写清缺陷位置。
