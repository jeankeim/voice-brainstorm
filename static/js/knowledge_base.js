/**
 * 知识库管理模块
 */

class KnowledgeBaseManager {
    constructor() {
        this.knowledgeBases = [];
        this.selectedKBs = new Set();
        this.useRAG = false;
        this.documents = {}; // 存储每个知识库的文档 {kbId: [docs]}
        this.expandedKBs = new Set(); // 展开状态的知识库
    }

    // 获取 visitor_id
    getVisitorId() {
        // 优先从 sessionManager 获取，否则从 localStorage
        if (typeof sessionManager !== 'undefined' && sessionManager.visitorId) {
            return sessionManager.visitorId;
        }
        return localStorage.getItem('visitor_id') || '';
    }

    // 获取知识库列表
    async loadKnowledgeBases() {
        try {
            const visitorId = this.getVisitorId();
            const resp = await fetch(`/api/knowledge-bases?visitor_id=${visitorId}`);
            
            if (!resp.ok) {
                throw new Error('Failed to load knowledge bases');
            }
            
            const data = await resp.json();
            this.knowledgeBases = data.knowledge_bases || [];
            this.renderKnowledgeBaseList();
            return this.knowledgeBases;
        } catch (error) {
            console.error('Load knowledge bases error:', error);
            return [];
        }
    }

    // 创建知识库
    async createKnowledgeBase(name, description = '') {
        try {
            const resp = await fetch('/api/knowledge-bases', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    visitor_id: this.getVisitorId(),
                    name,
                    description
                })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed to create knowledge base');
            }
            
            const data = await resp.json();
            await this.loadKnowledgeBases();
            return data;
        } catch (error) {
            console.error('Create knowledge base error:', error);
            alert('创建知识库失败: ' + error.message);
            throw error;
        }
    }

    // 删除知识库
    async deleteKnowledgeBase(kbId) {
        if (!confirm('确定要删除这个知识库吗？其中的所有文档都将被删除。')) {
            return;
        }
        
        try {
            const resp = await fetch(`/api/knowledge-bases/${kbId}?visitor_id=${this.getVisitorId()}`, {
                method: 'DELETE'
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed to delete knowledge base');
            }
            
            this.selectedKBs.delete(kbId);
            await this.loadKnowledgeBases();
        } catch (error) {
            console.error('Delete knowledge base error:', error);
            alert('删除知识库失败: ' + error.message);
        }
    }

    // 编辑知识库
    async updateKnowledgeBase(kbId, name, description) {
        try {
            const resp = await fetch(`/api/knowledge-bases/${kbId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    visitor_id: this.getVisitorId(),
                    name,
                    description
                })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed to update knowledge base');
            }
            
            await this.loadKnowledgeBases();
        } catch (error) {
            console.error('Update knowledge base error:', error);
            alert('更新知识库失败: ' + error.message);
            throw error;
        }
    }

    // 删除文档
    async deleteDocument(kbId, docId) {
        if (!confirm('确定要删除这个文档吗？')) {
            return;
        }
        
        try {
            const resp = await fetch(`/api/knowledge-bases/${kbId}/documents/${docId}?visitor_id=${this.getVisitorId()}`, {
                method: 'DELETE'
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed to delete document');
            }
            
            // 刷新文档列表
            await this.loadAndShowDocuments(kbId);
            this.renderKnowledgeBaseList();
        } catch (error) {
            console.error('Delete document error:', error);
            alert('删除文档失败: ' + error.message);
        }
    }

    // 上传文档
    async uploadDocument(kbId, file) {
        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('visitor_id', this.getVisitorId());
            
            const resp = await fetch(`/api/knowledge-bases/${kbId}/documents`, {
                method: 'POST',
                body: formData
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed to upload document');
            }
            
            const data = await resp.json();
            return data;
        } catch (error) {
            console.error('Upload document error:', error);
            alert('上传文档失败: ' + error.message);
            throw error;
        }
    }

    // 获取文档列表
    async loadDocuments(kbId) {
        try {
            const resp = await fetch(`/api/knowledge-bases/${kbId}/documents?visitor_id=${this.getVisitorId()}`);
            
            if (!resp.ok) {
                throw new Error('Failed to load documents');
            }
            
            const data = await resp.json();
            return data.documents || [];
        } catch (error) {
            console.error('Load documents error:', error);
            return [];
        }
    }

    // 切换知识库选择
    toggleKBSelection(kbId) {
        console.log('[KB] 切换选择:', kbId, '当前状态:', this.selectedKBs.has(kbId));
        if (this.selectedKBs.has(kbId)) {
            this.selectedKBs.delete(kbId);
        } else {
            this.selectedKBs.add(kbId);
        }
        console.log('[KB] 切换后:', Array.from(this.selectedKBs));
        this.renderSelectedKBs();
    }

    // 获取选中的知识库ID列表
    getSelectedKBIds() {
        const ids = Array.from(this.selectedKBs);
        console.log('[KB] 获取选中的知识库:', ids);
        return ids;
    }

    // 切换 RAG 开关
    toggleRAG() {
        this.useRAG = !this.useRAG;
        this.renderRAGStatus();
        return this.useRAG;
    }

    // 切换知识库展开状态
    async toggleKBExpand(kbId) {
        if (this.expandedKBs.has(kbId)) {
            this.expandedKBs.delete(kbId);
        } else {
            this.expandedKBs.add(kbId);
            // 加载文档列表
            if (!this.documents[kbId]) {
                await this.loadAndShowDocuments(kbId);
            }
        }
        this.renderKnowledgeBaseList();
    }

    // 加载并显示文档
    async loadAndShowDocuments(kbId) {
        const docs = await this.loadDocuments(kbId);
        this.documents[kbId] = docs;
    }

    // 渲染知识库列表
    renderKnowledgeBaseList() {
        const container = document.getElementById('kb-list');
        if (!container) return;
        
        if (this.knowledgeBases.length === 0) {
            container.innerHTML = '<p class="empty-hint">暂无知识库</p>';
            return;
        }
        
        container.innerHTML = this.knowledgeBases.map(kb => {
            const isExpanded = this.expandedKBs.has(kb.id);
            const docs = this.documents[kb.id] || [];
            
            return `
            <div class="kb-item ${isExpanded ? 'expanded' : ''}" data-id="${kb.id}">
                <div class="kb-header">
                    <input type="checkbox" class="kb-checkbox" 
                           ${this.selectedKBs.has(kb.id) ? 'checked' : ''} 
                           data-id="${kb.id}">
                    <span class="kb-name" data-id="${kb.id}">${this.escapeHtml(kb.name)}</span>
                    <span class="kb-doc-count">${docs.length} 个文档</span>
                    <button class="kb-toggle" data-id="${kb.id}">${isExpanded ? '▼' : '▶'}</button>
                    <button class="kb-edit" data-id="${kb.id}" title="编辑">✎</button>
                    <button class="kb-delete" data-id="${kb.id}" title="删除">&times;</button>
                </div>
                <div class="kb-desc">${this.escapeHtml(kb.description || '')}</div>
                
                ${isExpanded ? `
                <div class="kb-doc-list">
                    ${docs.length > 0 ? docs.map(doc => `
                        <div class="kb-doc-item" data-doc-id="${doc.id}">
                            <span class="kb-doc-name">${this.escapeHtml(doc.filename)}</span>
                            <span class="kb-doc-chunks">${doc.chunk_count} 块</span>
                            <button class="kb-doc-delete" data-doc-id="${doc.id}" title="删除文档">&times;</button>
                        </div>
                    `).join('') : '<p class="kb-doc-empty">暂无文档</p>'}
                </div>
                ` : ''}
                
                <div class="kb-docs">
                    <button class="kb-upload-btn" data-id="${kb.id}">上传文档</button>
                    <input type="file" class="kb-file-input hidden" data-id="${kb.id}" 
                           accept=".txt,.md,.pdf,.docx">
                </div>
            </div>
        `}).join('');
        
        // 绑定事件
        container.querySelectorAll('.kb-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                this.toggleKBSelection(e.target.dataset.id);
            });
        });
        
        container.querySelectorAll('.kb-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleKBExpand(btn.dataset.id);
            });
        });
        
        container.querySelectorAll('.kb-name').forEach(span => {
            span.addEventListener('click', () => {
                this.toggleKBExpand(span.dataset.id);
            });
        });
        
        container.querySelectorAll('.kb-edit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openEditKBModal(btn.dataset.id);
            });
        });
        
        container.querySelectorAll('.kb-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteKnowledgeBase(btn.dataset.id);
            });
        });
        
        // 文档删除按钮事件
        container.querySelectorAll('.kb-doc-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const kbId = btn.closest('.kb-item').dataset.id;
                this.deleteDocument(kbId, btn.dataset.docId);
            });
        });
        
        container.querySelectorAll('.kb-upload-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const input = container.querySelector(`.kb-file-input[data-id="${btn.dataset.id}"]`);
                input.click();
            });
        });
        
        container.querySelectorAll('.kb-file-input').forEach(input => {
            input.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (file) {
                    const kbId = input.dataset.id;
                    const btn = container.querySelector(`.kb-upload-btn[data-id="${kbId}"]`);
                    if (btn) {
                        btn.disabled = true;
                        btn.textContent = '上传中...';
                    }
                    try {
                        await this.uploadDocument(kbId, file);
                        alert('文档上传成功！');
                        // 刷新文档列表
                        await this.loadAndShowDocuments(kbId);
                        if (!this.expandedKBs.has(kbId)) {
                            this.expandedKBs.add(kbId);
                        }
                        this.renderKnowledgeBaseList();
                    } catch (err) {
                        console.error('Upload error:', err);
                    } finally {
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = '上传文档';
                        }
                        input.value = '';
                    }
                }
            });
        });
    }

    // 渲染选中的知识库
    renderSelectedKBs() {
        const container = document.getElementById('selected-kbs');
        if (!container) return;
        
        const selected = this.knowledgeBases.filter(kb => this.selectedKBs.has(kb.id));
        
        if (selected.length === 0) {
            container.innerHTML = '<span class="kb-hint">未选择知识库</span>';
        } else {
            container.innerHTML = selected.map(kb => `
                <span class="kb-tag">${this.escapeHtml(kb.name)}</span>
            `).join('');
        }
    }

    // 渲染 RAG 状态
    renderRAGStatus() {
        const btn = document.getElementById('rag-toggle');
        if (!btn) return;
        
        if (this.useRAG) {
            btn.classList.add('active');
            btn.textContent = 'RAG 开启';
        } else {
            btn.classList.remove('active');
            btn.textContent = 'RAG 关闭';
        }
    }

    // 打开编辑知识库对话框
    openEditKBModal(kbId) {
        const kb = this.knowledgeBases.find(k => k.id === kbId);
        if (!kb) return;
        
        document.getElementById('editKbId').value = kbId;
        document.getElementById('editKbName').value = kb.name;
        document.getElementById('editKbDesc').value = kb.description || '';
        document.getElementById('editKBModal').classList.remove('hidden');
    }

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

window.kbManager = new KnowledgeBaseManager();
