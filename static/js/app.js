(() => {
    "use strict";

    // ========== 状态管理 ==========
    const state = {
        messages: [],           // 当前对话消息 [{role, content}]
        sessionId: null,        // 当前会话ID
        isRecording: false,
        isStreaming: false,
        recognition: null,
    };

    // ========== DOM元素 ==========
    const $ = (sel) => document.querySelector(sel);
    const els = {
        sidebar: $("#sidebar"),
        overlay: $("#overlay"),
        openSidebar: $("#openSidebar"),
        closeSidebar: $("#closeSidebar"),
        historyList: $("#historyList"),
        welcomeView: $("#welcomeView"),
        chatView: $("#chatView"),
        chatMessages: $("#chatMessages"),
        textInput: $("#textInput"),
        voiceBtn: $("#voiceBtn"),
        sendBtn: $("#sendBtn"),
        voiceStatus: $("#voiceStatus"),
        voiceStatusText: $("#voiceStatusText"),
        actionBar: $("#actionBar"),
        summarizeBtn: $("#summarizeBtn"),
        exportBtn: $("#exportBtn"),
        newSession: $("#newSession"),
    };

    // ========== 语音识别 ==========
    function initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.warn("浏览器不支持语音识别");
            els.voiceBtn.title = "当前浏览器不支持语音识别，请使用Chrome";
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.lang = "zh-CN";
        recognition.continuous = true;
        recognition.interimResults = true;

        let finalTranscript = "";

        recognition.onresult = (event) => {
            let interim = "";
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interim += transcript;
                }
            }
            els.textInput.value = finalTranscript + interim;
            autoResizeTextarea();
        };

        recognition.onstart = () => {
            state.isRecording = true;
            finalTranscript = "";
            els.voiceBtn.classList.add("recording");
            els.voiceStatus.classList.remove("hidden");
            els.voiceStatusText.textContent = "正在录音，请说话...";
        };

        recognition.onend = () => {
            state.isRecording = false;
            els.voiceBtn.classList.remove("recording");
            els.voiceStatus.classList.add("hidden");
            // 如果有内容则自动聚焦输入框
            if (els.textInput.value.trim()) {
                els.textInput.focus();
            }
        };

        recognition.onerror = (event) => {
            console.error("语音识别错误:", event.error);
            state.isRecording = false;
            els.voiceBtn.classList.remove("recording");
            els.voiceStatus.classList.add("hidden");

            if (event.error === "not-allowed") {
                alert("请允许麦克风权限后重试");
            }
        };

        state.recognition = recognition;
    }

    function toggleRecording() {
        if (!state.recognition) {
            alert("当前浏览器不支持语音识别，请使用Chrome浏览器，或直接输入文字。");
            return;
        }
        if (state.isRecording) {
            state.recognition.stop();
        } else {
            els.textInput.value = "";
            state.recognition.start();
        }
    }

    // ========== Markdown简易解析 ==========
    function renderMarkdown(text) {
        let html = text
            // 转义HTML
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            // 标题
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            // 粗体和斜体
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/\*(.+?)\*/g, "<em>$1</em>")
            // 无序列表
            .replace(/^[\-\*] (.+)$/gm, "<li>$1</li>")
            // 有序列表
            .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
            // 段落
            .replace(/\n\n/g, "</p><p>")
            .replace(/\n/g, "<br>");

        // 包裹连续的li标签
        html = html.replace(/(<li>.*?<\/li>(?:<br>)?)+/g, (match) => {
            const items = match.replace(/<br>/g, "");
            return `<ul>${items}</ul>`;
        });

        return `<div class="markdown-content"><p>${html}</p></div>`;
    }

    // ========== 消息渲染 ==========
    function addMessageToDOM(role, content, animate = true) {
        const div = document.createElement("div");
        div.className = `message ${role}`;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";

        if (role === "ai") {
            bubble.innerHTML = renderMarkdown(content);
        } else {
            bubble.textContent = content;
        }

        if (!animate) div.style.animation = "none";
        div.appendChild(bubble);
        els.chatMessages.appendChild(div);
        scrollToBottom();
        return bubble;
    }

    function addTypingIndicator() {
        const div = document.createElement("div");
        div.className = "message ai";
        div.id = "typingMsg";

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;

        div.appendChild(bubble);
        els.chatMessages.appendChild(div);
        scrollToBottom();
        return bubble;
    }

    function removeTypingIndicator() {
        const el = document.getElementById("typingMsg");
        if (el) el.remove();
    }

    function scrollToBottom() {
        els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    }

    // ========== API调用 ==========
    async function sendToAPI(messages) {
        state.isStreaming = true;
        els.sendBtn.disabled = true;

        const typingBubble = addTypingIndicator();
        let fullContent = "";

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages }),
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || "请求失败");
            }

            removeTypingIndicator();
            const aiBubble = addMessageToDOM("ai", "");

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const data = line.slice(6).trim();
                    if (data === "[DONE]") continue;

                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.error) throw new Error(parsed.error);
                        if (parsed.content) {
                            fullContent += parsed.content;
                            aiBubble.innerHTML = renderMarkdown(fullContent);
                            scrollToBottom();
                        }
                    } catch (e) {
                        if (e.message && !e.message.includes("JSON")) {
                            throw e;
                        }
                    }
                }
            }

            // 保存AI消息
            state.messages.push({ role: "assistant", content: fullContent });
            autoSave();

            // 显示操作按钮
            if (state.messages.length >= 4) {
                els.actionBar.classList.remove("hidden");
            }
        } catch (error) {
            removeTypingIndicator();
            addMessageToDOM("ai", `出错了: ${error.message}`);
        } finally {
            state.isStreaming = false;
            els.sendBtn.disabled = false;
        }
    }

    // ========== 发送消息 ==========
    async function sendMessage() {
        const text = els.textInput.value.trim();
        if (!text || state.isStreaming) return;

        // 如果正在录音，先停止
        if (state.isRecording && state.recognition) {
            state.recognition.stop();
        }

        // 切换到对话视图
        els.welcomeView.classList.add("hidden");
        els.chatView.classList.remove("hidden");

        // 如果是新会话
        if (!state.sessionId) {
            state.sessionId = Date.now().toString();
        }

        // 添加用户消息
        state.messages.push({ role: "user", content: text });
        addMessageToDOM("user", text);

        // 清空输入
        els.textInput.value = "";
        autoResizeTextarea();

        // 发送到API
        await sendToAPI(state.messages);
    }

    // ========== 快捷操作 ==========
    async function requestSummary() {
        if (state.isStreaming) return;

        const text = "请根据我们之前的讨论，整理输出一份完整的总结。";
        els.textInput.value = "";

        state.messages.push({ role: "user", content: text });
        addMessageToDOM("user", text);

        await sendToAPI(state.messages);
    }

    function exportContent() {
        if (state.messages.length === 0) return;

        // 找到最后一条AI消息作为总结
        let exportText = "# 灵感风暴记录\n\n";
        exportText += `日期: ${new Date().toLocaleString("zh-CN")}\n\n---\n\n`;

        for (const msg of state.messages) {
            if (msg.role === "user") {
                exportText += `**我:** ${msg.content}\n\n`;
            } else {
                exportText += `**AI助手:**\n\n${msg.content}\n\n---\n\n`;
            }
        }

        // 下载文件
        const blob = new Blob([exportText], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `灵感风暴_${new Date().toLocaleDateString("zh-CN").replace(/\//g, "-")}.md`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // ========== 本地存储 ==========
    function autoSave() {
        if (!state.sessionId || state.messages.length === 0) return;

        const sessions = getSessions();
        const firstUserMsg = state.messages.find(m => m.role === "user");
        const title = firstUserMsg
            ? firstUserMsg.content.slice(0, 50) + (firstUserMsg.content.length > 50 ? "..." : "")
            : "新对话";

        sessions[state.sessionId] = {
            id: state.sessionId,
            title,
            messages: state.messages,
            updatedAt: Date.now(),
        };

        localStorage.setItem("brainstorm_sessions", JSON.stringify(sessions));
        renderHistory();
    }

    function getSessions() {
        try {
            return JSON.parse(localStorage.getItem("brainstorm_sessions") || "{}");
        } catch {
            return {};
        }
    }

    function loadSession(sessionId) {
        const sessions = getSessions();
        const session = sessions[sessionId];
        if (!session) return;

        state.sessionId = sessionId;
        state.messages = session.messages;

        // 清空并重新渲染
        els.chatMessages.innerHTML = "";
        els.welcomeView.classList.add("hidden");
        els.chatView.classList.remove("hidden");

        for (const msg of state.messages) {
            addMessageToDOM(msg.role === "assistant" ? "ai" : "user", msg.content, false);
        }

        if (state.messages.length >= 4) {
            els.actionBar.classList.remove("hidden");
        }

        closeSidebar();
        scrollToBottom();
    }

    function deleteSession(sessionId) {
        const sessions = getSessions();
        delete sessions[sessionId];
        localStorage.setItem("brainstorm_sessions", JSON.stringify(sessions));

        if (state.sessionId === sessionId) {
            newSession();
        }
        renderHistory();
    }

    function newSession() {
        state.sessionId = null;
        state.messages = [];
        els.chatMessages.innerHTML = "";
        els.chatView.classList.add("hidden");
        els.welcomeView.classList.remove("hidden");
        els.actionBar.classList.add("hidden");
        els.textInput.value = "";
        renderHistory();
    }

    // ========== 历史记录渲染 ==========
    function renderHistory() {
        const sessions = getSessions();
        const sorted = Object.values(sessions).sort((a, b) => b.updatedAt - a.updatedAt);

        if (sorted.length === 0) {
            els.historyList.innerHTML = '<p class="empty-hint">暂无记录</p>';
            return;
        }

        els.historyList.innerHTML = sorted.map(s => `
            <div class="history-item ${s.id === state.sessionId ? 'active' : ''}" data-id="${s.id}">
                <div class="history-item-title">${escapeHtml(s.title)}</div>
                <div class="history-item-time">${formatTime(s.updatedAt)}</div>
                <button class="history-item-delete" data-id="${s.id}" title="删除">&times;</button>
            </div>
        `).join("");

        // 绑定事件
        els.historyList.querySelectorAll(".history-item").forEach(el => {
            el.addEventListener("click", (e) => {
                if (e.target.classList.contains("history-item-delete")) return;
                loadSession(el.dataset.id);
            });
        });

        els.historyList.querySelectorAll(".history-item-delete").forEach(el => {
            el.addEventListener("click", (e) => {
                e.stopPropagation();
                if (confirm("确定删除这条记录？")) {
                    deleteSession(el.dataset.id);
                }
            });
        });
    }

    function formatTime(timestamp) {
        const d = new Date(timestamp);
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        if (isToday) {
            return `今天 ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
        }
        return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== 侧边栏 ==========
    function openSidebar() {
        els.sidebar.classList.add("open");
        els.overlay.classList.add("show");
    }

    function closeSidebar() {
        els.sidebar.classList.remove("open");
        els.overlay.classList.remove("show");
    }

    // ========== 输入框自适应高度 ==========
    function autoResizeTextarea() {
        const ta = els.textInput;
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
    }

    // ========== 事件绑定 ==========
    function bindEvents() {
        els.voiceBtn.addEventListener("click", toggleRecording);
        els.sendBtn.addEventListener("click", sendMessage);
        els.summarizeBtn.addEventListener("click", requestSummary);
        els.exportBtn.addEventListener("click", exportContent);
        els.newSession.addEventListener("click", newSession);
        els.openSidebar.addEventListener("click", openSidebar);
        els.closeSidebar.addEventListener("click", closeSidebar);
        els.overlay.addEventListener("click", closeSidebar);

        els.textInput.addEventListener("input", autoResizeTextarea);
        els.textInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // ========== 初始化 ==========
    async function init() {
        initSpeechRecognition();
        bindEvents();
        renderHistory();

        // 检查API配置
        try {
            const resp = await fetch("/api/check");
            const data = await resp.json();
            if (!data.configured) {
                addMessageToDOM("ai", "请先配置API Key。在启动服务时设置环境变量：\n\n`export DASHSCOPE_API_KEY=你的API密钥`\n\n然后重启服务。");
                els.welcomeView.classList.add("hidden");
                els.chatView.classList.remove("hidden");
            }
        } catch (e) {
            console.error("检查API配置失败:", e);
        }
    }

    init();
})();
