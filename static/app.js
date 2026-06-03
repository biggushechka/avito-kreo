// State Management
let appState = {
    config: {},
    slots: [],
    references: [],
    isGeneratingAll: false,
    isUploadingAll: false,
    currentAdText: "",
    productName: "",
    parameters: ""
};

// DOM Elements
const elements = {
    // Status Bar
    statusGemini: document.getElementById('status-gemini'),
    statusYandex: document.getElementById('status-yandex'),
    btnOpenSettings: document.getElementById('btn-open-settings'),
    
    // Sidebar
    globalContext: document.getElementById('global-context'),
    visualStyle: document.getElementById('visual-style'),
    refUploadZone: document.getElementById('ref-upload-zone'),
    refFileInput: document.getElementById('ref-file-input'),
    refPreviews: document.getElementById('ref-previews-container'),
    localDirInput: document.getElementById('local-dir-input'),
    yandexDirInput: document.getElementById('yandex-dir-input'),
    btnSaveSidebar: document.getElementById('btn-save-sidebar-configs'),
    
    // Workspace
    adInput: document.getElementById('ad-input'),
    btnRunAnalysis: document.getElementById('btn-run-analysis'),
    workspaceEmpty: document.getElementById('workspace-empty'),
    generatorWorkspace: document.getElementById('generator-workspace'),
    adSummaryText: document.getElementById('ad-summary-text'),
    slotsContainer: document.getElementById('slots-container'),
    yandexDirInputWs: document.getElementById('yandex-dir-input-ws'),
    localDirInputWs: document.getElementById('local-dir-input-ws'),
    
    // Bulk actions
    btnGenerateAll: document.getElementById('btn-generate-all'),
    btnUploadAll: document.getElementById('btn-upload-all'),
    btnCopyAllLinks: document.getElementById('btn-copy-all-links'),
    activityStatusBar: document.getElementById('activity-status-bar'),
    activityStatusText: document.getElementById('activity-status-text'),
    activityProgressBarFill: document.getElementById('activity-progress-bar-fill'),
    
    // Modals
    settingsModal: document.getElementById('settings-modal'),
    geminiKeyInput: document.getElementById('gemini-key-input'),
    yandexTokenInput: document.getElementById('yandex-token-input'),
    btnSaveSettings: document.getElementById('btn-save-settings'),
    btnCancelSettings: document.getElementById('btn-cancel-settings'),
    btnCloseSettings: document.getElementById('btn-close-settings-modal'),
    
    // Image Viewer Modal
    imageViewerModal: document.getElementById('image-viewer-modal'),
    viewerTitle: document.getElementById('viewer-title'),
    viewerImg: document.getElementById('viewer-img'),
    viewerBannerText: document.getElementById('viewer-banner-text'),
    viewerPrompt: document.getElementById('viewer-prompt'),
    btnCloseViewer: document.getElementById('btn-close-viewer'),
    btnCloseViewerModal: document.getElementById('btn-close-viewer-modal'),
    
    // Excel Export Panel
    excelExportPanel: document.getElementById('excel-export-panel'),
    excelProductName: document.getElementById('excel-product-name'),
    excelParameters: document.getElementById('excel-parameters'),
    excelRowOutput: document.getElementById('excel-row-output'),
    btnCopyExcelRow: document.getElementById('btn-copy-excel-row'),
    
    // Project Import/Export
    btnExportProject: document.getElementById('btn-export-project'),
    btnImportProject: document.getElementById('btn-import-project'),
    projectFileInput: document.getElementById('project-file-input'),
    
    // Generation Delay Setting
    generationDelayInput: document.getElementById('generation-delay-input')
};

// Event Listeners
document.addEventListener('DOMContentLoaded', initializeApp);

function initializeApp() {
    loadConfig();
    setupEventListeners();
}

function setupEventListeners() {
    // Config modal controls
    elements.btnOpenSettings.addEventListener('click', () => openModal(elements.settingsModal));
    elements.btnCloseSettings.addEventListener('click', () => closeModal(elements.settingsModal));
    elements.btnCancelSettings.addEventListener('click', () => closeModal(elements.settingsModal));
    elements.btnSaveSettings.addEventListener('click', saveModalConfig);
    
    // Sidebar Save
    elements.btnSaveSidebar.addEventListener('click', saveSidebarConfig);
    
    // Drag & Drop visual references
    elements.refUploadZone.addEventListener('click', () => elements.refFileInput.click());
    elements.refFileInput.addEventListener('change', handleFileSelect);
    elements.refUploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.refUploadZone.style.borderColor = 'var(--accent-cyan)';
    });
    elements.refUploadZone.addEventListener('dragleave', () => {
        elements.refUploadZone.style.borderColor = 'var(--border-color)';
    });
    elements.refUploadZone.addEventListener('drop', handleFileDrop);

    // Generator logic triggers
    elements.btnRunAnalysis.addEventListener('click', runAdAnalysis);
    
    // Bulk Actions
    elements.btnGenerateAll.addEventListener('click', generateAllImages);
    elements.btnUploadAll.addEventListener('click', uploadAllToYandex);
    elements.btnCopyAllLinks.addEventListener('click', copyAllYandexLinks);
    
    // Fullscreen Viewer Close
    elements.btnCloseViewer.addEventListener('click', () => closeModal(elements.imageViewerModal));
    elements.btnCloseViewerModal.addEventListener('click', () => closeModal(elements.imageViewerModal));

    // Workspace Path Syncing
    elements.localDirInputWs.addEventListener('input', () => {
        elements.localDirInput.value = elements.localDirInputWs.value;
    });
    elements.yandexDirInputWs.addEventListener('input', () => {
        elements.yandexDirInput.value = elements.yandexDirInputWs.value;
    });
    elements.localDirInputWs.addEventListener('change', saveSidebarConfig);
    elements.yandexDirInputWs.addEventListener('change', saveSidebarConfig);

    elements.localDirInput.addEventListener('input', () => {
        elements.localDirInputWs.value = elements.localDirInput.value;
    });
    elements.yandexDirInput.addEventListener('input', () => {
        elements.yandexDirInputWs.value = elements.yandexDirInput.value;
    });

    // Excel Panel Controls
    if (elements.btnCopyExcelRow) {
        elements.btnCopyExcelRow.addEventListener('click', copyExcelRow);
    }
    if (elements.excelProductName) {
        elements.excelProductName.addEventListener('input', updateExcelOutputRow);
    }
    if (elements.excelParameters) {
        elements.excelParameters.addEventListener('input', updateExcelOutputRow);
    }

    // Project Settings File Import/Export
    if (elements.btnExportProject) {
        elements.btnExportProject.addEventListener('click', exportProjectSettings);
    }
    if (elements.btnImportProject) {
        elements.btnImportProject.addEventListener('click', () => elements.projectFileInput.click());
    }
    if (elements.projectFileInput) {
        elements.projectFileInput.addEventListener('change', importProjectSettings);
    }
}

// Modal Helper Functions
function openModal(modal) {
    modal.classList.add('active');
}

function closeModal(modal) {
    modal.classList.remove('active');
}

// API Connection Checks
async function checkApiConnections() {
    setLoadingState(elements.statusGemini, 'checking');
    setLoadingState(elements.statusYandex, 'checking');
    
    try {
        const response = await fetch('/api/check-apis', { method: 'POST' });
        const data = await response.json();
        
        updateStatusBadge(elements.statusGemini, data.gemini_connected, 'Gemini API');
        updateStatusBadge(elements.statusYandex, data.yandex_connected, 'Яндекс.Диск');
        
        // Show credentials modal on first load if APIs are not connected
        if (!data.gemini_connected || !data.yandex_connected) {
            // Wait briefly then show modal to help user configure
            setTimeout(() => {
                openModal(elements.settingsModal);
            }, 1000);
        }
    } catch (error) {
        console.error('API check error:', error);
        updateStatusBadge(elements.statusGemini, false, 'Gemini API');
        updateStatusBadge(elements.statusYandex, false, 'Яндекс.Диск');
    }
}

function setLoadingState(badge, state) {
    const textSpan = badge.querySelector('.text');
    badge.className = 'status-badge';
    if (state === 'checking') {
        textSpan.innerText = 'Проверка...';
    }
}

function updateStatusBadge(badge, isConnected, labelText) {
    const textSpan = badge.querySelector('.text');
    badge.className = 'status-badge ' + (isConnected ? 'connected' : 'error');
    textSpan.innerText = isConnected ? 'Подключен' : 'Ошибка';
}

// Configuration load/save
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        appState.config = config;
        
        // Populate inputs
        elements.geminiKeyInput.value = config.gemini_api_key || '';
        elements.yandexTokenInput.value = config.yandex_token || '';
        
        elements.globalContext.value = config.global_context || '';
        elements.visualStyle.value = config.visual_style || '';
        elements.localDirInput.value = config.default_local_dir || '';
        elements.yandexDirInput.value = config.default_yandex_dir || '';
        elements.localDirInputWs.value = config.default_local_dir || '';
        elements.yandexDirInputWs.value = config.default_yandex_dir || '';
        if (elements.generationDelayInput) {
            elements.generationDelayInput.value = config.generation_delay_sec !== undefined ? config.generation_delay_sec : 5;
        }
        
        // Trigger verification
        checkApiConnections();
    } catch (error) {
        console.error('Failed to load configuration:', error);
        showNotification('Ошибка загрузки конфигурации', 'error');
    }
}

async function saveModalConfig() {
    const newConfig = {
        gemini_api_key: elements.geminiKeyInput.value,
        yandex_token: elements.yandexTokenInput.value,
        default_local_dir: elements.localDirInput.value,
        default_yandex_dir: elements.yandexDirInput.value,
        global_context: elements.globalContext.value,
        visual_style: elements.visualStyle.value,
        generation_delay_sec: elements.generationDelayInput ? (parseInt(elements.generationDelayInput.value) || 0) : 5
    };
    
    await submitConfig(newConfig, 'Ключи успешно сохранены');
    closeModal(elements.settingsModal);
}

async function saveSidebarConfig() {
    const newConfig = {
        gemini_api_key: elements.geminiKeyInput.value,
        yandex_token: elements.yandexTokenInput.value,
        default_local_dir: elements.localDirInput.value,
        default_yandex_dir: elements.yandexDirInput.value,
        global_context: elements.globalContext.value,
        visual_style: elements.visualStyle.value,
        generation_delay_sec: elements.generationDelayInput ? (parseInt(elements.generationDelayInput.value) || 0) : 5
    };
    
    await submitConfig(newConfig, 'Настройки сохранены');
}

async function submitConfig(configData, successMsg) {
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });
        const result = await response.json();
        if (result.status === 'success') {
            showNotification(successMsg, 'success');
            loadConfig(); // Reload config and mask keys
        } else {
            showNotification(result.detail || 'Не удалось сохранить настройки', 'error');
        }
    } catch (error) {
        console.error('Save config error:', error);
        showNotification('Ошибка сети при сохранении настроек', 'error');
    }
}

// Reference Images handling
function handleFileSelect(e) {
    uploadReferences(e.target.files);
}

function handleFileDrop(e) {
    e.preventDefault();
    elements.refUploadZone.style.borderColor = 'var(--border-color)';
    uploadReferences(e.dataTransfer.files);
}

async function uploadReferences(files) {
    if (files.length === 0) return;
    
    const formData = new FormData();
    for (let file of files) {
        formData.append('files', file);
    }
    
    try {
        showNotification('Загрузка референсов...', 'info');
        const response = await fetch('/api/upload-references', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (response.ok) {
            appState.references.push(...result.saved_files);
            renderReferencePreviews();
            showNotification('Референсы успешно загружены', 'success');
            await generateStyleFromReferences();
        } else {
            showNotification('Ошибка загрузки референсов: ' + result.detail, 'error');
        }
    } catch (error) {
        console.error('References upload error:', error);
        showNotification('Ошибка соединения при загрузке файлов', 'error');
    }
}

async function generateStyleFromReferences() {
    if (appState.references.length === 0) return;
    
    showNotification('Анализ стиля референсов...', 'info');
    
    // Show activity status bar
    elements.activityStatusBar.style.display = 'flex';
    updateActivityStatus('Анализируем загруженные референсы...', 50);
    
    try {
        const response = await fetch('/api/generate-style-guide', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ references: appState.references })
        });
        
        const result = await response.json();
        
        if (response.ok && result.style_guide) {
            elements.visualStyle.value = result.style_guide;
            // Highlight the text box briefly to draw user attention
            elements.visualStyle.style.borderColor = 'var(--accent-green)';
            elements.visualStyle.style.boxShadow = '0 0 10px rgba(0, 255, 135, 0.3)';
            setTimeout(() => {
                elements.visualStyle.style.borderColor = '';
                elements.visualStyle.style.boxShadow = '';
            }, 3000);
            
            showNotification('Стиль успешно обновлен на основе референсов!', 'success');
            updateActivityStatus('Анализ референсов завершен!', 100);
        } else {
            showNotification('Не удалось сгенерировать описание стиля: ' + (result.detail || 'Неизвестная ошибка'), 'error');
            updateActivityStatus('Сбой анализа референсов', 0);
        }
    } catch (error) {
        console.error('Style guide generation error:', error);
        showNotification('Ошибка сети при анализе стиля', 'error');
        updateActivityStatus('Ошибка соединения при анализе', 0);
    } finally {
        setTimeout(() => {
            if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                elements.activityStatusBar.style.display = 'none';
            }
        }, 2000);
    }
}

function renderReferencePreviews() {
    elements.refPreviews.innerHTML = '';
    appState.references.forEach((filePath, idx) => {
        const filename = filePath.split(/[\\/]/).pop();
        const previewEl = document.createElement('div');
        previewEl.className = 'ref-thumb';
        previewEl.title = filename;
        previewEl.innerHTML = `
            <img src="/static/placeholder.png" alt="Reference">
            <div class="delete-btn" onclick="deleteReference(${idx})">&times;</div>
        `;
        // Since it's a local file path on server, we use placeholder or let FastAPI serve it
        // To keep it simple, we just show a visual icon/thumbnail.
        elements.refPreviews.appendChild(previewEl);
    });
}

window.deleteReference = async function(index) {
    appState.references.splice(index, 1);
    renderReferencePreviews();
    if (appState.references.length > 0) {
        await generateStyleFromReferences();
    } else {
        elements.visualStyle.value = '';
    }
};

// 9-Slot Marketing breakdown analysis
async function runAdAnalysis() {
    const input = elements.adInput.value.trim();
    if (!input) {
        showNotification('Пожалуйста, введите параметры объявления', 'warning');
        return;
    }
    
    // Check if api keys are saved
    if (!appState.config.gemini_api_key) {
        showNotification('Укажите Gemini API Key в настройках!', 'error');
        openModal(elements.settingsModal);
        return;
    }

    setGeneratingState(true);
    appState.currentAdText = input;
    elements.adSummaryText.innerText = input;
    
    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                local_ad_input: input,
                references: appState.references
            })
        });
        const result = await response.json();
        
        if (response.ok) {
            appState.slots = result.slots;
            appState.productName = result.product_name || "";
            appState.parameters = result.parameters || "";
            
            if (elements.excelProductName) {
                elements.excelProductName.value = appState.productName;
            }
            if (elements.excelParameters) {
                elements.excelParameters.value = appState.parameters;
            }
            if (elements.excelExportPanel) {
                elements.excelExportPanel.style.display = 'block';
            }
            updateExcelOutputRow();

            renderSlots();
            elements.workspaceEmpty.style.display = 'none';
            elements.generatorWorkspace.style.display = 'flex';
            const hasAnyYandexLink = appState.slots.some(slot => !!slot.yandex_url);
            elements.btnCopyAllLinks.style.display = hasAnyYandexLink ? 'inline-flex' : 'none';
            showNotification('Анализ выполнен! Сформировано 9 слотов.', 'success');
        } else {
            showNotification('Ошибка маркетингового разбора: ' + result.detail, 'error');
        }
    } catch (error) {
        console.error('Analysis error:', error);
        showNotification('Ошибка сети при анализе', 'error');
    } finally {
        setGeneratingState(false);
    }
}

function setGeneratingState(isGenerating) {
    if (isGenerating) {
        elements.btnRunAnalysis.disabled = true;
        elements.btnRunAnalysis.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Разбор на слоты...';
    } else {
        elements.btnRunAnalysis.disabled = false;
        elements.btnRunAnalysis.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Разложить на 9 слотов';
    }
}

// Render 9 Slot Cards
function renderSlots() {
    elements.slotsContainer.innerHTML = '';
    appState.slots.forEach((slot, index) => {
        const card = document.createElement('div');
        card.className = 'slot-card';
        card.id = `slot-card-${index}`;
        card.dataset.index = index;
        
        const isGenerated = !!slot.local_temp_path;
        const isUploaded = !!slot.yandex_url;
        const filename = isGenerated ? slot.local_temp_path.split(/[\\/]/).pop() : '';
        
        card.innerHTML = `
            <div class="slot-header">
                <span class="slot-badge-num">${slot.slot_number}</span>
                <span class="slot-title">${slot.title}</span>
                <span class="slot-status-indicator" id="slot-status-${index}">
                    ${isUploaded ? '<i class="fa-solid fa-cloud-check" style="color: var(--accent-green)"></i> Загружен' : 
                      isGenerated ? '<i class="fa-solid fa-circle-check" style="color: var(--accent-cyan)"></i> Готов' : 
                      '<i class="fa-solid fa-circle-nodes" style="color: var(--text-muted)"></i> Ожидает'}
                </span>
            </div>
            <div class="slot-body">
                <div class="slot-logic-wrap">
                    <strong>Цель:</strong> ${slot.marketing_logic}
                </div>
                
                <div class="form-group">
                    <label>Текст на баннере:</label>
                    <textarea id="slot-banner-text-${index}" rows="2">${slot.banner_text}</textarea>
                </div>
                
                <div class="form-group">
                    <label>Промпт генерации (англ.):</label>
                    <textarea id="slot-prompt-${index}" rows="3">${slot.image_prompt}</textarea>
                </div>

                <div class="slot-visual-frame ${isGenerated ? '' : 'empty'}" id="slot-frame-${index}">
                    ${isGenerated ? 
                        `<img src="/temp_uploads/${filename}" id="slot-image-${index}" alt="Слот ${slot.slot_number}" onclick="viewImage(${index})">` : 
                        `<i class="fa-regular fa-image" style="font-size: 2rem; color: var(--border-color);"></i>`}
                    <div class="visual-actions-overlay">
                        ${isGenerated ? `<button class="visual-action-btn" title="Увеличить" onclick="viewImage(${index})"><i class="fa-solid fa-magnifying-glass-plus"></i></button>` : ''}
                    </div>
                </div>

                <div class="yandex-copy-container" id="slot-copy-yandex-wrap-${index}" style="display: ${isUploaded ? 'block' : 'none'}; margin-top: 0.5rem;">
                    <button class="btn btn-secondary btn-icon-text w-full" style="font-size: 0.85rem; padding: 0.5rem; justify-content: center;" onclick="copyToClipboard('${slot.yandex_url || ''}', this)">
                        <i class="fa-solid fa-copy"></i> Скопировать ссылку на Диск
                    </button>
                </div>

                <div class="yandex-link-wrap" id="slot-yandex-wrap-${index}" style="display: ${isUploaded ? 'flex' : 'none'};">
                    <i class="fa-brands fa-yandex"></i>
                    <a href="${slot.yandex_url || '#'}" target="_blank" id="slot-yandex-link-${index}">${slot.yandex_url || ''}</a>
                    <button class="btn-copy" onclick="copyToClipboard('${slot.yandex_url || ''}', this)" title="Скопировать ссылку">
                        <i class="fa-solid fa-copy"></i>
                    </button>
                </div>
            </div>
            <div class="slot-footer">
                <button class="btn btn-secondary btn-icon-text" id="slot-btn-gen-${index}" onclick="generateSingleImage(${index})">
                    <i class="fa-solid fa-image"></i> ${isGenerated ? 'Перегенерировать' : 'Создать картинку'}
                </button>
                <button class="btn btn-primary btn-icon-text" id="slot-btn-cloud-${index}" ${isGenerated ? '' : 'disabled'} onclick="uploadSingleToYandex(${index})">
                    <i class="fa-solid fa-cloud-arrow-up"></i> На Яндекс
                </button>
            </div>
        `;
        
        elements.slotsContainer.appendChild(card);
        
        // If file exists, update its thumbnail source dynamically
        if (isGenerated) {
            updateImageThumbnail(index, slot.local_temp_path);
        }
    });
    const hasAnyYandexLink = appState.slots.some(slot => !!slot.yandex_url);
    elements.btnCopyAllLinks.style.display = hasAnyYandexLink ? 'inline-flex' : 'none';
}

// Helpers to update UI elements inside slots
function updateImageThumbnail(index, path) {
    const imgEl = document.getElementById(`slot-image-${index}`);
    if (imgEl) {
        // We can serve the file by feeding python path to static? 
        // Our Python server runs locally, so we can access temp files.
        // Let's request the file from python backend using static route fallback
        // We added TEMP_UPLOADS_DIR and files are saved there.
        // Let's get the filename from the path
        const filename = path.split(/[\\/]/).pop();
        imgEl.src = `/temp_uploads/${filename}`;
    }
}

// Generate Single Image
async function generateSingleImage(index) {
    const slot = appState.slots[index];
    const promptText = document.getElementById(`slot-prompt-${index}`).value.trim();
    const bannerText = document.getElementById(`slot-banner-text-${index}`).value.trim();
    
    // Update local state copy
    slot.image_prompt = promptText;
    slot.banner_text = bannerText;

    const card = document.getElementById(`slot-card-${index}`);
    const frame = document.getElementById(`slot-frame-${index}`);
    const statusText = document.getElementById(`slot-status-${index}`);
    const genBtn = document.getElementById(`slot-btn-gen-${index}`);
    const cloudBtn = document.getElementById(`slot-btn-cloud-${index}`);
    
    // Set visual generating state for this card
    frame.className = 'slot-visual-frame generating';
    frame.innerHTML = '<div class="spinner"></div><small style="color: var(--accent-cyan)">Нейросеть рисует...</small>';
    statusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color: var(--accent-cyan)"></i> Создание...';
    genBtn.disabled = true;
    cloudBtn.disabled = true;
    
    if (!appState.isGeneratingAll) {
        elements.activityStatusBar.style.display = 'flex';
        updateActivityStatus(`Генерация картинки для слота ${slot.slot_number}: "${slot.title}"...`, 30);
    }
    
    try {
        const response = await fetch('/api/generate-image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            slot.local_temp_path = result.temp_file_path;
            
            // Draw the text plaque onto the image if banner text is present
            if (bannerText) {
                try {
                    if (!appState.isGeneratingAll) {
                        updateActivityStatus(`Наложение текстовой плашки...`, 90);
                    }
                    const imageSrc = `/temp_uploads/${result.filename}`;
                    const base64Data = await drawTextOverlay(imageSrc, bannerText);
                    
                    // Overwrite the temp file with the base64 image containing the plaque
                    await fetch('/api/save-base64', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            image_base64: base64Data,
                            temp_file_path: slot.local_temp_path
                        })
                    });
                } catch (err) {
                    console.error('Error drawing banner plaque:', err);
                }
            }
            
            // Save to Local Directory if specified
            await saveToLocalFolder(index);
            
            // Update Card visual (bypass browser cache with timestamp query parameter)
            frame.className = 'slot-visual-frame';
            frame.innerHTML = `
                <img src="/temp_uploads/${result.filename}?t=${Date.now()}" id="slot-image-${index}" alt="Слот ${slot.slot_number}" onclick="viewImage(${index})">
                <div class="visual-actions-overlay">
                    <button class="visual-action-btn" title="Увеличить" onclick="viewImage(${index})"><i class="fa-solid fa-magnifying-glass-plus"></i></button>
                </div>
            `;
            
            statusText.innerHTML = '<i class="fa-solid fa-circle-check" style="color: var(--accent-cyan)"></i> Готов';
            showNotification(`Изображение для слота ${slot.slot_number} готово!`, 'success');
            if (!appState.isGeneratingAll) {
                updateActivityStatus(`Слот ${slot.slot_number} успешно сгенерирован!`, 100);
                setTimeout(() => {
                    if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                        elements.activityStatusBar.style.display = 'none';
                    }
                }, 2000);
            }
        } else {
            // Restore visual layout
            frame.className = 'slot-visual-frame empty';
            frame.innerHTML = '<i class="fa-regular fa-image" style="font-size: 2rem; color: var(--border-color);"></i>';
            statusText.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color: var(--accent-red)"></i> Ошибка';
            showNotification(`Ошибка генерации слота ${slot.slot_number}: ${result.detail}`, 'error');
            if (!appState.isGeneratingAll) {
                updateActivityStatus(`Ошибка генерации слота ${slot.slot_number}`, 0);
                setTimeout(() => {
                    if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                        elements.activityStatusBar.style.display = 'none';
                    }
                }, 2000);
            }
        }
    } catch (error) {
        console.error('Image gen error:', error);
        frame.className = 'slot-visual-frame empty';
        frame.innerHTML = '<i class="fa-regular fa-image" style="font-size: 2rem; color: var(--border-color);"></i>';
        statusText.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color: var(--accent-red)"></i> Ошибка';
        showNotification('Ошибка сети при генерации', 'error');
        if (!appState.isGeneratingAll) {
            updateActivityStatus(`Ошибка соединения при генерации слота ${slot.slot_number}`, 0);
            setTimeout(() => {
                if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                    elements.activityStatusBar.style.display = 'none';
                }
            }, 2000);
        }
    } finally {
        genBtn.disabled = false;
        // Enable upload button only if we have a file
        cloudBtn.disabled = !slot.local_temp_path;
        // Refresh single slot triggers
        renderSingleSlotButtons(index);
    }
}

function renderSingleSlotButtons(index) {
    const slot = appState.slots[index];
    const genBtn = document.getElementById(`slot-btn-gen-${index}`);
    const cloudBtn = document.getElementById(`slot-btn-cloud-${index}`);
    
    if (slot.local_temp_path) {
        genBtn.innerHTML = '<i class="fa-solid fa-image"></i> Перегенерировать';
        cloudBtn.disabled = false;
    }
}

// Save image directly to configured local directory on user PC
async function saveToLocalFolder(index) {
    const slot = appState.slots[index];
    const localDir = elements.localDirInput.value.trim();
    if (!localDir || !slot.local_temp_path) return;
    
    // Create clean filename based on index and slot title
    const sanitizedTitle = sanitizeFilename(slot.title);
    const filename = `${String(slot.slot_number).padStart(2, '0')}_${sanitizedTitle}.jpg`;
    const fullDestPath = `${localDir}\\${filename}`;
    
    try {
        const response = await fetch('/api/save-local', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                local_file_path: slot.local_temp_path,
                disk_file_path: fullDestPath
            })
        });
        if (response.ok) {
            console.log(`Saved locally to: ${fullDestPath}`);
        }
    } catch (error) {
        console.error('Local save error:', error);
    }
}

// Upload Single image to Yandex.Disk
async function uploadSingleToYandex(index) {
    const slot = appState.slots[index];
    if (!slot.local_temp_path) {
        showNotification('Картинка ещё не сгенерирована!', 'warning');
        return;
    }
    
    if (!appState.config.yandex_token) {
        showNotification('Укажите токен Яндекс.Диска в настройках!', 'error');
        openModal(elements.settingsModal);
        return;
    }

    const statusText = document.getElementById(`slot-status-${index}`);
    const cloudBtn = document.getElementById(`slot-btn-cloud-${index}`);
    const yandexWrap = document.getElementById(`slot-yandex-wrap-${index}`);
    const yandexLink = document.getElementById(`slot-yandex-link-${index}`);
    
    statusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color: var(--accent-yellow)"></i> Выгрузка...';
    cloudBtn.disabled = true;
    
    if (!appState.isUploadingAll) {
        elements.activityStatusBar.style.display = 'flex';
        updateActivityStatus(`Загрузка слота ${slot.slot_number} на Яндекс.Диск...`, 50);
    }
    
    // Define path in Yandex Disk: /Root/CampaignName/01_Title.jpg
    const rootDir = elements.yandexDirInput.value.trim() || '/Generator_Kreo';
    const folderName = sanitizeFilename(appState.currentAdText);
    const sanitizedTitle = sanitizeFilename(slot.title);
    const filename = `${String(slot.slot_number).padStart(2, '0')}_${sanitizedTitle}.jpg`;
    
    const diskPath = `${rootDir}/${folderName}/${filename}`.replace(/\/+/g, '/');
    
    try {
        const response = await fetch('/api/upload-yandex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                local_file_path: slot.local_temp_path,
                disk_file_path: diskPath
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            slot.yandex_url = result.public_url;
            
            // Update Excel row since we got a new link
            updateExcelOutputRow();
            
            // Update UI
            statusText.innerHTML = '<i class="fa-solid fa-cloud-check" style="color: var(--accent-green)"></i> Загружен';
            yandexLink.href = result.public_url;
            yandexLink.innerText = result.public_url;
            yandexWrap.style.display = 'flex';
            
            // Show new copy button
            const copyBtnWrap = document.getElementById(`slot-copy-yandex-wrap-${index}`);
            if (copyBtnWrap) {
                copyBtnWrap.style.display = 'block';
                const copyBtn = copyBtnWrap.querySelector('button');
                copyBtn.setAttribute('onclick', `copyToClipboard('${result.public_url}', this)`);
            }
            
            // Show the top Copy All Links button
            elements.btnCopyAllLinks.style.display = 'inline-flex';
            
            // Re-bind clipboard action
            const copyBtn = yandexWrap.querySelector('.btn-copy');
            if (copyBtn) copyBtn.setAttribute('onclick', `copyToClipboard('${result.public_url}', this)`);
            
            showNotification(`Слот ${slot.slot_number} выгружен на Яндекс.Диск!`, 'success');
            if (!appState.isUploadingAll) {
                updateActivityStatus(`Слот ${slot.slot_number} успешно загружен!`, 100);
                setTimeout(() => {
                    if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                        elements.activityStatusBar.style.display = 'none';
                    }
                }, 2000);
            }
        } else {
            statusText.innerHTML = '<i class="fa-solid fa-circle-check" style="color: var(--accent-cyan)"></i> Готов';
            showNotification(`Ошибка загрузки на Диск: ${result.detail}`, 'error');
            if (!appState.isUploadingAll) {
                updateActivityStatus(`Ошибка загрузки слота ${slot.slot_number}`, 0);
                setTimeout(() => {
                    if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                        elements.activityStatusBar.style.display = 'none';
                    }
                }, 2000);
            }
        }
    } catch (error) {
        console.error('Yandex upload error:', error);
        statusText.innerHTML = '<i class="fa-solid fa-circle-check" style="color: var(--accent-cyan)"></i> Готов';
        showNotification('Ошибка сети при выгрузке', 'error');
        if (!appState.isUploadingAll) {
            updateActivityStatus(`Ошибка соединения при выгрузке слота ${slot.slot_number}`, 0);
            setTimeout(() => {
                if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                    elements.activityStatusBar.style.display = 'none';
                }
            }, 2000);
        }
    } finally {
        cloudBtn.disabled = false;
    }
}

// Bulk Actions: Run all sequentially
async function generateAllImages() {
    if (appState.isGeneratingAll) return;
    appState.isGeneratingAll = true;
    elements.btnGenerateAll.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Генерация пакета...';
    elements.btnGenerateAll.disabled = true;
    
    showNotification('Начало пакетной генерации. Это займет несколько минут.', 'info');
    
    // Show activity status bar
    elements.activityStatusBar.style.display = 'flex';
    updateActivityStatus('Начало генерации пакета изображений...', 0);
    
    try {
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
        const total = appState.slots.length;
        for (let i = 0; i < total; i++) {
            updateActivityStatus(`Генерация изображения для слота ${i+1} из ${total}: "${appState.slots[i].title}"...`, Math.round((i / total) * 100));
            // Highlight current card
            document.getElementById(`slot-card-${i}`).style.borderColor = 'var(--accent-cyan)';
            await generateSingleImage(i);
            document.getElementById(`slot-card-${i}`).style.borderColor = 'var(--border-color)';
            
            // Wait to respect free tier rate limits
            if (i < total - 1) {
                const delaySec = appState.config.generation_delay_sec !== undefined ? appState.config.generation_delay_sec : 5;
                if (delaySec > 0) {
                    updateActivityStatus(`Ожидание ${delaySec} сек для соблюдения бесплатных лимитов API...`, Math.round(((i + 0.5) / total) * 100));
                    await sleep(delaySec * 1000);
                }
            }
        }
        updateActivityStatus('Все изображения успешно сгенерированы!', 100);
        showNotification('Пакетная генерация успешно завершена!', 'success');
    } catch (error) {
        console.error('Bulk generation error:', error);
        showNotification('Пакетная генерация прервана из-за ошибки', 'error');
    } finally {
        appState.isGeneratingAll = false;
        elements.btnGenerateAll.innerHTML = '<i class="fa-solid fa-images"></i> Генерировать все картинки';
        elements.btnGenerateAll.disabled = false;
        
        // Hide activity bar after 3 seconds
        setTimeout(() => {
            if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                elements.activityStatusBar.style.display = 'none';
            }
        }, 3000);
    }
}

async function uploadAllToYandex() {
    if (appState.isUploadingAll) return;
    appState.isUploadingAll = true;
    elements.btnUploadAll.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Выгрузка пакета...';
    elements.btnUploadAll.disabled = true;
    
    showNotification('Выгрузка всех изображений на Яндекс.Диск...', 'info');
    
    // Show activity status bar
    elements.activityStatusBar.style.display = 'flex';
    updateActivityStatus('Начало пакетной выгрузки на Яндекс.Диск...', 0);
    
    try {
        const total = appState.slots.length;
        let uploadedCount = 0;
        for (let i = 0; i < total; i++) {
            const slot = appState.slots[i];
            if (slot.local_temp_path) {
                updateActivityStatus(`Загрузка слота ${i+1} из ${total} на Яндекс.Диск: "${slot.title}"...`, Math.round((i / total) * 100));
                document.getElementById(`slot-card-${i}`).style.borderColor = 'var(--accent-yellow)';
                await uploadSingleToYandex(i);
                document.getElementById(`slot-card-${i}`).style.borderColor = 'var(--border-color)';
                uploadedCount++;
            }
        }
        updateActivityStatus('Все изображения выгружены на Яндекс.Диск!', 100);
        showNotification('Все файлы загружены на Яндекс.Диск!', 'success');
    } catch (error) {
        console.error('Bulk upload error:', error);
        showNotification('Ошибка пакетной выгрузки на Диск', 'error');
    } finally {
        appState.isUploadingAll = false;
        elements.btnUploadAll.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Все на Яндекс.Диск';
        elements.btnUploadAll.disabled = false;
        
        // Hide activity bar after 3 seconds
        setTimeout(() => {
            if (!appState.isGeneratingAll && !appState.isUploadingAll) {
                elements.activityStatusBar.style.display = 'none';
            }
        }, 3000);
    }
}

// Fullscreen Viewer
window.viewImage = function(index) {
    const slot = appState.slots[index];
    if (!slot.local_temp_path) return;
    
    const filename = slot.local_temp_path.split(/[\\/]/).pop();
    elements.viewerImg.src = `/temp_uploads/${filename}`;
    elements.viewerTitle.innerText = `Слот ${slot.slot_number}: ${slot.title}`;
    elements.viewerBannerText.innerText = slot.banner_text;
    elements.viewerPrompt.innerText = slot.image_prompt;
    
    openModal(elements.imageViewerModal);
};

// Clipboard Helper
window.copyToClipboard = function(text, btnElement) {
    navigator.clipboard.writeText(text).then(() => {
        const icon = btnElement.querySelector('i');
        icon.className = 'fa-solid fa-check';
        icon.style.color = 'var(--accent-green)';
        showNotification('Ссылка скопирована в буфер обмена', 'success');
        
        setTimeout(() => {
            icon.className = 'fa-solid fa-copy';
            icon.style.color = '';
        }, 2000);
    }).catch(err => {
        showNotification('Не удалось скопировать', 'error');
    });
};

// Filename sanitizer to avoid filesystem issues
function sanitizeFilename(str) {
    // Basic transliteration for Russian characters to make paths look neat (Optional, but let's just keep Cyrillic letters and clean other chars)
    return str
        .replace(/[^a-zA-Z0-9а-яА-ЯёЁ_\-\s]/g, '')
        .trim()
        .replace(/\s+/g, '_');
}

// Copy all available Yandex.Disk URLs to clipboard
function copyAllYandexLinks() {
    const links = appState.slots
        .map(slot => slot.yandex_url)
        .filter(url => !!url);
        
    if (links.length === 0) {
        showNotification('Нет загруженных ссылок. Сначала выгрузите картинки на Яндекс.Диск.', 'warning');
        return;
    }
    
    const linksText = links.join('\n');
    navigator.clipboard.writeText(linksText).then(() => {
        showNotification(`Успешно скопировано ${links.length} ссылок в буфер обмена!`, 'success');
    }).catch(err => {
        showNotification('Не удалось скопировать ссылки', 'error');
    });
}

// Update the real-time activity status bar text and fill width
function updateActivityStatus(text, percentage) {
    if (elements.activityStatusText) {
        elements.activityStatusText.innerText = text;
    }
    if (elements.activityProgressBarFill) {
        elements.activityProgressBarFill.style.width = `${percentage}%`;
    }
}

// Floating Toast Notification
function showNotification(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast-notification ${type}`;
    
    let iconClass = 'fa-circle-info';
    if (type === 'success') iconClass = 'fa-circle-check';
    if (type === 'error') iconClass = 'fa-triangle-exclamation';
    if (type === 'warning') iconClass = 'fa-circle-exclamation';
    
    toast.innerHTML = `
        <i class="fa-solid ${iconClass}"></i>
        <span>${message}</span>
    `;
    
    // Append container if not exists
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('visible'), 10);
    
    // Remove after delay
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Add dynamic toast css rules in Javascript to avoid file edits on layout
const styleSheet = document.createElement("style");
styleSheet.innerText = `
.toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    z-index: 200;
}
.toast-notification {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 20px;
    border-radius: 8px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    font-size: 0.85rem;
    font-weight: 500;
    box-shadow: var(--shadow-md);
    transform: translateY(20px);
    opacity: 0;
    transition: all 0.3s cubic-bezier(0.68, -0.55, 0.27, 1.55);
}
.toast-notification.visible {
    transform: translateY(0);
    opacity: 1;
}
.toast-notification.success {
    border-color: rgba(0, 255, 135, 0.3);
    background: rgba(13, 27, 30, 0.95);
}
.toast-notification.success i { color: var(--accent-green); }
.toast-notification.error {
    border-color: rgba(255, 74, 107, 0.3);
    background: rgba(30, 13, 19, 0.95);
}
.toast-notification.error i { color: var(--accent-red); }
.toast-notification.warning {
    border-color: rgba(255, 203, 68, 0.3);
    background: rgba(30, 26, 13, 0.95);
}
.toast-notification.warning i { color: var(--accent-yellow); }
.toast-notification.info i { color: var(--accent-cyan); }
`;
document.head.appendChild(styleSheet);

// Excel export helpers
function updateExcelOutputRow() {
    if (!elements.excelRowOutput) return;
    
    const productName = elements.excelProductName ? elements.excelProductName.value.trim() : "";
    const parameters = elements.excelParameters ? elements.excelParameters.value.trim() : "";
    
    // Gather all Yandex Disk URLs from slots
    const links = appState.slots
        .map(slot => slot.yandex_url)
        .filter(url => !!url);
        
    // Join with newlines and escape quotes
    const linksString = links.join('\n');
    
    // In tab-separated copy-paste to Excel:
    // Columns are separated by tab.
    // If a column value contains newlines, wrap it in double quotes. 
    // Any double quotes in the cell value should be doubled.
    const escapedLinks = linksString ? `"${linksString.replace(/"/g, '""')}"` : '""';
    
    const excelRow = `${productName}\t${parameters}\t${escapedLinks}`;
    elements.excelRowOutput.value = excelRow;
}

function copyExcelRow() {
    if (!elements.excelRowOutput) return;
    
    const rowText = elements.excelRowOutput.value;
    if (!rowText) {
        showNotification('Нет данных для копирования', 'warning');
        return;
    }
    
    navigator.clipboard.writeText(rowText).then(() => {
        showNotification('Строка для Excel успешно скопирована!', 'success');
        
        const btn = elements.btnCopyExcelRow;
        if (btn) {
            const origHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Скопировано';
            btn.style.background = 'var(--accent-green)';
            setTimeout(() => {
                btn.innerHTML = origHtml;
                btn.style.background = '';
            }, 2000);
        }
    }).catch(err => {
        console.error('Copy Excel row error:', err);
        showNotification('Не удалось скопировать строку', 'error');
    });
}

// Project Settings Import/Export helpers
function exportProjectSettings() {
    const projectData = {
        global_context: elements.globalContext.value,
        visual_style: elements.visualStyle.value,
        default_local_dir: elements.localDirInput.value,
        default_yandex_dir: elements.yandexDirInput.value,
        references: appState.references
    };
    
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(projectData, null, 4));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    
    // Create a meaningful filename using the global context or timestamp
    let filename = "project_settings.json";
    if (elements.globalContext.value) {
        // Try to get a neat short name from the first words of the global context
        const firstLine = elements.globalContext.value.split('\n')[0];
        const match = firstLine.match(/(?:Продукт|Product):\s*([a-zA-Z0-9а-яА-ЯёЁ\s\-]+)/i);
        if (match && match[1]) {
            filename = `project_${sanitizeFilename(match[1].trim())}.json`;
        } else {
            filename = `project_${Date.now()}.json`;
        }
    }
    
    downloadAnchor.setAttribute("download", filename);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    
    showNotification('Настройки проекта экспортированы!', 'success');
}

function importProjectSettings(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = async function(event) {
        try {
            const projectData = JSON.parse(event.target.result);
            
            // Populate inputs
            if (projectData.global_context !== undefined) {
                elements.globalContext.value = projectData.global_context;
            }
            if (projectData.visual_style !== undefined) {
                elements.visualStyle.value = projectData.visual_style;
            }
            if (projectData.default_local_dir !== undefined) {
                elements.localDirInput.value = projectData.default_local_dir;
                elements.localDirInputWs.value = projectData.default_local_dir;
            }
            if (projectData.default_yandex_dir !== undefined) {
                elements.yandexDirInput.value = projectData.default_yandex_dir;
                elements.yandexDirInputWs.value = projectData.default_yandex_dir;
            }
            if (projectData.references !== undefined) {
                appState.references = projectData.references;
                renderReferencePreviews();
            }
            
            // Automatically submit config changes to the server to persist
            const newConfig = {
                gemini_api_key: elements.geminiKeyInput.value,
                yandex_token: elements.yandexTokenInput.value,
                default_local_dir: elements.localDirInput.value,
                default_yandex_dir: elements.yandexDirInput.value,
                global_context: elements.globalContext.value,
                visual_style: elements.visualStyle.value
            };
            
            await submitConfig(newConfig, 'Проект успешно импортирован и сохранен!');
            
        } catch (err) {
            console.error('Import parse error:', err);
            showNotification('Ошибка импорта: неверный формат файла настроек', 'error');
        }
        
        // Reset file input so same file can be selected again if needed
        elements.projectFileInput.value = '';
    };
    reader.readAsText(file);
}

// Draw a beautiful marketing plaque at the bottom of the image and overlay the text
function drawTextOverlay(imageSrc, bannerText) {
    return new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => {
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            const ctx = canvas.getContext('2d');
            
            // Draw original image
            ctx.drawImage(img, 0, 0);
            
            if (bannerText) {
                const width = canvas.width;
                const height = canvas.height;
                
                // Draw a dark premium slate bar at the bottom with 85% opacity
                const bannerHeight = Math.round(height * 0.12);
                const yPos = height - bannerHeight;
                
                ctx.fillStyle = 'rgba(11, 15, 25, 0.85)';
                ctx.fillRect(0, yPos, width, bannerHeight);
                
                // Draw a cyan-purple glowing border gradient line at the top
                const gradient = ctx.createLinearGradient(0, yPos, width, yPos);
                gradient.addColorStop(0, '#00f0ff');
                gradient.addColorStop(1, '#9f55ff');
                ctx.fillStyle = gradient;
                ctx.fillRect(0, yPos, width, Math.max(4, Math.round(height * 0.004)));
                
                // Draw text in centered bold white
                ctx.fillStyle = '#ffffff';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                
                // Set premium responsive font
                const fontSize = Math.round(bannerHeight * 0.35);
                ctx.font = `bold ${fontSize}px "Plus Jakarta Sans", "Montserrat", "Arial", sans-serif`;
                
                // Render text
                ctx.fillText(bannerText, width / 2, yPos + (bannerHeight / 2) + Math.round(height * 0.002));
            }
            
            resolve(canvas.toDataURL("image/jpeg", 0.95));
        };
        img.src = imageSrc;
    });
}
