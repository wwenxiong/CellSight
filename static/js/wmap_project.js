/**
 * Wmap - 工程文件 (.wyp) 生命周期管理与智能无模板工参导入
 */

const WmapProject = (function() {
    'use strict';

    let currentProject = null;

    let isModified = false;
    let pendingImportFile = null;
    let currentAnalysisResult = null;

    function getProject() {
        return currentProject;
    }

    function setProject(proj) {
        currentProject = proj;
        isModified = false;
        updateProjectUI();
    }

    function updateProjectUI() {
        const nameEl = document.getElementById('projectTitleText');
        if (nameEl) {
            nameEl.innerText = (currentProject && currentProject.meta && currentProject.meta.name) ? `${currentProject.meta.name}.wyp` : "未打开工程";
        }
        const badge = document.getElementById('projectSavedBadge');
        if (badge) {
            badge.style.display = isModified ? 'inline-block' : 'none';
        }
    }

    let newProjectSaveFileHandle = null;

    /**
     * 打开“新建工程”弹窗，提醒用户设置工程名称与保存路径
     */
    function openNewProjectModal() {
        if (isModified && !confirm("当前工程有未保存的修改，确认新建工程吗？")) {
            return;
        }

        const modal = document.getElementById('modalNewProject');
        if (!modal) return;

        const nameInput = document.getElementById('inputNewProjectName');
        const pathInput = document.getElementById('inputNewProjectPath');

        // 生成默认工程名称（如：网优工程_20261120）
        const now = new Date();
        const dStr = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
        const defaultName = `网优工程_${dStr}`;

        if (nameInput) nameInput.value = defaultName;
        if (pathInput) pathInput.value = "";
        newProjectSaveFileHandle = null;

        modal.style.display = 'flex';
        setTimeout(() => {
            if (nameInput) {
                nameInput.focus();
                nameInput.select();
            }
        }, 100);
    }

    /**
     * 新建工程：浏览选择存储路径
     */
    async function browseNewProjectPath() {
        const nameInput = document.getElementById('inputNewProjectName');
        const pathInput = document.getElementById('inputNewProjectPath');
        const baseName = (nameInput?.value.trim() || "新建网优工程").replace(/\.wyp$/i, '');
        const suggestedName = `${baseName}.wyp`;

        // 1. 优先尝试现代浏览器原生 File System Access API
        if (window.showSaveFilePicker) {
            try {
                const handle = await window.showSaveFilePicker({
                    suggestedName: suggestedName,
                    types: [{
                        description: 'Wmap 网优工程文件 (*.wyp)',
                        accept: { 'application/x-wyp': ['.wyp'] }
                    }]
                });
                newProjectSaveFileHandle = handle;
                if (pathInput) pathInput.value = handle.name;
                if (nameInput) nameInput.value = handle.name.replace(/\.wyp$/i, '');
                return;
            } catch (err) {
                if (err.name === 'AbortError') return;
                console.warn('showSaveFilePicker 取消或不支持:', err);
            }
        }

        // 2. 回退调用后端桌面原生另存对话框
        try {
            const resp = await fetch(`/api/wmap/project/pick_save_path?suggested_name=${encodeURIComponent(suggestedName)}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.path) {
                    if (pathInput) pathInput.value = data.path;
                    newProjectSaveFileHandle = null;
                    return;
                }
            }
        } catch (_) {}

        if (pathInput && !pathInput.value) {
            pathInput.value = `[默认下载目录] / ${suggestedName}`;
        }
    }

    /**
     * 确认创建新建工程
     */
    async function executeCreateNewProject() {
        const nameInput = document.getElementById('inputNewProjectName');
        const pathInput = document.getElementById('inputNewProjectPath');
        const coordSysSelect = document.getElementById('selectNewProjectCoordSys');
        const tileSelect = document.getElementById('selectNewProjectTile');

        let projName = nameInput ? nameInput.value.trim() : "";
        if (!projName) projName = "未命名网优工程";
        projName = projName.replace(/\.wyp$/i, '');

        const customPath = pathInput ? pathInput.value.trim() : "";

        try {
            const resp = await fetch(`/api/wmap/project/new?name=${encodeURIComponent(projName)}`);
            if (!resp.ok) throw new Error(await resp.text());
            const data = await resp.json();

            // 继承设定的路径与文件句柄，绑定到当前工程对象以便后续直接原地保存
            const validCustomPath = (customPath && (customPath.includes('/') || customPath.includes('\\')) && !customPath.startsWith('[')) ? customPath : '';
            if (validCustomPath) {
                data.custom_save_path = validCustomPath;
                data._filePath = validCustomPath;
            }
            if (newProjectSaveFileHandle) {
                data._fileHandle = newProjectSaveFileHandle;
            }
            selectedSaveFileHandle = newProjectSaveFileHandle;
            newProjectSaveFileHandle = null;

            // 应用初始底图与坐标系
            if (coordSysSelect && window.switchCoordSys) {
                window.switchCoordSys(coordSysSelect.value);
            }
            if (tileSelect && window.switchTileLayer) {
                window.switchTileLayer(tileSelect.value);
            }

            setProject(data);

            // 彻底清理当前工作区所有图层与工参数据
            if (typeof window.clearWorkspace === 'function') {
                window.clearWorkspace();
            } else if (window.appState) {
                if (window.appState.cellLayerGroup) window.appState.cellLayerGroup.clearLayers();
                if (window.appState.labelLayerGroup) window.appState.labelLayerGroup.clearLayers();
                window.appState.allCells = [];
                window.appState.selectedCells = [];
                window.appState.layerFilters = {};
                window.appState.layerColorFields = {};
                window.appState.layerLabelFields = {};
                window.appState.layerLabelLengths = {};
                window.appState.layerLabelVisibility = {};
            }
            if (typeof window.saveAppConfig === 'function') {
                window.saveAppConfig({ layerFilters: {}, layerColorFields: {}, layerCustomColors: {}, layerLabelFields: {}, layerLabelLengths: {}, layerLabelVisibility: {} });
            }

            closeDarkModal('modalNewProject');

            if (typeof showToast === 'function') {
                showToast(`已创建: ${projName}.wyp`, 'success');
            }
        } catch (e) {
            console.error('新建工程失败:', e);
            if (typeof showToast === 'function') {
                showToast(`创建工程失败: ${e.message}`, 'error');
            }
        }
    }

    /**
     * 新建工程入口
     */
    function newProject() {
        openNewProjectModal();
    }

    let selectedSaveFileHandle = null;

    /**
     * 打开“另存为 / 保存工程”弹窗
     */
    function openSaveAsModal() {
        if (!currentProject) {
            // 若尚未打开工程，保存时自动初始化工程对象
            currentProject = {
                meta: {
                    name: "网优工程",
                    version: "Wmap-1.0",
                    created_at: new Date().toLocaleString(),
                    updated_at: new Date().toLocaleString()
                },
                view_state: {
                    center: [113.3245, 23.1234],
                    zoom: 13,
                    tile_type: "amap"
                },
                style_config: {
                    sector_beamwidth: 65,
                    sector_radius_scale: 1.0,
                    sector_radius_mode: "band_adaptive",
                    color_mode: "rat",
                    show_labels: true,
                    show_cell_sectors: true,
                    layer_label_fields: {},
                    layer_label_lengths: {},
                    layer_label_visibility: {},
                    field_render: { layerFilters: {}, layerColorFields: {}, layerCustomColors: {}, layerLabelFields: {}, layerLabelLengths: {}, layerLabelVisibility: {} }
                },
                layers: {
                    param_cells: [],
                    annotations: [],
                    emergency_selection: {}
                }
            };
        }
        const modal = document.getElementById('modalSaveProject');
        if (!modal) return;

        const nameInput = document.getElementById('inputSaveProjectName');
        const pathInput = document.getElementById('inputSaveProjectPath');
        const cellCountEl = document.getElementById('saveProjectCellCount');
        const coordSysEl = document.getElementById('saveProjectCoordSys');
        const zoomEl = document.getElementById('saveProjectZoom');

        const baseName = ((currentProject.meta && currentProject.meta.name) || "网优工程").replace(/\.wyp$/i, '');
        if (nameInput) nameInput.value = baseName;
        if (pathInput) pathInput.value = "";
        selectedSaveFileHandle = null;

        const cellCount = (window.appState && window.appState.allCells ? window.appState.allCells.length : 0);
        if (cellCountEl) cellCountEl.innerText = `${cellCount.toLocaleString('en-US')} 个`;
        if (coordSysEl) coordSysEl.innerText = (window.appState && window.appState.coordSys === 'wgs84') ? 'WGS-84' : 'GCJ-02';
        if (zoomEl) zoomEl.innerText = `${(window.appState && window.appState.map) ? window.appState.map.getZoom() : 13} 级`;

        modal.style.display = 'flex';
        setTimeout(() => {
            if (nameInput) {
                nameInput.focus();
                nameInput.select();
            }
        }, 100);
    }

    /**
     * 浏览并挑选本地另存路径
     */
    async function browseSavePath() {
        const nameInput = document.getElementById('inputSaveProjectName');
        const pathInput = document.getElementById('inputSaveProjectPath');
        const baseName = (nameInput?.value.trim() || (currentProject && currentProject.meta && currentProject.meta.name) || "网优工程").replace(/\.wyp$/i, '');
        const suggestedName = `${baseName}.wyp`;

        // 1. 优先尝试现代浏览器原生 File System Access API
        if (window.showSaveFilePicker) {
            try {
                const handle = await window.showSaveFilePicker({
                    suggestedName: suggestedName,
                    types: [{
                        description: 'Wmap 网优工程文件 (*.wyp)',
                        accept: { 'application/x-wyp': ['.wyp'] }
                    }]
                });
                selectedSaveFileHandle = handle;
                if (pathInput) pathInput.value = handle.name;
                if (nameInput) nameInput.value = handle.name.replace(/\.wyp$/i, '');
                return;
            } catch (err) {
                if (err.name === 'AbortError') return;
                console.warn('showSaveFilePicker 取消或不支持:', err);
            }
        }

        // 2. 回退调用后端桌面原生另存对话框
        try {
            const resp = await fetch(`/api/wmap/project/pick_save_path?suggested_name=${encodeURIComponent(suggestedName)}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data.path) {
                    if (pathInput) pathInput.value = data.path;
                    selectedSaveFileHandle = null;
                    return;
                }
            }
        } catch (_) {}

        if (pathInput && !pathInput.value) {
            pathInput.value = `[默认下载目录] / ${suggestedName}`;
        }
    }

    /**
     * 同步当前视图、图层与样式状态，并执行 .wyp 打包与写入（进度统一展示在右下角状态栏）
     */
    async function performProjectSave(handle, filePath, options = {}) {
        const projName = (currentProject.meta && currentProject.meta.name) || "网优工程";
        const isSaveAs = !!options.isSaveAs;

        try {
            if (typeof window.setTaskStatus === 'function') {
                window.setTaskStatus(true, '保存中...', 20);
            }

            if (window.appState && window.appState.map) {
                const c = window.appState.map.getCenter();
                currentProject.view_state.center = [c.lng, c.lat];
                currentProject.view_state.zoom = window.appState.map.getZoom();
                currentProject.view_state.tile_type = window.appState.currentTileType || "amap";
            }
            if (window.appState && window.appState.allCells) {
                currentProject.layers.param_cells = window.appState.allCells;
            }
            if (window.appState && window.appState.selectedCells) {
                currentProject.layers.emergency_selection.selected_cells = window.appState.selectedCells;
                currentProject.layers.emergency_selection.diagnosed_cells = window.appState.diagnosedCells || [];
            }
            if (window.appState) {
                const colorMode = window.appState.sectorColorMode || 'none';
                currentProject.style_config.sector_beamwidth = window.appState.sectorBeamwidth || 65;
                currentProject.style_config.sector_radius_scale = (typeof window.appState.sectorRadiusScale === 'number' && window.appState.sectorRadiusScale > 0) ? window.appState.sectorRadiusScale : 1.0;
                currentProject.style_config.sector_color_mode = colorMode;
                currentProject.style_config.color_mode = colorMode;
                currentProject.style_config.show_labels = (window.appState.layerVisibility && window.appState.layerVisibility['labels'] === true);
                currentProject.style_config.layer_visibility = { ...(window.appState.layerVisibility || {}) };
                currentProject.style_config.layer_label_fields = { ...(window.appState.layerLabelFields || {}) };
                currentProject.style_config.layer_label_lengths = { ...(window.appState.layerLabelLengths || {}) };
                currentProject.style_config.layer_label_visibility = { ...(window.appState.layerLabelVisibility || {}) };
                currentProject.style_config.layer_colors = { ...(window.appState.layerColors || {}) };
                currentProject.style_config.field_render = {
                    layerFilters: window.appState.layerFilters || {},
                    layerColorFields: window.appState.layerColorFields || {},
                    layerCustomColors: window.appState.layerCustomColors || {},
                    layerLabelFields: window.appState.layerLabelFields || {},
                    layerLabelLengths: window.appState.layerLabelLengths || {},
                    layerLabelVisibility: window.appState.layerLabelVisibility || {},
                    layerColors: window.appState.layerColors || {}
                };
            }
            currentProject.meta.updated_at = new Date().toLocaleString();

            if (typeof window.setTaskStatus === 'function') {
                window.setTaskStatus(true, '打包中...', 50);
            }

            const validDiskPath = (filePath && (filePath.includes('/') || filePath.includes('\\')) && !filePath.startsWith('[')) ? filePath : '';
            const reqBody = {
                ...currentProject,
                custom_save_path: validDiskPath
            };

            const resp = await fetch('/api/wmap/project/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody)
            });

            if (!resp.ok) {
                throw new Error(await resp.text());
            }

            if (typeof window.setTaskStatus === 'function') {
                window.setTaskStatus(true, '写入中...', 85);
            }
            const blob = await resp.blob();

            if (handle) {
                try {
                    const writable = await handle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                } catch (fsErr) {
                    console.warn('句柄写入失败，回退到下载:', fsErr);
                    downloadBlob(blob, `${projName}.wyp`);
                }
            } else if (!validDiskPath && (isSaveAs || !currentProject._isRecent)) {
                downloadBlob(blob, `${projName}.wyp`);
            }

            if (handle) {
                currentProject._fileHandle = handle;
            }
            if (validDiskPath) {
                currentProject._filePath = validDiskPath;
            }

            isModified = false;
            updateProjectUI();
            loadRecentProjects();

            const savedDisplay = handle ? handle.name : (validDiskPath || `${projName}.wyp`);
            if (typeof window.setTaskStatus === 'function') {
                window.setTaskStatus(false, '已保存', 100);
            }
            if (typeof showToast === 'function') {
                showToast(`已保存: ${savedDisplay}`, 'success');
            }
        } catch (e) {
            console.error('保存工程失败:', e);
            if (typeof window.setTaskStatus === 'function') {
                window.setTaskStatus(false, `保存失败: ${e.message}`);
            }
            if (typeof showToast === 'function') {
                showToast(`保存工程失败: ${e.message}`, 'error');
            }
        }
    }

    /**
     * 执行另存为弹窗中的保存操作：立即关闭全屏弹窗，进度交由右下角状态栏展示
     */
    async function executeSaveProject() {
        if (!currentProject) {
            openSaveAsModal();
            return;
        }
        const nameInput = document.getElementById('inputSaveProjectName');
        const pathInput = document.getElementById('inputSaveProjectPath');
        let projName = nameInput ? nameInput.value.trim() : "";
        if (!projName) projName = currentProject.meta.name || "网优工程";
        projName = projName.replace(/\.wyp$/i, '');

        currentProject.meta.name = projName;
        const customPath = pathInput ? pathInput.value.trim() : "";
        const handle = selectedSaveFileHandle;
        selectedSaveFileHandle = null;

        // 立即关闭弹窗，避免保存耗时期间全屏遮罩占满屏幕
        closeDarkModal('modalSaveProject');
        await performProjectSave(handle, customPath, { isSaveAs: true });
    }

    function downloadBlob(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }

    /**
     * 保存当前工程文件：直接保存到当前工程，不再跳转另存弹窗（仅未打开任何工程时打开另存为）
     */
    async function saveProject() {
        if (!currentProject) {
            openSaveAsModal();
            return;
        }

        const handle = currentProject._fileHandle || null;
        const filePath = currentProject._filePath || currentProject.custom_save_path || '';
        await performProjectSave(handle, filePath, { isSaveAs: false });
    }

    /**
     * 打开“工程另存为”弹窗
     */
    function saveProjectAs() {
        openSaveAsModal();
    }

    /**
     * 恢复工程到界面（导入文件 / 打开最近工程共用）
     */
    function restoreProject(res) {
        if (!res || !res.success) {
            throw new Error((res && res.detail) || "解析工程文件失败");
        }
        setProject(res.project);

        // 还原按字段筛选 / 着色状态、图层显隐及扇区尺寸比例（必须在渲染之前；工程里没有则清空）
        const sc = res.project.style_config;
        const fr = sc && sc.field_render;
        if (window.appState) {
            if (sc && typeof sc.sector_radius_scale === 'number') {
                if (typeof window.updateSectorRadiusScale === 'function') {
                    window.updateSectorRadiusScale(Math.round(sc.sector_radius_scale * 100), true);
                } else {
                    window.appState.sectorRadiusScale = sc.sector_radius_scale;
                }
            }
            if (sc && typeof sc.sector_beamwidth === 'number') {
                if (typeof window.updateBeamwidth === 'function') {
                    window.updateBeamwidth(sc.sector_beamwidth, true);
                } else {
                    window.appState.sectorBeamwidth = sc.sector_beamwidth;
                }
            }
            // 还原扇区着色方案 (关闭 / 频段 / PCI模3)
            const colorMode = (sc && (sc.sector_color_mode || sc.color_mode)) || 'none';
            if (typeof window.setSectorColorMode === 'function') {
                window.setSectorColorMode(colorMode, true);
            } else {
                window.appState.sectorColorMode = colorMode;
            }

            // 还原图层显隐与标注开关
            if (sc && sc.layer_visibility && typeof sc.layer_visibility === 'object') {
                window.appState.layerVisibility = { ...sc.layer_visibility };
            }
            if (sc && typeof sc.show_labels === 'boolean') {
                if (!window.appState.layerVisibility) window.appState.layerVisibility = {};
                window.appState.layerVisibility['labels'] = sc.show_labels;
            }

            // 同步侧边栏控制项勾选状态
            if (window.appState.layerVisibility) {
                const chkLabels = document.getElementById('chkLayerLabels');
                if (chkLabels) chkLabels.checked = (window.appState.layerVisibility['labels'] === true);
                const chkEmerg = document.getElementById('chkLayerEmergency');
                if (chkEmerg) {
                    chkEmerg.checked = (window.appState.layerVisibility['emergency'] !== false);
                    const lbl = document.getElementById('lblLayerEmergency');
                    if (lbl) lbl.style.color = chkEmerg.checked ? '#1d1d1f' : '#86868b';
                }
                const chkPci = document.getElementById('chkLayerPciConflict');
                if (chkPci) chkPci.checked = (window.appState.layerVisibility['pci'] !== false);
                const chkImp = document.getElementById('chkLayerImported');
                if (chkImp) chkImp.checked = (window.appState.layerVisibility['imported'] !== false);
            }

            window.appState.layerFilters = (fr && fr.layerFilters) || {};
            window.appState.layerColorFields = (fr && fr.layerColorFields) || {};
            window.appState.layerCustomColors = (fr && fr.layerCustomColors) || {};
            window.appState.layerLabelFields = (sc && sc.layer_label_fields) || (fr && fr.layerLabelFields) || {};
            window.appState.layerLabelLengths = (sc && sc.layer_label_lengths) || (fr && fr.layerLabelLengths) || {};
            window.appState.layerLabelVisibility = (sc && sc.layer_label_visibility) || (fr && fr.layerLabelVisibility) || {};
            window.appState.layerColors = (sc && sc.layer_colors) || (fr && fr.layerColors) || {};
            if (typeof window.saveAppConfig === 'function') {
                window.saveAppConfig({
                    sectorRadiusScale: window.appState.sectorRadiusScale,
                    sectorBeamwidth: window.appState.sectorBeamwidth,
                    sectorColorMode: window.appState.sectorColorMode,
                    layerVisibility: window.appState.layerVisibility,
                    layerFilters: window.appState.layerFilters,
                    layerColorFields: window.appState.layerColorFields,
                    layerCustomColors: window.appState.layerCustomColors,
                    layerLabelFields: window.appState.layerLabelFields,
                    layerLabelLengths: window.appState.layerLabelLengths,
                    layerLabelVisibility: window.appState.layerLabelVisibility,
                    layerColors: window.appState.layerColors
                });
            }
        }

        // 还原底图类型与地图视窗
        if (res.project.view_state && window.appState) {
            const vs = res.project.view_state;
            if (vs.tile_type && typeof window.switchTileLayer === 'function' && window.appState.currentTileType !== vs.tile_type) {
                window.switchTileLayer(vs.tile_type);
            }
            if (vs.center && vs.zoom && window.appState.map) {
                window.appState.map.setView([vs.center[1], vs.center[0]], vs.zoom);
            }
        }

        // 还原工参扇区渲染（支持紧凑二维表 param_table 秒级还原，并兼容旧版 param_cells；先完成视窗首帧绘制）
        let cells = res.project.layers?.param_cells || [];
        const pt = res.project.layers?.param_table;
        if ((!cells || cells.length === 0) && pt && Array.isArray(pt.columns) && Array.isArray(pt.rows)) {
            const cols = pt.columns;
            const rows = pt.rows;
            const rLen = rows.length;
            const cLen = cols.length;
            cells = new Array(rLen);
            for (let i = 0; i < rLen; i++) {
                const row = rows[i];
                const obj = {};
                for (let j = 0; j < cLen; j++) {
                    obj[cols[j]] = row[j];
                }
                cells[i] = obj;
            }
            if (res.project.layers) {
                res.project.layers.param_cells = cells;
                delete res.project.layers.param_table;
            }
        }
        if (cells.length > 0) {
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(true, '渲染扇区...', 85);
            if (window.appState) {
                window.appState.allCells = cells;
            }
            const _finishRender = () => {
                if (typeof window.renderCellSectors === 'function') {
                    window.renderCellSectors(cells);
                }
                if (typeof window.setTaskStatus === 'function') window.setTaskStatus(false, '就绪', 100);
                if (typeof showToast === 'function') {
                    showToast(`已加载 ${cells.length} 个小区`, 'success');
                }
            };
            if (typeof window.requestAnimationFrame === 'function') {
                window.requestAnimationFrame(() => setTimeout(_finishRender, 0));
            } else {
                setTimeout(_finishRender, 0);
            }
        } else {
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(false, '就绪', 100);
            if (typeof showToast === 'function') {
                showToast(`已加载 0 个小区`, 'success');
            }
        }
    }

    /**
     * 通过原生文件选择器打开 .wyp 工程（优先获取可写句柄以便后续 Ctrl+S 直接原地覆写）
     */
    async function openProjectFilePicker() {
        if (window.showOpenFilePicker) {
            try {
                const [handle] = await window.showOpenFilePicker({
                    types: [{ description: 'Wmap 网优工程文件', accept: { 'application/octet-stream': ['.wyp'] } }],
                    multiple: false
                });
                if (handle) {
                    const file = await handle.getFile();
                    await importProjectFile(file, handle);
                    return;
                }
            } catch (err) {
                if (err && err.name === 'AbortError') return;
                console.warn('showOpenFilePicker 回退到普通文件选择:', err);
            }
        }
        const input = document.getElementById('inputWypFile');
        if (input) {
            input.value = '';
            input.click();
        }
    }

    /**
     * 导入/打开本地 .wyp 工程
     */
    async function importProjectFile(file, fileHandle = null) {
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);

        try {
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(true, '读取工程...', 25);
            if (typeof showToast === 'function') showToast('正在读取...', 'info');
            const resp = await fetch('/api/wmap/project/import', {
                method: 'POST',
                body: formData
            });
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(true, '解析工程...', 60);
            const res = await resp.json();
            if (res && res.project) {
                res.project._filePath = file.name;
                if (fileHandle) {
                    res.project._fileHandle = fileHandle;
                }
            }
            restoreProject(res);
        } catch (e) {
            console.error('打开工程失败:', e);
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(false, `打开失败: ${e.message}`);
            if (typeof showToast === 'function') {
                showToast(`打开工程失败: ${e.message}`, 'error');
            }
        }
    }

    /**
     * 打开服务端存档的最近工程（无需再选文件）
     */
    async function openRecentProject(projectId) {
        if (!projectId) return;
        try {
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(true, '加载工程...', 30);
            if (typeof showToast === 'function') showToast('正在打开...', 'info');
            const resp = await fetch(`/api/wmap/project/recent/${projectId}/open`, { method: 'POST' });
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(true, '解析工程...', 65);
            const res = await resp.json();
            if (!resp.ok) throw new Error(res.detail || '打开工程失败');
            if (res && res.project) {
                res.project._isRecent = true;
            }
            restoreProject(res);
        } catch (e) {
            console.error('打开最近工程失败:', e);
            if (typeof window.setTaskStatus === 'function') window.setTaskStatus(false, `打开失败: ${e.message}`);
            if (typeof showToast === 'function') {
                showToast(`打开工程失败: ${e.message}`, 'error');
            }
        }
    }

    /**
     * 加载最近工程列表并渲染到工程菜单
     */
    async function loadRecentProjects() {
        const container = document.getElementById('recentProjectsList');
        if (!container) return;
        try {
            const resp = await fetch('/api/wmap/project/recent');
            const data = await resp.json();
            const items = (data && data.projects) || [];
            if (items.length === 0) {
                container.innerHTML = '<div class="menu-empty-tip">暂无最近工程</div>';
                return;
            }
            container.innerHTML = items.map(p => {
                const safeName = String(p.name || '未命名工程').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const meta = `${p.updated_at || ''}${p.cell_count ? ` · ${p.cell_count} 小区` : ''}`;
                return `<button type="button" class="menu-recent-item" onclick="WmapProject.openRecentProject('${p.id}'); hideProjectMenu();">`
                    + `<span class="menu-recent-name">${safeName}</span>`
                    + `<span class="menu-recent-meta">${meta}</span></button>`;
            }).join('');
        } catch (e) {
            container.innerHTML = '<div class="menu-empty-tip">最近工程加载失败</div>';
        }
    }

    // 快捷键监听 (Ctrl+S 保存当前工程，Ctrl+Shift+S 另存为)
    window.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
            e.preventDefault();
            if (e.shiftKey) {
                openSaveAsModal();
            } else {
                saveProject();
            }
        }
    });

    return {
        getProject,
        setProject,
        newProject,
        openNewProjectModal,
        browseNewProjectPath,
        executeCreateNewProject,
        saveProject,
        saveProjectAs,
        openSaveAsModal,
        browseSavePath,
        executeSaveProject,
        openProjectFilePicker,
        importProjectFile,
        openRecentProject,
        loadRecentProjects,
        updateProjectUI
    };
})();

if (typeof window !== 'undefined') {
    window.WmapProject = WmapProject;
}

// 工程胶囊下拉菜单（新建 / 打开 / 保存 / 最近工程）
window.toggleProjectMenu = function(e) {
    if (e) e.stopPropagation();
    if (typeof window.hideTopDropdowns === 'function') {
        window.hideTopDropdowns('file');
    }
    const menu = document.getElementById('projectMenu');
    if (menu) {
        const willOpen = !menu.classList.contains('open');
        menu.classList.toggle('open');
        if (willOpen && window.WmapProject && typeof window.WmapProject.loadRecentProjects === 'function') {
            window.WmapProject.loadRecentProjects();
        }
    }
};
window.hideProjectMenu = function() {
    const menu = document.getElementById('projectMenu');
    if (menu) menu.classList.remove('open');
};
document.addEventListener('click', function(e) {
    const wrap = document.querySelector('.project-pill-wrap');
    if (wrap && !wrap.contains(e.target)) hideProjectMenu();
});
