// static/js/main.js - JavaScript Essencial para a Aplicação

document.addEventListener('DOMContentLoaded', function() {
    // 1. VALIDAÇÃO DE ARQUIVOS - ESSENCIAL
    const fileInput = document.getElementById('pdfFiles');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            validateFiles(this.files);
        });
    }

    // 2. CONTROLE DE FORMULÁRIOS - ESSENCIAL
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            handleFormSubmit(this);
        });
    });

    // 3. AUTO-DISMISS DE ALERTAS - ÚTIL
    initAutoDismissAlerts();
});

// FUNÇÃO 1: Validação de arquivos
function validateFiles(files) {
    let totalSize = 0;
    let hasInvalidFiles = false;
    
    for (let file of files) {
        totalSize += file.size;
        
        // Verificar se é PDF
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            hasInvalidFiles = true;
            showToast('Apenas arquivos PDF são permitidos', 'warning');
        }
    }
    
    // Verificar tamanho total (500MB)
    const maxSize = 500 * 1024 * 1024;
    if (totalSize > maxSize) {
        showToast('Tamanho total excede 500MB. Selecione arquivos menores.', 'danger');
        if (fileInput) fileInput.value = '';
        return;
    }
    
    // Atualizar contador de arquivos
    updateFileCounter(files.length, totalSize);
    
    if (hasInvalidFiles) {
        showToast('Alguns arquivos não são PDFs e serão ignorados', 'warning');
    }
}

// FUNÇÃO 2: Atualizar contador de arquivos
function updateFileCounter(fileCount, totalSize) {
    let fileInfo = document.getElementById('fileInfo');
    
    if (!fileInfo) {
        fileInfo = document.createElement('div');
        fileInfo.id = 'fileInfo';
        fileInfo.className = 'form-text text-info mt-2 fw-bold';
        const fileInput = document.getElementById('pdfFiles');
        fileInput.parentNode.appendChild(fileInfo);
    }
    
    fileInfo.textContent = `${fileCount} arquivo(s) selecionado(s) - ${formatFileSize(totalSize)}`;
}

// FUNÇÃO 3: Manipular envio de formulário
function handleFormSubmit(form) {
    const submitBtn = form.querySelector('button[type="submit"]');
    const files = document.getElementById('pdfFiles')?.files;
    
    if (submitBtn && files && files.length > 0) {
        // Feedback visual
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processando...';
        
        // Mostrar modal de progresso para uploads grandes
        if (files.length > 10) {
            showProgressModal(files.length);
        }
    }
}

// FUNÇÃO 4: Modal de progresso
function showProgressModal(totalFiles) {
    // Criar modal dinamicamente se não existir
    let modal = document.getElementById('progressModal');
    
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'progressModal';
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-primary text-white">
                        <h5 class="modal-title">
                            <i class="fas fa-sync-alt fa-spin me-2"></i>Processando Arquivos
                        </h5>
                    </div>
                    <div class="modal-body text-center py-4">
                        <div class="spinner-border text-primary mb-3" style="width: 3rem; height: 3rem;"></div>
                        <h5 class="text-primary" id="progressText">Preparando processamento...</h5>
                        <p class="text-muted mb-2" id="currentFile">${totalFiles} arquivos na fila</p>
                        <div class="progress mt-3">
                            <div class="progress-bar progress-bar-striped progress-bar-animated" 
                                 id="progressBar" style="width: 0%"></div>
                        </div>
                        <small class="text-muted" id="progressDetail">0% concluído</small>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
    }
    
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    
    // Simular progresso (em uma aplicação real, isso viria do servidor via WebSocket)
    simulateProgress(totalFiles);
}

// FUNÇÃO 5: Simular progresso (para demonstração)
function simulateProgress(totalFiles) {
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const progressDetail = document.getElementById('progressDetail');
    
    let progress = 0;
    const interval = setInterval(() => {
        progress += 2;
        if (progress <= 90) { // Para em 90% - o resto é processamento real
            progressBar.style.width = progress + '%';
            progressDetail.textContent = `${progress}% - Processando...`;
            
            // Atualizar texto a cada 20%
            if (progress % 20 === 0) {
                const filesProcessed = Math.floor((progress / 100) * totalFiles);
                progressText.textContent = `Processando ${filesProcessed} de ${totalFiles} arquivos`;
            }
        } else {
            clearInterval(interval);
        }
    }, 500);
}

// FUNÇÃO 6: Inicializar auto-dismiss de alertas
function initAutoDismissAlerts() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert.classList.contains('show')) {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }
        }, 5000); // Fecha após 5 segundos
    });
}

// FUNÇÃO 7: Utilidade - Formatar tamanho de arquivo
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// FUNÇÃO 8: Mostrar notificação toast
function showToast(message, type = 'info') {
    // Criar container de toasts se não existir
    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toastContainer';
        toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
        toastContainer.style.zIndex = '9999';
        document.body.appendChild(toastContainer);
    }
    
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-${getToastIcon(type)} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, { delay: 4000 });
    bsToast.show();
    
    // Remover do DOM após fechar
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// FUNÇÃO 9: Obter ícone para toast
function getToastIcon(type) {
    const icons = {
        'success': 'check-circle',
        'danger': 'exclamation-triangle',
        'warning': 'exclamation-circle',
        'info': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

// FUNÇÃO 10: Melhorar experiência em tabelas grandes
function enhanceTableExperience() {
    const tables = document.querySelectorAll('table');
    tables.forEach(table => {
        // Adicionar hover effects
        table.classList.add('table-hover');
        
        // Adicionar responsividade se não tiver
        if (!table.closest('.table-responsive')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'table-responsive';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }
    });
}

// Inicializar melhorias de tabela quando a página carregar
document.addEventListener('DOMContentLoaded', enhanceTableExperience);