/**
 * Wmap - 工程文件 (.wyp) 生命周期管理与智能无模板工参导入
 */

const WmapProject = (function() {
    'use strict';

    let currentProject = {
        meta: {
            name: "未命名网优工程",
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
            sector_radius_mode: "band_adaptive",
            color_mode: "rat",
            show_labels: true,
            show_cell_sectors: true
        },
        layers: {
            param_cells: [],
            annotations: [],
            emergency_selection: {}
        }
    };

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
            nameEl.innerText = currentProject.meta.name || "未命名工程";
        }
        const badge = document.getElementById('projectSavedBadge');
        if (badge) {
            badge.style.display = isModified ? 'inline-block' : 'none';
        }
    }

    /**
     * 新建工程
     */
    async function newProject() {
        if (isModified && !confirm("当前工程有未保存的修改，确认新建工程吗？")) {
            return;
        }
        try {
            const resp = await fetch('/api/wmap/project/new');
            const data = await resp.json();
            setProject(data);
            if (window.appState && window.appState.cellLayerGroup) {
                window.appState.cellLayerGroup.clearLayers();
                window.appState.allCells = [];
                window.appState.selectedCells = [];
            }
            if (typeof showToast === 'function') {
                showToast('已新建空白网优工程', 'success');
            }
        } catch (e) {
            console.error('新建工程失败:', e);
        }
    }

    let selectedSaveFileHandle = null;

    /**
     * 打开“另存为 / 保存工程”弹窗
     */
    function openSaveAsModal() {
        const modal = document.getElementById('modalSaveProject');
        if (!modal) return;

        const nameInput = document.getElementById('inputSaveProjectName');
        const pathInput = document.getElementById('inputSaveProjectPath');
        const cellCountEl = document.getElementById('saveProjectCellCount');
        const coordSysEl = document.getElementById('saveProjectCoordSys');
        const zoomEl = document.getElementById('saveProjectZoom');

        const baseName = (currentProject.meta.name || "未命名网优工程").replace(/\.wyp$/i, '');
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
        const baseName = (nameInput?.value.trim() || currentProject.meta.name || "网优工程").replace(/\.wyp$/i, '');
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
     * 执行保存工程
     */
    async function executeSaveProject() {
        const nameInput = document.getElementById('inputSaveProjectName');
        const pathInput = document.getElementById('inputSaveProjectPath');
        let projName = nameInput ? nameInput.value.trim() : "";
        if (!projName) projName = currentProject.meta.name || "网优工程";
        projName = projName.replace(/\.wyp$/i, '');

        currentProject.meta.name = projName;
        currentProject.meta.updated_at = new Date().toLocaleString();

        const customPath = pathInput ? pathInput.value.trim() : "";
        const btnConfirm = document.getElementById('btnConfirmSaveProject');
        const origBtnText = btnConfirm ? btnConfirm.innerText : '确定保存';
        if (btnConfirm) {
            btnConfirm.disabled = true;
            btnConfirm.innerText = '正在保存…';
        }

        try {
            // 同步当前最新视图与图层数据
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

            const reqBody = {
                ...currentProject,
                custom_save_path: (customPath && (customPath.includes('/') || customPath.includes('\\')) && !customPath.startsWith('[')) ? customPath : ''
            };

            const resp = await fetch('/api/wmap/project/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqBody)
            });

            if (!resp.ok) {
                throw new Error(await resp.text());
            }

            const blob = await resp.blob();

            // 若用户通过原生对话框指定了句柄，直接写入该物理文件
            if (selectedSaveFileHandle) {
                try {
                    const writable = await selectedSaveFileHandle.createWritable();
                    await writable.write(blob);
                    await writable.close();
                } catch (fsErr) {
                    console.warn('句柄写入失败，回退到下载:', fsErr);
                    downloadBlob(blob, `${projName}.wyp`);
                }
            } else if (!reqBody.custom_save_path) {
                downloadBlob(blob, `${projName}.wyp`);
            }

            isModified = false;
            updateProjectUI();
            loadRecentProjects();
            closeDarkModal('modalSaveProject');

            const savedDisplay = selectedSaveFileHandle ? selectedSaveFileHandle.name : (customPath || `${projName}.wyp`);
            if (typeof showToast === 'function') {
                showToast(`工程文件已成功保存: ${savedDisplay}`, 'success');
            }
        } catch (e) {
            console.error('保存工程失败:', e);
            if (typeof showToast === 'function') {
                showToast(`保存工程失败: ${e.message}`, 'error');
            }
        } finally {
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.innerText = origBtnText;
            }
            selectedSaveFileHandle = null;
        }
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
     * 保存/导出工程为 .wyp (弹窗选择名称与路径)
     */
    function saveProject() {
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

        // 还原地图视窗
        if (res.project.view_state && window.appState && window.appState.map) {
            const vs = res.project.view_state;
            if (vs.center && vs.zoom) {
                window.appState.map.setView([vs.center[1], vs.center[0]], vs.zoom);
            }
        }

        // 还原工参扇区渲染
        const cells = res.project.layers?.param_cells || [];
        if (cells.length > 0 && typeof window.renderCellSectors === 'function') {
            window.appState.allCells = cells;
            window.renderCellSectors(cells);
        }

        if (typeof showToast === 'function') {
            showToast(`工程恢复成功: 加载了 ${cells.length} 个小区`, 'success');
        }
    }

    /**
     * 导入/打开本地 .wyp 工程
     */
    async function importProjectFile(file) {
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);

        try {
            if (typeof showToast === 'function') showToast('正在解析工程文件...', 'info');
            const resp = await fetch('/api/wmap/project/import', {
                method: 'POST',
                body: formData
            });
            const res = await resp.json();
            restoreProject(res);
        } catch (e) {
            console.error('打开工程失败:', e);
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
            if (typeof showToast === 'function') showToast('正在打开工程...', 'info');
            const resp = await fetch(`/api/wmap/project/recent/${projectId}/open`, { method: 'POST' });
            const res = await resp.json();
            if (!resp.ok) throw new Error(res.detail || '打开工程失败');
            restoreProject(res);
        } catch (e) {
            console.error('打开最近工程失败:', e);
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

    // 快捷键监听 (Ctrl+S / Ctrl+Shift+S)
    window.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
            e.preventDefault();
            openSaveAsModal();
        }
    });

    return {
        getProject,
        setProject,
        newProject,
        saveProject,
        openSaveAsModal,
        browseSavePath,
        executeSaveProject,
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
