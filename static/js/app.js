/**
 * LTE/NR 应急通信保障平台 - 赛博深色大屏控制器
 * High-Tech Cyber Command Center Frontend Controller
 */

// 全局状态
const appState = {
    currentTab: 'emergency',
    coordSys: 'gcj02',
    currentTileType: 'amap', // 'amap' (GCJ-02) 或 'wgs84'
    selectMode: 'circle',    // 'circle', 'polygon'
    queryFilterMode: 'within', // 'within', 'impacted'
    
    // Wmap 网优专属扩展属性
    renderMode: 'sector',
    sectorBeamwidth: 65,
    sectorColorMode: 'rat', // 'rat' | 'freq_band' | 'pci' | 'alarm'
    layerVisibility: { '5G': true, '4G': true, 'emergency': true, 'pci': true, 'labels': false },
    allCells: [],
    labelLayerGroup: null,
    pciConflictLayerGroup: null,
    
    // 视口动态渲染与LOD性能控制配置
    viewportSettings: {
        minZoom: 12,
        maxZoom: 0,
        maxRenderLimit: 800
    },
    
    baseParams: null,
    selectedCells: [],
    siteList: [],          // 按基站聚合的小区列表
    filteredSites: [],     // 当前表格筛选显示的基站列表
    currentRatFilter: 'ALL',
    tableSearchKeyword: '',
    paramViewMode: 'site', // 'site' (基站折叠视图) 或 'cell' (小区平铺明细视图) 或 'alarm' (告警指标视图)
    expandedSiteSet: new Set(), // 存储已展开下属小区的 siteName
    
    // 图层与图元
    map: null,
    cellLayerGroup: null,
    drawLayerGroup: null,
    importedBoundaryGroup: null,
    centerLayerGroup: null,
    currentShapeLayer: null,
    drawControl: null,
    
    // 导入边界与多区域管理
    importedRegionsData: null,
    activeRegionIndex: -1,
    importCoordSys: 'wgs84',
    
    // 告警与诊断
    alarmFile: null,
    kpiFile: null,
    kpiFiles: [],          // 存储上传的4G网管指标文件列表 (最多3个)
    matchedData: null,
    diagnosisResult: null,
    diagnosedCells: [],    // 存储比对出的异常小区指标与告警数据
    allDiagnosedCells: [],
    
    // 任务历史 (由后端持久化接口动态加载)
    recentTasks: [],
    
    // 测距工具状态
    isMeasuring: false,
    measurePoints: [],
    measureGroup: null,
    measureMoveLine: null,
    measureTooltip: null
};

// ---------------------------------------------------------------------------
// 辅助安全请求函数
// ---------------------------------------------------------------------------
async function safeFetchJson(url, options = {}) {
    const res = await fetch(url, options);
    const rawText = await res.text();
    let data = null;
    try {
        data = rawText ? JSON.parse(rawText) : {};
    } catch (e) {
        throw new Error(`服务器响应异常 (HTTP ${res.status}): ${rawText.slice(0, 100)}`);
    }
    if (!res.ok) {
        throw new Error((data && data.detail) || `请求失败 (HTTP ${res.status})`);
    }
    return data;
}

// ---------------------------------------------------------------------------
// 偏好参数本地持久化管理器 (修改即保存，刷新页面自动恢复)
// ---------------------------------------------------------------------------
const STORAGE_KEY_CONFIG = 'lte_emergency_app_config_v1';

const DEFAULT_APP_CONFIG = {
    radius: 5000,
    selectMode: 'circle',
    coordSys: 'gcj02',
    showLte: true,
    showNr: true,
    showEventArea: true,
    showImported: true,
    showPci: true,
    showLabels: false,
    baseLayer: 'normal',
    centerLng: null,
    centerLat: null,
    eventAddress: ''
};

function getStoredAppConfig() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY_CONFIG);
        if (raw) return JSON.parse(raw);
    } catch (e) {
        console.warn('读取本地配置失败', e);
    }
    return {};
}

function saveAppConfig(partialConfig) {
    try {
        const current = getStoredAppConfig();
        const updated = Object.assign({}, DEFAULT_APP_CONFIG, current, partialConfig);
        localStorage.setItem(STORAGE_KEY_CONFIG, JSON.stringify(updated));
    } catch (e) {
        console.warn('保存本地配置失败', e);
    }
}
window.saveAppConfig = saveAppConfig;
window.getStoredAppConfig = getStoredAppConfig;

function applyStoredAppConfig() {
    const cfg = getStoredAppConfig();
    if (!cfg || Object.keys(cfg).length === 0) return;

    // 1. 恢复半径设置 (如 500米)
    if (cfg.radius && typeof cfg.radius === 'number') {
        if (typeof window.setRadiusValue === 'function') {
            window.setRadiusValue(cfg.radius, false);
        }
    }

    // 2. 恢复图层显隐勾选与地图渲染状态（统一走左侧图层面板）
    const layerMap = [
        { key: 'showEventArea', id: 'chkLayerEmergency', type: 'emergency' },
        { key: 'showImported', id: 'chkLayerImported', type: 'imported' },
        { key: 'showPci', id: 'chkLayerPciConflict', type: 'pci' },
        { key: 'showLabels', id: 'chkLayerLabels', type: 'labels' },
        { key: 'showLte', id: 'chkLayer4G', type: '4G' },
        { key: 'showNr', id: 'chkLayer5G', type: '5G' }
    ];
    // 兼容旧版存储键：showCoverage 曾控制圈选范围，等同于 showEventArea
    if (cfg.showEventArea === undefined && cfg.showCoverage !== undefined) {
        cfg.showEventArea = cfg.showCoverage;
    }
    layerMap.forEach(({ key, id, type }) => {
        if (cfg[key] === undefined) return;
        const chk = document.getElementById(id);
        if (chk) chk.checked = !!cfg[key];
        if (!appState.layerVisibility) appState.layerVisibility = {};
        appState.layerVisibility[type] = !!cfg[key];
    });
    if (cfg.showEventArea === false && appState.map) {
        if (appState.drawLayerGroup) appState.map.removeLayer(appState.drawLayerGroup);
        if (appState.centerLayerGroup) appState.map.removeLayer(appState.centerLayerGroup);
    }
    if (cfg.showImported === false && appState.map && appState.importedBoundaryGroup) {
        appState.map.removeLayer(appState.importedBoundaryGroup);
    }

    // 3. 恢复坐标系选择
    if (cfg.coordSys) {
        if (typeof window.switchCoordSys === 'function') {
            window.switchCoordSys(cfg.coordSys, true);
        }
    }

    // 4. 恢复圈选方式
    if (cfg.selectMode) {
        appState.selectMode = cfg.selectMode;
        if (typeof updateSelectModeUI === 'function') {
            updateSelectModeUI(cfg.selectMode);
        }
    }

    // 5. 恢复底图类型
    if (cfg.baseLayer === 'satellite' && appState.layers && appState.layers.current !== 'satellite') {
        if (typeof toggleBaseLayer === 'function') {
            toggleBaseLayer(true);
        }
    }

    // 6. 恢复中心点经纬度与地标
    if (cfg.centerLng && cfg.centerLat && !isNaN(cfg.centerLng) && !isNaN(cfg.centerLat)) {
        if (typeof setMapCenter === 'function') {
            setMapCenter(parseFloat(cfg.centerLng), parseFloat(cfg.centerLat), cfg.eventAddress || null);
            appState.hasUserSelected = true;
            if (appState.map) {
                appState.map.setView([parseFloat(cfg.centerLat), parseFloat(cfg.centerLng)], 12);
            }
        }
    }
}
window.applyStoredAppConfig = applyStoredAppConfig;

// ---------------------------------------------------------------------------
// 页面入口初始化
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    loadStoredViewportSettings();
    initMap();
    initEventListeners();
    applyStoredAppConfig();
    checkBaseParams();
    loadAmapConfig();
    loadRecentTasks();
    startClock();
    updateMapControlsPosition();
    initAmapSettingsEvents();
    initBoundaryImportEvents();
});

// ---------------------------------------------------------------------------
// 1. 地图初始化 (默认高德街道底图，工参所在城市经纬度)
// ---------------------------------------------------------------------------
function initMap() {
    appState.map = L.map('map', {
        center: [29.7191, 107.5787], // 工参代表集中区域经纬度
        zoom: 12,
        preferCanvas: true, // 开启 HTML5 Canvas 高性能矢量渲染引擎
        zoomControl: false // 使用自定义缩放控件
    });
    if (L.canvas) {
        appState.sectorCanvasRenderer = L.canvas({ padding: 0.5 });
    }

    // 默认高德街道矢量底图
    const amapNormal = L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=7', {
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18,
        attribution: '© 高德地图 (Amap)'
    }).addTo(appState.map);

    // 备用卫星影像底图
    const amapSatBase = L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', {
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18,
        attribution: '© 高德地图 (Amap)'
    });
    const amapSatLabels = L.tileLayer('https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}', {
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18
    });
    const amapSatellite = L.layerGroup([amapSatBase, amapSatLabels]);

    appState.layers = {
        satellite: amapSatellite,
        normal: amapNormal,
        current: 'normal'
    };

    // 业务图层
    appState.centerLayerGroup = L.layerGroup().addTo(appState.map);
    appState.cellLayerGroup = L.layerGroup().addTo(appState.map);
    appState.labelLayerGroup = L.layerGroup().addTo(appState.map);
    appState.pciConflictLayerGroup = L.featureGroup().addTo(appState.map);
    appState.drawLayerGroup = L.featureGroup().addTo(appState.map);
    appState.importedBoundaryGroup = L.featureGroup().addTo(appState.map);
    appState.searchTargetGroup = L.layerGroup().addTo(appState.map);

    // Leaflet Draw 插件配置
    const drawOptions = {
        position: 'topright',
        draw: {
            polyline: false,
            rectangle: false,
            circlemarker: false,
            marker: false,
            circle: false,
            polygon: {
                allowIntersection: false,
                shapeOptions: {
                    color: '#0071e3',
                    fillColor: '#0071e3',
                    fillOpacity: 0.18,
                    weight: 2
                }
            }
        },
        edit: {
            featureGroup: appState.drawLayerGroup,
            remove: true
        }
    };
    appState.drawControl = new L.Control.Draw(drawOptions);

    // 绘制完成监听 (支持多边形、矩形、圆形等任意图元重绘)
    appState.map.on(L.Draw.Event.CREATED, function (e) {
        const type = e.layerType;
        const layer = e.layer;

        if (appState.currentDrawer) {
            try { appState.currentDrawer.disable(); } catch (err) {}
            appState.currentDrawer = null;
        }

        appState.drawLayerGroup.clearLayers();
        appState.drawLayerGroup.addLayer(layer);
        appState.currentShapeLayer = layer;

        if (type === 'polygon' || type === 'rectangle') {
            let latlngs = layer.getLatLngs();
            while (Array.isArray(latlngs) && latlngs.length > 0 && Array.isArray(latlngs[0])) {
                latlngs = latlngs[0];
            }
            const cleanCoords = [];
            if (Array.isArray(latlngs)) {
                for (const p of latlngs) {
                    if (p && typeof p.lat === 'number' && typeof p.lng === 'number' && !isNaN(p.lat) && !isNaN(p.lng)) {
                        cleanCoords.push([p.lng, p.lat]);
                    }
                }
            }
            if (cleanCoords.length >= 3) {
                appState.lastPolygonCoords = cleanCoords;

                // 计算多边形质心并更新中心点标记
                const c_lng = cleanCoords.reduce((sum, pt) => sum + pt[0], 0) / cleanCoords.length;
                const c_lat = cleanCoords.reduce((sum, pt) => sum + pt[1], 0) / cleanCoords.length;
                setMapCenter(c_lng, c_lat, `自定义多边形(${cleanCoords.length}个顶点)`);

                executePolygonSelection(cleanCoords);
            } else {
                showToast('请至少绘制包含 3 个顶点的有效多边形', 'warning');
            }
        } else if (type === 'circle') {
            const center = layer.getLatLng();
            let radius = Math.round(layer.getRadius());
            if (radius < 50) radius = 50;
            document.getElementById('inputCenterLng').value = center.lng.toFixed(4);
            document.getElementById('inputCenterLat').value = center.lat.toFixed(4);
            setRadiusValue(radius);
            setMapCenter(center.lng, center.lat, '圆形圈选区域');
            executeCircleSelection(center.lng, center.lat, radius);
        }
    });

    // 绘制停止监听
    appState.map.on(L.Draw.Event.DRAWSTOP, function () {
        appState.currentDrawer = null;
    });

    // 地图与图层点击拾取中心点
    function handleMapPickCenter(e) {
        if (appState.selectMode === 'circle' && !appState.currentDrawer && e && e.latlng) {
            setMapCenter(e.latlng.lng, e.latlng.lat);
        }
    }
    appState.map.on('click', handleMapPickCenter);
    appState.drawLayerGroup.on('click', handleMapPickCenter);
    appState.centerLayerGroup.on('click', handleMapPickCenter);

    // 初始化地图右键菜单 (获取经纬度与取消当前状态)
    initMapContextMenu();

    // 初始绘制一次中心点与辐射圈 (工参所在城市经纬度)
    setMapCenter(107.5787, 29.7191);
}

function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).catch(() => {});
        return;
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
        document.execCommand('copy');
    } catch (e) {}
    document.body.removeChild(ta);
}

function cancelCurrentState() {
    // 向导里出来画多边形时若中途取消，不再自动返回向导
    appState.wizardReturnAfterDraw = false;
    let hasCancelled = false;

    // 1. 禁用并销毁正在进行的任何绘制（多边形、矩形等）
    if (appState.currentDrawer) {
        try {
            appState.currentDrawer.disable();
        } catch (err) {}
        appState.currentDrawer = null;
        hasCancelled = true;
    }

    // 2. 终止正在进行的地图测距
    if (appState.isMeasuring) {
        stopMapMeasure(true);
        hasCancelled = true;
    }

    // 3. 恢复为默认的圆形圈选模式
    if (appState.selectMode !== 'circle') {
        appState.selectMode = 'circle';
        updateSelectModeUI('circle');
        saveAppConfig({ selectMode: 'circle' });

        const defaultLng = (appState.baseParams && (appState.baseParams.center_lng_gcj || appState.baseParams.center_lng_wgs)) || 107.5787;
        const defaultLat = (appState.baseParams && (appState.baseParams.center_lat_gcj || appState.baseParams.center_lat_wgs)) || 29.7191;
        const lng = parseFloat(document.getElementById('inputCenterLng').value) || defaultLng;
        const lat = parseFloat(document.getElementById('inputCenterLat').value) || defaultLat;
        const radiusM = parseFloat(document.getElementById('selectRadius').value) || 5000;
        drawCirclePreview(lng, lat, radiusM);
        hasCancelled = true;
    }

    // 4. 重置地图鼠标指针与状态
    if (appState.map) {
        const container = appState.map.getContainer();
        if (container) {
            container.style.cursor = '';
        }
    }

    showToast('已取消当前状态并恢复默认圈选', 'success');
    return hasCancelled;
}
window.cancelCurrentState = cancelCurrentState;

function undoLastPolygonVertex() {
    if (!appState.currentDrawer) {
        showToast('当前未在多边形绘制中', 'warning');
        return;
    }

    const drawer = appState.currentDrawer;
    if (drawer._markers && Array.isArray(drawer._markers)) {
        if (drawer._markers.length > 1) {
            if (typeof drawer.deleteLastVertex === 'function') {
                drawer.deleteLastVertex();
                showToast('已撤销上一个顶点', 'success');
                return;
            }
        } else if (drawer._markers.length === 1) {
            // 仅剩 1 个顶点时，重置绘制器以回到纯净待选点状态
            startDrawPolygon();
            showToast('已撤销首个顶点，可重新选点', 'success');
            return;
        } else {
            showToast('暂无已添加的顶点可撤销', 'warning');
            return;
        }
    }

    if (typeof drawer.deleteLastVertex === 'function') {
        try {
            drawer.deleteLastVertex();
            showToast('已撤销上一个顶点', 'success');
            return;
        } catch (e) {}
    }

    showToast('暂无可撤销的顶点', 'warning');
}
window.undoLastPolygonVertex = undoLastPolygonVertex;

function initMapContextMenu() {
    if (!appState.map) return;

    let menu = document.getElementById('mapContextMenu');
    if (!menu) {
        menu = document.createElement('div');
        menu.id = 'mapContextMenu';
        menu.className = 'map-context-menu';
        document.body.appendChild(menu);
    }

    const hideMenu = () => {
        if (menu) menu.style.display = 'none';
    };

    appState.map.on('contextmenu', function (e) {
        if (!e.latlng) return;
        const lng = Number(e.latlng.lng.toFixed(6));
        const lat = Number(e.latlng.lat.toFixed(6));
        const coordStr = `${lng}, ${lat}`;

        const isDrawingPolygon = !!(appState.currentDrawer && (appState.selectMode === 'polygon' || appState.selectMode === 'rect'));
        const undoHtml = isDrawingPolygon ? `
            <div class="map-context-menu-item warning" id="menuItemUndoVertex" style="border-top: 1px solid rgba(0, 0, 0, 0.06); margin-top: 2px; padding-top: 7px;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ff9f0a" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
                <span style="color: #ff9f0a;">撤销上一步 (退格)</span>
            </div>
        ` : '';

        menu.innerHTML = `
            <div class="map-context-menu-item" id="menuItemGetCoords">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#0071e3" stroke-width="2"><path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
                <span>获取经纬度 (${coordStr})</span>
            </div>
            ${undoHtml}
            <div class="map-context-menu-item danger" id="menuItemCancelState" style="border-top: 1px solid rgba(0, 0, 0, 0.06); margin-top: 2px; padding-top: 7px;">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ff3b30" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                <span style="color: #ff3b30;">取消当前状态</span>
            </div>
        `;
        menu.style.display = 'block';

        // 碰撞防护：计算右键坐标并防止超出屏幕可视边界
        const menuWidth = 220;
        const menuHeight = isDrawingPolygon ? 108 : 76;
        let posX = e.originalEvent ? e.originalEvent.clientX : 100;
        let posY = e.originalEvent ? e.originalEvent.clientY : 100;
        if (posX + menuWidth > window.innerWidth) {
            posX = Math.max(8, window.innerWidth - menuWidth - 8);
        }
        if (posY + menuHeight > window.innerHeight) {
            posY = Math.max(8, window.innerHeight - menuHeight - 8);
        }
        menu.style.left = `${posX}px`;
        menu.style.top = `${posY}px`;

        const btnGet = document.getElementById('menuItemGetCoords');
        if (btnGet) {
            btnGet.onclick = function (evt) {
                evt.stopPropagation();
                hideMenu();
                copyTextToClipboard(coordStr);
                const inputAddr = document.getElementById('inputEventAddress');
                if (inputAddr) inputAddr.value = coordStr;
                showToast(`已获取经纬度: ${coordStr} 并复制到剪贴板`, 'success');
            };
        }

        const btnUndo = document.getElementById('menuItemUndoVertex');
        if (btnUndo) {
            btnUndo.onclick = function (evt) {
                evt.stopPropagation();
                hideMenu();
                undoLastPolygonVertex();
            };
        }

        const btnCancel = document.getElementById('menuItemCancelState');
        if (btnCancel) {
            btnCancel.onclick = function (evt) {
                evt.stopPropagation();
                hideMenu();
                cancelCurrentState();
            };
        }
    });

    appState.map.on('click', hideMenu);
    appState.map.on('movestart', hideMenu);
    appState.map.on('zoomstart', hideMenu);
    document.addEventListener('click', hideMenu);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') hideMenu();
    });
}

// ---------------------------------------------------------------------------
// 2. 地图中心点设置与红圈水波纹脉冲标记
// ---------------------------------------------------------------------------
function setMapCenter(lng, lat, addressName = null) {
    document.getElementById('inputCenterLng').value = lng.toFixed(4);
    document.getElementById('inputCenterLat').value = lat.toFixed(4);
    const coordCenterEl = document.getElementById('coordCenterText');
    if (coordCenterEl) {
        coordCenterEl.innerText = `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
    }
    if (addressName) {
        document.getElementById('inputEventAddress').value = addressName;
    }

    // 绘制中心点标记
    appState.centerLayerGroup.clearLayers();

    // 醒目圆心红圈脉冲水波纹 HTML Marker (现代极简雷达准星 SVG，无多余文字标签)
    const centerHtml = `
        <div class="event-center-marker">
            <div class="sonar-ripple"></div>
            <div class="marker-inner-pin">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5">
                    <circle cx="12" cy="12" r="3" fill="#ffffff"/>
                    <circle cx="12" cy="12" r="8"/>
                    <line x1="12" y1="2" x2="12" y2="6"/>
                    <line x1="12" y1="18" x2="12" y2="22"/>
                    <line x1="2" y1="12" x2="6" y2="12"/>
                    <line x1="18" y1="12" x2="22" y2="12"/>
                </svg>
            </div>
        </div>
    `;
    const icon = L.divIcon({
        html: centerHtml,
        className: 'custom-center-divicon',
        iconSize: [32, 32],
        iconAnchor: [16, 16]
    });

    L.marker([lat, lng], { 
        icon: icon, 
        interactive: false,
        zIndexOffset: 10000 
    }).addTo(appState.centerLayerGroup);

    // 圆心中心实体高亮定位微锚点（独立于覆盖范围图层，始终可见）
    L.circleMarker([lat, lng], {
        radius: 4,
        color: '#ffffff',
        weight: 2,
        fillColor: '#ff3b30',
        fillOpacity: 1,
        interactive: false,
        zIndexOffset: 10000
    }).addTo(appState.centerLayerGroup);

    // 若用户配置了关掉事件区域图层，保持从地图中移除；否则确保其在地图上
    if (appState.layerVisibility && appState.layerVisibility['emergency'] === false) {
        if (appState.map) appState.map.removeLayer(appState.centerLayerGroup);
    } else {
        if (appState.map && !appState.map.hasLayer(appState.centerLayerGroup)) {
            appState.map.addLayer(appState.centerLayerGroup);
        }
    }

    // 若当前为圆形模式，刷新半径圈
    if (appState.selectMode === 'circle') {
        const radiusM = parseFloat(document.getElementById('selectRadius').value) || 5000;
        drawCirclePreview(lng, lat, radiusM);
    }

    // 自动持久化保存中心点坐标与地标
    const addrInput = document.getElementById('inputEventAddress');
    saveAppConfig({
        centerLng: lng,
        centerLat: lat,
        eventAddress: addressName || (addrInput ? addrInput.value : '')
    });
}

// 绘制圆形圈选半透明遮罩与同心刻度线
function drawCirclePreview(lng, lat, radiusM) {
    appState.drawLayerGroup.clearLayers();

    // 外圈实线（interactive: false 确保鼠标点击事件直达地图拾取中心点）
    const circle = L.circle([lat, lng], {
        radius: radiusM,
        color: '#0071e3',
        fillColor: '#0071e3',
        fillOpacity: 0.16,
        weight: 2,
        interactive: false
    }).addTo(appState.drawLayerGroup);

    // 内同心虚线（如 50% 半径）
    L.circle([lat, lng], {
        radius: radiusM * 0.5,
        color: 'rgba(0, 113, 227, 0.25)',
        dashArray: '4, 6',
        fill: false,
        weight: 1.5,
        interactive: false
    }).addTo(appState.drawLayerGroup);

    appState.currentShapeLayer = circle;

    // 若用户配置了关掉基站覆盖范围图层，保持从地图中移除
    if (appState.layerVisibility && appState.layerVisibility['emergency'] === false && appState.map) {
        appState.map.removeLayer(appState.drawLayerGroup);
    }
}

// ---------------------------------------------------------------------------
// 3. 工参加载与指标同步
// ---------------------------------------------------------------------------
async function checkBaseParams() {
    try {
        const data = await safeFetchJson('/api/params/status');
        if (data && data.loaded) {
            updateBaseParamUI(data);
        } else {
            // 自动加载默认工参
            autoLoadDefaultParams();
        }
    } catch (err) {
        console.warn('检测工参状态失败，自动尝试加载内置工参');
        autoLoadDefaultParams();
    }
}

async function autoLoadDefaultParams() {
    const formData = new FormData();
    formData.append('use_default', 'true');
    try {
        const data = await safeFetchJson('/api/params/load', {
            method: 'POST',
            body: formData
        });
        updateBaseParamUI(data);
    } catch (err) {
        console.error('加载工参失败', err);
    }
}

function updateBaseParamUI(data) {
    if (!data) return;
    appState.baseParams = data;
    
    const lte = Number(data.lte_cells || 0);
    const nr = Number(data.nr_cells || 0);
    const total = data.total_cells !== undefined ? Number(data.total_cells) : (lte + nr);
    const sites = Number(data.total_sites || 0);

    // 统一同步全界面指标
    updateWmapMetrics(sites, lte, nr, total);

    if (data.update_time) {
        const elTime = document.getElementById('topStatUpdateTime');
        if (elTime) elTime.innerText = data.update_time;
    }

    // 若工参携带了小区列表，自动渲染到地图上
    if (data.cells && Array.isArray(data.cells) && data.cells.length > 0) {
        appState.allCells = data.cells;
        appState.selectedCells = data.cells;
        renderCellSectors(data.cells);
    }

    // 地图默认定位到工参所属的核心区域城市经纬度
    const targetLat = (appState.currentTileType === 'amap' ? (data.center_lat_gcj || data.center_lat_wgs) : data.center_lat_wgs) || 29.7191;
    const targetLng = (appState.currentTileType === 'amap' ? (data.center_lng_gcj || data.center_lng_wgs) : data.center_lng_wgs) || 107.5787;

    if (!appState.hasUserSelected && appState.map) {
        appState.map.setView([targetLat, targetLng], 12);
        setMapCenter(targetLng, targetLat);
    }
}

// ---------------------------------------------------------------------------
// 4. 空间圈选执行
// ---------------------------------------------------------------------------
function triggerMainSelection() {
    if (appState.selectMode === 'circle') {
        const lng = parseFloat(document.getElementById('inputCenterLng').value);
        const lat = parseFloat(document.getElementById('inputCenterLat').value);
        let radius = parseFloat(document.getElementById('selectRadius').value);
        if (isNaN(radius) || radius < 50) radius = 50;
        if (isNaN(lng) || isNaN(lat)) {
            showToast('请输入有效的经纬度坐标', 'error');
            return;
        }
        executeCircleSelection(lng, lat, radius);
    } else if (appState.selectMode === 'polygon') {
        if (appState.lastPolygonCoords && appState.lastPolygonCoords.length >= 3) {
            executePolygonSelection(appState.lastPolygonCoords);
        } else {
            startDrawPolygon();
        }
    }
}

async function executeCircleSelection(lng, lat, radius, taskName = null, addressName = null) {
    showLoading('正在查询...');
    try {
        const address = addressName !== null ? addressName : (document.getElementById('inputEventAddress').value || '');
        const eventName = taskName !== null ? taskName : (address || `圆形圈选保障(${radius}米)`);

        const formData = new FormData();
        formData.append('center_lng', lng);
        formData.append('center_lat', lat);
        formData.append('radius_m', radius);
        formData.append('coord_sys', appState.coordSys);
        formData.append('event_name', eventName);
        formData.append('address', address);

        const data = await safeFetchJson('/api/spatial/circle', {
            method: 'POST',
            body: formData
        });

        appState.hasUserSelected = true;
        handleSelectionResult(data, {
            type: 'circle',
            center: [lat, lng],
            radius: radius
        });
        showToast(`已圈选 ${data.total_sites} 基站 (${data.total_cells} 小区)`, 'success');
        loadRecentTasks();
    } catch (err) {
        showToast(`圈选失败: ${err.message}`, 'error');
    } finally {
        hideLoading();
    }
}

async function executePolygonSelection(coords, taskName = null, addressName = null) {
    showLoading('正在查询...');
    try {
        const address = addressName !== null ? addressName : (document.getElementById('inputEventAddress').value || '');
        const eventName = taskName !== null ? taskName : (address || `多边形圈选(${coords.length}顶点)`);

        const formData = new FormData();
        formData.append('polygon', JSON.stringify(coords));
        formData.append('coord_sys', appState.coordSys);
        formData.append('event_name', eventName);
        formData.append('address', address);

        const data = await safeFetchJson('/api/spatial/polygon', {
            method: 'POST',
            body: formData
        });

        appState.hasUserSelected = true;
        handleSelectionResult(data, {
            type: 'polygon',
            coords: coords
        });
        showToast(`已圈选 ${data.total_sites} 基站 (${data.total_cells} 小区)`, 'success');
        loadRecentTasks();
    } catch (err) {
        showToast(`多边形圈选失败: ${err.message}`, 'error');
    } finally {
        hideLoading();
    }
}

// ---------------------------------------------------------------------------
// 5. 圈选结果处理与联动渲染 (整合 02 圈选结果与基站工参)
// ---------------------------------------------------------------------------
function handleSelectionResult(data, shapeInfo) {
    appState.selectedCells = data.cells || [];

    // 1. 将小区聚合为基站清单 (并挂载下属小区数组供展开明细)
    appState.siteList = aggregateCellsToSites(appState.selectedCells);
    appState.filteredSites = [...appState.siteList];

    // 2. 统计计算
    const lteSitesCount = appState.siteList.filter(s => s.rat === '4G').length;
    const nrSitesCount = appState.siteList.filter(s => s.rat === '5G').length;
    const totalSitesCount = appState.siteList.length;
    const totalCellsCount = appState.selectedCells.length;

    // 3. 更新右侧整合面板 02 标题与制式标签数量
    const tipEl = document.getElementById('rightPanelTotalSitesTip');
    if (tipEl) tipEl.innerText = `共 ${totalSitesCount} 基站 / ${totalCellsCount} 小区`;
    
    const countAllEl = document.getElementById('countRatAll');
    if (countAllEl) countAllEl.innerText = totalSitesCount;
    const countLteEl = document.getElementById('countRatLte');
    if (countLteEl) countLteEl.innerText = lteSitesCount;
    const countNrEl = document.getElementById('countRatNr');
    if (countNrEl) countNrEl.innerText = nrSitesCount;

    const textSelCount = document.getElementById('textSelectedSitesCount');
    if (textSelCount) textSelCount.innerText = `已选 ${totalSitesCount} 个基站 (${totalCellsCount} 个小区)`;

    // 4. 更新右侧整合卡片中的宏观指标
    const metricTotalCells = document.getElementById('dockMetricTotalCells');
    if (metricTotalCells) metricTotalCells.innerText = data.total_cells || totalCellsCount;
    const metricTotalSites = document.getElementById('dockMetricTotalSites');
    if (metricTotalSites) metricTotalSites.innerText = totalSitesCount;
    const metricLteSites = document.getElementById('dockMetricLteSites');
    if (metricLteSites) metricLteSites.innerText = lteSitesCount;
    const metricNrSites = document.getElementById('dockMetricNrSites');
    if (metricNrSites) metricNrSites.innerText = nrSitesCount;

    // 计算覆盖面积 (平方公里)
    let areaKm2 = '18.6';
    if (shapeInfo.type === 'circle') {
        const rKm = shapeInfo.radius / 1000;
        const calcArea = Math.PI * rKm * rKm;
        areaKm2 = calcArea >= 0.1 ? calcArea.toFixed(1) : (calcArea >= 0.01 ? calcArea.toFixed(2) : calcArea.toFixed(4));
    } else if (shapeInfo.type === 'polygon' && shapeInfo.coords) {
        areaKm2 = (shapeInfo.coords.length * 3.5).toFixed(1);
    }
    const metricArea = document.getElementById('dockMetricAreaKm2');
    if (metricArea) metricArea.innerText = `${areaKm2} km²`;

    // 仪表盘圆环偏移量动态更新 (满圈 175)
    const gauge = document.getElementById('gaugeCircle');
    if (gauge) {
        const ratio = Math.min(1, (totalCellsCount || 50) / 300);
        gauge.style.strokeDashoffset = String(175 * (1 - ratio));
    }

    // 5. 渲染表格
    applyTableFilters();

    // 6. 刷新持久化任务记录
    loadRecentTasks();

    // 7. 地图渲染基站打点
    renderCellMarkers(appState.selectedCells);

    // 8. 从应急向导出来画多边形：选区完成后自动返回向导第 1 步
    if (appState.wizardReturnAfterDraw) {
        appState.wizardReturnAfterDraw = false;
        setTimeout(() => { if (typeof openPipelineModal === 'function') openPipelineModal(1); }, 350);
    }
}

// 小区数据按基站名称/ID聚合，并完整保留每个基站所属小区明细
function aggregateCellsToSites(cells) {
    const siteMap = new Map();
    cells.forEach(cell => {
        const siteName = cell.site_name || cell.site_id || '未知基站';
        if (!siteMap.has(siteName)) {
            siteMap.set(siteName, {
                site_name: siteName,
                site_id: cell.site_id || '',
                rat: cell.rat || '4G',
                longitude: cell.longitude,
                latitude: cell.latitude,
                longitude_gcj: cell.longitude_gcj,
                latitude_gcj: cell.latitude_gcj,
                sector_count: 0,
                selected: true,
                cells: []
            });
        }
        const siteObj = siteMap.get(siteName);
        siteObj.sector_count += 1;
        siteObj.cells.push(cell);
    });
    return Array.from(siteMap.values());
}

// ---------------------------------------------------------------------------
// 6. 右侧面板 02 基站与小区工参表格渲染与视图交互
// ---------------------------------------------------------------------------

// 视图切换：基站视图 (site) 或 小区明细视图 (cell) 或 告警指标视图 (alarm)
function switchParamViewMode(mode) {
    appState.paramViewMode = mode;
    const btnSite = document.getElementById('btnViewBySite');
    const btnCell = document.getElementById('btnViewByCell');
    const btnAlarm = document.getElementById('btnViewByAlarm');
    const btnToggleAll = document.getElementById('btnToggleAllExpand');
    const inputSearch = document.getElementById('inputTableFilter');
    
    if (btnSite) btnSite.classList.toggle('active', mode === 'site');
    if (btnCell) btnCell.classList.toggle('active', mode === 'cell');
    if (btnAlarm) btnAlarm.classList.toggle('active', mode === 'alarm');
    
    if (btnToggleAll) {
        if (mode === 'site') {
            btnToggleAll.style.display = 'inline-block';
            btnToggleAll.innerText = '展开全部小区';
            btnToggleAll.title = '展开或收起每个基站下属的小区';
            btnToggleAll.onclick = toggleExpandAllSites;
        } else if (mode === 'alarm') {
            btnToggleAll.style.display = 'inline-block';
            btnToggleAll.innerText = '查告警与指标';
            btnToggleAll.title = '打开窗口导入告警与指标';
            btnToggleAll.onclick = openCombinedAnalysisDiagnosisModal;
        } else {
            btnToggleAll.style.display = 'none';
        }
    }

    // 动态调整表头与搜索提示
    const theadRow = document.getElementById('tableHeaderRow');
    if (theadRow) {
        if (mode === 'site') {
            theadRow.innerHTML = `
                <th style="width: 26px;"><input type="checkbox" id="checkSelectAllSites" onchange="toggleSelectAllSites(this.checked)" checked></th>
                <th>基站名称 (含下属小区)</th>
                <th style="width: 50px;">制式</th>
                <th style="width: 60px; text-align: center;">小区数</th>
            `;
            if (inputSearch) inputSearch.placeholder = '搜索基站名、小区名称、CGI、小区ID...';
        } else if (mode === 'cell') {
            theadRow.innerHTML = `
                <th style="width: 26px;"><input type="checkbox" id="checkSelectAllSites" onchange="toggleSelectAllSites(this.checked)" checked></th>
                <th>小区名称 / 所属基站</th>
                <th style="width: 48px;">制式</th>
                <th style="width: 80px;">CGI / 小区ID</th>
                <th style="width: 50px;">频段</th>
                <th style="width: 45px; text-align: center;">方位角</th>
                <th style="width: 65px;">经度</th>
                <th style="width: 65px;">纬度</th>
            `;
            if (inputSearch) inputSearch.placeholder = '搜索小区名称、所属基站、CGI、频段...';
        } else if (mode === 'alarm') {
            theadRow.innerHTML = `
                <th style="width: 52px; text-align: center;">级别</th>
                <th>小区名称 / 所属基站</th>
                <th style="width: 72px;">异常分类</th>
                <th>当前告警</th>
                <th style="width: 105px;">PRB/RRC/接通率</th>
                <th style="width: 55px;">时间</th>
            `;
            if (inputSearch) inputSearch.placeholder = '搜索告警名称、小区、基站...';
        }
    }

    applyTableFilters();
}

// 展开/收起单个基站的小区明细
function toggleExpandSite(siteName) {
    if (appState.expandedSiteSet.has(siteName)) {
        appState.expandedSiteSet.delete(siteName);
    } else {
        appState.expandedSiteSet.add(siteName);
    }
    renderBaseStationTable(appState.filteredSites);
}

// 一键展开/收起全部基站下属小区
function toggleExpandAllSites() {
    const btn = document.getElementById('btnToggleAllExpand');
    const isAllExpanded = appState.filteredSites.length > 0 && 
                          appState.filteredSites.every(s => appState.expandedSiteSet.has(s.site_name));
    if (isAllExpanded) {
        appState.expandedSiteSet.clear();
        if (btn) btn.innerText = '展开全部小区';
    } else {
        appState.filteredSites.forEach(s => appState.expandedSiteSet.add(s.site_name));
        if (btn) btn.innerText = '收起全部小区';
    }
    renderBaseStationTable(appState.filteredSites);
}

// 点击基站行聚焦地图
function onSiteRowClick(siteName) {
    const site = appState.siteList.find(s => s.site_name === siteName);
    if (site && site.latitude && site.longitude && appState.map) {
        let lat = parseFloat(site.latitude);
        let lng = parseFloat(site.longitude);
        if (appState.currentTileType === 'amap' && site.latitude_gcj && site.longitude_gcj) {
            lat = parseFloat(site.latitude_gcj);
            lng = parseFloat(site.longitude_gcj);
        }
        appState.map.panTo([lat, lng]);
    }
}

// 渲染基站视图表格 (带下属小区展开卡片)
function renderBaseStationTable(sites) {
    const tbody = document.getElementById('tbodyBaseStations');
    if (!tbody) return;

    if (!sites || sites.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: #86868b; padding: 24px;">当前区域未命中基站数据</td></tr>`;
        return;
    }

    const html = sites.slice(0, 150).map((site, idx) => {
        const isLte = site.rat === '4G';
        const ratBadge = isLte 
            ? `<span class="badge-rat-lte">LTE</span>`
            : `<span class="badge-rat-nr">NR</span>`;
        const icon = isLte 
            ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0071e3" stroke-width="2" style="vertical-align:-1px;margin-right:3px;"><path d="M12 2L4 22h16L12 2z"/><line x1="8" y1="12" x2="16" y2="12"/></svg>` 
            : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#bf5af2" stroke-width="2" style="vertical-align:-1px;margin-right:3px;"><path d="M12 2L4 22h16L12 2z"/><line x1="8" y1="12" x2="16" y2="12"/></svg>`;
        const isExpanded = appState.expandedSiteSet.has(site.site_name);
        const arrow = isExpanded ? '▼' : '▶';
        const cells = site.cells || [];
        const safeSiteName = (site.site_name || '').replace(/'/g, "\\'");

        // 展开的下属小区明细卡片 (Data-Terminal 超紧凑微徽章网格)
        let cellDetailHtml = '';
        if (isExpanded && cells.length > 0) {
            const cellItems = cells.map(c => {
                const cellFreq = c.freq_band || (c.rat === '4G' ? 'LTE' : 'NR');
                const azStr = (c.azimuth !== undefined && c.azimuth !== null && c.azimuth !== '') ? `${c.azimuth}°` : '-';
                const tiltStr = (c.tilt !== undefined && c.tilt !== null && c.tilt !== '') ? `${c.tilt}°` : '-';
                return `
                    <div class="cell-item-chip" title="CGI: ${c.cgi || '未知'} | 频段: ${cellFreq} | 方位角: ${azStr} | 下倾角: ${tiltStr}">
                        <span style="font-weight: 600; color: #1d1d1f;">${c.cell_name || c.cell_id}</span>
                        <span class="cell-prop-badge">${cellFreq}</span>
                        <span class="cell-prop-badge" style="color: #ff9f0a;">${azStr}</span>
                        <span class="cell-prop-badge" style="color: #86868b;">${tiltStr}</span>
                    </div>
                `;
            }).join('');

            cellDetailHtml = `
                <tr class="cell-sub-row">
                    <td></td>
                    <td colspan="3" style="padding: 3px 6px;">
                        <div class="cell-sub-card">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
                                <span style="font-size: 10px; color: #0071e3; font-weight: 600;">下属 ${cells.length} 个扇区 (频段 / 方位角 / 下倾角)</span>
                            </div>
                            <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                                ${cellItems}
                            </div>
                        </div>
                    </td>
                </tr>
            `;
        }

        return `
            <tr style="cursor: pointer;" onclick="onSiteRowClick('${safeSiteName}')">
                <td onclick="event.stopPropagation();"><input type="checkbox" ${site.selected ? 'checked' : ''} onchange="toggleSiteSelect(${idx}, this.checked)"></td>
                <td style="font-weight: 500; color: #1d1d1f;">
                    <span class="cell-expand-btn" onclick="event.stopPropagation(); toggleExpandSite('${safeSiteName}')" title="展开/收起该基站所属小区">${arrow}</span>
                    ${icon} <span>${site.site_name}</span>
                    <span class="cell-count-tag">${cells.length}小区</span>
                </td>
                <td>${ratBadge}</td>
                <td style="font-family: monospace; text-align: center; color: #0071e3; font-weight: 600;">${site.sector_count}</td>
            </tr>
            ${cellDetailHtml}
        `;
    }).join('');

    tbody.innerHTML = html;
}

// 渲染小区平铺视图表格 (直接展示圈选区域内所有小区工参)
function renderCellFlatTable(cells) {
    const tbody = document.getElementById('tbodyBaseStations');
    if (!tbody) return;

    if (!cells || cells.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #86868b; padding: 24px;">当前区域未命中有效小区工参</td></tr>`;
        return;
    }

    const html = cells.slice(0, 200).map((c) => {
        const isLte = (c.rat === '4G' || c.rat === 'LTE');
        const ratBadge = isLte 
            ? `<span class="badge-rat-lte">LTE</span>`
            : `<span class="badge-rat-nr">NR</span>`;
        const lngStr = c.longitude ? Number(c.longitude).toFixed(4) : '-';
        const latStr = c.latitude ? Number(c.latitude).toFixed(4) : '-';
        const cellId = c.cell_id || '-';
        const cgi = c.cgi || '-';
        const freq = c.freq_band || (isLte ? '1.8G' : '3.5G');
        const az = (c.azimuth !== undefined && c.azimuth !== null && c.azimuth !== '') ? `${c.azimuth}°` : '-';
        const tilt = (c.tilt !== undefined && c.tilt !== null && c.tilt !== '') ? `${c.tilt}°` : '-';

        return `
            <tr>
                <td><input type="checkbox" checked disabled style="opacity: 0.5;"></td>
                <td style="color: #1d1d1f; font-weight: 500;">
                    <div style="color: #0071e3; font-weight: 600; font-size: 11px;">${c.cell_name || ('Cell ' + cellId)}</div>
                    <div style="font-size: 9.5px; color: #86868b; font-family: monospace;">${c.site_name || c.site_id || '-'}</div>
                </td>
                <td>${ratBadge}</td>
                <td style="font-family: monospace; color: #1d1d1f; font-size: 10.5px;">
                    <div>${cellId}</div>
                    <div style="color: #86868b; font-size: 9px;">${cgi}</div>
                </td>
                <td style="color: #86868b; font-size: 10.5px; font-family: monospace;">${freq}</td>
                <td style="text-align: center; color: #ff9f0a; font-family: monospace; font-size: 10.5px;" title="下倾角: ${tilt}">${az}</td>
                <td style="font-family: monospace; color: #86868b; font-size: 10.5px;">${lngStr}</td>
                <td style="font-family: monospace; color: #86868b; font-size: 10.5px;">${latStr}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = html;
}

// 渲染异常告警与指标明细表格 (支持随时打开查阅)
function renderAlarmMetricsTable(cells) {
    const tbody = document.getElementById('tbodyBaseStations');
    if (!tbody) return;

    if (!cells || cells.length === 0) {
        if (!appState.diagnosisResult) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: #86868b; padding: 36px 16px;">
                        <div style="margin-bottom: 8px; display: flex; justify-content: center;"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#86868b" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div>
                        <div style="color: #6e6e73; font-weight: 500; font-size: 13px;">尚未导入告警或性能表</div>
                        <div style="font-size: 11.5px; color: #86868b; margin-top: 6px;">点击下方【查告警与指标】导入表格比对</div>
                    </td>
                </tr>`;
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; color: #30d158; padding: 32px 16px;">
                        <div style="margin-bottom: 8px; display: flex; justify-content: center;"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="8 12 11 15 16 9"/></svg></div>
                        <div style="font-weight: 600; font-size: 13px;">圈选范围内未发现异常小区</div>
                        <div style="font-size: 11.5px; color: #86868b; margin-top: 4px;">无退服告警，PRB利用率与接通率均在正常门限内</div>
                    </td>
                </tr>`;
        }
        return;
    }

    const html = cells.map(c => {
        let badge = `<span style="background: rgba(255, 59, 48, 0.12); color:#ff3b30; border:1px solid rgba(255, 59, 48, 0.25); padding:1px 6px; border-radius:4px; font-weight:bold; font-size:10px;">P0 退服</span>`;
        if (c.diag_level === 'P1') {
            badge = `<span style="background: rgba(255, 159, 10, 0.12); color:#ff9f0a; border:1px solid rgba(255, 159, 10, 0.25); padding:1px 6px; border-radius:4px; font-weight:bold; font-size:10px;">P1 拥塞/干扰</span>`;
        } else if (c.diag_level === 'P2') {
            badge = `<span style="background: rgba(0, 113, 227, 0.12); color:#0071e3; border:1px solid rgba(0, 113, 227, 0.25); padding:1px 6px; border-radius:4px; font-weight:bold; font-size:10px;">P2 质差</span>`;
        }

        const safeCellName = (c.cell_name || c.cell_id || '').replace(/'/g, "\\'");
        const safeSiteName = (c.site_name || c.site_id || '').replace(/'/g, "\\'");
        const alarmDesc = c.alarm_name || c.diag_detail || c.alarm_cause || '性能指标越限';
        const timeStr = c.start_time ? c.start_time.slice(-8) : '近期';

        // 核心性能KPI指标卡片
        const kpiChips = [];
        if (c.prb_dl_util !== undefined && c.prb_dl_util !== null && c.prb_dl_util !== '') {
            const prbVal = parseFloat(c.prb_dl_util);
            const prbColor = prbVal >= 80 ? '#ff3b30' : (prbVal >= 70 ? '#ff9f0a' : '#0071e3');
            kpiChips.push(`<span style="color:${prbColor}; font-weight:600;">PRB:${prbVal}%</span>`);
        }
        if (c.rrc_conn_max !== undefined && c.rrc_conn_max !== null && c.rrc_conn_max !== '') {
            kpiChips.push(`<span>RRC:${c.rrc_conn_max}</span>`);
        }
        if (c.setup_success_rate !== undefined && c.setup_success_rate !== null && c.setup_success_rate !== '') {
            const srVal = parseFloat(c.setup_success_rate);
            const srColor = srVal < 98 ? '#ff3b30' : '#30d158';
            kpiChips.push(`<span style="color:${srColor};">接通:${srVal}%</span>`);
        }
        if (c.drop_rate !== undefined && c.drop_rate !== null && c.drop_rate !== '') {
            const drVal = parseFloat(c.drop_rate);
            if (drVal > 0.5) kpiChips.push(`<span style="color:#ff3b30;">掉话:${drVal}%</span>`);
        }
        const kpiHtml = kpiChips.length > 0 
            ? `<div style="display:flex; flex-direction:column; gap:2px; font-size:10px; font-family:monospace;">${kpiChips.join('')}</div>`
            : `<span style="color:#86868b; font-size:11px;">-</span>`;

        return `
            <tr style="cursor: pointer;" onclick="onAlarmRowClick('${safeCellName}', '${safeSiteName}')" title="点击在地图上精准聚焦并展开该小区告警与KPI">
                <td style="text-align: center;">${badge}</td>
                <td>
                    <div style="color: #1d1d1f; font-weight: 600; font-size: 12px;">${c.cell_name || c.cell_id}</div>
                    <div style="font-size: 10px; color: #86868b;">基站: ${c.site_name || c.site_id}</div>
                </td>
                <td style="color: #ff9f0a; font-size: 11.5px; font-weight: 500;">${c.diag_type || '异常'}</td>
                <td style="color: #6e6e73; font-size: 11px;" title="${alarmDesc}">
                    <div style="max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${alarmDesc}</div>
                </td>
                <td>${kpiHtml}</td>
                <td style="font-family: monospace; color: #86868b; font-size: 10px;">${timeStr}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = html;
}

function filterTableByRat(rat) {
    appState.currentRatFilter = rat;
    document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
    if (rat === 'ALL') document.getElementById('tabRatAll').classList.add('active');
    if (rat === '4G') document.getElementById('tabRatLte').classList.add('active');
    if (rat === '5G') document.getElementById('tabRatNr').classList.add('active');

    applyTableFilters();
}

function onTableSearchInput(val) {
    appState.tableSearchKeyword = (val || '').trim().toLowerCase();
    applyTableFilters();
}

function applyTableFilters() {
    const kw = appState.tableSearchKeyword;
    const rat = appState.currentRatFilter;

    if (appState.paramViewMode === 'alarm') {
        let filteredAlarms = appState.diagnosedCells || [];
        if (rat !== 'ALL') {
            filteredAlarms = filteredAlarms.filter(c => {
                const cRat = (c.rat === '4G' || c.rat === 'LTE') ? '4G' : ((c.rat === '5G' || c.rat === 'NR') ? '5G' : c.rat);
                return cRat === rat;
            });
        }
        if (kw) {
            filteredAlarms = filteredAlarms.filter(c => 
                (c.cell_name && c.cell_name.toLowerCase().includes(kw)) ||
                (c.site_name && c.site_name.toLowerCase().includes(kw)) ||
                (c.diag_type && c.diag_type.toLowerCase().includes(kw)) ||
                (c.alarm_name && c.alarm_name.toLowerCase().includes(kw)) ||
                (c.diag_detail && c.diag_detail.toLowerCase().includes(kw)) ||
                (c.diag_level && c.diag_level.toLowerCase().includes(kw))
            );
        }
        renderAlarmMetricsTable(filteredAlarms);
        return;
    }

    if (appState.paramViewMode === 'site') {
        let filtered = appState.siteList;
        if (rat !== 'ALL') {
            filtered = filtered.filter(s => s.rat === rat);
        }
        if (kw) {
            filtered = filtered.filter(s => {
                const matchSite = (s.site_name && s.site_name.toLowerCase().includes(kw)) ||
                                  (s.site_id && s.site_id.toLowerCase().includes(kw));
                const matchCell = (s.cells || []).some(c => 
                    (c.cell_name && c.cell_name.toLowerCase().includes(kw)) ||
                    (c.cell_id && String(c.cell_id).toLowerCase().includes(kw)) ||
                    (c.cgi && c.cgi.toLowerCase().includes(kw))
                );
                return matchSite || matchCell;
            });
        }
        appState.filteredSites = filtered;
        renderBaseStationTable(filtered);
    } else {
        let filteredCells = appState.selectedCells;
        if (rat !== 'ALL') {
            filteredCells = filteredCells.filter(c => {
                const cRat = (c.rat === '4G' || c.rat === 'LTE') ? '4G' : ((c.rat === '5G' || c.rat === 'NR') ? '5G' : c.rat);
                return cRat === rat;
            });
        }
        if (kw) {
            filteredCells = filteredCells.filter(c => 
                (c.cell_name && c.cell_name.toLowerCase().includes(kw)) ||
                (c.cell_id && String(c.cell_id).toLowerCase().includes(kw)) ||
                (c.cgi && c.cgi.toLowerCase().includes(kw)) ||
                (c.site_name && c.site_name.toLowerCase().includes(kw)) ||
                (c.site_id && String(c.site_id).toLowerCase().includes(kw))
            );
        }
        renderCellFlatTable(filteredCells);
    }
}

function toggleSiteSelect(idx, checked) {
    if (appState.filteredSites[idx]) {
        appState.filteredSites[idx].selected = checked;
    }
    const count = appState.siteList.filter(s => s.selected).length;
    document.getElementById('textSelectedSitesCount').innerText = `已选 ${count} 个基站`;
}

function toggleSelectAllSites(checked) {
    appState.siteList.forEach(s => s.selected = checked);
    renderBaseStationTable(appState.filteredSites);
    const count = checked ? appState.siteList.length : 0;
    document.getElementById('textSelectedSitesCount').innerText = `已选 ${count} 个基站`;
}

// 告警小区行点击联动：在地图上平移并主动展开该小区的告警与指标 Popup
function onAlarmRowClick(cellName, siteName) {
    if (appState.cellMarkersMap) {
        const marker = appState.cellMarkersMap.get(cellName) || appState.cellMarkersMap.get(siteName);
        if (marker && appState.map) {
            const latLng = marker.getLatLng();
            appState.map.panTo(latLng);
            marker.openPopup();
            return;
        }
    }
    onSiteRowClick(siteName);
}
window.onAlarmRowClick = onAlarmRowClick;

// 挂载全局方法供 HTML 调用
window.switchParamViewMode = switchParamViewMode;
window.toggleExpandSite = toggleExpandSite;
window.toggleExpandAllSites = toggleExpandAllSites;
window.onSiteRowClick = onSiteRowClick;

// ---------------------------------------------------------------------------
// 7. Wmap 核心: 地图基站与按方位角扇区矢量渲染 (支持视口动态裁切与 Canvas 极速绘制)
// ---------------------------------------------------------------------------

function loadStoredViewportSettings() {
    try {
        const stored = localStorage.getItem('wmap_viewport_settings');
        if (stored) {
            const parsed = JSON.parse(stored);
            appState.viewportSettings = Object.assign({ minZoom: 12, maxZoom: 0, maxRenderLimit: 800 }, parsed);
        } else {
            appState.viewportSettings = { minZoom: 12, maxZoom: 0, maxRenderLimit: 800 };
        }
    } catch (_) {
        appState.viewportSettings = { minZoom: 12, maxZoom: 0, maxRenderLimit: 800 };
    }
}
window.loadStoredViewportSettings = loadStoredViewportSettings;

function saveViewportSettings(settings) {
    try {
        appState.viewportSettings = Object.assign({}, appState.viewportSettings, settings);
        localStorage.setItem('wmap_viewport_settings', JSON.stringify(appState.viewportSettings));
    } catch (_) {}
}
window.saveViewportSettings = saveViewportSettings;

let viewportRenderDebounceTimer = null;

function triggerViewportSectorRender() {
    if (viewportRenderDebounceTimer) clearTimeout(viewportRenderDebounceTimer);
    viewportRenderDebounceTimer = setTimeout(() => {
        renderSectorsInCurrentViewport();
    }, 100);
}
window.triggerViewportSectorRender = triggerViewportSectorRender;

function updateDynamicCellLayers(cells) {
    const container = document.getElementById('dynamicCellLayersContainer');
    const legendTitle = document.getElementById('mapLegendLayerTitle');
    const legendCount = document.getElementById('mapLegendCellCount');

    const layerMap = new Map();
    (cells || []).forEach(cell => {
        const name = (cell.layer_name && String(cell.layer_name).trim()) ? String(cell.layer_name).trim() : '工参图层';
        layerMap.set(name, (layerMap.get(name) || 0) + 1);
    });

    if (layerMap.size === 0) {
        layerMap.set('工参图层', 0);
    }

    // 1. 在地图右上角悬浮图例上面显示图层名字
    if (legendTitle) {
        const layerNames = Array.from(layerMap.keys());
        if (layerNames.length === 1) {
            legendTitle.innerText = `图层: ${layerNames[0]}`;
            legendTitle.title = layerNames[0];
        } else {
            legendTitle.innerText = `图层: ${layerNames[0]} 等 ${layerNames.length} 个`;
            legendTitle.title = layerNames.join('、');
        }
    }
    if (legendCount) {
        legendCount.innerText = `${(cells ? cells.length : 0).toLocaleString('en-US')} 扇区`;
    }

    // 2. 左侧面板动态图层管理器
    if (!container) return;
    container.innerHTML = '';

    const colors = ['#0071e3', '#30d158', '#bf5af2', '#ff9f0a', '#5e5ce6', '#64d2ff', '#ff375f'];
    let idx = 0;

    layerMap.forEach((count, layerName) => {
        const row = document.createElement('div');
        row.className = 'layer-item-row';

        const label = document.createElement('label');
        label.className = 'layer-item-label';

        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.checked = appState.layerVisibility ? (appState.layerVisibility[layerName] !== false) : true;
        chk.onchange = function() {
            if (!appState.layerVisibility) appState.layerVisibility = {};
            appState.layerVisibility[layerName] = this.checked;
            renderSectorsInCurrentViewport();
        };

        const dot = document.createElement('span');
        const color = colors[idx % colors.length];
        dot.style.cssText = `display:inline-block; width:10px; height:10px; border-radius:2px; background:${color}; flex-shrink:0;`;

        const nameSpan = document.createElement('span');
        nameSpan.innerText = layerName;
        nameSpan.title = layerName;
        nameSpan.style.cssText = "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:140px;";

        label.appendChild(chk);
        label.appendChild(dot);
        label.appendChild(nameSpan);

        const countSpan = document.createElement('span');
        countSpan.style.cssText = "font-size:11px; color:#86868b;";
        countSpan.innerText = Number(count).toLocaleString('en-US');

        row.appendChild(label);
        row.appendChild(countSpan);
        container.appendChild(row);
        idx++;
    });
}
window.updateDynamicCellLayers = updateDynamicCellLayers;

function renderCellSectors(cells) {
    if (!cells || !Array.isArray(cells)) return;
    appState.currentRenderCells = cells;

    // 1. 全局统计：基于全量工参统计基站数与自定义图层数
    const siteSet = new Set();
    const layerSet = new Set();

    cells.forEach(cell => {
        const siteKey = cell.site_name || cell.site_id || (cell.latitude + ',' + cell.longitude);
        siteSet.add(siteKey);
        const lName = (cell.layer_name && String(cell.layer_name).trim()) ? String(cell.layer_name).trim() : '工参图层';
        layerSet.add(lName);
    });

    // 统一同步全界面指标、图例与动态图层列表
    updateWmapMetrics(siteSet.size, layerSet.size, cells.length);
    updateDynamicCellLayers(cells);

    // 2. 触发视口动态渲染
    renderSectorsInCurrentViewport();
}

function renderSectorsInCurrentViewport() {
    if (!appState.map || !appState.cellLayerGroup) return;

    appState.cellLayerGroup.clearLayers();
    if (appState.labelLayerGroup) appState.labelLayerGroup.clearLayers();
    if (!appState.cellMarkersMap) appState.cellMarkersMap = new Map();
    appState.cellMarkersMap.clear();

    const cells = appState.currentRenderCells || (appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []));
    if (!cells || cells.length === 0) {
        const elVp = document.getElementById('statusViewportCount');
        if (elVp) elVp.innerText = '0 扇区';
        return;
    }

    if (!appState.sectorCanvasRenderer && L.canvas) {
        appState.sectorCanvasRenderer = L.canvas({ padding: 0.5 });
    }

    const zoom = appState.map.getZoom();
    const cfg = appState.viewportSettings || { minZoom: 12, maxZoom: 0, maxRenderLimit: 800 };
    const minZoom = (cfg.minZoom !== undefined && cfg.minZoom !== null) ? Number(cfg.minZoom) : 12;
    const maxZoom = (cfg.maxZoom !== undefined && cfg.maxZoom !== null) ? Number(cfg.maxZoom) : 0;
    const maxRenderLimit = (cfg.maxRenderLimit !== undefined && cfg.maxRenderLimit !== null) ? Number(cfg.maxRenderLimit) : 800;

    // 1. 最小层级控制（缩小地图到一定比例后自动隐藏，防全省海量扇区卡死）
    if (zoom < minZoom) {
        const elVp = document.getElementById('statusViewportCount');
        if (elVp) elVp.innerText = `视野过小 (请放大至 ${minZoom} 级以上呈现)`;
        return;
    }

    // 2. 最大层级控制（放大地图到一定比例后自动隐藏扇区）
    if (maxZoom > 0 && zoom > maxZoom) {
        const elVp = document.getElementById('statusViewportCount');
        if (elVp) elVp.innerText = `视野超限 (超过 ${maxZoom} 级自动隐藏)`;
        return;
    }

    // 建立诊断异常小区的快速索引字典
    const alarmMap = new Map();
    (appState.diagnosedCells || []).forEach(ac => {
        if (ac.cell_name) alarmMap.set(String(ac.cell_name).toLowerCase(), ac);
        if (ac.cell_id) alarmMap.set(String(ac.cell_id).toLowerCase(), ac);
        if (ac.cgi) alarmMap.set(String(ac.cgi).toLowerCase(), ac);
    });

    // 快速提取视口包围盒 (向外拓展 15% 缓冲区以消除平移边缘空白)
    const bounds = appState.map.getBounds().pad(0.15);
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    const minLat = sw.lat, maxLat = ne.lat;
    const minLng = sw.lng, maxLng = ne.lng;
    const isAmap = (appState.currentTileType === 'amap');

    const visibleCells = [];
    for (let i = 0; i < cells.length; i++) {
        const cell = cells[i];
        let lat = parseFloat(cell.latitude);
        let lng = parseFloat(cell.longitude);
        if (isAmap && cell.latitude_gcj && cell.longitude_gcj) {
            lat = parseFloat(cell.latitude_gcj);
            lng = parseFloat(cell.longitude_gcj);
        }
        if (isNaN(lat) || isNaN(lng) || (lat === 0 && lng === 0)) continue;

        if (lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng) {
            visibleCells.push(cell);
        }
    }

    const totalVisible = visibleCells.length;
    let renderCells = visibleCells;

    // 3. 视口渲染上限控制（优先绘制屏幕中心，毫秒级快速切片，保 60 FPS）
    if (maxRenderLimit > 0 && totalVisible > maxRenderLimit) {
        const center = appState.map.getCenter();
        const cLat = center.lat;
        const cLng = center.lng;
        visibleCells.sort((a, b) => {
            const latA = parseFloat(isAmap && a.latitude_gcj ? a.latitude_gcj : a.latitude);
            const lngA = parseFloat(isAmap && a.longitude_gcj ? a.longitude_gcj : a.longitude);
            const latB = parseFloat(isAmap && b.latitude_gcj ? b.latitude_gcj : b.latitude);
            const lngB = parseFloat(isAmap && b.longitude_gcj ? b.longitude_gcj : b.longitude);
            const dA = (latA - cLat) * (latA - cLat) + (lngA - cLng) * (lngA - cLng);
            const dB = (latB - cLat) * (latB - cLat) + (lngB - cLng) * (lngB - cLng);
            return dA - dB;
        });
        renderCells = visibleCells.slice(0, maxRenderLimit);
    }

    // 更新底部视口扇区计数
    const elVp = document.getElementById('statusViewportCount');
    if (elVp) {
        if (maxRenderLimit > 0 && totalVisible > maxRenderLimit) {
            elVp.innerText = `${renderCells.length.toLocaleString('en-US')} / ${totalVisible.toLocaleString('en-US')} 扇区 (已控流)`;
        } else {
            elVp.innerText = `${renderCells.length.toLocaleString('en-US')} 扇区`;
        }
    }

    const showLabels = appState.layerVisibility && appState.layerVisibility['labels'] === true && zoom >= 14;
    let labelCount = 0;

    // 仅绘制控流后的视口内小区（毫秒级 Canvas 渲染）
    renderCells.forEach(cell => {
        // 图层可见性过滤 (按自定义图层名称过滤)
        const layerKey = (cell.layer_name && String(cell.layer_name).trim()) ? String(cell.layer_name).trim() : '工参图层';
        if (appState.layerVisibility && appState.layerVisibility[layerKey] === false) return;

        const rat = String(cell.rat || '4G').toUpperCase();
        const is5G = (rat === '5G' || rat === 'NR');

        let lat = parseFloat(cell.latitude);
        let lng = parseFloat(cell.longitude);
        if (isAmap && cell.latitude_gcj && cell.longitude_gcj) {
            lat = parseFloat(cell.latitude_gcj);
            lng = parseFloat(cell.longitude_gcj);
        }

        // 检查该小区是否命中告警
        const cellKey = (cell.cell_name || '').toLowerCase();
        const idKey = (cell.cell_id !== undefined && cell.cell_id !== null) ? String(cell.cell_id).toLowerCase() : '';
        const cgiKey = (cell.cgi || '').toLowerCase();
        const alarmInfo = alarmMap.get(cellKey) || (idKey ? alarmMap.get(idKey) : null) || (cgiKey ? alarmMap.get(cgiKey) : null);

        // 获取扇区颜色 (考虑告警、PCI模3、频段或制式)
        const colors = window.WmapSector ? WmapSector.getSectorColors(cell, appState.sectorColorMode, alarmMap) : { stroke: '#0071e3', fill: '#0071e3' };

        // 构造详细弹窗内容
        let popupContent = `
            <div style="font-size: 12px; line-height: 1.6; color: #1d1d1f; min-width: 230px; font-family: -apple-system, sans-serif;">
                <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1.5px solid #6e6e73; padding-bottom: 5px; margin-bottom: 6px;">
                    <span style="font-weight: 700; font-size: 13.5px; color: #1d1d1f;">${cell.cell_name || cell.cell_id}</span>
                    <span style="background: rgba(0, 113, 227, 0.1); color: #0071e3; padding: 1px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">${cell.rat || '4G'}</span>
                </div>
                <div>基站名称: <b>${cell.site_name || cell.site_id || '-'}</b></div>
                <div>天线方位角: <b style="color: #0071e3;">${cell.azimuth !== undefined && cell.azimuth !== null ? cell.azimuth + '°' : '全向/未配'}</b></div>
                <div>物理小区PCI: <b>${cell.pci || '-'}</b> | 频段: <b>${cell.freq_band || '-'}</b></div>
                <div>全球小区标识: <span style="font-family: monospace; font-size: 11px;">${cell.cgi || '-'}</span></div>
                <div>经纬度坐标: <span style="font-family: monospace; font-size: 11px;">${lng.toFixed(5)}, ${lat.toFixed(5)}</span></div>
        `;

        if (alarmInfo) {
            const badgeClass = alarmInfo.diag_level === 'P0' ? 'color:#ff3b30;' : (alarmInfo.diag_level === 'P1' ? 'color:#ff9f0a;' : 'color:#0071e3;');
            popupContent += `
                <div style="margin-top: 6px; padding: 4px 6px; background: rgba(255, 59, 48, 0.06); border-left: 3px solid #ff3b30; border-radius: 4px;">
                    <div style="font-weight: 600; ${badgeClass}">[${alarmInfo.diag_level}] ${alarmInfo.diag_type || '异常'}</div>
                    <div style="color: #86868b; font-size: 11px;">${alarmInfo.alarm_name || alarmInfo.diag_detail || '性能越限'}</div>
                </div>
            `;
        }
        popupContent += `</div>`;

        let layerObj = null;
        const isOmni = window.WmapSector ? WmapSector.isOmniCell(cell) : false;

        if (isOmni) {
            // 全向站 / 室分：渲染精致同心圆
            layerObj = L.circleMarker([lat, lng], {
                renderer: appState.sectorCanvasRenderer,
                radius: 7,
                color: colors.stroke,
                weight: 2,
                fillColor: colors.fill,
                fillOpacity: 0.6
            });
        } else {
            // 定向扇区：按方位角生成真实波瓣多边形
            const az = parseFloat(cell.azimuth) || 0;
            const radius = window.WmapSector ? WmapSector.getAdaptiveRadius(cell) : 130;
            const coords = window.WmapSector ? WmapSector.getSectorPolygonCoordinates(lat, lng, az, appState.sectorBeamwidth, radius) : [[lat, lng]];

            layerObj = L.polygon(coords, {
                renderer: appState.sectorCanvasRenderer,
                color: colors.stroke,
                weight: 1.5,
                fillColor: colors.fill,
                fillOpacity: 0.45
            });
        }

        // 交互效果与 Tooltip
        layerObj.on('mouseover', function () {
            layerObj.setStyle({ fillOpacity: 0.85, weight: 2.5 });
        });
        layerObj.on('mouseout', function () {
            layerObj.setStyle({ fillOpacity: isOmni ? 0.6 : 0.45, weight: 1.5 });
        });
        layerObj.bindPopup(popupContent);
        
        // 绑定悬浮简要 Tooltip
        const tipText = `${cell.cell_name || cell.cell_id} (${cell.azimuth}° | PCI:${cell.pci || '-'})`;
        layerObj.bindTooltip(tipText, { direction: 'top', offset: [0, -5], opacity: 0.9 });

        layerObj.addTo(appState.cellLayerGroup);

        // 小区标注文字（开关开启且 Zoom≥14 时显示，最多 300 个，防卡顿）
        if (showLabels && labelCount < 300 && appState.labelLayerGroup && cell.cell_name) {
            const label = L.marker([lat, lng], {
                interactive: false,
                icon: L.divIcon({
                    className: 'wmap-cell-label',
                    html: `<div style="background:rgba(255, 255, 255, 0.95); border:1px solid rgba(0, 113, 227, 0.25); color:#1d1d1f; font-size:10px; padding:1px 5px; border-radius:3px; white-space:nowrap; transform:translate(8px,-8px);">${cell.cell_name}</div>`,
                    iconSize: [0, 0]
                })
            });
            label.addTo(appState.labelLayerGroup);
            labelCount++;
        }

        // 索引映射
        if (cell.cell_name) appState.cellMarkersMap.set(cell.cell_name, layerObj);
        if (cell.cell_id) appState.cellMarkersMap.set(String(cell.cell_id), layerObj);
        if (cell.site_name && !appState.cellMarkersMap.has(cell.site_name)) {
            appState.cellMarkersMap.set(cell.site_name, layerObj);
        }
    });
}
window.renderSectorsInCurrentViewport = renderSectorsInCurrentViewport;

function renderCellMarkers(cells) {
    // 兼容原有接口调用，直接引导至专业扇区渲染
    renderCellSectors(cells);
}

function updateWmapMetrics(siteCount, layerCountOrLte, countOrNr = 0, totalCells = null) {
    let total = totalCells;
    let layers = 1;
    if (total === null || total === undefined) {
        if (typeof countOrNr === 'number' && countOrNr > 0) {
            total = countOrNr;
            layers = layerCountOrLte || 1;
        } else {
            total = (Number(layerCountOrLte) || 0) + (Number(countOrNr) || 0);
        }
    } else {
        layers = layerCountOrLte || 1;
    }

    const elTopSites = document.getElementById('topStatTotalSites');
    const elTopCells = document.getElementById('topStatTotalCells');
    const elTopLayers = document.getElementById('topStatTotalLayers');
    const elLeftSites = document.getElementById('leftStatTotalSites');
    const elLeftCells = document.getElementById('leftStatTotalCells');
    const elVol = document.getElementById('statusDataVolume');

    if (elTopSites) elTopSites.innerText = Number(siteCount).toLocaleString('en-US');
    if (elTopCells) elTopCells.innerText = Number(total).toLocaleString('en-US');
    if (elTopLayers) elTopLayers.innerText = Number(layers).toLocaleString('en-US');
    if (elLeftSites) elLeftSites.innerText = Number(siteCount).toLocaleString('en-US');
    if (elLeftCells) elLeftCells.innerText = Number(total).toLocaleString('en-US');

    // 兼容可能存在的旧元素
    const elTopLte = document.getElementById('topStatLteCells');
    const elTopNr = document.getElementById('topStatNrCells');
    if (elTopLte) elTopLte.innerText = Number(total).toLocaleString('en-US');
    if (elTopNr) elTopNr.innerText = Number(layers).toLocaleString('en-US');

    // 同步底部状态栏数据量
    if (elVol) {
        elVol.innerText = `${Number(siteCount).toLocaleString('en-US')} 站 · ${Number(total).toLocaleString('en-US')} 小区`;
    }
}

// ---------------------------------------------------------------------------
// Wmap 网优交互与工具逻辑
// ---------------------------------------------------------------------------

// 图层显隐控制
function toggleLayerVisibility(type, visible) {
    if (!appState.layerVisibility) appState.layerVisibility = {};
    appState.layerVisibility[type] = visible;

    if (type === 'emergency') {
        // 应急圈选范围：圈选边界 + 事件中心点
        [appState.drawLayerGroup, appState.centerLayerGroup].forEach(g => {
            if (!g || !appState.map) return;
            if (visible) g.addTo(appState.map);
            else appState.map.removeLayer(g);
        });
    } else if (type === 'imported') {
        if (appState.importedBoundaryGroup) {
            if (visible) appState.importedBoundaryGroup.addTo(appState.map);
            else appState.map.removeLayer(appState.importedBoundaryGroup);
        }
    } else if (type === 'pci') {
        if (appState.pciConflictLayerGroup) {
            if (visible) appState.pciConflictLayerGroup.addTo(appState.map);
            else appState.map.removeLayer(appState.pciConflictLayerGroup);
        }
    } else {
        // 自定义工参图层重绘
        renderSectorsInCurrentViewport();
    }

    // 持久化图层显隐（本地存储，刷新自动恢复）
    if (typeof saveAppConfig === 'function') {
        saveAppConfig({
            showLte: appState.layerVisibility['4G'] !== false,
            showNr: appState.layerVisibility['5G'] !== false,
            showEventArea: appState.layerVisibility['emergency'] !== false,
            showImported: appState.layerVisibility['imported'] !== false,
            showPci: appState.layerVisibility['pci'] !== false,
            showLabels: appState.layerVisibility['labels'] === true
        });
    }
}
window.toggleLayerVisibility = toggleLayerVisibility;

// 小区标注文字开关（Zoom≥14 时显示小区名）
function toggleLayerLabels(checked) {
    if (!appState.layerVisibility) appState.layerVisibility = {};
    appState.layerVisibility['labels'] = !!checked;
    const activeCells = appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []);
    renderCellSectors(activeCells);
    if (typeof saveAppConfig === 'function') {
        saveAppConfig({ showLabels: !!checked });
    }
}
window.toggleLayerLabels = toggleLayerLabels;

// 调节扇区水平张角
function updateBeamwidth(val) {
    const bw = parseInt(val, 10);
    appState.sectorBeamwidth = bw;
    const txt = document.getElementById('beamwidthValText');
    if (txt) txt.innerText = `${bw}°`;
    const activeCells = appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []);
    renderCellSectors(activeCells);
}
window.updateBeamwidth = updateBeamwidth;

// 循环切换扇区着色方案 (制式 -> 频段 -> PCI模3 -> 制式)
function cycleSectorColorMode() {
    const modes = ['rat', 'freq_band', 'pci'];
    const labels = { 'rat': '制式', 'freq_band': '频段', 'pci': 'PCI模3' };
    const currIdx = modes.indexOf(appState.sectorColorMode || 'rat');
    const nextMode = modes[(currIdx + 1) % modes.length];
    appState.sectorColorMode = nextMode;

    const txt = document.getElementById('textSectorColorMode');
    if (txt) txt.innerText = `着色: ${labels[nextMode]}`;

    const activeCells = appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []);
    renderCellSectors(activeCells);
    if (typeof showToast === 'function') showToast(`扇区已切换为按【${labels[nextMode]}】着色`, 'info');
}
window.cycleSectorColorMode = cycleSectorColorMode;

// 自适应居中当前所有小区
function fitAllCellsBounds() {
    const cells = appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []);
    if (!cells || cells.length === 0) {
        if (typeof showToast === 'function') showToast('当前暂无可居中的工参数据', 'warning');
        return;
    }
    const bounds = [];
    cells.forEach(c => {
        let lat = parseFloat(c.latitude);
        let lng = parseFloat(c.longitude);
        if (appState.currentTileType === 'amap' && c.latitude_gcj && c.longitude_gcj) {
            lat = parseFloat(c.latitude_gcj);
            lng = parseFloat(c.longitude_gcj);
        }
        if (!isNaN(lat) && !isNaN(lng) && lat !== 0) bounds.push([lat, lng]);
    });
    if (bounds.length > 0 && appState.map) {
        appState.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
    }
}
window.fitAllCellsBounds = fitAllCellsBounds;

// ---------------------------------------------------------------------------
// 智能无模板工参导入交互
// ---------------------------------------------------------------------------

let currentSmartAnalysis = null;

function updateSmartImportProgress(percent, stageText, detailText, isError = false, isSuccess = false) {
    const box = document.getElementById('smartImportProgressBox');
    const bar = document.getElementById('smartImportProgressBar');
    const pctEl = document.getElementById('smartImportProgressPercent');
    const stageEl = document.getElementById('smartImportProgressStage');
    const detailEl = document.getElementById('smartImportProgressDetail');
    const spinner = document.getElementById('smartImportProgressSpinner');

    if (!box) return;
    box.classList.remove('hidden');

    const pct = Math.min(100, Math.max(0, Math.round(percent)));
    if (bar) {
        bar.style.width = `${pct}%`;
        if (isError) {
            bar.style.backgroundColor = '#ff3b30';
        } else if (isSuccess || pct >= 100) {
            bar.style.backgroundColor = '#34c759';
        } else {
            bar.style.backgroundColor = '#0071e3';
        }
    }
    if (pctEl) {
        pctEl.innerText = `${pct}%`;
        pctEl.style.color = isError ? '#ff3b30' : (isSuccess || pct >= 100 ? '#34c759' : '#0071e3');
    }
    if (stageEl) {
        stageEl.innerText = stageText || '正在处理...';
        stageEl.style.color = isError ? '#ff3b30' : '#1d1d1f';
    }
    if (detailEl) detailEl.innerText = detailText || '';
    if (spinner) {
        spinner.style.display = (isError || isSuccess || pct >= 100) ? 'none' : 'inline-block';
    }
}

let currentSmartImportRat = '4G';

window.setSmartImportRat = function(rat) {
    currentSmartImportRat = (rat === '5G') ? '5G' : '4G';
    const btn4G = document.getElementById('btnSmartRat4G');
    const btn5G = document.getElementById('btnSmartRat5G');
    if (btn4G && btn5G) {
        if (currentSmartImportRat === '4G') {
            btn4G.style.background = '#0071e3';
            btn4G.style.color = '#ffffff';
            btn5G.style.background = 'transparent';
            btn5G.style.color = '#6e6e73';
        } else {
            btn5G.style.background = '#0071e3';
            btn5G.style.color = '#ffffff';
            btn4G.style.background = 'transparent';
            btn4G.style.color = '#6e6e73';
        }
    }
};

function openSmartImportModal() {
    const modal = document.getElementById('modalSmartImport');
    if (modal) modal.style.display = 'flex';
    const box = document.getElementById('smartImportProgressBox');
    if (box) box.classList.add('hidden');

    const inputLayer = document.getElementById('inputSmartLayerName');
    if (inputLayer && !inputLayer.value) {
        inputLayer.value = '工参图层';
    }

    // 若已有工参，导入模式默认建议“追加合并”；若为空则默认“全新覆盖”
    const selMode = document.getElementById('selectSmartImportMode');
    if (selMode) {
        selMode.value = (appState.allCells && appState.allCells.length > 0) ? 'append' : 'replace';
    }

    const btnConfirm = document.getElementById('btnConfirmSmartImport');
    if (btnConfirm) {
        btnConfirm.disabled = !currentSmartAnalysis;
        btnConfirm.innerText = '确认导入并渲染';
    }
}
window.openSmartImportModal = openSmartImportModal;

async function handleSmartParamFileSelected(file) {
    if (!file) return;
    const titleEl = document.getElementById('smartParamFileTitle');
    if (titleEl) titleEl.innerText = `已选文件: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;

    // 默认图层名称设为文件名（去扩展名）
    const inputLayer = document.getElementById('inputSmartLayerName');
    if (inputLayer) {
        const defaultName = file.name.replace(/\.[^/.]+$/, "") || '工参图层';
        inputLayer.value = defaultName;
    }

    updateSmartImportProgress(25, '正在读取表格结构与识别表头...', `文件: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const resp = await fetch('/api/wmap/importer/analyze', {
            method: 'POST',
            body: formData
        });
        if (!resp.ok) throw new Error(await resp.text());
        const data = await resp.json();
        currentSmartAnalysis = data;

        updateSmartImportProgress(100, '✅ 表头分析完成', `识别到 ${data.columns ? data.columns.length : 0} 个列字段，已自动匹配常用列`, false, true);

        setTimeout(() => {
            const box = document.getElementById('smartImportProgressBox');
            if (box) box.classList.add('hidden');
            renderSmartMappingUI(data);
        }, 500);

    } catch (e) {
        console.error('分析工参表失败:', e);
        updateSmartImportProgress(100, '❌ 分析表格失败', e.message || '格式不支持或文件已损坏', true);
        if (typeof showToast === 'function') showToast(`分析表格失败: ${e.message}`, 'error');
    }
}
window.handleSmartParamFileSelected = handleSmartParamFileSelected;

function renderSmartMappingUI(analysis) {
    const container = document.getElementById('smartMappingContainer');
    const grid = document.getElementById('smartMappingGrid');
    const btnConfirm = document.getElementById('btnConfirmSmartImport');
    if (!container || !grid) return;

    grid.innerHTML = '';
    const cols = analysis.columns || [];
    const suggested = analysis.suggested_mapping || {};

    (analysis.standard_fields || []).forEach(std => {
        const row = document.createElement('div');
        row.style.cssText = "display: flex; align-items: center; justify-content: space-between; background: rgba(0, 0, 0, 0.04); border: 1px solid rgba(0, 113, 227, 0.1); border-radius: 5px; padding: 6px 10px; font-size: 12px;";

        const leftLabel = document.createElement('div');
        leftLabel.innerHTML = `<span style="color: ${std.required ? '#ff3b30' : '#86868b'};">${std.required ? '*' : ''}</span> <span style="color: #1d1d1f; font-weight: 500;">${std.name}</span>`;

        const select = document.createElement('select');
        select.id = `mapSelect_${std.key}`;
        select.style.cssText = "background: #ffffff; border: 1px solid rgba(0, 113, 227, 0.18); color: #0071e3; font-size: 11px; padding: 3px 6px; border-radius: 4px; max-width: 170px;";

        const emptyOpt = document.createElement('option');
        emptyOpt.value = "";
        emptyOpt.innerText = "-- 请选择 --";
        select.appendChild(emptyOpt);

        cols.forEach(col => {
            const opt = document.createElement('option');
            opt.value = col;
            opt.innerText = col;
            if (suggested[std.key] === col) opt.selected = true;
            select.appendChild(opt);
        });

        row.appendChild(leftLabel);
        row.appendChild(select);
        grid.appendChild(row);
    });

    container.style.display = 'block';
    if (btnConfirm) btnConfirm.disabled = false;
}

async function confirmSmartImport() {
    if (!currentSmartAnalysis) return;
    const mapping = {};
    (currentSmartAnalysis.standard_fields || []).forEach(std => {
        const sel = document.getElementById(`mapSelect_${std.key}`);
        if (sel && sel.value) mapping[std.key] = sel.value;
    });

    const coordSys = document.getElementById('selectSmartCoordSys')?.value || 'WGS-84';
    const saveTpl = document.getElementById('chkSaveAsTemplate')?.checked || false;
    const tplName = document.getElementById('inputCustomTemplateName')?.value || '';

    const btnConfirm = document.getElementById('btnConfirmSmartImport');
    const originalBtnText = btnConfirm ? btnConfirm.innerText : '确认导入并渲染';

    // 禁用确认按钮，防止重复提交
    if (btnConfirm) {
        btnConfirm.disabled = true;
        btnConfirm.innerHTML = `<span style="display: inline-flex; align-items: center; gap: 6px;"><span class="spinner" style="width: 12px; height: 12px; border-width: 2px;"></span><span>正在导入...</span></span>`;
    }
    if (typeof setTaskStatus === 'function') setTaskStatus(true, '工参导入中…');

    // 阶段进度平滑演进
    let progressTimer = null;
    let currentPct = 15;
    updateSmartImportProgress(currentPct, '正在解析表格数据...', '读取表格并保持原始表头结构');

    progressTimer = setInterval(() => {
        if (currentPct < 75) {
            currentPct += Math.random() * 8 + 4;
            if (currentPct < 35) {
                updateSmartImportProgress(currentPct, '正在解析表格数据...', '提取映射字段并保持原始列');
            } else if (currentPct < 60) {
                updateSmartImportProgress(currentPct, '正在清洗数据与转换坐标...', '规范化经纬度、方位角并执行坐标系对齐');
            } else {
                updateSmartImportProgress(currentPct, '正在存入本地 SQLite 数据库...', '建立空间与小区索引并持久化');
            }
        }
    }, 280);

    try {
        const importMode = document.getElementById('selectSmartImportMode')?.value || 'replace';
        const layerName = document.getElementById('inputSmartLayerName')?.value.trim() || '工参图层';

        const resp = await fetch('/api/wmap/importer/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                temp_file_id: currentSmartAnalysis.temp_file_id,
                field_mapping: mapping,
                coord_sys: coordSys,
                layer_name: layerName,
                rat: '4G',
                import_mode: importMode,
                save_as_template: saveTpl,
                template_name: tplName
            })
        });

        clearInterval(progressTimer);

        if (!resp.ok) {
            let errMsg = '服务器处理失败';
            try {
                const errData = await resp.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {
                errMsg = await resp.text();
            }
            throw new Error(errMsg);
        }

        const res = await resp.json();
        const cellCount = (res.cells || []).length;

        // 阶段 4：生成扇区与渲染
        updateSmartImportProgress(88, '正在构建地图扇区...', `已解析 ${cellCount.toLocaleString('en-US')} 个小区，正在生成方位角扇区图层`);

        await new Promise(r => setTimeout(r, 60));

        // 存入当前全局工参并全量以扇区渲染
        appState.allCells = res.cells || [];
        appState.selectedCells = res.cells || [];
        renderCellSectors(res.cells);
        fitAllCellsBounds();

        // 阶段 5：完成
        updateSmartImportProgress(100, `✅ 导入成功！共加载 ${cellCount.toLocaleString('en-US')} 个小区扇区`, '工参已持久化存入 SQLite 数据库', false, true);

        // 同步底部状态栏数据量
        const elVol = document.getElementById('statusDataVolume');
        if (elVol && res.summary) {
            elVol.innerText = `${Number(res.summary.total_sites || 0).toLocaleString('en-US')} 站 · ${Number(res.summary.total_cells || cellCount).toLocaleString('en-US')} 小区`;
        }
        if (typeof setTaskStatus === 'function') setTaskStatus(false, '空闲');

        // 延迟 800ms 关闭弹窗，让用户清晰看到 100% 成功状态
        setTimeout(() => {
            closeDarkModal('modalSmartImport');
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.innerText = originalBtnText;
            }
            const box = document.getElementById('smartImportProgressBox');
            if (box) box.classList.add('hidden');

            if (typeof showToast === 'function') {
                showToast(res.message || `工参导入成功：已加载 ${cellCount} 个小区扇区！`, 'success');
            }
        }, 800);

    } catch (e) {
        clearInterval(progressTimer);
        console.error('工参导入失败:', e);
        updateSmartImportProgress(currentPct, '❌ 导入失败', e.message || '未知异常', true);
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.innerText = '重试导入';
        }
        if (typeof setTaskStatus === 'function') setTaskStatus(false, '导入异常');
        if (typeof showToast === 'function') showToast(`工参导入失败: ${e.message}`, 'error');
    }
}
window.confirmSmartImport = confirmSmartImport;

// ---------------------------------------------------------------------------
// PCI 冲突检测逻辑
// ---------------------------------------------------------------------------

async function openPciConflictCheck() {
    const modal = document.getElementById('modalPciConflict');
    if (modal) modal.style.display = 'flex';

    const tbody = document.getElementById('tbodyPciConflicts');
    const countEl = document.getElementById('pciConflictCount');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #0071e3; padding: 20px;">正在智能扫描冲突...</td></tr>`;

    try {
        const cells = appState.selectedCells && appState.selectedCells.length > 0 ? appState.selectedCells : (appState.allCells || []);
        const resp = await fetch('/api/wmap/pci/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cells: cells, distance_threshold_m: 6000 })
        });
        const data = await resp.json();
        if (countEl) countEl.innerText = data.total_conflicts || 0;

        if (!data.conflicts || data.conflicts.length === 0) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #30d158; padding: 20px;">✅ 当前视窗内未发现 6km 范围内的同频同PCI冲突！</td></tr>`;
            return;
        }

        if (tbody) {
            tbody.innerHTML = '';
            data.conflicts.forEach((c, idx) => {
                const tr = document.createElement('tr');
                tr.style.cssText = "border-bottom: 1px solid rgba(0, 113, 227, 0.08); transition: background 0.15s;";
                tr.innerHTML = `
                    <td style="padding: 7px 10px;"><span style="color: ${c.severity === '严重' ? '#ff3b30' : '#ff9f0a'}; font-weight: 600;">${c.severity}</span></td>
                    <td style="padding: 7px 10px; font-weight: 700; color: #ff9f0a; font-family: monospace;">${c.pci}</td>
                    <td style="padding: 7px 10px;">${c.rat} (${c.freq_band})</td>
                    <td style="padding: 7px 10px; color: #1d1d1f;">${c.cell_a.cell_name}</td>
                    <td style="padding: 7px 10px; color: #1d1d1f;">${c.cell_b.cell_name}</td>
                    <td style="padding: 7px 10px; font-family: monospace; color: #0071e3;">${c.distance_m} m</td>
                    <td style="padding: 7px 10px; font-family: monospace;">${c.bearing_deg}°</td>
                    <td style="padding: 7px 10px; text-align: center;">
                        <button type="button" class="btn btn-primary" style="padding: 2px 8px; font-size: 11px;" onclick="locatePciConflict(${c.cell_a.latitude_gcj}, ${c.cell_a.longitude_gcj}, ${c.cell_b.latitude_gcj}, ${c.cell_b.longitude_gcj}, '${c.cell_a.cell_name}', '${c.cell_b.cell_name}', '${c.pci}')">定位</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error('PCI冲突检测失败:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: #ff3b30; padding: 20px;">检测失败: ${e.message}</td></tr>`;
    }
}
window.openPciConflictCheck = openPciConflictCheck;

function locatePciConflict(latA, lngA, latB, lngB, nameA, nameB, pci) {
    closeDarkModal('modalPciConflict');
    if (!appState.map) return;

    if (appState.pciConflictLayerGroup) {
        appState.pciConflictLayerGroup.clearLayers();

        // 绘制冲突红色闪烁连线
        const line = L.polyline([[latA, lngA], [latB, lngB]], {
            color: '#ff3b30',
            weight: 3,
            dashArray: '6, 6'
        }).addTo(appState.pciConflictLayerGroup);

        // 中间放置冲突标注
        const midLat = (latA + latB) / 2;
        const midLng = (lngA + lngB) / 2;
        L.marker([midLat, midLng], {
            icon: L.divIcon({
                className: 'pci-conflict-tag',
                html: `<div style="background:rgba(255, 59, 48, 0.9); color:#fff; font-size:11px; font-weight:bold; padding:2px 8px; border-radius:4px; white-space:nowrap; box-shadow:0 0 10px rgba(255, 59, 48, 0.35);">PCI ${pci} 冲突</div>`
            })
        }).addTo(appState.pciConflictLayerGroup);
    }

    // 缩放到该区域
    appState.map.fitBounds([[latA, lngA], [latB, lngB]], { padding: [60, 60], maxZoom: 16 });
    if (typeof showToast === 'function') {
        showToast(`已在地图高亮 PCI ${pci} 冲突连线: ${nameA} ↔ ${nameB}`, 'warning');
    }
}
window.locatePciConflict = locatePciConflict;


// ---------------------------------------------------------------------------
// 8. 交互事件绑定与圈选工具控制
// ---------------------------------------------------------------------------
function updateSelectModeUI(mode) {
    document.querySelectorAll('.mode-pill-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.map-tool-btn').forEach(btn => {
        if (btn.id === 'toolBtnCircle' || btn.id === 'toolBtnPolygon' || btn.id === 'toolBtnRect') {
            btn.classList.remove('active');
        }
    });

    const circleSec = document.getElementById('circleRadiusSection');
    const redrawBar = document.getElementById('polygonRedrawBar');

    // 右上角地图工具栏快捷圈选图标状态同步
    const topCircleBtn = document.getElementById('toolBtnCircleMap');
    const topPolygonBtn = document.getElementById('toolBtnPolygonMap');
    if (topCircleBtn) topCircleBtn.classList.toggle('active', mode === 'circle');
    if (topPolygonBtn) topPolygonBtn.classList.toggle('active', mode === 'polygon' || mode === 'rect');

    if (mode === 'circle') {
        const pill = document.getElementById('pillModeCircle');
        const tool = document.getElementById('toolBtnCircle');
        if (pill) pill.classList.add('active');
        if (tool) tool.classList.add('active');
        if (circleSec) circleSec.style.display = 'block';
        if (redrawBar) redrawBar.style.display = 'none';
    } else if (mode === 'polygon') {
        const pill = document.getElementById('pillModePolygon');
        const tool = document.getElementById('toolBtnPolygon');
        if (pill) pill.classList.add('active');
        if (tool) tool.classList.add('active');
        if (circleSec) circleSec.style.display = 'none';
        if (redrawBar) redrawBar.style.display = 'block';
    } else if (mode === 'rect') {
        const pill = document.getElementById('pillModePolygon');
        const tool = document.getElementById('toolBtnRect');
        if (pill) pill.classList.add('active');
        if (tool) tool.classList.add('active');
        if (circleSec) circleSec.style.display = 'none';
        if (redrawBar) redrawBar.style.display = 'block';
    }
}

function startDrawPolygon() {
    if (appState.currentDrawer) {
        try { appState.currentDrawer.disable(); } catch (err) {}
        appState.currentDrawer = null;
    }

    appState.selectMode = 'polygon';
    updateSelectModeUI('polygon');

    // 清空旧的多边形图层与坐标缓存，允许任意重绘
    if (appState.drawLayerGroup) {
        appState.drawLayerGroup.clearLayers();
    }
    appState.lastPolygonCoords = null;

    const polyOptions = (appState.drawControl && appState.drawControl.options && appState.drawControl.options.draw && appState.drawControl.options.draw.polygon) || {
        shapeOptions: {
            color: '#0071e3',
            weight: 2,
            fillColor: '#0071e3',
            fillOpacity: 0.18
        }
    };
    appState.currentDrawer = new L.Draw.Polygon(appState.map, polyOptions);
    appState.currentDrawer.enable();
}

function startDrawRect() {
    if (appState.currentDrawer) {
        try { appState.currentDrawer.disable(); } catch (err) {}
        appState.currentDrawer = null;
    }

    appState.selectMode = 'polygon';
    updateSelectModeUI('rect');

    if (appState.drawLayerGroup) {
        appState.drawLayerGroup.clearLayers();
    }
    appState.lastPolygonCoords = null;

    const rectOptions = (appState.drawControl && appState.drawControl.options && appState.drawControl.options.draw && appState.drawControl.options.draw.rectangle) || {
        shapeOptions: {
            color: '#0071e3',
            weight: 2,
            fillColor: '#0071e3',
            fillOpacity: 0.18
        }
    };
    appState.currentDrawer = new L.Draw.Rectangle(appState.map, rectOptions);
    appState.currentDrawer.enable();
}

function startDrawCircle() {
    if (appState.currentDrawer) {
        try { appState.currentDrawer.disable(); } catch (err) {}
        appState.currentDrawer = null;
    }

    appState.selectMode = 'circle';
    updateSelectModeUI('circle');

    const defaultLng = (appState.baseParams && (appState.baseParams.center_lng_gcj || appState.baseParams.center_lng_wgs)) || 107.5787;
    const defaultLat = (appState.baseParams && (appState.baseParams.center_lat_gcj || appState.baseParams.center_lat_wgs)) || 29.7191;
    const lng = parseFloat(document.getElementById('inputCenterLng').value) || defaultLng;
    const lat = parseFloat(document.getElementById('inputCenterLat').value) || defaultLat;
    const radiusM = parseFloat(document.getElementById('selectRadius').value) || 5000;
    drawCirclePreview(lng, lat, radiusM);
}

window.startDrawPolygon = startDrawPolygon;
window.startDrawRect = startDrawRect;
window.startDrawCircle = startDrawCircle;

function initEventListeners() {
    // 键盘快捷键：Esc 取消状态，Backspace 或 Ctrl+Z 撤销多边形顶点
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            cancelCurrentState();
        } else if ((e.key === 'Backspace' || (e.ctrlKey && e.key.toLowerCase() === 'z') || (e.metaKey && e.key.toLowerCase() === 'z')) && appState.currentDrawer) {
            const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
            if (tag !== 'input' && tag !== 'textarea') {
                e.preventDefault();
                undoLastPolygonVertex();
            }
        }
    });

    // 圈选方式切换
    window.setSelectMode = function(mode) {
        if (mode === 'circle') {
            if (appState.currentDrawer) {
                try { appState.currentDrawer.disable(); } catch (err) {}
                appState.currentDrawer = null;
            }
            startDrawCircle();
        } else if (mode === 'polygon') {
            // 若当前正在多边形绘制中，再次点击直接取消绘制并还原到圆形圈选模式
            if (appState.currentDrawer) {
                cancelCurrentState();
                return;
            }
            startDrawPolygon();
        }
        saveAppConfig({ selectMode: appState.selectMode });
    };

    // 半径设置核心控制函数 (单位: 米，最小 50 米)
    function setRadiusValue(val, fromInput = false) {
        let num = parseInt(val, 10);
        if (isNaN(num) || num < 50) num = 50;

        const displayEl = document.getElementById('displayRadiusNum');
        if (displayEl) {
            if ('value' in displayEl) {
                if (!fromInput) displayEl.value = num;
            } else {
                displayEl.innerText = num;
            }
        }
        const slider = document.getElementById('sliderRadius');
        if (slider) slider.value = Math.min(50000, num);
        const hidden = document.getElementById('selectRadius');
        if (hidden) hidden.value = num;

        // 联动预设快捷胶囊按钮高亮
        document.querySelectorAll('.radius-preset-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.val, 10) === num);
        });

        if (appState.selectMode === 'circle') {
            const lng = parseFloat(document.getElementById('inputCenterLng').value);
            const lat = parseFloat(document.getElementById('inputCenterLat').value);
            if (!isNaN(lng) && !isNaN(lat)) {
                drawCirclePreview(lng, lat, num);
            }
        }

        // 自动本地持久化当前半径设置
        saveAppConfig({ radius: num });
    }
    window.setRadiusValue = setRadiusValue;

    // 半径滑块拖动
    window.onRadiusSliderChange = function(val) {
        setRadiusValue(val, false);
    };

    // 半径输入框输入 (实时同步)
    window.onRadiusInputChange = function(val) {
        const raw = parseInt(val, 10);
        if (!isNaN(raw) && raw >= 50) {
            setRadiusValue(raw, true);
        }
    };

    // 半径输入框失焦校验 (保底最小 50 米)
    window.onRadiusInputBlur = function(el) {
        let num = parseInt(el ? el.value : 0, 10);
        if (isNaN(num) || num < 50) num = 50;
        setRadiusValue(num, false);
    };

    // 快捷米数预设按钮点击
    window.setRadiusPreset = function(meters) {
        setRadiusValue(meters, false);
    };

    // 坐标系切换
    window.switchCoordSys = function(sys, silent = false) {
        appState.coordSys = sys;
        const btnGCJ = document.getElementById('btnCoordGCJ');
        const btnWGS = document.getElementById('btnCoordWGS');
        if (btnGCJ) btnGCJ.classList.toggle('active', sys === 'gcj02');
        if (btnWGS) btnWGS.classList.toggle('active', sys === 'wgs84');
        saveAppConfig({ coordSys: sys });
        updateStatusBarCoordSys();
    };

    // 查询模式切换
    window.setQueryFilterMode = function(mode) {
        appState.queryFilterMode = mode || 'within';
        const cW = document.getElementById('cardModeWithin');
        const cI = document.getElementById('cardModeImpacted');
        if (cW) cW.classList.toggle('active', mode === 'within');
        if (cI) cI.classList.toggle('active', mode === 'impacted');
    };

    // 导出圈选工参清单 (安全绑定)
    const btnExp = document.getElementById('btnExportSelectedParams');
    if (btnExp) {
        btnExp.addEventListener('click', () => {
            window.open('/api/spatial/export', '_blank');
        });
    }

    // 搜索地址回车与输入联想监听
    const inputAddr = document.getElementById('inputEventAddress');
    if (inputAddr) {
        inputAddr.addEventListener('input', (e) => onAddressInput(e.target.value));
        inputAddr.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeAddressSearch(true);
            }
        });
    }

    // 点击地图任意区域关闭搜索下拉框
    appState.map.on('click', () => {
        const dropdown = document.getElementById('searchResultsDropdown');
        if (dropdown) dropdown.style.display = 'none';
        const globalDropdown = document.getElementById('globalSearchResultsDropdown');
        if (globalDropdown) globalDropdown.style.display = 'none';
    });

    // 底部状态栏：鼠标坐标跟随 + 比例尺 + 视口扇区动态重绘（随视野变化）
    appState.map.on('mousemove', (e) => updateStatusBarCoords(e.latlng));
    appState.map.on('mouseout', () => updateStatusBarCoords(null));
    appState.map.on('moveend zoomend', () => {
        updateStatusBarScale();
        triggerViewportSectorRender();
    });
    updateStatusBarScale();
    updateStatusBarCoordSys();

    // 通报标题改动时同步刷新导出检查卡
    const inputEventName = document.getElementById('inputEventName');
    if (inputEventName) inputEventName.addEventListener('input', () => updateExportCheckCard());

    // 点击页面其它区域关闭全局搜索下拉
    document.addEventListener('click', (e) => {
        const searchBar = document.getElementById('globalSearchBar');
        const dropdown = document.getElementById('globalSearchResultsDropdown');
        if (dropdown && searchBar && !searchBar.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });

    // 数据分析上传与匹配
    initAnalysisEvents();
    // 诊断与报告事件
    initDiagnosisEvents();
}

// ---------------------------------------------------------------------------
// 9. Wmap 全局通用地标/基站/经纬度检索引擎
// ---------------------------------------------------------------------------

let _globalSearchDebounceTimer = null;

function onGlobalSearchInput(keyword) {
    const clearBtn = document.getElementById('btnGlobalSearchClear');
    const kw = (keyword || '').trim();
    if (clearBtn) clearBtn.style.display = kw ? 'inline-block' : 'none';

    clearTimeout(_globalSearchDebounceTimer);
    if (!kw) {
        const dropdown = document.getElementById('globalSearchResultsDropdown');
        if (dropdown) dropdown.style.display = 'none';
        return;
    }
    _globalSearchDebounceTimer = setTimeout(() => {
        executeGlobalSearch(false);
    }, 300);
}
window.onGlobalSearchInput = onGlobalSearchInput;

function clearGlobalSearch() {
    const inp = document.getElementById('inputGlobalSearch');
    if (inp) inp.value = '';
    const clearBtn = document.getElementById('btnGlobalSearchClear');
    if (clearBtn) clearBtn.style.display = 'none';
    const dropdown = document.getElementById('globalSearchResultsDropdown');
    if (dropdown) dropdown.style.display = 'none';
    if (appState.searchTargetGroup) {
        appState.searchTargetGroup.clearLayers();
    }
}
window.clearGlobalSearch = clearGlobalSearch;

async function executeGlobalSearch(autoPick = true) {
    const inputEl = document.getElementById('inputGlobalSearch');
    const keyword = inputEl ? inputEl.value.trim() : '';
    if (!keyword) {
        if (autoPick && typeof showToast === 'function') {
            showToast('请输入要检索的地标、基站、小区或经纬度', 'warning');
        }
        return;
    }

    // 1. 优先经纬度直接解析 (如 "113.32, 23.12")
    const coords = parseCoordinates(keyword);
    if (coords) {
        const sysLabel = (appState.coordSys || 'gcj02').toUpperCase();
        const coordItem = {
            name: `坐标定位 (${coords.lng}, ${coords.lat})`,
            address: `经度: ${coords.lng}, 纬度: ${coords.lat}（${sysLabel} 坐标直达）`,
            district: "坐标直达",
            lng: coords.lng,
            lat: coords.lat,
            source: "经纬度定位",
            type: "coord"
        };
        renderGlobalSearchDropdown([coordItem]);
        if (autoPick) selectGlobalSearchResult(0);
        return;
    }

    // 2. 调用后端统一地理编码与基站检索接口
    try {
        const url = `/api/spatial/geocode?keyword=${encodeURIComponent(keyword)}&coord_sys=${appState.coordSys}`;
        const data = await safeFetchJson(url);

        if (data && data.results && data.results.length > 0) {
            renderGlobalSearchDropdown(data.results);
            if (autoPick) selectGlobalSearchResult(0);
        } else {
            const dropdown = document.getElementById('globalSearchResultsDropdown');
            if (dropdown) dropdown.style.display = 'none';
            if (autoPick && typeof showToast === 'function') {
                showToast('未找到匹配的地标或基站', 'warning');
            }
        }
    } catch (err) {
        if (autoPick && typeof showToast === 'function') {
            showToast(`检索失败: ${err.message}`, 'error');
        }
    }
}
window.executeGlobalSearch = executeGlobalSearch;

function renderGlobalSearchDropdown(results) {
    const dropdown = document.getElementById('globalSearchResultsDropdown');
    if (!dropdown) return;
    if (!results || results.length === 0) {
        dropdown.style.display = 'none';
        return;
    }

    appState._lastGlobalSearchResults = results;
    dropdown.innerHTML = results.slice(0, 10).map((item, idx) => `
        <div class="global-search-item" onclick="selectGlobalSearchResult(${idx})">
            <div class="global-search-item-title">
                <span style="display: flex; align-items: center; gap: 6px;">
                    <span style="color: #0071e3;">📍</span>
                    <span>${escapeHtml(item.name)}</span>
                </span>
                <span style="font-size: 10px; color: #0071e3; background: rgba(0, 113, 227, 0.1); padding: 1px 6px; border-radius: 4px;">${escapeHtml(item.district || item.source || '地标')}</span>
            </div>
            <div class="global-search-item-addr">${escapeHtml(item.address || '')}</div>
        </div>
    `).join('');
    dropdown.style.display = 'block';
}

function selectGlobalSearchResult(idx) {
    const results = appState._lastGlobalSearchResults;
    if (!results || !results[idx]) return;

    const best = results[idx];
    const inp = document.getElementById('inputGlobalSearch');
    if (inp) inp.value = best.name;
    const dropdown = document.getElementById('globalSearchResultsDropdown');
    if (dropdown) dropdown.style.display = 'none';

    // 双向同步给左侧应急面板输入框与隐藏表单
    const eventAddrInp = document.getElementById('inputEventAddress');
    if (eventAddrInp) eventAddrInp.value = best.name;
    const centerLngInp = document.getElementById('inputCenterLng');
    const centerLatInp = document.getElementById('inputCenterLat');
    if (centerLngInp) centerLngInp.value = best.lng;
    if (centerLatInp) centerLatInp.value = best.lat;

    // 平滑飞行至该位置
    if (appState.map) {
        appState.map.flyTo([best.lat, best.lng], 15, { duration: 0.9 });
    }

    // 绘制高亮图钉与卡片
    renderSearchTargetMarker(best);

    // 若当前正在应急保障面板，自动同步圆心
    const emergencyContent = document.getElementById('contentLeftEmergency');
    if (emergencyContent && emergencyContent.style.display !== 'none') {
        setMapCenter(best.lng, best.lat, best.name);
    }

    if (typeof showToast === 'function') {
        showToast(`已定位: ${best.name}`, 'success');
    }
}
window.selectGlobalSearchResult = selectGlobalSearchResult;

function setAsEmergencyCenter(lng, lat, name) {
    // 打开应急保障向导（第 1 步：定界）
    if (typeof openEmergencyWizard === 'function') {
        openEmergencyWizard();
    }
    const eventAddrInp = document.getElementById('inputEventAddress');
    if (eventAddrInp) eventAddrInp.value = name || '已选中心点';
    setMapCenter(lng, lat, name);
    if (typeof showToast === 'function') {
        showToast(`已将【${name}】设为应急保障圈选中心`, 'success');
    }
}
window.setAsEmergencyCenter = setAsEmergencyCenter;

// 保留原应急面板内的地址搜索逻辑 (双向兼容)
function clearEventAddress() {
    clearGlobalSearch();
    const eventInp = document.getElementById('inputEventAddress');
    if (eventInp) eventInp.value = '';
    const dropdown = document.getElementById('searchResultsDropdown');
    if (dropdown) dropdown.style.display = 'none';
}

let _searchDebounceTimer = null;
function onAddressInput(keyword) {
    const globalInp = document.getElementById('inputGlobalSearch');
    if (globalInp) globalInp.value = keyword;
    onGlobalSearchInput(keyword);
}

function parseCoordinates(text) {
    if (!text) return null;
    const s = text.trim();
    const pattern = /^(?:(?:(?:经度|lng|lon|e)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)\s*[,，;\s/|]+\s*(?:(?:纬度|lat|n)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)|(?:(?:纬度|lat|n)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?)\s*[,，;\s/|]+\s*(?:(?:经度|lng|lon|e)\s*[:：]?\s*)?([+-]?\d+(?:\.\d+)?))\s*$/i;
    const m = s.match(pattern);
    if (!m) return null;

    let v1, v2, isLatFirst;
    if (m[1] !== undefined && m[2] !== undefined) {
        v1 = parseFloat(m[1]);
        v2 = parseFloat(m[2]);
        isLatFirst = /(?:纬度|lat|n)/i.test(s.slice(0, Math.floor(s.length / 2)));
    } else {
        v1 = parseFloat(m[3]);
        v2 = parseFloat(m[4]);
        isLatFirst = true;
    }

    let lat, lng;
    if (isLatFirst) {
        lat = v1; lng = v2;
    } else {
        lng = v1; lat = v2;
    }

    if (Math.abs(lng) <= 90.0 && Math.abs(lat) > 90.0) {
        const tmp = lng; lng = lat; lat = tmp;
    } else if (lat >= 73.0 && lat <= 138.0 && lng >= 3.0 && lng <= 54.0) {
        const tmp = lng; lng = lat; lat = tmp;
    }

    if (lng >= -180.0 && lng <= 180.0 && lat >= -90.0 && lat <= 90.0) {
        return {
            lng: Number(lng.toFixed(6)),
            lat: Number(lat.toFixed(6))
        };
    }
    return null;
}

async function executeAddressSearch(autoPick = true) {
    const inputEl = document.getElementById('inputEventAddress');
    const keyword = inputEl ? inputEl.value.trim() : '';
    const globalInp = document.getElementById('inputGlobalSearch');
    if (globalInp) globalInp.value = keyword;
    executeGlobalSearch(autoPick);
}

function renderSearchDropdown(results) {
    const dropdown = document.getElementById('searchResultsDropdown');
    if (!dropdown) return;
    if (!results || results.length === 0) {
        dropdown.style.display = 'none';
        return;
    }

    appState._lastSearchResults = results;
    dropdown.innerHTML = results.slice(0, 8).map((item, idx) => `
        <div class="search-dropdown-item" onclick="selectSearchResult(${idx})">
            <div class="search-item-title">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#0071e3" stroke-width="2" style="flex-shrink:0;"><path d="M12 2a8 8 0 0 0-8 8c0 5.25 8 12 8 12s8-6.75 8-12a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
                <span>${escapeHtml(item.name)}</span>
                <span style="font-size: 10px; color: #0071e3; margin-left: auto;">${escapeHtml(item.district || item.source || '')}</span>
            </div>
            <div class="search-item-addr">${escapeHtml(item.address || '')}</div>
        </div>
    `).join('');
    dropdown.style.display = 'block';
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.selectSearchResult = function(idx) {
    const results = appState._lastSearchResults;
    if (!results || !results[idx]) return;

    const best = results[idx];
    document.getElementById('inputEventAddress').value = best.name;
    const dropdown = document.getElementById('searchResultsDropdown');
    if (dropdown) dropdown.style.display = 'none';

    // 1. 平滑移动地图视角至目标点 (放大至 15 级更清晰查看地标与周边)
    if (appState.map) {
        appState.map.flyTo([best.lat, best.lng], 15, {
            duration: 0.9,
            easeLinearity: 0.25
        });
    }

    // 2. 同步更新中心点数据及半径圈预览
    setMapCenter(best.lng, best.lat, best.name);

    // 3. 在目标区域绘制超醒目的标点 (雷达波纹 + 霓虹水滴大Pin + 悬浮胶囊 + 弹出卡片)
    renderSearchTargetMarker(best);

    showToast(`定位成功: ${best.name}`, 'success');
};

function renderSearchTargetMarker(target) {
    if (!appState.map) return;
    if (!appState.searchTargetGroup) {
        appState.searchTargetGroup = L.layerGroup().addTo(appState.map);
    }
    appState.searchTargetGroup.clearLayers();

    const name = target.name || '搜索目标';
    const address = target.address || '';
    const lat = target.lat;
    const lng = target.lng;

    // 醒目标点 HTML (雷达光圈 + 霓虹大Pin + 悬浮地名胶囊)
    const markerHtml = `
        <div class="search-target-beacon">
            <div class="beacon-ground-rings">
                <div class="beacon-ring ring-1"></div>
                <div class="beacon-ring ring-2"></div>
                <div class="beacon-ring ring-3"></div>
            </div>
            <div class="beacon-pin-wrapper">
                <div class="beacon-label-tag" title="${escapeHtml(name)}">
                    <span class="beacon-label-icon">📍</span>
                    <span class="beacon-label-text">${escapeHtml(name)}</span>
                </div>
                <div class="beacon-pin-body">
                    <svg class="beacon-pin-svg" viewBox="0 0 36 48" width="36" height="48" fill="none">
                        <defs>
                            <filter id="beaconGlow" x="-30%" y="-30%" width="160%" height="160%">
                                <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#ff2d55" flood-opacity="0.6"/>
                            </filter>
                            <linearGradient id="pinGrad" x1="0" y1="0" x2="1" y2="1">
                                <stop offset="0%" stop-color="#ff2d55"/>
                                <stop offset="60%" stop-color="#ff375f"/>
                                <stop offset="100%" stop-color="#ff9f0a"/>
                            </linearGradient>
                        </defs>
                        <path d="M18 46 C18 46, 33 26, 33 17 A15 15 0 0 0 3 17 C3 26, 18 46, 18 46 Z" fill="url(#pinGrad)" stroke="#ffffff" stroke-width="2" filter="url(#beaconGlow)"/>
                        <circle cx="18" cy="17" r="6.5" fill="#ffffff"/>
                        <circle cx="18" cy="17" r="3.2" fill="#ff2d55"/>
                    </svg>
                </div>
            </div>
        </div>
    `;

    const beaconIcon = L.divIcon({
        html: markerHtml,
        className: 'custom-search-beacon-divicon',
        iconSize: [220, 96],
        iconAnchor: [110, 88] // 底部尖端精确锚定在地图经纬度上
    });

    const marker = L.marker([lat, lng], {
        icon: beaconIcon,
        zIndexOffset: 12000 // 位于最顶层，不被基站和小区遮挡
    }).addTo(appState.searchTargetGroup);

    // 绑定高颜值暗色弹出卡片
    const popupContent = `
        <div class="search-target-popup">
            <div class="search-popup-header">
                <span class="search-popup-badge">🎯 搜索定位目标</span>
                <span class="search-popup-coords">${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E</span>
            </div>
            <div class="search-popup-title">${escapeHtml(name)}</div>
            ${address ? `<div class="search-popup-addr">${escapeHtml(address)}</div>` : ''}
            <div class="search-popup-actions" style="display: flex; gap: 8px; margin-top: 8px;">
                <button type="button" class="btn btn-primary" onclick="setAsEmergencyCenter(${lng}, ${lat}, '${escapeHtml(name)}')" style="flex: 1; padding: 5px 10px; font-size: 11px; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; gap: 4px;">
                    ⚡ 设为应急中心
                </button>
                <button type="button" class="btn btn-outline" onclick="if(navigator.clipboard){navigator.clipboard.writeText('${lng.toFixed(6)}, ${lat.toFixed(6)}'); showToast('坐标已复制', 'info');}" style="padding: 5px 10px; font-size: 11px; border-radius: 5px; border-color: rgba(0, 113, 227, 0.18); color: #6e6e73;">
                    复制坐标
                </button>
            </div>
        </div>
    `;

    marker.bindPopup(popupContent, {
        offset: [0, -56],
        className: 'dark-target-popup-wrapper',
        closeButton: true,
        autoClose: false,
        closeOnClick: false
    });

    // 配合 flyTo 动效延迟打开弹窗提示
    setTimeout(() => {
        if (marker && appState.map && appState.map.hasLayer(marker)) {
            marker.openPopup();
        }
    }, 450);
}

// ---------------------------------------------------------------------------
// 9.1 左右面板一键折叠（Docking 把手）与底部抽屉控制
// ---------------------------------------------------------------------------
// 面板显隐改变地图容器尺寸后，让 Leaflet 重算（防止瓦片错位）
function invalidateMapSize() {
    if (appState.map) appState.map.invalidateSize();
}

window.togglePanelLeft = function(collapse) {
    const panel = document.getElementById('panelEmergencyTask');
    if (!panel) return;
    const shouldCollapse = collapse !== undefined ? collapse : !panel.classList.contains('collapsed');
    panel.classList.toggle('collapsed', shouldCollapse);

    // 同步专属悬浮唤出标签显示/隐藏
    const expandBtn = document.getElementById('btnExpandPanelLeft');
    if (expandBtn) {
        expandBtn.style.display = shouldCollapse ? 'flex' : 'none';
    }

    // 更新贴边把手指示箭头与提示
    const handle = document.getElementById('handleDockLeft');
    if (handle) {
        const span = handle.querySelector('span');
        if (span) span.innerText = shouldCollapse ? '▶' : '◀';
        handle.title = shouldCollapse ? '展开图层面板' : '折叠图层面板';
    }
    invalidateMapSize();
    checkPureMapState();
};

window.togglePanelRight = function(collapse) {
    const panel = document.getElementById('panelBaseStationData');
    if (!panel) return;
    const shouldCollapse = collapse !== undefined ? collapse : !panel.classList.contains('collapsed');
    panel.classList.toggle('collapsed', shouldCollapse);

    // 同步专属悬浮唤出标签显示/隐藏
    const expandBtn = document.getElementById('btnExpandPanelRight');
    if (expandBtn) {
        expandBtn.style.display = shouldCollapse ? 'flex' : 'none';
    }

    // 更新贴边把手指示箭头与提示
    const handle = document.getElementById('handleDockRight');
    if (handle) {
        const span = handle.querySelector('span');
        if (span) span.innerText = shouldCollapse ? '◀' : '▶';
        handle.title = shouldCollapse ? '展开 02 工参信息面板' : '折叠 02 工参信息面板';
    }
    invalidateMapSize();
    checkPureMapState();
};

// 底部历史任务抽屉栏展开/收起 (默认折叠为 32px 胶囊栏)
window.toggleTaskDrawer = function(collapse) {
    const drawer = document.getElementById('bottomTaskDrawer');
    if (!drawer) return;
    const shouldCollapse = collapse !== undefined ? collapse : !drawer.classList.contains('collapsed');
    drawer.classList.toggle('collapsed', shouldCollapse);
    const arrow = document.getElementById('drawerArrow');
    if (arrow) arrow.innerText = shouldCollapse ? '⬆' : '⬇';
    checkPureMapState();
};
window.toggleBottomDock = window.toggleTaskDrawer;

window.togglePureMapMode = function(enable) {
    const pLeft = document.getElementById('panelEmergencyTask');
    const isPure = enable !== undefined ? enable : !(pLeft && pLeft.classList.contains('collapsed'));
    togglePanelLeft(isPure);
    togglePanelRight(isPure);
    toggleTaskDrawer(isPure);
    const topBar = document.getElementById('pureMapTopBar');
    if (topBar) topBar.style.display = isPure ? 'flex' : 'none';
};

// 地图角落控件位置自适应：三栏布局下地图容器已是剩余空间，水平位置固定；
// 只随底部抽屉的展开/折叠调整垂直位置
function updateMapControlsPosition() {
    const drawer = document.getElementById('bottomTaskDrawer');
    const isDrawerCollapsed = !drawer || drawer.classList.contains('collapsed');
    const bottom = isDrawerCollapsed ? '44px' : '175px';

    const controls = document.getElementById('mapControlsBottomRight');
    if (controls) controls.style.bottom = bottom;

    const toolsBL = document.getElementById('mapToolsBottomLeft');
    if (toolsBL) toolsBL.style.bottom = bottom;
}
window.updateMapControlsPosition = updateMapControlsPosition;

function checkPureMapState() {
    const pLeft = document.getElementById('panelEmergencyTask');
    const pRight = document.getElementById('panelBaseStationData');
    const drawer = document.getElementById('bottomTaskDrawer');
    const allCollapsed = (pLeft && pLeft.classList.contains('collapsed')) &&
                         (pRight && pRight.classList.contains('collapsed')) &&
                         (!drawer || drawer.classList.contains('collapsed'));
    const topBar = document.getElementById('pureMapTopBar');
    if (topBar) topBar.style.display = allCollapsed ? 'flex' : 'none';
    updateMapControlsPosition();
}

// ---------------------------------------------------------------------------
// 9.2 底部状态栏：鼠标坐标跟随 / 比例尺 / 坐标系 / 数据量 / 任务状态
// ---------------------------------------------------------------------------
function updateStatusBarCoords(latlng) {
    const el = document.getElementById('statusCoord');
    if (!el) return;
    el.innerText = latlng ? `${latlng.lat.toFixed(4)}, ${latlng.lng.toFixed(4)}` : '--, --';
}

function updateStatusBarScale() {
    const el = document.getElementById('statusScale');
    if (!el || !appState.map) return;
    const zoom = appState.map.getZoom();
    const center = appState.map.getCenter();
    const metersPerPixel = 156543.03392 * Math.cos(center.lat * Math.PI / 180) / Math.pow(2, zoom);
    const denom = Math.round(metersPerPixel * 96 / 0.0254);
    el.innerText = '1 : ' + denom.toLocaleString('en-US');
}

function updateStatusBarCoordSys() {
    const btn = document.getElementById('statusCoordSysBtn');
    if (btn) btn.innerText = appState.coordSys === 'wgs84' ? 'WGS-84' : 'GCJ-02';
}

window.toggleStatusCoordSys = function() {
    if (typeof switchCoordSys === 'function') {
        switchCoordSys(appState.coordSys === 'wgs84' ? 'gcj02' : 'wgs84');
    }
};

function setTaskStatus(busy, text) {
    const dot = document.getElementById('statusTaskDot');
    const el = document.getElementById('statusTaskText');
    if (dot) dot.classList.toggle('busy', !!busy);
    if (el) el.innerText = text || (busy ? '处理中…' : '空闲');
}

// 定位到当前位置（浏览器定位；失败时提示，不跳去别处）
window.locateMe = function() {
    if (!navigator.geolocation) {
        showToast('当前环境不支持定位', 'warning');
        return;
    }
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            appState.map.setView([lat, lng], Math.max(appState.map.getZoom(), 14));
            showToast('已定位到当前位置', 'success');
        },
        () => showToast('无法获取当前位置，请检查定位权限', 'warning'),
        { timeout: 8000 }
    );
};

// 快速聚焦工参核心保障区域城市经纬度
function focusParamCore() {
    let targetLat = 29.7191;
    let targetLng = 107.5787;
    if (appState.baseParams) {
        targetLat = (appState.currentTileType === 'amap' ? (appState.baseParams.center_lat_gcj || appState.baseParams.center_lat_wgs) : appState.baseParams.center_lat_wgs) || targetLat;
        targetLng = (appState.currentTileType === 'amap' ? (appState.baseParams.center_lng_gcj || appState.baseParams.center_lng_wgs) : appState.baseParams.center_lng_wgs) || targetLng;
    }
    setMapCenter(targetLng, targetLat);
    appState.map.setView([targetLat, targetLng], 12);
    triggerMainSelection();
}
const focusChongqingCore = focusParamCore;
window.focusParamCore = focusParamCore;
window.focusChongqingCore = focusChongqingCore;

// ---------------------------------------------------------------------------
// 10. 顶部时钟与任务记录渲染
// ---------------------------------------------------------------------------
function startClock() {
    setInterval(() => {
        const now = new Date();
        const str = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
        const el = document.getElementById('topStatUpdateTime');
        if (el) el.innerText = str;
    }, 1000);
}

async function loadRecentTasks() {
    try {
        const res = await safeFetchJson('/api/tasks/recent?limit=5');
        const tasks = (res && res.tasks) || [];
        appState.recentTasks = tasks;
        renderRecentTasks(tasks);
        const badge = document.getElementById('badgeRecentTaskCount');
        if (badge) badge.innerText = tasks.length;
        const drawerCount = document.getElementById('drawerTaskCount');
        if (drawerCount) drawerCount.innerText = tasks.length;
    } catch (err) {
        console.error('获取最近任务失败', err);
    }
}
window.loadRecentTasks = loadRecentTasks;

function renderRecentTasks(tasks) {
    const list = document.getElementById('recentTasksList');
    if (!list) return;

    const data = tasks || appState.recentTasks || [];
    if (data.length === 0) {
        list.innerHTML = `
            <div class="task-log-empty" style="text-align: center; color: #86868b; font-size: 11px; padding: 18px 0;">
                暂无历史任务记录，圈选后自动保存
            </div>
        `;
        return;
    }

    list.innerHTML = data.map(t => {
        const isCircle = t.shape_type === 'circle';
        const radiusM = (t.shape_params && t.shape_params.radius_m) ? Math.round(t.shape_params.radius_m) : 5000;
        const shapeText = isCircle ? `⭕ ${radiusM}m` : `⬡ 多边形`;

        // 截取时间 MM-DD HH:mm
        const timeStr = t.create_time ? t.create_time.slice(5, 16) : '--';
        const titleStr = t.event_name || t.address || '保障任务';

        let wordBtn = '';
        if (t.artifacts && t.artifacts.word_path) {
            wordBtn = `<a href="/api/report/download/${t.artifacts.word_path}" class="task-btn-action" title="下载Word应急通报" target="_blank" onclick="event.stopPropagation()"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#0071e3" stroke-width="2" style="vertical-align:-1px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></a>`;
        }

        let excelBtn = '';
        if (t.artifacts && t.artifacts.excel_path) {
            excelBtn = `<a href="/api/report/download/${t.artifacts.excel_path}" class="task-btn-action" title="下载Excel工参清单" target="_blank" onclick="event.stopPropagation()"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2" style="vertical-align:-1px;"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg></a>`;
        }

        return `
            <div class="task-log-row" title="点击查看此任务历史记录">
                <div class="task-log-main" onclick="loadHistoricalTask('${t.task_id}')" style="display: flex; align-items: center; gap: 6px; flex: 1; overflow: hidden; cursor: pointer;">
                    <span class="task-log-time">● ${timeStr}</span>
                    <span class="task-log-name" title="${titleStr}">${titleStr}</span>
                    <span class="task-log-type">${shapeText}</span>
                    <span class="task-log-count">${(t.metrics && t.metrics.total_sites) || 0}基站</span>
                </div>
                <div class="task-log-actions" style="display: flex; align-items: center; gap: 4px;">
                    <button type="button" class="task-btn-action task-btn-replay" onclick="loadHistoricalTask('${t.task_id}')" title="查看历史记录">查看</button>
                    ${wordBtn}
                    ${excelBtn}
                    <button type="button" class="task-btn-action task-btn-del" onclick="deleteHistoricalTask('${t.task_id}', event)" title="删除此记录">✕</button>
                </div>
            </div>
        `;
    }).join('');
}
window.renderRecentTasks = renderRecentTasks;

// 诊断结果与指标异常快照恢复至 UI
function applyDiagnosisSnapshotToUI(diagData) {
    if (!diagData) return;
    appState.diagnosisResult = diagData;

    const scoreEl = document.getElementById('healthScore');
    if (scoreEl) scoreEl.innerText = diagData.health_score || '98';
    const descEl = document.getElementById('healthDesc');
    if (descEl) descEl.innerText = diagData.overall_status || '网络运行良好';

    const countP0 = document.getElementById('countP0');
    if (countP0) countP0.innerText = diagData.p0_count || 0;
    const countP1 = document.getElementById('countP1');
    if (countP1) countP1.innerText = diagData.p1_count || 0;
    const countP2 = document.getElementById('countP2');
    if (countP2) countP2.innerText = diagData.p2_count || 0;
    const countNormal = document.getElementById('countNormal');
    if (countNormal) countNormal.innerText = diagData.normal_count || 0;

    const diagCells = diagData.diagnosed_cells || [];
    appState.diagnosedCells = diagCells;
    appState.allDiagnosedCells = diagCells;
    const tipEl = document.getElementById('diagnoseCellsCountTip');
    if (tipEl) tipEl.innerText = `共 ${diagCells.length} 个异常小区需处理`;

    if (typeof renderDiagnosisTable === 'function') {
        renderDiagnosisTable(diagCells);
    }
    if (typeof renderDiagnosisCharts === 'function') {
        renderDiagnosisCharts(diagData);
    }

    // 更新右侧面板的告警指标数量徽标
    const badge = document.getElementById('badgeAlarmViewCount');
    if (badge) {
        badge.innerText = diagCells.length;
        if (diagCells.length > 0) {
            badge.style.background = '#ff3b30';
            badge.style.color = '#ffffff';
            badge.style.fontWeight = 'bold';
        } else {
            badge.style.background = 'rgba(255, 59, 48, 0.18)';
            badge.style.color = '#ff3b30';
            badge.style.fontWeight = 'normal';
        }
    }
}
window.applyDiagnosisSnapshotToUI = applyDiagnosisSnapshotToUI;

// 历史保障任务档案调阅 (直接加载快照：场景 + 工参 + 报告 + 指标数据，绝不重新连库查询分析)
async function loadHistoricalTask(taskId) {
    showLoading('加载中...');
    try {
        // 请求后端激活当前任务并获取完整历史快照
        let task = null;
        try {
            const res = await safeFetchJson(`/api/tasks/${taskId}/activate`, { method: 'POST' });
            if (res && res.task) task = res.task;
        } catch (e) {
            console.warn('激活历史任务接口降级读取详情', e);
        }
        if (!task) {
            task = await safeFetchJson(`/api/tasks/${taskId}`);
        }
        if (!task) {
            showToast('未找到该任务档案信息', 'error');
            return;
        }

        closeAllDarkModals();

        // 1. 恢复场景信息 (保障地址、事件名称、坐标系)
        if (task.address) {
            const addrInput = document.getElementById('inputEventAddress');
            if (addrInput) addrInput.value = task.address;
        }
        const eventNameInput = document.getElementById('inputEventName');
        if (eventNameInput && task.event_name) {
            eventNameInput.value = task.event_name;
        }

        const params = task.shape_params || {};
        if (params.coord_sys && params.coord_sys !== appState.coordSys) {
            switchCoordSys(params.coord_sys, true);
        }

        // 2. 还原地图圈选场景几何图元与视野视角
        if (task.shape_type === 'circle') {
            const centerLng = parseFloat(params.center_lng);
            const centerLat = parseFloat(params.center_lat);
            const radiusM = parseFloat(params.radius_m) || 5000;

            if (isNaN(centerLng) || isNaN(centerLat)) {
                throw new Error('任务历史中心点坐标无效');
            }

            appState.selectMode = 'circle';
            updateSelectModeUI('circle');
            setRadiusValue(radiusM, false);
            setMapCenter(centerLng, centerLat, task.address);

            const zoomLevel = Math.max(12, Math.min(16, 17 - Math.round(Math.log2(radiusM / 100))));
            if (appState.map) {
                appState.map.flyTo([centerLat, centerLng], zoomLevel, { duration: 0.8 });
            }

            drawCirclePreview(centerLng, centerLat, radiusM);
        } else if (task.shape_type === 'polygon') {
            const cleanCoords = params.polygon_coords || params.coords || [];
            if (cleanCoords.length >= 3) {
                appState.selectMode = 'polygon';
                updateSelectModeUI('polygon');
                appState.lastPolygonCoords = cleanCoords;

                // 重新构建并绘制 Leaflet 多边形图元
                const latlngs = cleanCoords.map(p => [p[1], p[0]]);
                appState.drawLayerGroup.clearLayers();
                const polygonLayer = L.polygon(latlngs, {
                    color: '#0071e3',
                    fillColor: '#0071e3',
                    fillOpacity: 0.18,
                    weight: 2
                }).addTo(appState.drawLayerGroup);
                appState.currentShapeLayer = polygonLayer;

                const cLng = parseFloat(params.center_lng) || (cleanCoords.reduce((s, p) => s + p[0], 0) / cleanCoords.length);
                const cLat = parseFloat(params.center_lat) || (cleanCoords.reduce((s, p) => s + p[1], 0) / cleanCoords.length);
                setMapCenter(cLng, cLat, task.address);

                if (appState.map) {
                    appState.map.fitBounds(polygonLayer.getBounds(), { padding: [40, 40], maxZoom: 15 });
                }
            }
        }

        // 3. 恢复当时圈选出的基站与小区工参快照 (零重新查询，直接加载保存的历史数据)
        const snapshotCells = task.cells || [];
        const snapshotMetrics = task.metrics || {};
        const shapeInfo = {
            type: task.shape_type,
            radius: params.radius_m || 5000,
            coords: params.polygon_coords || []
        };
        const selectionData = {
            cells: snapshotCells,
            total_cells: snapshotMetrics.total_cells || snapshotCells.length,
            total_sites: snapshotMetrics.total_sites || 0
        };

        handleSelectionResult(selectionData, shapeInfo);

        // 4. 恢复当时的指标与告警诊断数据快照 (若当时执行过诊断)
        const diag = task.diagnosis;
        if (diag && (diag.status === 'completed' || (diag.diagnosed_cells && diag.diagnosed_cells.length > 0))) {
            applyDiagnosisSnapshotToUI(diag);
            // 重新在地图打点，标出异常小区告警状态
            renderCellMarkers(appState.selectedCells);
        } else {
            appState.diagnosisResult = null;
            appState.diagnosedCells = [];
            appState.allDiagnosedCells = [];
            const badge = document.getElementById('badgeAlarmViewCount');
            if (badge) {
                badge.innerText = '0';
                badge.style.background = 'rgba(255, 59, 48, 0.18)';
                badge.style.color = '#ff3b30';
                badge.style.fontWeight = 'normal';
            }
        }

        // 5. 恢复当时生成的报告文件状态 (若存在)
        if (task.artifacts) {
            appState.lastGeneratedReports = task.artifacts;
        }

        // 6. 展开右侧 02 面板，供工程师直接检视历史工参与指标
        togglePanelRight(false);
    } catch (err) {
        showToast(`加载失败: ${err.message}`, 'error');
    } finally {
        hideLoading();
    }
}
window.loadHistoricalTask = loadHistoricalTask;

// 删除指定历史任务
async function deleteHistoricalTask(taskId, event) {
    if (event) event.stopPropagation();
    if (!confirm('确定要删除此条历史任务记录吗？')) return;

    try {
        await safeFetchJson(`/api/tasks/${taskId}`, { method: 'DELETE' });
        showToast('已删除', 'success');
        loadRecentTasks();
        const modal = document.getElementById('modalTaskHistory');
        if (modal && modal.style.display !== 'none') {
            refreshTaskHistoryModal();
        }
    } catch (err) {
        showToast(`删除失败: ${err.message}`, 'error');
    }
}
window.deleteHistoricalTask = deleteHistoricalTask;

// 清空所有历史任务
async function clearAllHistoricalTasks() {
    if (!confirm('确定要清空全部历史任务记录吗？此操作无法撤销。')) return;

    try {
        await safeFetchJson('/api/tasks/clear', { method: 'POST' });
        showToast('已清空', 'success');
        loadRecentTasks();
        const modal = document.getElementById('modalTaskHistory');
        if (modal && modal.style.display !== 'none') {
            refreshTaskHistoryModal();
        }
    } catch (err) {
        showToast(`清空失败: ${err.message}`, 'error');
    }
}
window.clearAllHistoricalTasks = clearAllHistoricalTasks;

// 打开历史任务档案台账模态框
async function openTaskHistoryModal() {
    openDarkModal('modalTaskHistory');
    const searchInput = document.getElementById('inputSearchTaskHistory');
    if (searchInput) searchInput.value = '';
    await refreshTaskHistoryModal();
}
window.openTaskHistoryModal = openTaskHistoryModal;

// 刷新历史任务台账表格
async function refreshTaskHistoryModal(keyword = '') {
    const tbody = document.getElementById('taskHistoryTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 30px; color: #86868b;">正在加载任务档案...</td></tr>';

    try {
        const url = keyword ? `/api/tasks/list?keyword=${encodeURIComponent(keyword)}` : '/api/tasks/list';
        const res = await safeFetchJson(url);
        const tasks = (res && res.tasks) || [];

        const badge = document.getElementById('modalHistoryCountBadge');
        if (badge) badge.innerText = `${tasks.length} 条`;

        if (tasks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #86868b;">暂无匹配的历史保障任务</td></tr>';
            return;
        }

        tbody.innerHTML = tasks.map(t => {
            const isCircle = t.shape_type === 'circle';
            const shapeParams = t.shape_params || {};
            const metrics = t.metrics || {};
            const shapeDesc = isCircle 
                ? `<span style="color: #0071e3;">⭕ 圆形 (${Math.round(shapeParams.radius_m || 5000)}米)</span>` 
                : `<span style="color: #0071e3;">⬡ 多边形 (${(shapeParams.polygon_coords || shapeParams.coords || []).length}顶点)</span>`;
            
            const areaDesc = `<div style="font-size: 11px; color: #86868b; margin-top: 2px;">覆盖: ${metrics.area_km2 || '--'} km²</div>`;

            let diagDesc = '<span style="color: #86868b;">未诊断</span>';
            if (t.diagnosis && t.diagnosis.status === 'completed') {
                diagDesc = `
                    <div style="display: flex; gap: 4px; font-size: 11px;">
                        <span style="color: #ff3b30; font-weight: 600;">P0:${t.diagnosis.p0_count || 0}</span>
                        <span style="color: #ff9f0a; font-weight: 600;">P1:${t.diagnosis.p1_count || 0}</span>
                        <span style="color: #30d158; font-weight: 600;">正常:${t.diagnosis.normal_count || 0}</span>
                    </div>
                `;
            }

            let artifactsDesc = '<span style="color: #86868b; font-size: 11px;">无输出附件</span>';
            const docs = [];
            if (t.artifacts && t.artifacts.word_path) {
                docs.push(`<a href="/api/report/download/${t.artifacts.word_path}" class="task-btn-action" target="_blank" title="下载 Word 通报" style="display:inline-flex;align-items:center;gap:3px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>通报</a>`);
            }
            if (t.artifacts && t.artifacts.excel_path) {
                docs.push(`<a href="/api/report/download/${t.artifacts.excel_path}" class="task-btn-action" target="_blank" title="下载 Excel 清单" style="display:inline-flex;align-items:center;gap:3px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>清单</a>`);
            }
            if (docs.length > 0) {
                artifactsDesc = `<div style="display: flex; gap: 4px;">${docs.join('')}</div>`;
            }

            return `
                <tr style="border-bottom: 1px solid rgba(0, 0, 0, 0.06); height: 50px;">
                    <td style="padding: 8px 12px; font-family: monospace; color: #86868b; font-size: 11.5px;">${t.create_time}</td>
                    <td style="padding: 8px 12px;">
                        <div style="font-weight: 600; color: #1d1d1f;">${t.event_name || '应急保障任务'}</div>
                        <div style="font-size: 11px; color: #86868b;">${t.address || '--'}</div>
                    </td>
                    <td style="padding: 8px 12px;">${shapeDesc}${areaDesc}</td>
                    <td style="padding: 8px 12px;">
                        <span style="color: #0071e3; font-weight: 600;">${metrics.total_sites || 0} 基站</span> / ${metrics.total_cells || 0} 小区
                        <div style="font-size: 11px; color: #86868b;">4G:${metrics.lte_cells || 0} | 5G:${metrics.nr_cells || 0}</div>
                    </td>
                    <td style="padding: 8px 12px;">${diagDesc}</td>
                    <td style="padding: 8px 12px;">${artifactsDesc}</td>
                    <td style="padding: 8px 12px; text-align: center; white-space: nowrap;">
                        <button type="button" class="btn btn-primary" onclick="loadHistoricalTask('${t.task_id}')" style="padding: 4px 10px; font-size: 11px; margin-right: 4px;">
                            查看
                        </button>
                        <button type="button" class="btn btn-outline" onclick="deleteHistoricalTask('${t.task_id}', event)" style="padding: 4px 8px; font-size: 11px; border-color: rgba(255, 59, 48, 0.25); color: #ff3b30; display: inline-flex; align-items: center;" title="删除记录">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 30px; color: #ff3b30;">加载失败: ${err.message}</td></tr>`;
    }
}
window.refreshTaskHistoryModal = refreshTaskHistoryModal;

let _taskSearchTimer = null;
function onSearchTaskHistory(kw) {
    clearTimeout(_taskSearchTimer);
    _taskSearchTimer = setTimeout(() => {
        refreshTaskHistoryModal(kw);
    }, 300);
}
window.onSearchTaskHistory = onSearchTaskHistory;

// ---------------------------------------------------------------------------
// 11. 应急保障流水线 (Pipeline / Stepper) 专属控制器
// ---------------------------------------------------------------------------
appState.pipelineCurrentStep = 1;

window.switchPipelineStep = function(step) {
    appState.pipelineCurrentStep = step;

    const p1 = document.getElementById('pipelineStepPanel1');
    const p2 = document.getElementById('pipelineStepPanel2');
    const p3 = document.getElementById('pipelineStepPanel3');

    if (p1) p1.style.display = (step === 1) ? 'flex' : 'none';
    if (p2) p2.style.display = (step === 2) ? 'flex' : 'none';
    if (p3) p3.style.display = (step === 3) ? 'flex' : 'none';

    // 步骤 2 = 查指标·诊断（上传区 + 诊断结果区合一）：有诊断结果时才展示结果区
    const hasDiag = !!(appState.diagnosisResult && appState.diagnosisResult.diagnosed_cells);
    if (step === 2) {
        const resSec = document.getElementById('pipelineStep2Results');
        const divider = document.getElementById('pipelineStep2Divider');
        if (resSec) resSec.style.display = hasDiag ? 'block' : 'none';
        if (divider) divider.style.display = hasDiag ? 'block' : 'none';
        if (hasDiag && resSec) {
            // 有结果时滚动到结果区；否则停在上传区顶部
            requestAnimationFrame(() => resSec.scrollIntoView({ block: 'start' }));
        }
        // 结果区显示时重算图表尺寸（图表在隐藏容器里渲染时尺寸为 0）
        if (hasDiag && typeof resizeDiagnosisCharts === 'function') {
            requestAnimationFrame(() => resizeDiagnosisCharts());
        }
    }

    // 状态指示徽标
    const badge = document.getElementById('pipelineCurrentStepBadge');
    if (badge) {
        if (step === 1) badge.innerText = '第 1 步 / 共 3 步';
        else if (step === 2) badge.innerText = '第 2 步 / 共 3 步';
        else if (step === 3) badge.innerText = '第 3 步 / 共 3 步';
    }

    // 步进器标签状态高亮
    const tab1 = document.getElementById('pipelineStepTab1');
    const tab2 = document.getElementById('pipelineStepTab2');
    const tab3 = document.getElementById('pipelineStepTab3');
    const arr1 = document.getElementById('pipelineArrow1');
    const arr2 = document.getElementById('pipelineArrow2');

    [tab1, tab2, tab3].forEach(t => {
        if (t) t.classList.remove('active', 'completed');
    });

    if (step === 1) {
        if (tab1) tab1.classList.add('active');
        if (arr1) arr1.classList.remove('passed');
        if (arr2) arr2.classList.remove('passed');
    } else if (step === 2) {
        if (tab1) tab1.classList.add('completed');
        if (tab2) tab2.classList.add('active');
        if (arr1) arr1.classList.add('passed');
        if (arr2) arr2.classList.remove('passed');
    } else if (step === 3) {
        if (tab1) tab1.classList.add('completed');
        if (tab2) tab2.classList.add('completed');
        if (tab3) tab3.classList.add('active');
        if (arr1) arr1.classList.add('passed');
        if (arr2) arr2.classList.add('passed');
    }

    updatePipelineSummary();
};

window.reRunMatchAndDiagnose = function() {
    executeCombinedDataMatchAndDiagnose(false);
};

window.updatePipelineSummary = function() {
    const totalSites = appState.selectedSites ? appState.selectedSites.length : (appState.matchedData?.total_sites || 0);
    const totalCells = appState.selectedCells ? appState.selectedCells.length : (appState.matchedData?.total_cells || 0);
    const anomalyCount = appState.diagnosedCells ? appState.diagnosedCells.length : (appState.diagnosisResult?.diagnosed_cells?.length || 0);

    const step1Tip = document.getElementById('pipelineStep1AreaSitesTip');
    if (step1Tip) {
        step1Tip.innerText = `已圈选 ${totalSites} 个基站（${totalCells} 个小区）`;
    }

    const step3Sites = document.getElementById('pipelineStep3SitesTip');
    if (step3Sites) step3Sites.innerText = `${totalSites} 基站`;

    const step3Cells = document.getElementById('pipelineStep3CellsTip');
    if (step3Cells) step3Cells.innerText = `${totalCells} 小区`;

    const summaryTitle = document.getElementById('pipelineStep3SummaryTitle');
    const summarySub = document.getElementById('pipelineStep3SummarySub');
    if (summaryTitle && summarySub) {
        if (appState.diagnosisResult) {
            summaryTitle.innerText = `${totalSites} 基站，${totalCells} 小区，${anomalyCount} 异常`;
            summarySub.innerText = '';
        } else {
            summaryTitle.innerText = `${totalSites} 基站，${totalCells} 小区`;
            summarySub.innerText = '';
        }
    }

    // 智能同步保障任务名称至导出文件名输入框
    const inputEvent = document.getElementById('inputEventName');
    if (inputEvent) {
        const addrInput = document.getElementById('inputEventAddress');
        const currAddress = addrInput ? addrInput.value.trim() : '';
        const taskName = appState.currentTask?.event_name;
        if (taskName) {
            inputEvent.value = taskName;
        } else if (currAddress && (inputEvent.value === '南川水江应急无线通信保障' || !inputEvent.value.trim())) {
            inputEvent.value = `${currAddress}应急无线通信保障`;
        }
    }

    updateExportCheckCard();
};

// 导出前检查卡：每行写具体值；阻塞项禁用生成按钮并给跳转修复链接，建议项只提示
function setCheckRow(rowId, valueId, valueText, ok, failText, onFix, advisory) {
    const row = document.getElementById(rowId);
    const val = document.getElementById(valueId);
    if (!row || !val) return;
    val.innerText = ok ? valueText : failText;
    row.classList.toggle('blocker', !ok);
    row.classList.toggle('advisory', !!advisory && ok);
    let fixBtn = row.querySelector('.check-fix');
    if (!ok && onFix) {
        if (!fixBtn) {
            fixBtn = document.createElement('button');
            fixBtn.type = 'button';
            fixBtn.className = 'check-fix';
            fixBtn.innerText = '去修复 →';
            row.appendChild(fixBtn);
        }
        fixBtn.onclick = onFix;
    } else if (fixBtn) {
        fixBtn.remove();
    }
}

function updateExportCheckCard() {
    const card = document.getElementById('exportCheckCard');
    if (!card) return;
    const totalSites = appState.selectedSites ? appState.selectedSites.length : (appState.matchedData?.total_sites || 0);
    const totalCells = appState.selectedCells ? appState.selectedCells.length : (appState.matchedData?.total_cells || 0);
    const anomalyCount = appState.diagnosedCells ? appState.diagnosedCells.length : (appState.diagnosisResult?.diagnosed_cells?.length || 0);
    const hasDiag = !!appState.diagnosisResult;
    const titleInput = document.getElementById('inputEventName');
    const title = titleInput ? titleInput.value.trim() : '';

    setCheckRow('checkRowSites', 'checkValueSites', `${totalSites} 个`, totalSites > 0, '未圈选任何基站', () => switchPipelineStep(1));
    setCheckRow('checkRowCells', 'checkValueCells', `${totalCells} 个`, totalCells > 0, '未圈选任何小区', () => switchPipelineStep(1));
    setCheckRow('checkRowAnomaly', 'checkValueAnomaly', hasDiag ? `${anomalyCount} 个` : '未诊断', true, '', null, !hasDiag);
    setCheckRow('checkRowTitle', 'checkValueTitle', title || '未填写', !!title, '通报标题为空', () => { const el = document.getElementById('inputEventName'); if (el) el.focus(); });

    const blockers = card.querySelectorAll('.export-check-row.blocker').length;
    const btn = document.getElementById('btnGenerateReport');
    const note = document.getElementById('exportCheckNote');
    if (btn) btn.disabled = blockers > 0;
    if (note) note.innerText = blockers > 0 ? `有 ${blockers} 项未通过，处理后才能生成通报。` : (hasDiag ? '' : '未上传告警/指标文件，将导出基础通报（无诊断结论）。');
}

window.openPipelineModal = function(step = 1) {
    closeAllDarkModals();
    openDarkModal('modalDataAnalysis');
    switchPipelineStep(step);
};

window.openCombinedAnalysisDiagnosisModal = function() {
    // 第 2 步 = 查指标·诊断（上传区 + 结果区合一；无结果时只显示上传区）
    openPipelineModal(2);
};

// 应急保障向导入口（顶栏按钮 / 地图右键“设为应急中心”）：第 1 步定界
window.openEmergencyWizard = function() {
    openPipelineModal(1);
};

// 向导第 2 步内回到上传区（诊断结果区底部的“上一步”）
window.scrollWizardToUpload = function() {
    const el = document.getElementById('pipelineStep2Upload');
    if (el) el.scrollIntoView({ block: 'start' });
};

// 向导第 1 步里选“多边形”：弹窗会挡住地图，须先关闭向导再绘制；画完自动返回向导第 1 步
window.wizardSelectMode = function(mode) {
    if (mode === 'polygon') {
        appState.wizardReturnAfterDraw = true;
        closeDarkModal('modalDataAnalysis');
        setSelectMode('polygon');
    } else {
        setSelectMode('circle');
    }
};

// 向导第 1 步里的“查询”按钮：多边形模式且尚未画好时，同样先关向导去地图上画
window.wizardTriggerSelection = function() {
    if (appState.selectMode === 'polygon' && !(appState.lastPolygonCoords && appState.lastPolygonCoords.length >= 3)) {
        appState.wizardReturnAfterDraw = true;
        closeDarkModal('modalDataAnalysis');
        startDrawPolygon();
        return;
    }
    triggerMainSelection();
};

window.switchMainTab = function(tabName) {
    appState.currentTab = tabName;
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    // 默认关闭所有模态框
    closeAllDarkModals();

    const navEmergency = document.getElementById('navItemEmergency');
    const navHistory = document.getElementById('navItemHistory');

    if (tabName === 'emergency') {
        if (navEmergency) navEmergency.classList.add('active');
    } else if (tabName === 'params') {
        const pRight = document.getElementById('panelBaseStationData');
        if (pRight && pRight.classList.contains('collapsed')) {
            togglePanelRight(false);
        }
    } else if (tabName === 'analysis' || tabName === 'diagnosis') {
        openCombinedAnalysisDiagnosisModal();
    } else if (tabName === 'report') {
        openReportModal();
    } else if (tabName === 'history') {
        if (navHistory) navHistory.classList.add('active');
        openTaskHistoryModal();
    }
};

function openDarkModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

window.closeDarkModal = function(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
};

function closeAllDarkModals() {
    ['modalDataAnalysis', 'modalMapSettings', 'modalTaskHistory'].forEach(id => {
        closeDarkModal(id);
    });
}

// ---------------------------------------------------------------------------
// 12. 导入网管表格比对逻辑
// ---------------------------------------------------------------------------
function initAnalysisEvents() {
    // 拖拽上传与文件选择：告警
    const dropAlarm = document.getElementById('dropZoneAlarm');
    const inputAlarm = document.getElementById('fileAlarm');
    if (dropAlarm && inputAlarm) {
        dropAlarm.addEventListener('click', () => inputAlarm.click());
        inputAlarm.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                appState.alarmFile = e.target.files[0];
                const fnEl = document.getElementById('alarmFileName');
                if (fnEl) fnEl.innerText = appState.alarmFile.name;
            }
        });
    }

    // 拖拽上传与文件选择：KPI (支持最多3个网管文件汇总)
    const dropKpi = document.getElementById('dropZoneKpi');
    const inputKpi = document.getElementById('fileKpi');
    if (dropKpi && inputKpi) {
        dropKpi.addEventListener('click', (e) => {
            if (e.target.closest('.btn-remove-kpi-file')) return;
            inputKpi.click();
        });

        dropKpi.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropKpi.style.borderColor = '#0071e3';
            dropKpi.style.background = 'rgba(0, 113, 227, 0.08)';
        });
        dropKpi.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropKpi.style.borderColor = 'rgba(0, 113, 227, 0.2)';
            dropKpi.style.background = 'rgba(0, 0, 0, 0.04)';
        });
        dropKpi.addEventListener('drop', (e) => {
            e.preventDefault();
            dropKpi.style.borderColor = 'rgba(0, 113, 227, 0.2)';
            dropKpi.style.background = 'rgba(0, 0, 0, 0.04)';
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                addKpiFiles(Array.from(e.dataTransfer.files));
            }
        });

        inputKpi.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                addKpiFiles(Array.from(e.target.files));
                inputKpi.value = ''; // 允许重复选择相同文件重新触发
            }
        });
    }

    // 执行导表匹配与门限比对
    const btnRun = document.getElementById('btnRunMatch');
    if (btnRun) {
        btnRun.addEventListener('click', () => {
            const hasKpi = (appState.kpiFiles && appState.kpiFiles.length > 0) || appState.kpiFile;
            if (!appState.alarmFile && !hasKpi) {
                showToast('请先导入告警或指标文件', 'warning');
                return;
            }
            executeCombinedDataMatchAndDiagnose(false);
        });
    }
}

// ---------------------------------------------------------------------------
// 多网管 KPI 文件管理（支持4G/5G最多6个文件）
// ---------------------------------------------------------------------------
function addKpiFiles(newFiles) {
    if (!appState.kpiFiles) appState.kpiFiles = [];
    const validExts = ['.csv', '.xlsx', '.xls'];
    let addedCount = 0;

    for (const f of newFiles) {
        const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
        if (!validExts.includes(ext)) {
            showToast(`文件 ${f.name} 格式不支持，请上传 CSV 或 Excel 文件`, 'warning');
            continue;
        }
        if (appState.kpiFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
            continue;
        }
        if (appState.kpiFiles.length >= 6) {
            showToast('最多 6 个指标文件', 'warning');
            break;
        }
        appState.kpiFiles.push(f);
        addedCount++;
    }

    appState.kpiFile = appState.kpiFiles[0] || null;
    renderKpiFileList();

    if (addedCount > 0) {
        showToast(`已添加 ${addedCount} 个文件`, 'info');
    }
}

function removeKpiFile(index) {
    if (appState.kpiFiles && appState.kpiFiles.length > index) {
        const removed = appState.kpiFiles.splice(index, 1);
        appState.kpiFile = appState.kpiFiles[0] || null;
        renderKpiFileList();
        if (removed && removed[0]) {
            showToast(`已移除 ${removed[0].name}`, 'info');
        }
    }
}
window.removeKpiFile = removeKpiFile;

function renderKpiFileList() {
    const listEl = document.getElementById('kpiFileList');
    const nameEl = document.getElementById('kpiFileName');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (!appState.kpiFiles || appState.kpiFiles.length === 0) {
        if (nameEl) nameEl.innerText = '';
        return;
    }

    if (nameEl) {
        nameEl.innerText = `已选 ${appState.kpiFiles.length} 个网管指标文件 (最多6个)`;
    }

    appState.kpiFiles.forEach((file, idx) => {
        const item = document.createElement('div');
        item.style.cssText = 'display: flex; align-items: center; justify-content: space-between; background: rgba(0, 113, 227, 0.08); border: 1px solid rgba(0, 113, 227, 0.18); border-radius: 4px; padding: 4px 8px; font-size: 11px; color: #1d1d1f;';

        const sizeKb = (file.size / 1024).toFixed(1) + ' KB';
        item.innerHTML = `
            <div style="display: flex; align-items: center; gap: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 85%;">
                <span style="color: #0071e3; font-weight: bold; font-family: monospace;">[网管${idx + 1}]</span>
                <span style="overflow: hidden; text-overflow: ellipsis; color: #1d1d1f;" title="${file.name}">${file.name}</span>
                <span style="color: #86868b; font-size: 10px;">(${sizeKb})</span>
            </div>
            <button type="button" class="btn-remove-kpi-file" onclick="event.stopPropagation(); removeKpiFile(${idx})" title="移除此文件" style="background: none; border: none; color: #ff3b30; cursor: pointer; padding: 0 4px; font-size: 13px; font-weight: bold; line-height: 1;">✕</button>
        `;
        listEl.appendChild(item);
    });
}

// 导入表格比对：读表 + 按站号匹配 + 比对门限
async function executeCombinedDataMatchAndDiagnose(useDefault = false) {
    showLoading('正在比对...');
    try {
        // 第一阶段：读取表格并按小区/基站关联匹配
        const formData = new FormData();
        if (useDefault) {
            formData.append('use_default', 'true');
        } else {
            if (appState.alarmFile) formData.append('alarm_file', appState.alarmFile);
            if (appState.kpiFiles && appState.kpiFiles.length > 0) {
                appState.kpiFiles.forEach(f => {
                    formData.append('kpi_files', f);
                });
            } else if (appState.kpiFile) {
                formData.append('kpi_file', appState.kpiFile);
            }
        }

        const matchData = await safeFetchJson('/api/match/upload', {
            method: 'POST',
            body: formData
        });

        appState.matchedData = matchData;
        const matchSummary = document.getElementById('matchResultSummary');
        if (matchSummary) matchSummary.style.display = 'flex';
        const stats = matchData.match_statistics || {};
        const statFull = document.getElementById('statMatchFull');
        if (statFull) statFull.innerText = stats['告警+性能已匹配'] || 0;
        const statAlarm = document.getElementById('statMatchAlarmOnly');
        if (statAlarm) statAlarm.innerText = stats['仅告警匹配'] || 0;
        const statKpi = document.getElementById('statMatchKpiOnly');
        if (statKpi) statKpi.innerText = stats['仅性能匹配'] || 0;
        const statNone = document.getElementById('statMatchNone');
        if (statNone) statNone.innerText = stats['仅工参未匹配'] || 0;

        const statKpiSummary = document.getElementById('statKpiSummary');
        if (statKpiSummary) {
            if (matchData.kpi_file_count && matchData.kpi_file_count > 0) {
                statKpiSummary.style.display = 'inline-block';
                statKpiSummary.innerText = `[已汇总 ${matchData.kpi_file_count} 个网管指标库: 共 ${matchData.kpi_count || 0} 个小区]`;
            } else {
                statKpiSummary.style.display = 'none';
            }
        }

        // 第二阶段：比对指标门限筛出异常小区
        const diagData = await safeFetchJson('/api/diagnosis/run', { method: 'POST' });
        appState.diagnosisResult = diagData;
        
        // 更新统计与占比
        const scoreEl = document.getElementById('healthScore');
        if (scoreEl) scoreEl.innerText = diagData.health_score || '98';
        const descEl = document.getElementById('healthDesc');
        if (descEl) descEl.innerText = diagData.overall_status || '网络运行良好';
        
        const countP0 = document.getElementById('countP0');
        if (countP0) countP0.innerText = diagData.p0_count || 0;
        const countP1 = document.getElementById('countP1');
        if (countP1) countP1.innerText = diagData.p1_count || 0;
        const countP2 = document.getElementById('countP2');
        if (countP2) countP2.innerText = diagData.p2_count || 0;
        const countNormal = document.getElementById('countNormal');
        if (countNormal) countNormal.innerText = diagData.normal_count || 0;

        const diagCells = diagData.diagnosed_cells || [];
        appState.diagnosedCells = diagCells;
        const tipEl = document.getElementById('diagnoseCellsCountTip');
        if (tipEl) tipEl.innerText = `共 ${diagCells.length} 个异常小区需处理`;

        // 渲染异常清单
        renderDiagnosisTable(diagCells);
        if (typeof renderDiagnosisCharts === 'function') {
            renderDiagnosisCharts(diagData);
        }

        // 更新右侧面板的告警指标数量徽标
        const badge = document.getElementById('badgeAlarmViewCount');
        if (badge) {
            badge.innerText = diagCells.length;
            if (diagCells.length > 0) {
                badge.style.background = '#ff3b30';
                badge.style.color = '#ffffff';
                badge.style.fontWeight = 'bold';
            } else {
                badge.style.background = 'rgba(255, 59, 48, 0.18)';
                badge.style.color = '#ff3b30';
            }
        }

        // 刷新地图标点以展示异常小区呼吸脉冲
        if (appState.selectedCells && appState.selectedCells.length > 0) {
            renderCellMarkers(appState.selectedCells);
        }

        // 自动展开右侧工参面板并切换至【🚨 告警与指标】模式
        togglePanelRight(false);
        switchParamViewMode('alarm');

        showToast(`分析完成 (${diagCells.length} 异常)`, 'success');
        // 流水线推进至步骤 2
        switchPipelineStep(2);
    } catch (err) {
        showToast(`比对失败: ${err.message}`, 'error');
    } finally {
        hideLoading();
    }
}
window.executeCombinedDataMatchAndDiagnose = executeCombinedDataMatchAndDiagnose;

function initDiagnosisEvents() {
    const btnDiag = document.getElementById('btnRunDiagnosis');
    if (btnDiag) {
        btnDiag.addEventListener('click', async () => {
            showLoading('正在比对...');
            try {
                const data = await safeFetchJson('/api/diagnosis/run', { method: 'POST' });
                appState.diagnosisResult = data;
                
                const scoreEl = document.getElementById('healthScore');
                if (scoreEl) scoreEl.innerText = data.health_score || '98';
                const descEl = document.getElementById('healthDesc');
                if (descEl) descEl.innerText = data.overall_status || '网络运行良好';
                
                const countP0 = document.getElementById('countP0');
                if (countP0) countP0.innerText = data.p0_count || 0;
                const countP1 = document.getElementById('countP1');
                if (countP1) countP1.innerText = data.p1_count || 0;
                const countP2 = document.getElementById('countP2');
                if (countP2) countP2.innerText = data.p2_count || 0;
                const countNormal = document.getElementById('countNormal');
                if (countNormal) countNormal.innerText = data.normal_count || 0;

                const diagCells = data.diagnosed_cells || [];
                appState.diagnosedCells = diagCells;
                const tipEl = document.getElementById('diagnoseCellsCountTip');
                if (tipEl) tipEl.innerText = `共 ${diagCells.length} 个异常小区需处理`;

                renderDiagnosisTable(diagCells);
                if (typeof renderDiagnosisCharts === 'function') {
                    renderDiagnosisCharts(data);
                }

                // 更新右侧面板的告警指标数量徽标
                const badge = document.getElementById('badgeAlarmViewCount');
                if (badge) {
                    badge.innerText = diagCells.length;
                    if (diagCells.length > 0) {
                        badge.style.background = '#ff3b30';
                        badge.style.color = '#ffffff';
                        badge.style.fontWeight = 'bold';
                    } else {
                        badge.style.background = 'rgba(255, 59, 48, 0.18)';
                        badge.style.color = '#ff3b30';
                    }
                }

                // 刷新地图标点以展示异常小区呼吸脉冲
                if (appState.selectedCells && appState.selectedCells.length > 0) {
                    renderCellMarkers(appState.selectedCells);
                }

                // 切换至告警指标视图
                switchParamViewMode('alarm');

                showToast('比对完成', 'success');
                switchPipelineStep(2);
            } catch (err) {
                showToast(`比对失败: ${err.message}`, 'error');
            } finally {
                hideLoading();
            }
        });
    }

// 打开通报与清单导出 (定位至流水线步骤 3：导出通报)
window.openReportModal = function() {
    openPipelineModal(3);
};

    // 报告生成
    document.getElementById('btnGenerateReport').addEventListener('click', async () => {
        showLoading('正在生成...');
        try {
            const eventName = document.getElementById('inputEventName').value.trim() || '应急通信保障处置通报';
            const formData = new FormData();
            formData.append('event_name', eventName);

            const data = await safeFetchJson('/api/report/generate', {
                method: 'POST',
                body: formData
            });

            appState.lastGeneratedReports = {
                word_file: data.word_file,
                excel_file: data.excel_file,
                word_path: data.word_file,
                excel_path: data.excel_file
            };

            const downloadArea = document.getElementById('downloadArea');
            if (downloadArea) {
                document.getElementById('wordFileName').innerText = data.word_file;
                document.getElementById('excelFileName').innerText = data.excel_file;

                document.getElementById('cardDownloadWord').onclick = () => {
                    window.open(`/api/report/download/${data.word_file}`, '_blank');
                };
                document.getElementById('cardDownloadExcel').onclick = () => {
                    window.open(`/api/report/download/${data.excel_file}`, '_blank');
                };

                // 生成完成后才展示下载区域
                downloadArea.style.display = 'grid';
            }

            showToast('生成成功', 'success');
        } catch (err) {
            showToast(`通报生成失败: ${err.message}`, 'error');
        } finally {
            hideLoading();
        }
    });
}

function renderDiagnosisTable(cells) {
    const tbody = document.getElementById('tbodyDiagnosis');
    if (!tbody) return;

    const abnormalCells = cells.filter(c => c.diag_level && c.diag_level !== '正常');
    if (abnormalCells.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #30d158; padding: 24px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#30d158" stroke-width="2.5" style="vertical-align:-2px;margin-right:4px;"><circle cx="12" cy="12" r="10"/><polyline points="8 12 11 15 16 9"/></svg>圈选区域内未发现退服断站或超标小区</td></tr>`;
        return;
    }

    tbody.innerHTML = abnormalCells.map(c => {
        let badge = `<span style="color:#ff3b30; font-weight:bold;">P0 退服</span>`;
        if (c.diag_level === 'P1') badge = `<span style="color:#ff9f0a; font-weight:bold;">P1 拥塞</span>`;
        if (c.diag_level === 'P2') badge = `<span style="color:#0071e3; font-weight:bold;">P2 质差</span>`;

        const suggestion = c.diag_suggestion || c.diag_detail || c.alarm_name || c.alarm_cause || '核查处理';

        return `
            <tr>
                <td>${badge}</td>
                <td style="color:#1d1d1f;">${c.site_name || c.site_id}</td>
                <td style="color:#0071e3;">${c.cell_name || c.cell_id}</td>
                <td>${c.diag_type || '异常'}</td>
                <td style="color:#6e6e73;" title="${suggestion}">${suggestion}</td>
                <td style="font-family:monospace; color:#86868b;">${c.start_time || '近期'}</td>
            </tr>
        `;
    }).join('');
}

// ---------------------------------------------------------------------------
// 诊断图表 (ECharts)：级别分布环形图 + 异常类型柱状图 + PRB Top10 横向条形图
// ---------------------------------------------------------------------------
const DIAG_CHART_COLORS = { P0: '#ff3b30', P1: '#ff9f0a', P2: '#0071e3', '正常': '#30d158' };

function renderDiagnosisCharts(diagData) {
    if (typeof echarts === 'undefined' || !diagData) return;
    appState.diagnosisCharts = appState.diagnosisCharts || {};

    // 1. 告警级别分布（环形图）
    const donutEl = document.getElementById('chartLevelDonut');
    if (donutEl) {
        const chart = appState.diagnosisCharts.donut || echarts.init(donutEl);
        appState.diagnosisCharts.donut = chart;
        const data = [
            { value: diagData.p0_count || 0, name: 'P0 退服' },
            { value: diagData.p1_count || 0, name: 'P1 拥塞' },
            { value: diagData.p2_count || 0, name: 'P2 质差' },
            { value: diagData.normal_count || 0, name: '正常' }
        ];
        chart.setOption({
            tooltip: { trigger: 'item', backgroundColor: '#ffffff', borderColor: 'rgba(0, 113, 227, 0.18)', textStyle: { color: '#1d1d1f', fontSize: 12 } },
            legend: { bottom: 0, textStyle: { color: '#86868b', fontSize: 11 } },
            color: [DIAG_CHART_COLORS.P0, DIAG_CHART_COLORS.P1, DIAG_CHART_COLORS.P2, DIAG_CHART_COLORS['正常']],
            series: [{
                type: 'pie', radius: ['45%', '70%'], center: ['50%', '42%'],
                avoidLabelOverlap: true,
                label: { show: false },
                emphasis: { label: { show: true, fontSize: 12, fontWeight: 'bold', color: '#1d1d1f' } },
                data
            }]
        });
    }

    const cells = diagData.diagnosed_cells || [];

    // 2. 异常类型分布（柱状图）
    const typeEl = document.getElementById('chartTypeBar');
    if (typeEl) {
        const chart = appState.diagnosisCharts.typeBar || echarts.init(typeEl);
        appState.diagnosisCharts.typeBar = chart;
        const counts = {};
        cells.forEach(c => { const t = c.diag_type || '异常'; counts[t] = (counts[t] || 0) + 1; });
        const names = Object.keys(counts);
        const values = names.map(n => counts[n]);
        chart.setOption({
            tooltip: { trigger: 'axis', backgroundColor: '#ffffff', borderColor: 'rgba(0, 113, 227, 0.18)', textStyle: { color: '#1d1d1f', fontSize: 12 } },
            grid: { left: 8, right: 12, top: 12, bottom: 28, containLabel: true },
            xAxis: { type: 'category', data: names, axisLabel: { color: '#86868b', fontSize: 11, interval: 0, rotate: names.length > 4 ? 20 : 0 } },
            yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#86868b', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(0, 113, 227, 0.08)' } } },
            series: [{
                type: 'bar', data: values, barWidth: '55%',
                itemStyle: { color: '#0071e3', borderRadius: [4, 4, 0, 0] },
                label: { show: true, position: 'top', color: '#1d1d1f', fontSize: 11 }
            }]
        });
    }

    // 3. 下行 PRB 利用率 Top 10（横向条形图）
    const prbEl = document.getElementById('chartPrbTop');
    if (prbEl) {
        const chart = appState.diagnosisCharts.prbTop || echarts.init(prbEl);
        appState.diagnosisCharts.prbTop = chart;
        const ranked = cells
            .map(c => ({ name: c.cell_name || c.cell_id || '未知小区', prb: parseFloat(c.prb_dl_util) || 0, level: c.diag_level || '' }))
            .filter(c => c.prb > 0)
            .sort((a, b) => b.prb - a.prb)
            .slice(0, 10)
            .reverse();
        chart.setOption({
            tooltip: {
                trigger: 'axis', backgroundColor: '#ffffff', borderColor: 'rgba(0, 113, 227, 0.18)',
                textStyle: { color: '#1d1d1f', fontSize: 12 },
                formatter: p => `${p[0].name}<br/>下行 PRB 利用率：${p[0].value}%`
            },
            grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
            xAxis: { type: 'value', max: 100, axisLabel: { color: '#86868b', fontSize: 11, formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(0, 113, 227, 0.08)' } } },
            yAxis: {
                type: 'category', data: ranked.map(c => c.name),
                axisLabel: { color: '#6e6e73', fontSize: 11, width: 180, overflow: 'truncate' }
            },
            series: [{
                type: 'bar', data: ranked.map(c => c.prb), barWidth: '60%',
                itemStyle: {
                    borderRadius: [0, 4, 4, 0],
                    color: p => (DIAG_CHART_COLORS[ranked[p.dataIndex]?.level] || '#0071e3')
                },
                label: { show: true, position: 'right', color: '#1d1d1f', fontSize: 11, formatter: '{c}%' }
            }]
        });
    }
}
window.renderDiagnosisCharts = renderDiagnosisCharts;

function resizeDiagnosisCharts() {
    if (!appState.diagnosisCharts) return;
    Object.values(appState.diagnosisCharts).forEach(c => { try { c.resize(); } catch (e) { /* ignore */ } });
}
window.resizeDiagnosisCharts = resizeDiagnosisCharts;

// ---------------------------------------------------------------------------
// 13. 系统与地图设置 (高德精准检索)
// ---------------------------------------------------------------------------
window.openMapSettingsModal = function() {
    openDarkModal('modalMapSettings');
    const resultEl = document.getElementById('amapTestResult');
    if (resultEl) {
        resultEl.style.display = 'none';
        resultEl.innerHTML = '';
    }
    const keyInput = document.getElementById('inputAmapApiKey');
    const svgEye = document.getElementById('svgEyeIcon');
    const btnToggle = document.getElementById('btnToggleKeyVisibility');
    if (keyInput) keyInput.type = 'password';
    if (svgEye) {
        svgEye.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
    }
    if (btnToggle) btnToggle.title = '显示 Key';
    loadAmapConfig();

    // 同步视口渲染控制配置到下拉框
    loadStoredViewportSettings();
    const selMin = document.getElementById('selectSectorMinZoom');
    const selMax = document.getElementById('selectSectorMaxZoom');
    const selLimit = document.getElementById('selectSectorRenderLimit');
    if (selMin && appState.viewportSettings) selMin.value = String(appState.viewportSettings.minZoom ?? 12);
    if (selMax && appState.viewportSettings) selMax.value = String(appState.viewportSettings.maxZoom ?? 0);
    if (selLimit && appState.viewportSettings) selLimit.value = String(appState.viewportSettings.maxRenderLimit ?? 800);
};

window.closeMapSettingsModal = function() {
    closeDarkModal('modalMapSettings');
};

window.setAmapCityQuick = function(cityName) {
    const input = document.getElementById('inputAmapCity');
    if (input) {
        input.value = cityName;
        input.focus();
    }
};

async function loadAmapConfig() {
    try {
        const data = await safeFetchJson('/api/config/amap');
        const keyInput = document.getElementById('inputAmapApiKey');
        const cityInput = document.getElementById('inputAmapCity');
        const tipEl = document.getElementById('inferredCityTip');
        const statusBadge = document.getElementById('amapConfigStatusBadge');

        if (data.configured && keyInput) {
            keyInput.value = data.api_key_masked;
        }
        const activeCity = data.default_city || data.inferred_city || '重庆市';
        if (cityInput && (!cityInput.value || !data.user_customized_city)) {
            cityInput.value = activeCity;
        }
        if (tipEl) {
            tipEl.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg><span>默认已根据工参经纬度自动设为: <b>${activeCity}</b></span>`;
        }
        if (statusBadge) {
            statusBadge.style.display = 'inline-flex';
            if (data.configured) {
                statusBadge.style.background = 'rgba(48, 209, 88, 0.1)';
                statusBadge.style.color = '#30d158';
                statusBadge.style.border = '1px solid rgba(48, 209, 88, 0.2)';
                statusBadge.innerHTML = '● 检索服务已启用';
            } else {
                statusBadge.style.background = 'rgba(255, 159, 10, 0.1)';
                statusBadge.style.color = '#ff9f0a';
                statusBadge.style.border = '1px solid rgba(255, 159, 10, 0.2)';
                statusBadge.innerHTML = '● 待配置 Key (回退本地)';
            }
        }
    } catch (e) {
        console.warn('获取高德配置失败', e);
    }
}

function initAmapSettingsEvents() {
    // 1. 切换 API Key 明文/密文显示
    const btnToggle = document.getElementById('btnToggleKeyVisibility');
    if (btnToggle) {
        btnToggle.onclick = function() {
            const keyInput = document.getElementById('inputAmapApiKey');
            const svgEye = document.getElementById('svgEyeIcon');
            if (!keyInput || !svgEye) return;
            if (keyInput.type === 'password') {
                keyInput.type = 'text';
                btnToggle.title = '隐藏 Key';
                svgEye.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
            } else {
                keyInput.type = 'password';
                btnToggle.title = '显示 Key';
                svgEye.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
            }
        };
    }

    // 2. 测试 Key 连通性
    const btnTest = document.getElementById('btnTestAmapConnection');
    if (btnTest) {
        btnTest.onclick = async function() {
            const key = (document.getElementById('inputAmapApiKey').value || '').trim();
            const resultEl = document.getElementById('amapTestResult');
            if (!key) {
                resultEl.style.display = 'block';
                resultEl.style.background = 'rgba(255, 159, 10, 0.1)';
                resultEl.style.border = '1px solid rgba(255, 159, 10, 0.2)';
                resultEl.style.color = '#ff9f0a';
                resultEl.innerHTML = '<div style="display:flex;align-items:center;gap:6px;">⚠️ 请输入高德 Web 服务 API Key 后再进行连通性测试</div>';
                return;
            }

            const originalHtml = btnTest.innerHTML;
            btnTest.disabled = true;
            btnTest.innerHTML = '<span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-right:6px;"></span> 测试中...';

            resultEl.style.display = 'block';
            resultEl.style.background = 'rgba(0, 113, 227, 0.08)';
            resultEl.style.border = '1px solid rgba(0, 113, 227, 0.18)';
            resultEl.style.color = '#0071e3';
            resultEl.innerHTML = '<div style="display:flex;align-items:center;gap:6px;"><span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;"></span> 正在向高德开放平台发送测试请求，验证 Key 有效性...</div>';

            try {
                const formData = new FormData();
                formData.append('api_key', key);
                const res = await fetch('/api/config/amap/test', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (data.valid) {
                    resultEl.style.background = 'rgba(48, 209, 88, 0.1)';
                    resultEl.style.border = '1px solid rgba(48, 209, 88, 0.25)';
                    resultEl.style.color = '#30d158';
                    resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✓</span> <b>连通性测试通过！</b> ${data.message || '高德地理编码与检索服务响应正常。'}</div>`;
                } else {
                    resultEl.style.background = 'rgba(255, 59, 48, 0.1)';
                    resultEl.style.border = '1px solid rgba(255, 59, 48, 0.25)';
                    resultEl.style.color = '#ff3b30';
                    resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✕</span> <b>连通性验证失败：</b> ${data.message || 'Key 无效或无 Web 服务权限'}</div>`;
                }
            } catch (err) {
                resultEl.style.background = 'rgba(255, 59, 48, 0.1)';
                resultEl.style.border = '1px solid rgba(255, 59, 48, 0.25)';
                resultEl.style.color = '#ff3b30';
                resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✕</span> <b>网络请求异常：</b> ${err.message}</div>`;
            } finally {
                btnTest.disabled = false;
                btnTest.innerHTML = originalHtml;
            }
        };
    }

    // 3. 监听扇区视口控制即时改动
    ['selectSectorMinZoom', 'selectSectorMaxZoom', 'selectSectorRenderLimit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                const selMin = document.getElementById('selectSectorMinZoom');
                const selMax = document.getElementById('selectSectorMaxZoom');
                const selLimit = document.getElementById('selectSectorRenderLimit');
                if (selMin && selMax && selLimit) {
                    saveViewportSettings({
                        minZoom: parseInt(selMin.value, 10) || 0,
                        maxZoom: parseInt(selMax.value, 10) || 0,
                        maxRenderLimit: parseInt(selLimit.value, 10) || 0
                    });
                    renderSectorsInCurrentViewport();
                }
            });
        }
    });

    // 4. 保存配置
    const btnSave = document.getElementById('btnSaveAmapSettings');
    if (btnSave) {
        btnSave.onclick = async function() {
            // 保存视口渲染控制配置
            const selMin = document.getElementById('selectSectorMinZoom');
            const selMax = document.getElementById('selectSectorMaxZoom');
            const selLimit = document.getElementById('selectSectorRenderLimit');
            if (selMin && selMax && selLimit) {
                saveViewportSettings({
                    minZoom: parseInt(selMin.value, 10) || 0,
                    maxZoom: parseInt(selMax.value, 10) || 0,
                    maxRenderLimit: parseInt(selLimit.value, 10) || 0
                });
                renderSectorsInCurrentViewport();
            }

            const key = (document.getElementById('inputAmapApiKey').value || '').trim();
            const city = (document.getElementById('inputAmapCity').value || '').trim();
            const resultEl = document.getElementById('amapTestResult');

            const originalHtml = btnSave.innerHTML;
            btnSave.disabled = true;
            btnSave.innerHTML = '<span class="spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-right:6px;"></span> 保存中...';

            try {
                const formData = new FormData();
                formData.append('api_key', key);
                formData.append('city', city);
                formData.append('test_now', key ? 'true' : 'false');

                const res = await fetch('/api/config/amap', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    resultEl.style.display = 'block';
                    resultEl.style.background = 'rgba(48, 209, 88, 0.1)';
                    resultEl.style.border = '1px solid rgba(48, 209, 88, 0.25)';
                    resultEl.style.color = '#30d158';
                    resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✓</span> <b>保存成功！</b> ${data.message}</div>`;
                    if (typeof showToast === 'function') {
                        showToast('已保存', 'success');
                    }
                    await loadAmapConfig();
                    setTimeout(() => {
                        closeMapSettingsModal();
                    }, 800);
                } else {
                    resultEl.style.display = 'block';
                    resultEl.style.background = 'rgba(255, 59, 48, 0.1)';
                    resultEl.style.border = '1px solid rgba(255, 59, 48, 0.25)';
                    resultEl.style.color = '#ff3b30';
                    resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✕</span> <b>保存失败：</b> ${data.message || '请核对 Key 权限及网络连接'}</div>`;
                }
            } catch (err) {
                resultEl.style.display = 'block';
                resultEl.style.background = 'rgba(255, 59, 48, 0.1)';
                resultEl.style.border = '1px solid rgba(255, 59, 48, 0.25)';
                resultEl.style.color = '#ff3b30';
                resultEl.innerHTML = `<div style="display:flex;align-items:center;gap:6px;"><span>✕</span> <b>网络请求异常：</b> ${err.message}</div>`;
            } finally {
                btnSave.disabled = false;
                btnSave.innerHTML = originalHtml;
            }
        };
    }
}

// 地图辅助动作
function resetNorth() {
    appState.map.setZoom(appState.map.getZoom());
}

function toggleBaseLayer(silent = false) {
    if (!appState.layers || !appState.map) return;
    if (appState.layers.current === 'normal') {
        appState.layers.current = 'satellite';
        appState.map.removeLayer(appState.layers.normal);
        appState.layers.satellite.addTo(appState.map);
    } else {
        appState.layers.current = 'normal';
        appState.map.removeLayer(appState.layers.satellite);
        appState.layers.normal.addTo(appState.map);
    }
    saveAppConfig({ baseLayer: appState.layers.current });
}

// ---------------------------------------------------------------------------
// 测距工具模块 (多段连续折线测距，实时提示，双击完成，一键清除)
// ---------------------------------------------------------------------------
function formatDistance(meters) {
    if (meters < 1000) {
        return Math.round(meters) + ' 米';
    }
    return (meters / 1000).toFixed(2) + ' 公里';
}

function initMeasureGroup() {
    if (!appState.measureGroup && appState.map) {
        appState.measureGroup = L.featureGroup().addTo(appState.map);
    }
}

function clearMeasureLayers() {
    if (appState.measureGroup) {
        appState.measureGroup.clearLayers();
    }
    if (appState.measureMoveLine && appState.map) {
        appState.map.removeLayer(appState.measureMoveLine);
        appState.measureMoveLine = null;
    }
    if (appState.measureTooltip && appState.map) {
        appState.map.removeLayer(appState.measureTooltip);
        appState.measureTooltip = null;
    }
    appState.measurePoints = [];
}

function setMeasureButtonsActive(active) {
    ['toolBtnMeasureTop', 'toolBtnMeasureMap'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.classList.toggle('active', active);
    });
}

function toggleMapMeasure() {
    if (appState.isMeasuring) {
        stopMapMeasure(false);
    } else {
        startMapMeasure();
    }
}
window.toggleMapMeasure = toggleMapMeasure;

function startMapMeasure() {
    if (!appState.map) return;
    
    // 若正在多边形圈选，先中止圈选
    if (appState.currentDrawer) {
        try { appState.currentDrawer.disable(); } catch (err) {}
        appState.currentDrawer = null;
    }
    
    appState.isMeasuring = true;
    initMeasureGroup();
    clearMeasureLayers();
    
    setMeasureButtonsActive(true);
    
    appState.map.getContainer().style.cursor = 'crosshair';
    appState.map.doubleClickZoom.disable();
    
    appState.map.on('click', handleMeasureClick);
    appState.map.on('mousemove', handleMeasureMouseMove);
    appState.map.on('dblclick', handleMeasureDblClick);
}

function stopMapMeasure(clear = false) {
    appState.isMeasuring = false;
    
    setMeasureButtonsActive(false);
    
    if (appState.map) {
        appState.map.getContainer().style.cursor = '';
        appState.map.doubleClickZoom.enable();
        
        appState.map.off('click', handleMeasureClick);
        appState.map.off('mousemove', handleMeasureMouseMove);
        appState.map.off('dblclick', handleMeasureDblClick);
        
        if (appState.measureMoveLine) {
            appState.map.removeLayer(appState.measureMoveLine);
            appState.measureMoveLine = null;
        }
        if (appState.measureTooltip) {
            appState.map.removeLayer(appState.measureTooltip);
            appState.measureTooltip = null;
        }
    }
    
    if (clear) {
        clearMeasureLayers();
    }
}
window.stopMapMeasure = stopMapMeasure;
window.clearMeasureLayers = clearMeasureLayers;

function createMeasureNodeIcon() {
    return L.divIcon({
        className: 'custom-measure-node',
        html: '<div style="width: 10px; height: 10px; background: #ffffff; border: 2px solid #0071e3; border-radius: 50%; box-shadow: 0 0 8px rgba(0, 113, 227, 0.5); transform: translate(-3px, -3px);"></div>',
        iconSize: [10, 10]
    });
}

function handleMeasureClick(e) {
    if (!appState.isMeasuring) return;
    const latlng = e.latlng;
    initMeasureGroup();
    
    const pts = appState.measurePoints;
    pts.push(latlng);
    
    const count = pts.length;
    let totalDist = 0;
    let segDist = 0;
    
    if (count > 1) {
        for (let i = 1; i < count; i++) {
            totalDist += pts[i - 1].distanceTo(pts[i]);
        }
        segDist = pts[count - 2].distanceTo(latlng);
        
        // 绘制高亮实线段
        L.polyline([pts[count - 2], latlng], {
            color: '#0071e3',
            weight: 3.5,
            opacity: 0.95
        }).addTo(appState.measureGroup);
    }
    
    // 打点标记与常驻距离 Tooltip
    const marker = L.marker(latlng, { icon: createMeasureNodeIcon(), interactive: false }).addTo(appState.measureGroup);
    
    let tooltipHtml = '';
    if (count === 1) {
        tooltipHtml = '<span style="color:#0071e3; font-weight:700;">起点</span>';
    } else {
        tooltipHtml = `<span>+${formatDistance(segDist)}</span> <span style="color:#86868b; margin:0 3px;">|</span> <span style="color:#0071e3; font-weight:700;">总长 ${formatDistance(totalDist)}</span>`;
    }
    
    marker.bindTooltip(tooltipHtml, {
        permanent: true,
        direction: 'top',
        className: 'measure-tooltip',
        offset: [0, -8]
    }).openTooltip();
}

function handleMeasureMouseMove(e) {
    if (!appState.isMeasuring || !appState.map) return;
    const latlng = e.latlng;
    const pts = appState.measurePoints;
    
    if (!appState.measureTooltip) {
        appState.measureTooltip = L.tooltip({
            permanent: true,
            direction: 'right',
            className: 'measure-tooltip measure-floating-tooltip',
            offset: [12, 0]
        }).setLatLng(latlng).addTo(appState.map);
    } else {
        appState.measureTooltip.setLatLng(latlng);
    }
    
    if (pts.length === 0) {
        appState.measureTooltip.setContent('点击地图确定测距起点');
        return;
    }
    
    const lastPt = pts[pts.length - 1];
    const segDist = lastPt.distanceTo(latlng);
    let totalDist = segDist;
    for (let i = 1; i < pts.length; i++) {
        totalDist += pts[i - 1].distanceTo(pts[i]);
    }
    
    // 更新动态跟随虚线
    if (!appState.measureMoveLine) {
        appState.measureMoveLine = L.polyline([lastPt, latlng], {
            color: '#ff9f0a',
            weight: 2,
            opacity: 0.85,
            dashArray: '5, 8'
        }).addTo(appState.map);
    } else {
        appState.measureMoveLine.setLatLngs([lastPt, latlng]);
    }
    
    appState.measureTooltip.setContent(`
        <div>+${formatDistance(segDist)} (总计: ${formatDistance(totalDist)})</div>
        <div style="font-size: 10px; color: #86868b; margin-top: 2px;">单击下一折点，双击结束</div>
    `);
}

function handleMeasureDblClick(e) {
    if (!appState.isMeasuring) return;
    const pts = appState.measurePoints;
    if (pts.length > 1) {
        let total = 0;
        for (let i = 1; i < pts.length; i++) {
            total += pts[i - 1].distanceTo(pts[i]);
        }
        
        // 终点附带“总距 + ✖ 清除”药丸标签
        const lastPt = pts[pts.length - 1];
        L.marker(lastPt, {
            icon: L.divIcon({
                className: 'custom-measure-end',
                html: `<div style="background: #ffffff; border: 1px solid #ff3b30; border-radius: 4px; padding: 2px 8px; color: #1d1d1f; font-size: 11px; white-space: nowrap; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.14); display: flex; align-items: center; gap: 6px; cursor: pointer;" onclick="clearMeasureLayers(); stopMapMeasure(true);">
                    <span>总距: <b style="color: #0071e3;">${formatDistance(total)}</b></span>
                    <span style="color: #ff3b30; display: flex; align-items: center;" title="清除测距标尺"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ff3b30" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
                </div>`,
                iconSize: [130, 24],
                iconAnchor: [65, -12]
            })
        }).addTo(appState.measureGroup);
    }
    stopMapMeasure(false);
}

function downloadParamPackage() {
    window.open('/api/spatial/export', '_blank');
}

// ---------------------------------------------------------------------------
// UI 遮罩与 Toast 提示
// ---------------------------------------------------------------------------
function showLoading(msg) {
    const el = document.getElementById('loadingOverlay');
    const textEl = document.getElementById('loadingText');
    if (textEl) textEl.innerText = msg || '正在处理中...';
    if (el) el.style.display = 'flex';
    setTaskStatus(true, msg || '处理中…');
}

function hideLoading() {
    const el = document.getElementById('loadingOverlay');
    if (el) el.style.display = 'none';
    setTaskStatus(false);
}

function showToast(msg, type = 'info') {
    // 操作类与引导类普通提示一律静默，不再弹出遮挡屏幕上方
    if (type === 'info') return;
    const toast = document.getElementById('toastMessage');
    if (!toast) return;
    toast.innerText = msg;
    toast.className = `toast show ${type}`;
    if (type === 'error') toast.style.backgroundColor = '#ff3b30';
    else if (type === 'success') toast.style.backgroundColor = '#30d158';
    else if (type === 'warning') toast.style.backgroundColor = '#ff9f0a';
    else toast.style.backgroundColor = '#1d1d1f';
    toast.style.color = '#ffffff';

    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.className = 'toast';
    }, 2800);
}

// ===========================================================================
// 模块五：经纬度边界与保障区域导入 (支持 TXT / 微信保障通知 / GeoJSON)
// ===========================================================================

// 打开边界导入模态框
window.openImportBoundaryModal = function() {
    openDarkModal('modalImportBoundary');
};

// 切换导入数据坐标系 (WGS-84 vs GCJ-02)
window.setImportCoordSys = function(sys) {
    appState.importCoordSys = sys;
    const btnWGS = document.getElementById('btnImportCoordWGS');
    const btnGCJ = document.getElementById('btnImportCoordGCJ');
    if (btnWGS) btnWGS.classList.toggle('active', sys === 'wgs84');
    if (btnGCJ) btnGCJ.classList.toggle('active', sys === 'gcj02');
};

// 文件选择事件
window.handleBoundaryFileSelect = function(input) {
    if (!input || !input.files || input.files.length === 0) return;
    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = function(e) {
        const textarea = document.getElementById('textareaBoundaryText');
        if (textarea) textarea.value = e.target.result;
    };
    reader.onerror = function() {
        showToast('读取文件失败', 'error');
    };
    reader.readAsText(file, 'utf-8');
};

// 执行导入并在地图上自动绘制范围
window.executeBoundaryImport = async function() {
    const textarea = document.getElementById('textareaBoundaryText');
    const content = (textarea ? textarea.value : '').trim();

    if (!content) {
        showToast('请粘贴经纬度文本或选择文件', 'warning');
        return;
    }

    showLoading('正在解析...');
    try {
        const formData = new FormData();
        formData.append('text', content);
        formData.append('coord_sys', appState.importCoordSys || 'wgs84');
        const parsedResult = await safeFetchJson('/api/spatial/import_boundary', {
            method: 'POST',
            body: formData
        });

        if (!parsedResult || parsedResult.total_regions === 0) {
            showToast('未识别到有效的多边形边界', 'error');
            return;
        }

        // 关闭弹窗
        closeDarkModal('modalImportBoundary');

        // 存储当前解析结果
        appState.importedRegionsData = parsedResult;
        appState.activeRegionIndex = -1;

        // 切换到多边形圈选模式
        appState.selectMode = 'polygon';
        updateSelectModeUI('polygon');

        // 清空手动绘制的临时图层，绘制导入的边界多边形
        if (appState.drawLayerGroup) {
            appState.drawLayerGroup.clearLayers();
        }
        renderImportedBoundaries(parsedResult);

        // 更新左侧面板 UI
        updateImportedRegionsUI(parsedResult);

        // 默认聚焦首个区域基站
        if (parsedResult.regions.length > 0) {
            activateImportedRegion(0);
        }
    } catch (err) {
        showToast(err.message || '边界解析失败', 'error');
    } finally {
        hideLoading();
    }
};

// 在地图上绘制所有导入的区域多边形
function renderImportedBoundaries(regionsData) {
    if (!appState.map) return;
    if (!appState.importedBoundaryGroup) {
        appState.importedBoundaryGroup = L.featureGroup().addTo(appState.map);
    }
    appState.importedBoundaryGroup.clearLayers();

    if (!regionsData || !regionsData.regions || regionsData.regions.length === 0) return;

    const currentTileIsAmap = (appState.currentTileType === 'amap');

    regionsData.regions.forEach((region, idx) => {
        // 后端已自动高精度计算好 GCJ-02 与 WGS-84 坐标，根据当前底图类型自适应选取
        const pts = (currentTileIsAmap && region.coords_gcj) ? region.coords_gcj : (region.coords_wgs || region.coords);
        const mapLatLngs = pts.map(pt => [pt[1], pt[0]]);

        const polygonLayer = L.polygon(mapLatLngs, {
            color: '#0071e3',
            weight: 2.5,
            fillColor: '#0071e3',
            fillOpacity: 0.2,
            lineJoin: 'round'
        });

        // 悬浮名称提示
        polygonLayer.bindTooltip(`<b>${escapeHtml(region.name)}</b>`, {
            permanent: false,
            direction: 'top',
            className: 'boundary-map-tooltip'
        });

        // 点击详情气泡
        const popupContent = `
            <div style="font-family: inherit; font-size: 12px; color: #1d1d1f; min-width: 190px; padding: 2px;">
                <div style="font-weight: 700; font-size: 13.5px; color: #0071e3; margin-bottom: 5px;">${escapeHtml(region.name)}</div>
                ${regionsData.activity_name ? `<div style="color: #86868b; font-size: 11px; margin-bottom: 4px;">活动: ${escapeHtml(regionsData.activity_name)}</div>` : ''}
                <div style="color: #86868b; font-size: 11px; margin-bottom: 8px;">边界顶点数: ${region.points_count || region.coords.length} 个</div>
                <button type="button" class="btn btn-primary" onclick="activateImportedRegion(${idx})" style="width: 100%; padding: 5px 8px; font-size: 11.5px; font-weight: 600; display: flex; align-items: center; justify-content: center; gap: 4px;">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    查询此区域基站
                </button>
            </div>
        `;
        polygonLayer.bindPopup(popupContent);

        polygonLayer.on('click', () => {
            activateImportedRegion(idx);
        });

        region._layer = polygonLayer;
        appState.importedBoundaryGroup.addLayer(polygonLayer);
    });

    // 自动自适应缩放到所有多边形
    if (appState.importedBoundaryGroup.getLayers().length > 0) {
        appState.map.fitBounds(appState.importedBoundaryGroup.getBounds(), {
            padding: [45, 45],
            maxZoom: 16
        });
    }
}

// 更新左侧面板的导入区域卡片与列表
function updateImportedRegionsUI(regionsData) {
    const card = document.getElementById('importedRegionsCard');
    const countEl = document.getElementById('importedRegionsCount');
    const subTitleEl = document.getElementById('importedRegionsSubTitle');
    const listEl = document.getElementById('importedRegionsList');
    const inputAddress = document.getElementById('inputEventAddress');

    if (!card || !listEl) return;

    if (!regionsData || regionsData.total_regions === 0) {
        card.style.display = 'none';
        listEl.innerHTML = '';
        return;
    }

    card.style.display = 'block';
    if (countEl) countEl.innerText = regionsData.total_regions;

    // 回填活动名称到事件区域输入框
    if (regionsData.activity_name && inputAddress) {
        inputAddress.value = regionsData.activity_name;
    }

    listEl.innerHTML = '';
    regionsData.regions.forEach((r, idx) => {
        const item = document.createElement('div');
        item.className = 'imported-region-item' + (appState.activeRegionIndex === idx ? ' active' : '');
        item.id = `importedRegionItem_${idx}`;
        item.innerHTML = `
            <span style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span style="color: #0071e3; font-weight: 700;">${idx + 1}.</span>
                <span>${escapeHtml(r.name)}</span>
            </span>
            <span class="region-badge">${r.points_count || r.coords.length}点</span>
        `;
        item.onclick = () => activateImportedRegion(idx);
        listEl.appendChild(item);
    });
}

// 高亮选中特定区域的 UI 态
function highlightImportedRegionUI(activeIdx) {
    if (!appState.importedRegionsData || !appState.importedRegionsData.regions) return;

    appState.importedRegionsData.regions.forEach((r, idx) => {
        const item = document.getElementById(`importedRegionItem_${idx}`);

        if (item) {
            item.classList.toggle('active', activeIdx === idx);
        }

        if (r._layer) {
            if (activeIdx === -1) {
                // 全部高亮
                r._layer.setStyle({
                    color: '#0071e3',
                    fillColor: '#0071e3',
                    fillOpacity: 0.22,
                    weight: 2.5
                });
            } else if (idx === activeIdx) {
                // 当前激活项高亮黄色/高亮青色
                r._layer.setStyle({
                    color: '#ff9f0a',
                    fillColor: '#ff9f0a',
                    fillOpacity: 0.3,
                    weight: 3.5
                });
                if (r._layer.bringToFront) r._layer.bringToFront();
            } else {
                // 非激活项变暗淡
                r._layer.setStyle({
                    color: '#0071e3',
                    fillColor: '#005bb5',
                    fillOpacity: 0.12,
                    weight: 1.5
                });
            }
        }
    });
}

// 激活并查询指定导入区域的基站
window.activateImportedRegion = function(idx) {
    if (!appState.importedRegionsData || !appState.importedRegionsData.regions[idx]) return;
    const region = appState.importedRegionsData.regions[idx];
    appState.activeRegionIndex = idx;

    // 1. 高亮 UI 与多边形
    highlightImportedRegionUI(idx);

    // 2. 视野自适应平移至该多边形
    if (region._layer && appState.map) {
        appState.map.fitBounds(region._layer.getBounds(), {
            padding: [40, 40],
            maxZoom: 16
        });
    }

    // 3. 执行多边形空间查询
    const taskTitle = appState.importedRegionsData.activity_name 
        ? `${appState.importedRegionsData.activity_name}-${region.name}`
        : region.name;
    
    // 更新中心点经纬度显示
    const c_lng = region.coords.reduce((sum, pt) => sum + pt[0], 0) / region.coords.length;
    const c_lat = region.coords.reduce((sum, pt) => sum + pt[1], 0) / region.coords.length;
    setMapCenter(c_lng, c_lat, region.name);

    executePolygonSelection(region.coords, taskTitle, region.name);
};

// 汇总查询所有导入区域基站
window.queryAllImportedRegions = async function() {
    if (!appState.importedRegionsData || !appState.importedRegionsData.regions || appState.importedRegionsData.regions.length === 0) return;
    const regions = appState.importedRegionsData.regions;

    // 1. 全部高亮并在地图上展现全局视野
    if (appState.map && appState.importedBoundaryGroup) {
        appState.map.fitBounds(appState.importedBoundaryGroup.getBounds(), {
            padding: [45, 45],
            maxZoom: 16
        });
    }
    highlightImportedRegionUI(-1);

    const taskTitle = appState.importedRegionsData.activity_name || `联合保障区域(${regions.length}个)`;
    const allCoords = regions.map(r => r.coords);

    showLoading('正在汇总查询...');
    try {
        const formData = new FormData();
        formData.append('multipolygon', JSON.stringify(allCoords));
        formData.append('coord_sys', appState.importCoordSys || 'wgs84');
        formData.append('event_name', taskTitle);
        formData.append('address', `${taskTitle} (共${regions.length}个保障区域)`);

        const data = await safeFetchJson('/api/spatial/multipolygon', {
            method: 'POST',
            body: formData
        });

        appState.hasUserSelected = true;
        handleSelectionResult(data, {
            type: 'polygon',
            coords: allCoords[0]
        });
        showToast(`已圈选 ${data.total_sites} 基站 (${data.total_cells} 小区)`, 'success');
        loadRecentTasks();
    } catch (err) {
        showToast(`多区域汇总圈选失败: ${err.message}`, 'error');
    } finally {
        hideLoading();
    }
};

// 清空已导入的区域
// 清除已画好的多边形/导入边界 (带二次确认)
window.clearDrawnBoundaries = function() {
    const hasDrawn = (appState.drawLayerGroup && appState.drawLayerGroup.getLayers().length > 0) || !!appState.lastPolygonCoords;
    const hasImported = (appState.importedBoundaryGroup && appState.importedBoundaryGroup.getLayers().length > 0) || !!appState.importedRegionsData;

    if (!hasDrawn && !hasImported) {
        showToast('无边框', 'warning');
        return;
    }

    if (!confirm('确认清除？')) {
        return;
    }

    // 终止当前正在进行的绘制操作
    if (appState.currentDrawer) {
        try { appState.currentDrawer.disable(); } catch (err) {}
        appState.currentDrawer = null;
    }

    // 清空手动绘制多边形
    if (appState.drawLayerGroup) {
        appState.drawLayerGroup.clearLayers();
    }
    appState.lastPolygonCoords = null;
    appState.currentShapeLayer = null;

    // 清空导入的区域边界
    if (appState.importedBoundaryGroup) {
        appState.importedBoundaryGroup.clearLayers();
    }
    appState.importedRegionsData = null;
    appState.activeRegionIndex = -1;

    const card = document.getElementById('importedRegionsCard');
    if (card) card.style.display = 'none';
    const list = document.getElementById('importedRegionsList');
    if (list) list.innerHTML = '';

    // 若当前仍处于多边形圈选模式，重新进入绘制就绪状态
    if (appState.selectMode === 'polygon') {
        startDrawPolygon();
    }

    showToast('已清除', 'success');
};

// 清空已导入的区域
window.clearImportedRegions = function() {
    if (!confirm('确认清空？')) {
        return;
    }
    if (appState.importedBoundaryGroup) {
        appState.importedBoundaryGroup.clearLayers();
    }
    appState.importedRegionsData = null;
    appState.activeRegionIndex = -1;
    const card = document.getElementById('importedRegionsCard');
    if (card) card.style.display = 'none';
    const list = document.getElementById('importedRegionsList');
    if (list) list.innerHTML = '';
    showToast('已清空', 'info');
};

// 初始化边界拖拽与输入监听事件
function initBoundaryImportEvents() {
    const dropZone = document.getElementById('dropZoneBoundary');
    if (dropZone) {
        ['dragenter', 'dragover'].forEach(name => {
            dropZone.addEventListener(name, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach(name => {
            dropZone.addEventListener(name, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove('dragover');
            });
        });

        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer ? e.dataTransfer.files : null;
            if (files && files.length > 0) {
                const input = document.getElementById('inputBoundaryFile');
                if (input) {
                    input.files = files;
                    handleBoundaryFileSelect(input);
                }
            }
        });
    }

    // 全局支持将 .txt 或 .json 文件直接拖入页面窗口导入
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => {
        const files = e.dataTransfer ? e.dataTransfer.files : null;
        if (files && files.length > 0) {
            const f = files[0];
            if (f.name.endsWith('.txt') || f.name.endsWith('.json') || f.name.endsWith('.geojson')) {
                e.preventDefault();
                openImportBoundaryModal();
                const input = document.getElementById('inputBoundaryFile');
                if (input) {
                    input.files = files;
                    handleBoundaryFileSelect(input);
                }
            }
        }
    });
}

