(() => {
    "use strict";

    // ========== 状态管理 ==========
    const state = {
        messages: [],           // 当前对话消息 [{role, content}]
        sessionId: null,        // 当前会话ID
        isRecording: false,
        isStreaming: false,
        recognition: null,
        visitorId: null,        // 访客唯一标识
        usageInfo: null,        // 使用情况信息
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
        fileBtn: $("#fileBtn"),
        fileInput: $("#fileInput"),
    };

    // ========== 语音识别 (使用后端 DashScope ASR) ==========
    let mediaRecorder = null;
    let audioChunks = [];
    let recordingStartTime = null;
    let recordingTimer = null;
    let audioContext = null;
    let analyser = null;
    let dataArray = null;
    let animationId = null;
    const MAX_RECORDING_SECONDS = 20;  // 最大录音时长

    function initSpeechRecognition() {
        console.log("初始化语音识别...");
        
        // 检查浏览器是否支持 MediaRecorder
        if (!navigator.mediaDevices || !window.MediaRecorder) {
            console.warn("浏览器不支持录音");
            els.voiceBtn.title = "当前浏览器不支持录音，请使用Chrome/Edge/Safari";
            return;
        }
        
        console.log("MediaRecorder 支持检测通过");
        console.log("voiceBtn 元素:", els.voiceBtn);

        // 使用后端 ASR ，前端只负责录音
        state.recognition = {
            start: startRecording,
            stop: stopRecording
        };
        
        console.log("语音识别初始化完成");
    }

    function formatDuration(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    function updateRecordingTimer() {
        if (!recordingStartTime) return;
        const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
        const remaining = MAX_RECORDING_SECONDS - elapsed;
        const durationText = formatDuration(elapsed);
        
        // 显示倒计时，最后 5 秒变红
        const isWarning = remaining <= 5;
        const timerClass = isWarning ? 'recording-timer warning' : 'recording-timer';
        els.voiceStatusText.innerHTML = `正在录音 <span class="${timerClass}">${durationText}</span> / 20秒`;
        
        // 超过 20 秒自动停止
        if (elapsed >= MAX_RECORDING_SECONDS) {
            console.log("录音超过 20 秒，自动停止");
            stopRecording();
        }
    }

    function initAudioVisualizer(stream) {
        // 创建音频分析器
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        
        const bufferLength = analyser.frequencyBinCount;
        dataArray = new Uint8Array(bufferLength);
        
        // 创建波形容器
        let waveContainer = document.getElementById('audioWaveform');
        if (!waveContainer) {
            waveContainer = document.createElement('div');
            waveContainer.id = 'audioWaveform';
            waveContainer.className = 'audio-waveform';
            // 创建波形条
            for (let i = 0; i < 20; i++) {
                const bar = document.createElement('div');
                bar.className = 'wave-bar';
                waveContainer.appendChild(bar);
            }
            els.voiceStatus.appendChild(waveContainer);
        }
        
        const bars = waveContainer.querySelectorAll('.wave-bar');
        
        function animate() {
            if (!state.isRecording) return;
            
            analyser.getByteFrequencyData(dataArray);
            
            // 更新波形条高度
            for (let i = 0; i < bars.length; i++) {
                const dataIndex = Math.floor(i * (bufferLength / bars.length));
                const value = dataArray[dataIndex];
                const height = Math.max(4, (value / 255) * 40);
                bars[i].style.height = `${height}px`;
            }
            
            animationId = requestAnimationFrame(animate);
        }
        
        animate();
    }

    function stopAudioVisualizer() {
        if (animationId) {
            cancelAnimationFrame(animationId);
            animationId = null;
        }
        if (audioContext) {
            audioContext.close();
            audioContext = null;
        }
        // 重置波形条
        const waveContainer = document.getElementById('audioWaveform');
        if (waveContainer) {
            const bars = waveContainer.querySelectorAll('.wave-bar');
            bars.forEach(bar => bar.style.height = '4px');
        }
    }

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // 使用 MediaRecorder 录制音频
            const mimeType = MediaRecorder.isTypeSupported('audio/webm') 
                ? 'audio/webm' 
                : 'audio/mp4';
            
            mediaRecorder = new MediaRecorder(stream, { mimeType });
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                console.log("onstop 触发, audioChunks 长度:", audioChunks.length);
                
                // 停止计时器和波形动画
                if (recordingTimer) {
                    clearInterval(recordingTimer);
                    recordingTimer = null;
                }
                stopAudioVisualizer();
                recordingStartTime = null;
                
                if (audioChunks.length === 0) {
                    console.warn("没有收集到音频数据");
                    alert("录音时间太短，请重试");
                    return;
                }
                
                const audioBlob = new Blob(audioChunks, { type: mimeType });
                console.log("音频 Blob 大小:", audioBlob.size, "bytes");
                
                await sendAudioToServer(audioBlob);
                
                // 停止所有音轨
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start(100); // 每100ms收集一次数据
            
            // 开始计时
            recordingStartTime = Date.now();
            updateRecordingTimer();
            recordingTimer = setInterval(updateRecordingTimer, 1000);
            
            // 初始化波形动画
            initAudioVisualizer(stream);
            
            state.isRecording = true;
            els.voiceBtn.classList.add("recording");
            els.voiceStatus.classList.remove("hidden");
            console.log("录音开始");
            
        } catch (err) {
            console.error("启动录音失败:", err);
            alert("启动录音失败，请检查麦克风权限: " + err.message);
        }
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
            console.log("录音停止");
        }
        state.isRecording = false;
        els.voiceBtn.classList.remove("recording");
        els.voiceStatus.classList.add("hidden");
    }

    async function sendAudioToServer(audioBlob) {
        console.log("sendAudioToServer 被调用");
        
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        try {
            els.voiceStatusText.textContent = "正在识别...";
            console.log("开始发送请求到 /api/speech-to-text");
            
            const response = await fetch('/api/speech-to-text', {
                method: 'POST',
                body: formData
            });
            
            console.log("收到响应:", response.status);

            const data = await response.json();
            console.log("响应数据:", data);
            
            if (data.error) {
                console.error("识别错误:", data.error);
                alert("语音识别失败: " + data.error);
            } else if (data.text) {
                els.textInput.value = data.text;
                autoResizeTextarea();
                els.textInput.focus();
                console.log("识别结果:", data.text);
            } else {
                console.warn("响应中没有 text 字段");
            }
        } catch (err) {
            console.error("发送音频失败:", err);
            alert("语音识别服务错误: " + err.message);
        }
    }

    function toggleRecording() {
        console.log("toggleRecording 被调用, state.recognition:", state.recognition, "state.isRecording:", state.isRecording);
        
        if (!state.recognition) {
            alert("当前浏览器不支持语音识别，请使用Chrome浏览器，或直接输入文字。");
            return;
        }
        if (state.isRecording) {
            console.log("停止录音...");
            try {
                state.recognition.stop();
            } catch (e) {
                console.error("停止录音失败:", e);
                // 强制重置状态
                state.isRecording = false;
                els.voiceBtn.classList.remove("recording");
                els.voiceStatus.classList.add("hidden");
            }
        } else {
            console.log("开始录音...");
            els.textInput.value = "";
            try {
                state.recognition.start();
            } catch (e) {
                console.error("启动录音失败:", e);
                alert("启动录音失败，请检查麦克风权限。错误: " + e.message);
                // 重置状态
                state.isRecording = false;
                els.voiceBtn.classList.remove("recording");
                els.voiceStatus.classList.add("hidden");
            }
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

    // ========== API调用（带重试机制） ==========
    async function sendToAPIWithRetry(messages, maxRetries = 2) {
        let lastError = null;
        
        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                if (attempt > 0) {
                    console.log(`第 ${attempt} 次重试...`);
                    // 显示重试提示
                    const retryMsg = attempt === 1 ? "连接不稳定，正在重试..." : `正在第 ${attempt} 次重试...`;
                    addMessageToDOM("ai", retryMsg);
                    await new Promise(r => setTimeout(r, 1000)); // 等待 1 秒后重试
                }
                
                const result = await sendToAPIInternal(messages);
                return result;
            } catch (error) {
                lastError = error;
                console.error(`尝试 ${attempt + 1} 失败:`, error);
                
                // 如果是限制错误，不重试
                if (error.message && error.message.includes("次数已用完")) {
                    throw error;
                }
                
                // 最后一次尝试失败，抛出错误
                if (attempt === maxRetries) {
                    throw error;
                }
            }
        }
    }

    async function sendToAPIInternal(messages) {
        state.isStreaming = true;
        els.sendBtn.disabled = true;

        const typingBubble = addTypingIndicator();
        let fullContent = "";
        let lastChunkTime = Date.now();
        const CHUNK_TIMEOUT = 30000; // 30 秒无数据视为超时

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { 
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream"
                },
                body: JSON.stringify({ messages, visitor_id: state.visitorId }),
            });
            
            // 检查是否触发限制
            if (response.status === 429) {
                const errorData = await response.json();
                removeTypingIndicator();
                addMessageToDOM("ai", `⚠️ ${errorData.error}`);
                showLimitReachedModal();
                return;
            }

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
                // 检查超时
                if (Date.now() - lastChunkTime > CHUNK_TIMEOUT) {
                    throw new Error("响应超时");
                }

                const { done, value } = await reader.read();
                if (done) break;

                // 更新最后接收时间
                lastChunkTime = Date.now();

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
            
            // 增加使用次数
            incrementUsageCount();

            // 显示操作按钮
            if (state.messages.length >= 4) {
                els.actionBar.classList.remove("hidden");
            }
            
            return fullContent;
        } catch (error) {
            removeTypingIndicator();
            throw error;
        } finally {
            state.isStreaming = false;
            els.sendBtn.disabled = false;
        }
    }

    // 对外暴露的 API 调用函数（带重试）
    async function sendToAPI(messages) {
        try {
            return await sendToAPIWithRetry(messages);
        } catch (error) {
            addMessageToDOM("ai", `出错了: ${error.message}`);
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

    // ========== 发送图片消息 ==========
    async function sendImageMessage(file, imageUrl) {
        // 切换到对话视图
        els.welcomeView.classList.add('hidden');
        els.chatView.classList.remove('hidden');

        // 如果是新会话
        if (!state.sessionId) {
            state.sessionId = Date.now().toString();
        }

        // 添加用户消息（显示用）
        addFileMessage('user', file, imageUrl);

        // 添加消息到状态（多模态格式）
        state.messages.push({
            role: "user",
            content: `我上传了一张图片"${file.name}"，请帮我分析。`,
            image_url: imageUrl
        });

        // 清空输入
        els.textInput.value = "";
        autoResizeTextarea();

        // 发送到API
        await sendToAPI(state.messages);
    }

    // ========== 文件上传 ==========
    function initFileUpload() {
        els.fileBtn.addEventListener("click", () => {
            els.fileInput.click();
        });

        els.fileInput.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            // 检查文件类型
            const allowedTypes = [
                'text/plain', 'text/markdown', 'application/pdf',
                'image/jpeg', 'image/png', 'image/gif', 'image/webp',
                'audio/mpeg', 'audio/wav', 'audio/x-m4a', 'audio/webm'
            ];
            const allowedExts = ['.txt', '.md', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp3', '.wav', '.m4a', '.webm'];
            
            const ext = '.' + file.name.split('.').pop().toLowerCase();
            state.currentFileExt = ext; // 保存扩展供后续使用
            
            if (!allowedTypes.includes(file.type) && !allowedExts.includes(ext)) {
                alert('不支持的文件类型。支持：文本、PDF、图片、音频文件');
                return;
            }

            // 检查文件大小 (10MB)
            if (file.size > 10 * 1024 * 1024) {
                alert('文件太大，最大支持 10MB');
                return;
            }

            await uploadFile(file);
            els.fileInput.value = ''; // 清空以便重复上传
        });
    }

    async function uploadFile(file) {
        els.fileBtn.classList.add('uploading');
        els.fileBtn.disabled = true;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || '上传失败');
            }

            // 如果是文本文件，读取内容并发送
            const fileExt = state.currentFileExt || '';
            if (file.type === 'text/plain' || file.type === 'text/markdown' || fileExt === '.txt' || fileExt === '.md') {
                // 切换到对话视图
                els.welcomeView.classList.add('hidden');
                els.chatView.classList.remove('hidden');
                // 添加文件消息到界面
                addFileMessage('user', file, data.url);
                const text = await file.text();
                els.textInput.value = `我上传了一个文件"${file.name}"，内容如下：\n\n${text}`;
                await sendMessage();
            } else if (file.type.startsWith('image/')) {
                // 对于图片，使用 R2 公开 URL 发送
                // 添加短暂延迟，确保 R2 图片完全可用
                await new Promise(r => setTimeout(r, 800));
                await sendImageMessage(file, data.url);
            } else if (file.name.toLowerCase().endsWith('.pdf')) {
                // 处理 PDF 文件
                els.welcomeView.classList.add('hidden');
                els.chatView.classList.remove('hidden');
                addFileMessage('user', file, data.url);
                
                if (data.pdf_content && data.pdf_content.success) {
                    const { text, pages } = data.pdf_content;
                    els.textInput.value = `我上传了一个 PDF 文件"${file.name}"，共 ${pages} 页，内容如下：\n\n${text}\n\n请帮我分析这个 PDF 的内容。`;
                    await sendMessage();
                } else {
                    els.textInput.value = `我上传了一个 PDF 文件"${file.name}"，但无法提取内容。链接：${data.url}\n\n请帮我分析。`;
                    await sendMessage();
                }
            } else {
                // 切换到对话视图
                els.welcomeView.classList.add('hidden');
                els.chatView.classList.remove('hidden');
                // 添加文件消息到界面
                addFileMessage('user', file, data.url);
                // 对于音频，发送描述消息
                els.textInput.value = `我上传了一个音频"${file.name}"，链接：${data.url}\n\n请帮我分析这个音频。`;
                await sendMessage();
            }

        } catch (error) {
            alert('上传失败: ' + error.message);
        } finally {
            els.fileBtn.classList.remove('uploading');
            els.fileBtn.disabled = false;
        }
    }

    function addFileMessage(role, file, url) {
        const div = document.createElement('div');
        div.className = `message ${role}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        // 文件图标
        let icon = '📄';
        if (file.type.startsWith('image/')) icon = '🖼️';
        else if (file.type.startsWith('audio/')) icon = '🎵';
        else if (file.name.endsWith('.pdf')) icon = '📑';
        else if (file.name.endsWith('.txt') || file.name.endsWith('.md')) icon = '📝';

        let content = `<div>上传了 ${icon} ${file.name}</div>`;
        
        // 图片预览
        if (file.type.startsWith('image/')) {
            content += `<img src="${url}" class="file-preview" alt="${file.name}">`;
        } else {
            content += `<div class="message-file"><span class="file-icon">${icon}</span><span class="file-name">${file.name}</span></div>`;
        }

        bubble.innerHTML = content;
        div.appendChild(bubble);
        els.chatMessages.appendChild(div);
        scrollToBottom();
    }

    // ========== 示例提示词 ==========
    function initExamplePrompts() {
        document.querySelectorAll('.example-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                els.textInput.value = prompt;
                autoResizeTextarea();
                sendMessage();
            });
        });
    }

    // ========== 新手引导 ==========
    function initGuide() {
        // 检查是否已看过引导
        const hasSeenGuide = localStorage.getItem('has_seen_guide');
        if (hasSeenGuide) return;
        
        const guideOverlay = document.getElementById('guideOverlay');
        const steps = [
            document.getElementById('guideStep1'),
            document.getElementById('guideStep2'),
            document.getElementById('guideStep3')
        ];
        let currentStep = 0;
        
        // 显示引导
        guideOverlay.classList.remove('hidden');
        
        // 绑定下一步按钮
        guideOverlay.querySelectorAll('.guide-next').forEach(btn => {
            btn.addEventListener('click', () => {
                const nextStep = btn.dataset.step;
                
                if (nextStep === 'finish') {
                    // 完成引导
                    guideOverlay.classList.add('hidden');
                    localStorage.setItem('has_seen_guide', 'true');
                } else {
                    // 切换到下一步
                    steps[currentStep].classList.add('hidden');
                    currentStep = parseInt(nextStep) - 1;
                    steps[currentStep].classList.remove('hidden');
                }
            });
        });
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

        initFileUpload();
        initExamplePrompts();
    }

    // ========== 访客标识管理 ==========
    function getOrCreateVisitorId() {
        let visitorId = localStorage.getItem("visitor_id");
        if (!visitorId) {
            // 生成唯一标识: 时间戳 + 随机数 + 浏览器指纹简版
            const fingerprint = navigator.userAgent.slice(0, 20) + screen.width + screen.height;
            visitorId = "v_" + Date.now() + "_" + Math.random().toString(36).substr(2, 9) + "_" + btoa(fingerprint).slice(0, 8);
            localStorage.setItem("visitor_id", visitorId);
        }
        state.visitorId = visitorId;
        return visitorId;
    }

    async function fetchUsageInfo() {
        const visitorId = getOrCreateVisitorId();
        try {
            const resp = await fetch("/api/usage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ visitor_id: visitorId })
            });
            const data = await resp.json();
            if (!data.error) {
                state.usageInfo = data;
                updateUsageDisplay();
            }
        } catch (e) {
            console.error("获取使用信息失败:", e);
        }
    }

    async function incrementUsageCount() {
        const visitorId = state.visitorId;
        if (!visitorId) return;
        
        try {
            const resp = await fetch("/api/increment-usage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ visitor_id: visitorId })
            });
            const data = await resp.json();
            if (!data.error) {
                state.usageInfo = {
                    ...state.usageInfo,
                    used_today: data.count,
                    remaining: data.remaining
                };
                updateUsageDisplay();
            }
        } catch (e) {
            console.error("更新使用次数失败:", e);
        }
    }

    function updateUsageDisplay() {
        if (!state.usageInfo) return;
        
        const { remaining, daily_limit } = state.usageInfo;
        let usageBadge = document.getElementById("usageBadge");
        
        if (!usageBadge) {
            usageBadge = document.createElement("div");
            usageBadge.id = "usageBadge";
            usageBadge.className = "usage-badge";
            document.querySelector(".top-bar").appendChild(usageBadge);
        }
        
        usageBadge.textContent = `今日剩余: ${remaining}/${daily_limit}`;
        usageBadge.className = "usage-badge" + (remaining <= 3 ? " low" : "");
        
        // 如果次数用完，禁用输入
        if (remaining <= 0) {
            els.textInput.placeholder = "今日免费次数已用完，请明天再来";
            els.textInput.disabled = true;
            els.sendBtn.disabled = true;
            els.voiceBtn.disabled = true;
            els.fileBtn.disabled = true;
        }
    }

    function showLimitReachedModal() {
        const modal = document.createElement("div");
        modal.className = "limit-modal";
        modal.innerHTML = `
            <div class="limit-modal-content">
                <h3>今日次数已用完</h3>
                <p>您已达到今日免费使用上限（${state.usageInfo?.daily_limit || 10}次）</p>
                <p class="reset-time">次数将在次日 00:00 重置</p>
                <button onclick="this.closest('.limit-modal').remove()">我知道了</button>
            </div>
        `;
        document.body.appendChild(modal);
    }

    // ========== 初始化 ==========
    async function init() {
        initSpeechRecognition();
        bindEvents();
        renderHistory();
        
        // 初始化访客标识并获取使用信息
        getOrCreateVisitorId();
        await fetchUsageInfo();
        
        // 初始化新手引导
        initGuide();

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
