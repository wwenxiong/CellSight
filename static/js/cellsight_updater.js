/* eslint-disable no-unused-vars */
/**
 * CellSight 在线自动更新交互模块
 */
(function () {
    let _pollTimer = null;
    let _hasAutoPrompted = false;
    let _lastState = null;

    function _el(id) {
        return document.getElementById(id);
    }

    function _formatBytes(bytes) {
        if (!bytes || bytes <= 0) return '';
        const mb = bytes / (1024 * 1024);
        return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
    }

    function _stopPolling() {
        if (_pollTimer) {
            clearInterval(_pollTimer);
            _pollTimer = null;
        }
    }

    function _startPolling() {
        if (_pollTimer) return;
        _pollTimer = setInterval(fetchUpdateStatus, 450);
    }

    function renderState(state) {
        if (!state) return;
        _lastState = state;

        const verBadge = _el('aboutVersionBadge');
        if (verBadge && state.current_version) {
            verBadge.textContent = `v${state.current_version}`;
        }

        const aboutHint = _el('aboutUpdateStatus');
        const checkBtn = _el('btnCheckUpdate');
        if (checkBtn) {
            checkBtn.disabled = state.status === 'checking' || state.status === 'downloading';
            checkBtn.textContent = state.status === 'checking' ? '检查中…' : '检查更新';
        }
        if (aboutHint) {
            if (state.status === 'available' || state.status === 'downloading' || state.status === 'ready') {
                aboutHint.textContent = `发现新版本 v${state.latest_version}`;
                aboutHint.className = 'about-update-status has-update';
            } else if (state.status === 'up_to_date') {
                aboutHint.textContent = '已是最新版本';
                aboutHint.className = 'about-update-status';
            } else if (state.status === 'error') {
                aboutHint.textContent = state.error || '检查失败';
                aboutHint.className = 'about-update-status is-error';
            } else {
                aboutHint.textContent = '';
            }
        }

        // 顶部栏更新提示胶囊：仅在有可用更新/下载中/就绪时显示
        const headerBtn = _el('btnHeaderUpdateBadge');
        if (headerBtn) {
            const showHeaderBadge = ['available', 'downloading', 'ready'].includes(state.status);
            headerBtn.classList.toggle('hidden', !showHeaderBadge);
            if (state.status === 'downloading') {
                headerBtn.textContent = `更新中 ${state.progress || 0}%`;
            } else if (state.status === 'ready') {
                headerBtn.textContent = `重启更新 v${state.latest_version}`;
            } else if (state.latest_version) {
                headerBtn.textContent = `新版 v${state.latest_version}`;
            }
        }

        // 更新弹窗内容
        const titleEl = _el('updateModalTitle');
        const verLineEl = _el('updateModalVersionLine');
        const notesEl = _el('updateModalChangelog');
        const progWrap = _el('updateProgressWrap');
        const progFill = _el('updateProgressFill');
        const progText = _el('updateProgressText');
        const errEl = _el('updateModalError');
        const actionBtn = _el('btnUpdatePrimaryAction');
        const laterBtn = _el('btnUpdateLater');
        const closeXBtn = _el('btnUpdateCloseX');

        if (titleEl) {
            titleEl.textContent = state.status === 'ready' ? '新版本已准备就绪' : `发现新版本 v${state.latest_version || ''}`;
        }
        if (verLineEl) {
            const sizeStr = _formatBytes(state.size);
            verLineEl.textContent = `当前 v${state.current_version || '1.0.0'} → 最新 v${state.latest_version || ''}${sizeStr ? ` · ${sizeStr}` : ''}`;
        }
        if (notesEl) {
            const items = Array.isArray(state.changelog) ? state.changelog : [];
            notesEl.innerHTML = items.length
                ? items.map(line => `<li>${String(line).replace(/</g, '&lt;')}</li>`).join('')
                : '<li>包含功能优化与问题修复</li>';
        }
        if (errEl) {
            const hasErr = state.status === 'error' && state.error;
            errEl.textContent = hasErr ? state.error : '';
            errEl.classList.toggle('hidden', !hasErr);
        }
        if (progWrap && progFill && progText) {
            const showProg = state.status === 'downloading' || state.status === 'ready' || state.status === 'installing';
            progWrap.classList.toggle('hidden', !showProg);
            const pct = Math.max(0, Math.min(100, Number(state.progress || 0)));
            progFill.style.width = `${pct}%`;
            if (state.status === 'installing') {
                progText.textContent = '正在启动安装程序…';
            } else if (state.status === 'ready') {
                progText.textContent = '下载完成，校验通过 (100%)';
            } else {
                progText.textContent = `正在下载安装包… ${pct}%`;
            }
        }
        if (actionBtn) {
            actionBtn.disabled = state.status === 'downloading' || state.status === 'installing';
            if (state.status === 'ready') {
                actionBtn.textContent = '立即安装并重启';
            } else if (state.status === 'downloading') {
                actionBtn.textContent = `下载中 ${state.progress || 0}%`;
            } else if (state.status === 'installing') {
                actionBtn.textContent = '正在重启安装…';
            } else {
                actionBtn.textContent = '立即更新';
            }
        }
        if (laterBtn) {
            laterBtn.classList.toggle('hidden', Boolean(state.force_update) || state.status === 'installing');
        }
        if (closeXBtn) {
            closeXBtn.classList.toggle('hidden', Boolean(state.force_update) || state.status === 'installing');
        }

        // 轮询控制
        if (state.status === 'downloading' || state.status === 'checking' || state.status === 'installing') {
            _startPolling();
        } else {
            _stopPolling();
        }

        // 首次发现新版时自动弹出提示（策略 A）
        if (state.status === 'available' && !_hasAutoPrompted) {
            _hasAutoPrompted = true;
            openUpdateModal();
        }
    }

    async function fetchUpdateStatus() {
        try {
            const res = await fetch('/api/update/status');
            if (!res.ok) return null;
            const data = await res.json();
            renderState(data);
            return data;
        } catch (e) {
            return null;
        }
    }

    async function checkUpdateManual() {
        renderState(Object.assign({}, _lastState || {}, { status: 'checking', error: '' }));
        try {
            const res = await fetch('/api/update/check', { method: 'POST' });
            if (!res.ok) throw new Error('请求失败');
            const data = await res.json();
            renderState(data);
            if (data.status === 'available' || data.status === 'ready') {
                if (typeof window.hideAboutDropdown === 'function') window.hideAboutDropdown();
                openUpdateModal();
            } else if (data.status === 'up_to_date' && typeof window.showToast === 'function') {
                window.showToast(`当前已是最新版本 v${data.current_version}`);
            } else if (data.status === 'error' && typeof window.showToast === 'function') {
                window.showToast(data.error || '检查更新失败');
            } else if (!data.update_configured && typeof window.showToast === 'function') {
                window.showToast('尚未配置更新服务器地址 (update_url)');
            }
        } catch (e) {
            renderState(Object.assign({}, _lastState || {}, { status: 'error', error: '检查更新失败' }));
        }
    }

    async function handlePrimaryAction() {
        const st = _lastState ? _lastState.status : '';
        if (st === 'ready') {
            try {
                const res = await fetch('/api/update/install', { method: 'POST' });
                if (res.ok) renderState(await res.json());
            } catch (e) { /* 忽略退出断开 */ }
            return;
        }
        if (st === 'available' || st === 'error') {
            try {
                const res = await fetch('/api/update/download', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    renderState(data);
                    _startPolling();
                }
            } catch (e) {
                renderState(Object.assign({}, _lastState || {}, { status: 'error', error: '启动下载失败' }));
            }
        }
    }

    function openUpdateModal() {
        const modal = _el('modalAppUpdate');
        if (modal) {
            modal.classList.remove('hidden');
            modal.style.display = 'flex';
        }
    }

    function closeUpdateModal() {
        if (_lastState && (_lastState.force_update || _lastState.status === 'installing')) return;
        const modal = _el('modalAppUpdate');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.add('hidden');
        }
    }

    window.CellSightUpdater = {
        fetchStatus: fetchUpdateStatus,
        checkManual: checkUpdateManual,
        handlePrimaryAction: handlePrimaryAction,
        openModal: openUpdateModal,
        closeModal: closeUpdateModal,
    };

    document.addEventListener('DOMContentLoaded', () => {
        fetchUpdateStatus();
        // 延迟再拉一次，承接 launcher 启动后异步 check_update 的结果
        setTimeout(fetchUpdateStatus, 2500);
    });
})();
