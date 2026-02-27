/**
 * 会话管理模块 - 后端持久化版本
 */

class SessionManager {
    constructor() {
        this.visitorId = this.getOrCreateVisitorId();
        this.currentSessionId = null;
        this.sessions = [];
    }

    getOrCreateVisitorId() {
        let id = localStorage.getItem('visitor_id');
        if (!id) {
            id = 'v_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('visitor_id', id);
        }
        return id;
    }

    async createSession(title = '新对话') {
        try {
            const resp = await fetch('/api/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ visitor_id: this.visitorId, title })
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '创建会话失败');
            }
            
            const data = await resp.json();
            this.currentSessionId = data.id;
            return data;
        } catch (error) {
            console.error('创建会话失败:', error);
            throw error;
        }
    }

    async getSessions() {
        try {
            const resp = await fetch(`/api/sessions?visitor_id=${this.visitorId}`);
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '获取会话失败');
            }
            
            const data = await resp.json();
            this.sessions = data.sessions || [];
            return this.sessions;
        } catch (error) {
            console.error('获取会话失败:', error);
            return [];
        }
    }

    async loadSession(sessionId) {
        try {
            const resp = await fetch(`/api/sessions/${sessionId}?visitor_id=${this.visitorId}`);
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '加载会话失败');
            }
            
            const data = await resp.json();
            this.currentSessionId = sessionId;
            return data;
        } catch (error) {
            console.error('加载会话失败:', error);
            throw error;
        }
    }

    async deleteSession(sessionId) {
        try {
            const resp = await fetch(`/api/sessions/${sessionId}?visitor_id=${this.visitorId}`, {
                method: 'DELETE'
            });
            
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || '删除会话失败');
            }
            
            if (this.currentSessionId === sessionId) {
                this.currentSessionId = null;
            }
            
            return await resp.json();
        } catch (error) {
            console.error('删除会话失败:', error);
            throw error;
        }
    }

    getCurrentSessionId() {
        return this.currentSessionId;
    }

    setCurrentSessionId(sessionId) {
        this.currentSessionId = sessionId;
    }

    clearCurrentSession() {
        this.currentSessionId = null;
    }

    formatTime(timestamp) {
        const d = new Date(timestamp);
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        
        if (isToday) {
            return `今天 ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
        }
        return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    }
}

window.sessionManager = new SessionManager();
