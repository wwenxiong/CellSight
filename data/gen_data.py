# -*- coding: utf-8 -*-
"""Generate realistic demo data for LTE/NR emergency wireless assurance system."""
import csv, io, os, random

random.seed(42)
OUT = os.path.dirname(os.path.abspath(__file__))

def bom_writer(path):
    f = open(path, "w", encoding="utf-8-sig", newline="")
    return f

# ── Site location pool (fictional area 广州市天河区) ──────────────────────────
# 18 LTE sites, 12 NR sites (some co-located)
lte_sites = [
    ("L2001", "天河体育中心-HLH-1",  113.3220, 23.1350),
    ("L2002", "珠江新城-HLH-2",      113.3300, 23.1200),
    ("L2003", "天河城-HLH-3",        113.3250, 23.1380),
    ("L2004", "五山路-HLH-4",        113.3150, 23.1430),
    ("L2005", "华南理工-HLH-5",      113.3100, 23.1480),
    ("L2006", "岗顶-HLH-6",          113.3200, 23.1400),
    ("L2007", "体育西路-HLH-7",      113.3280, 23.1320),
    ("L2008", "林和西-HLH-8",        113.3310, 23.1390),
    ("L2009", "广州东站-HLH-9",      113.3340, 23.1410),
    ("L2010", "员村-HLH-10",         113.3400, 23.1280),
    ("L2011", "猎德-HLH-11",         113.3380, 23.1190),
    ("L2012", "花城大道-HLH-12",     113.3350, 23.1230),
    ("L2013", "黄埔大道西-HLH-13",   113.3260, 23.1260),
    ("L2014", "石牌桥-HLH-14",       113.3230, 23.1300),
    ("L2015", "龙口西-HLH-15",       113.3170, 23.1370),
    ("L2016", "天河北路-HLH-16",     113.3290, 23.1440),
    ("L2017", "棠下-HLH-17",         113.3450, 23.1350),
    ("L2018", "程介村-HLH-18",       113.3500, 23.1400),
]

nr_sites = [
    # co-located with some LTE sites
    ("N3001", "天河体育中心-NLH-1",  113.3220, 23.1350),
    ("N3002", "珠江新城-NLH-2",      113.3300, 23.1200),
    ("N3003", "天河城-NLH-3",        113.3250, 23.1380),
    ("N3004", "五山路-NLH-4",        113.3150, 23.1430),
    ("N3005", "华南理工-NLH-5",      113.3100, 23.1480),
    ("N3006", "岗顶-NLH-6",          113.3200, 23.1400),
    ("N3007", "体育西路-NLH-7",      113.3280, 23.1320),
    ("N3008", "广州东站-NLH-8",      113.3340, 23.1410),
    # NR-only sites
    ("N3009", "花城汇-NLH-9",        113.3330, 23.1180),
    ("N3010", "冼村-NLH-10",         113.3360, 23.1250),
    ("N3011", "天河公园-NLH-11",     113.3420, 23.1310),
    ("N3012", "天寿路-NLH-12",       113.3190, 23.1460),
]

lte_bands = ["FDD1800", "FDD900", "TDD2600", "TDD2300"]
nr_bands  = ["N41(2.6G)", "N78(3.5G)", "N28(700M)"]
cover_types_pool = (["室外"] * 13 + ["室内"] * 3 + ["微站"] * 2)

enodeb_base = 10001
gnb_base    = 30001

# ── File 1: base_param_lte.csv ──────────────────────────────────────────────
lte_rows = []
for idx, (sid, sname, lon, lat) in enumerate(lte_sites):
    # 14 sites with 3 sectors + 4 sites with 2 sectors = 50 cells
    n_cells = 2 if idx in (4, 9, 14, 17) else 3
    enodeb = enodeb_base + idx
    for c in range(n_cells):
        az = [0, 120, 240][c] if n_cells == 3 else [0, 180][c]
        cgi = f"460-00-{enodeb:05d}-{c}"
        band = lte_bands[(idx + c) % len(lte_bands)]
        tilt = random.randint(3, 10)
        ct = random.choice(cover_types_pool)
        lte_rows.append({
            "rat": "4G", "site_id": sid, "site_name": sname,
            "cell_id": c, "cell_name": f"{sname}-{c}",
            "cgi": cgi,
            "longitude": f"{lon + random.uniform(-0.001, 0.001):.4f}",
            "latitude":  f"{lat + random.uniform(-0.001, 0.001):.4f}",
            "freq_band": band, "azimuth": az, "tilt": tilt,
            "cover_type": ct,
        })

with bom_writer(os.path.join(OUT, "base_param_lte.csv")) as f:
    cols = ["rat","site_id","site_name","cell_id","cell_name","cgi",
            "longitude","latitude","freq_band","azimuth","tilt","cover_type"]
    w = csv.DictWriter(f, cols)
    w.writeheader()
    w.writerows(lte_rows)
print(f"LTE cells generated: {len(lte_rows)}")

# ── File 2: base_param_nr.csv ───────────────────────────────────────────────
nr_rows = []
for idx, (sid, sname, lon, lat) in enumerate(nr_sites):
    # 6 sites with 3 sectors + 6 sites with 2 sectors = 30 cells
    n_cells = 2 if idx in (3, 5, 7, 9, 10, 11) else 3
    gnb = gnb_base + idx
    for c in range(n_cells):
        az = [0, 120, 240][c] if n_cells == 3 else [0, 180][c]
        cgi = f"460-00-{gnb:05d}-{c}"
        band = nr_bands[(idx + c) % len(nr_bands)]
        tilt = random.randint(3, 10)
        ct = random.choice(cover_types_pool)
        nr_rows.append({
            "rat": "5G", "site_id": sid, "site_name": sname,
            "cell_id": c, "cell_name": f"{sname}-{c}",
            "cgi": cgi,
            "longitude": f"{lon + random.uniform(-0.001, 0.001):.4f}",
            "latitude":  f"{lat + random.uniform(-0.001, 0.001):.4f}",
            "freq_band": band, "azimuth": az, "tilt": tilt,
            "cover_type": ct,
        })

with bom_writer(os.path.join(OUT, "base_param_nr.csv")) as f:
    cols = ["rat","site_id","site_name","cell_id","cell_name","cgi",
            "longitude","latitude","freq_band","azimuth","tilt","cover_type"]
    w = csv.DictWriter(f, cols)
    w.writeheader()
    w.writerows(nr_rows)
print(f"NR cells generated: {len(nr_rows)}")

# Collect all CGIs
all_cgis_lte = [r["cgi"] for r in lte_rows]
all_cgis_nr  = [r["cgi"] for r in nr_rows]
all_cgis = all_cgis_lte + all_cgis_nr

# Define "story" cells
# Emergency: a gas explosion near 广州东站 area knocked out some sites
# L2009 (广州东站) and N3008 (co-located) are FULLY DOWN
# L2008 (林和西) partially affected (1 cell down)
# Neighboring sites overloaded: L2007, L2016, N3007
# Interference issues: L2003, L2015
# Poor quality: L2010, N3011

down_cgis_full = [r["cgi"] for r in lte_rows if r["site_id"] == "L2009"] + \
                 [r["cgi"] for r in nr_rows  if r["site_id"] == "N3008"]
down_cgi_partial = [r["cgi"] for r in lte_rows if r["site_id"] == "L2008" and r["cell_id"] == 2]
overloaded_cgis = [r["cgi"] for r in lte_rows if r["site_id"] in ("L2007", "L2016")] + \
                  [r["cgi"] for r in nr_rows  if r["site_id"] == "N3007"]
interference_cgis = [r["cgi"] for r in lte_rows if r["site_id"] in ("L2003", "L2015")]
poor_quality_cgis = [r["cgi"] for r in lte_rows if r["site_id"] == "L2010"] + \
                    [r["cgi"] for r in nr_rows  if r["site_id"] == "N3011"]

all_down = down_cgis_full + down_cgi_partial

# ── File 3: sample_alarms.csv ───────────────────────────────────────────────
def cgi_to_site_cell(cgi):
    """Extract site_id-like and cell_id from a cgi string."""
    parts = cgi.split("-")
    enb = parts[2]
    cid = parts[3]
    return enb, cid

alarm_rows = []
base_ts = "2026-10-30"

# Critical alarms for fully-down site L2009 cells
for cgi in [r["cgi"] for r in lte_rows if r["site_id"] == "L2009"]:
    enb, cid = cgi_to_site_cell(cgi)
    alarm_rows.append({
        "告警名称": "小区不可用",
        "告警级别": "紧急",
        "发生时间": f"{base_ts} 02:17:33",
        "CGI": cgi,
        "基站ID": enb,
        "小区ID": cid,
    })

# S1 link down for N3008 (co-located NR)
nr_down_cgis = [r["cgi"] for r in nr_rows if r["site_id"] == "N3008"]
alarm_rows.append({
    "告警名称": "S1接口链路断",
    "告警级别": "紧急",
    "发生时间": f"{base_ts} 02:17:35",
    "CGI": nr_down_cgis[0],
    "基站ID": cgi_to_site_cell(nr_down_cgis[0])[0],
    "小区ID": cgi_to_site_cell(nr_down_cgis[0])[1],
})

# Optical module alarm for partial-down L2008 cell
alarm_rows.append({
    "告警名称": "光模块收发异常",
    "告警级别": "紧急",
    "发生时间": f"{base_ts} 02:18:05",
    "CGI": down_cgi_partial[0],
    "基站ID": cgi_to_site_cell(down_cgi_partial[0])[0],
    "小区ID": cgi_to_site_cell(down_cgi_partial[0])[1],
})

# More critical: another NR cell at N3008
if len(nr_down_cgis) > 1:
    alarm_rows.append({
        "告警名称": "小区不可用",
        "告警级别": "紧急",
        "发生时间": f"{base_ts} 02:17:40",
        "CGI": nr_down_cgis[1],
        "基站ID": cgi_to_site_cell(nr_down_cgis[1])[0],
        "小区ID": cgi_to_site_cell(nr_down_cgis[1])[1],
    })

# Moderate alarms: VSWR on interference sites
for i, cgi in enumerate(interference_cgis[:2]):
    enb, cid = cgi_to_site_cell(cgi)
    name = "VSWR告警" if i == 0 else "天馈驻波比异常"
    alarm_rows.append({
        "告警名称": name,
        "告警级别": "重要",
        "发生时间": f"{base_ts} 02:2{i}:15",
        "CGI": cgi,
        "基站ID": enb,
        "小区ID": cid,
    })

# GPS lock lost on overloaded site
alarm_rows.append({
    "告警名称": "GPS失锁",
    "告警级别": "重要",
    "发生时间": f"{base_ts} 02:35:22",
    "CGI": overloaded_cgis[0],
    "基站ID": cgi_to_site_cell(overloaded_cgis[0])[0],
    "小区ID": cgi_to_site_cell(overloaded_cgis[0])[1],
})

# Another moderate: RRU link issue
alarm_rows.append({
    "告警名称": "RRU链路异常",
    "告警级别": "重要",
    "发生时间": f"{base_ts} 03:05:44",
    "CGI": poor_quality_cgis[0],
    "基站ID": cgi_to_site_cell(poor_quality_cgis[0])[0],
    "小区ID": cgi_to_site_cell(poor_quality_cgis[0])[1],
})

# Minor alarms
minor_alarm_data = [
    ("温度过高预警", "L2001", 0, "04:12:30"),
    ("电池放电告警", "L2005", 1, "02:45:10"),
    ("负荷预警",     "L2007", 0, "03:30:55"),
    ("负荷预警",     "L2016", 1, "03:32:18"),
    ("温度过高预警", "N3002", 0, "05:15:40"),
    ("电池放电告警", "L2017", 2, "02:50:22"),
]
for aname, sid, cid, ts in minor_alarm_data:
    # find matching row
    match = [r for r in lte_rows + nr_rows if r["site_id"] == sid and r["cell_id"] == cid]
    if match:
        cgi = match[0]["cgi"]
        enb, ci = cgi_to_site_cell(cgi)
        alarm_rows.append({
            "告警名称": aname,
            "告警级别": "一般",
            "发生时间": f"{base_ts} {ts}",
            "CGI": cgi,
            "基站ID": enb,
            "小区ID": ci,
        })

with bom_writer(os.path.join(OUT, "sample_alarms.csv")) as f:
    cols = ["告警名称","告警级别","发生时间","CGI","基站ID","小区ID"]
    w = csv.DictWriter(f, cols)
    w.writeheader()
    w.writerows(alarm_rows)
print(f"Alarms generated: {len(alarm_rows)}")

# ── File 4: sample_kpi.csv ──────────────────────────────────────────────────
# Pick ~40 cells out of all, skip some intentionally
# Make sure down/overloaded/interference/poor cells are included
special_cgis = set(all_down + overloaded_cgis + interference_cgis + poor_quality_cgis)
remaining = [c for c in all_cgis if c not in special_cgis]
random.shuffle(remaining)
# pick enough normals to reach ~40 total
n_normals = 40 - len(special_cgis)
selected_normals = remaining[:n_normals]

kpi_rows = []

def normal_kpi(cgi):
    return {
        "CGI": cgi,
        "最大RRC连接数": random.randint(50, 200),
        "下行PRB利用率": round(random.uniform(15.0, 60.0), 1),
        "上行PRB利用率": round(random.uniform(8.0, 35.0), 1),
        "上行干扰电平": round(random.uniform(-112.0, -105.0), 1),
        "无线掉线率": round(random.uniform(0.3, 1.5), 2),
        "接通率": round(random.uniform(97.0, 99.8), 2),
        "切换成功率": round(random.uniform(95.0, 99.5), 2),
        "RRC建立尝试次数": random.randint(800, 3500),
        "小区可用率": round(random.uniform(99.5, 100.0), 2),
        "下行吞吐率": round(random.uniform(25.0, 85.0), 1),
        "上行吞吐率": round(random.uniform(5.0, 25.0), 1),
    }

# Normal cells
for cgi in selected_normals:
    kpi_rows.append(normal_kpi(cgi))

# Fully-down cells (退服)
for cgi in down_cgis_full:
    kpi_rows.append({
        "CGI": cgi,
        "最大RRC连接数": 0,
        "下行PRB利用率": 0.0,
        "上行PRB利用率": 0.0,
        "上行干扰电平": 0.0,
        "无线掉线率": 0.0,
        "接通率": 0.0,
        "切换成功率": 0.0,
        "RRC建立尝试次数": 0,
        "小区可用率": 0.0,
        "下行吞吐率": 0.0,
        "上行吞吐率": 0.0,
    })

# Partially-down cell
for cgi in down_cgi_partial:
    kpi_rows.append({
        "CGI": cgi,
        "最大RRC连接数": 2,
        "下行PRB利用率": 0.5,
        "上行PRB利用率": 0.2,
        "上行干扰电平": -88.0,
        "无线掉线率": 85.0,
        "接通率": 12.5,
        "切换成功率": 5.0,
        "RRC建立尝试次数": 15,
        "小区可用率": 3.2,
        "下行吞吐率": 0.3,
        "上行吞吐率": 0.1,
    })

# Overloaded cells (high load, displaced traffic)
for cgi in overloaded_cgis:
    kpi_rows.append({
        "CGI": cgi,
        "最大RRC连接数": random.randint(450, 620),
        "下行PRB利用率": round(random.uniform(85.0, 97.0), 1),
        "上行PRB利用率": round(random.uniform(60.0, 82.0), 1),
        "上行干扰电平": round(random.uniform(-108.0, -103.0), 1),
        "无线掉线率": round(random.uniform(2.0, 4.5), 2),
        "接通率": round(random.uniform(88.0, 94.0), 2),
        "切换成功率": round(random.uniform(85.0, 92.0), 2),
        "RRC建立尝试次数": random.randint(5000, 9500),
        "小区可用率": round(random.uniform(98.5, 100.0), 2),
        "下行吞吐率": round(random.uniform(8.0, 18.0), 1),
        "上行吞吐率": round(random.uniform(2.0, 6.0), 1),
    })

# High interference cells
for cgi in interference_cgis:
    kpi_rows.append({
        "CGI": cgi,
        "最大RRC连接数": random.randint(100, 250),
        "下行PRB利用率": round(random.uniform(30.0, 55.0), 1),
        "上行PRB利用率": round(random.uniform(25.0, 50.0), 1),
        "上行干扰电平": round(random.uniform(-97.0, -90.0), 1),
        "无线掉线率": round(random.uniform(2.5, 5.0), 2),
        "接通率": round(random.uniform(90.0, 95.0), 2),
        "切换成功率": round(random.uniform(88.0, 94.0), 2),
        "RRC建立尝试次数": random.randint(1500, 4000),
        "小区可用率": round(random.uniform(97.0, 99.5), 2),
        "下行吞吐率": round(random.uniform(12.0, 30.0), 1),
        "上行吞吐率": round(random.uniform(3.0, 10.0), 1),
    })

# Poor quality cells
for cgi in poor_quality_cgis:
    kpi_rows.append({
        "CGI": cgi,
        "最大RRC连接数": random.randint(80, 180),
        "下行PRB利用率": round(random.uniform(25.0, 50.0), 1),
        "上行PRB利用率": round(random.uniform(15.0, 35.0), 1),
        "上行干扰电平": round(random.uniform(-108.0, -102.0), 1),
        "无线掉线率": round(random.uniform(4.5, 8.0), 2),
        "接通率": round(random.uniform(85.0, 92.5), 2),
        "切换成功率": round(random.uniform(78.0, 87.0), 2),
        "RRC建立尝试次数": random.randint(1200, 3000),
        "小区可用率": round(random.uniform(95.0, 98.5), 2),
        "下行吞吐率": round(random.uniform(10.0, 25.0), 1),
        "上行吞吐率": round(random.uniform(2.0, 8.0), 1),
    })

# Shuffle so it looks natural
random.shuffle(kpi_rows)

with bom_writer(os.path.join(OUT, "sample_kpi.csv")) as f:
    cols = ["CGI","最大RRC连接数","下行PRB利用率","上行PRB利用率","上行干扰电平",
            "无线掉线率","接通率","切换成功率","RRC建立尝试次数","小区可用率",
            "下行吞吐率","上行吞吐率"]
    w = csv.DictWriter(f, cols)
    w.writeheader()
    w.writerows(kpi_rows)
print(f"KPI rows generated: {len(kpi_rows)}")

# Summary
print("\n=== Generation Summary ===")
print(f"LTE cells: {len(lte_rows)} across {len(lte_sites)} sites")
print(f"NR  cells: {len(nr_rows)} across {len(nr_sites)} sites")
print(f"Alarms:    {len(alarm_rows)}")
print(f"KPI rows:  {len(kpi_rows)}")
print(f"Down CGIs: {all_down}")
print(f"Overloaded: {overloaded_cgis}")
print(f"Interference: {interference_cgis}")
print(f"Poor quality: {poor_quality_cgis}")
