const DEFAULT_AGENT_BASE_URL = 'http://192.168.1.135:8000';
const DEFAULT_TRANSCRIBE_BASE_URL = 'http://192.168.1.135:3010';

const threadListEl = document.getElementById('threadList');
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const recordButton = document.getElementById('recordButton');
const debugButton = document.getElementById('debugButton');
const recordingStatusEl = document.getElementById('recordingStatus');
const serviceStatusDotEl = document.getElementById('serviceStatusDot');
const serviceStatusTextEl = document.getElementById('serviceStatusText');
const newChatButton = document.getElementById('newChatButton');

const DEFAULT_THREAD_TITLE = 'New chat';
const HEALTH_CHECK_INTERVAL_MS = 5000;
const serviceHealthTargets = [
  { name: 'agent', url: `${DEFAULT_AGENT_BASE_URL}/health` },
  { name: 'transcribe', url: `${DEFAULT_TRANSCRIBE_BASE_URL}/health` },
];

const state = {
  threads: [],
  currentThreadId: null,
  mediaRecorder: null,
  mediaStream: null,
  isRecording: false,
  isProcessingRecording: false,
  isCheckingServices: false,
};

async function isServiceAvailable(url) {
  try {
    const response = await fetch(url, { method: 'GET' });
    return response.ok;
  } catch {
    return false;
  }
}

function updateServiceStatusUi(unavailableServices) {
  if (unavailableServices.length === 0) {
    serviceStatusDotEl.classList.remove('status-error');
    serviceStatusDotEl.classList.add('status-ok');
    serviceStatusTextEl.textContent = 'Connections available';
    return;
  }

  serviceStatusDotEl.classList.remove('status-ok');
  serviceStatusDotEl.classList.add('status-error');
  serviceStatusTextEl.textContent = `Unavailable: ${unavailableServices.join(', ')}`;
}

async function refreshServiceStatus() {
  if (state.isCheckingServices) {
    return;
  }

  state.isCheckingServices = true;
  try {
    const checks = await Promise.all(
      serviceHealthTargets.map(async (service) => ({
        name: service.name,
        ok: await isServiceAvailable(service.url),
      })),
    );
    const unavailable = checks.filter((item) => !item.ok).map((item) => item.name);
    updateServiceStatusUi(unavailable);
  } finally {
    state.isCheckingServices = false;
  }
}

function setRecordingStatus(message = '', statusClass = '') {
  recordingStatusEl.textContent = message;
  recordingStatusEl.classList.remove('recording', 'processing');
  recordButton.classList.remove('recording', 'processing');

  if (statusClass) {
    recordingStatusEl.classList.add(statusClass);
    recordButton.classList.add(statusClass);
  }
}

const MIC_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>';
const STOP_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>';
const SPINNER_ICON = '<svg class="spin-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-9-9"></path></svg>';

function setIdleRecordUi() {
  recordButton.innerHTML = MIC_ICON;
  recordButton.disabled = false;
  recordButton.setAttribute('aria-label', 'Start recording');
  recordButton.setAttribute('title', 'Start recording');
  setRecordingStatus('', '');
}

function setRecordingUi() {
  recordButton.innerHTML = STOP_ICON;
  recordButton.disabled = false;
  recordButton.setAttribute('aria-label', 'Stop recording');
  recordButton.setAttribute('title', 'Stop recording');
  setRecordingStatus('Recording... click Stop when you are done.', 'recording');
}

function setProcessingUi() {
  recordButton.innerHTML = SPINNER_ICON;
  recordButton.disabled = true;
  recordButton.setAttribute('aria-label', 'Transcribing');
  recordButton.setAttribute('title', 'Transcribing');
  setRecordingStatus('Transcribing and sending your message...', 'processing');
}

function createThread(title = DEFAULT_THREAD_TITLE) {
  const id = `thread-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const thread = {
    id,
    title,
    messages: [],
  };
  state.threads.push(thread);
  state.currentThreadId = id;
  renderThreads();
  renderMessages();
  notifyStateChanged();
  return thread;
}

function renderThreads() {
  threadListEl.innerHTML = '';
  state.threads.forEach((thread) => {
    const item = document.createElement('li');
    item.dataset.threadId = thread.id;

    const titleEl = document.createElement('span');
    titleEl.className = 'thread-title';
    titleEl.textContent = thread.title;
    item.appendChild(titleEl);

    const deleteButton = document.createElement('button');
    deleteButton.className = 'thread-delete-button';
    deleteButton.textContent = '✕';
    deleteButton.setAttribute('aria-label', `Delete ${thread.title}`);
    deleteButton.title = 'Delete chat';
    deleteButton.addEventListener('click', (event) => {
      event.stopPropagation();
      if (window.confirm(`Delete "${thread.title}"?`)) {
        deleteThread(thread.id);
      }
    });
    item.appendChild(deleteButton);

    item.addEventListener('click', () => {
      state.currentThreadId = thread.id;
      renderMessages();
      notifyStateChanged();
    });
    threadListEl.appendChild(item);
  });
}

function deleteThread(threadId) {
  const index = state.threads.findIndex((thread) => thread.id === threadId);
  if (index === -1) {
    return;
  }

  state.threads.splice(index, 1);

  if (state.currentThreadId === threadId) {
    state.currentThreadId = state.threads.length > 0 ? state.threads[0].id : null;
  }

  if (state.threads.length === 0) {
    createThread();
    return;
  }

  renderThreads();
  renderMessages();
  notifyStateChanged();
}

function renderMessages() {
  messagesEl.innerHTML = '';
  const thread = state.threads.find((item) => item.id === state.currentThreadId);
  if (!thread) {
    return;
  }

  for (const message of thread.messages) {
    const row = document.createElement('div');
    row.className = `message-row ${message.role}`;

    const avatar = document.createElement('img');
    avatar.className = 'avatar';
    avatar.src = message.role === 'assistant' ? 'img/jarvis.png' : 'img/ironman.png';
    avatar.alt = message.role;

    const bubble = document.createElement('div');
    bubble.className = `message ${message.role}`;
    bubble.textContent = message.text;

    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesEl.appendChild(row);
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

let thinkingIntervalId = null;
let thinkingRowEl = null;

function showThinkingIndicator() {
  hideThinkingIndicator();

  const row = document.createElement('div');
  row.className = 'message-row assistant';

  const avatar = document.createElement('img');
  avatar.className = 'avatar';
  avatar.src = 'img/jarvis.png';
  avatar.alt = 'assistant';

  const bubble = document.createElement('div');
  bubble.className = 'message assistant thinking-message';

  row.appendChild(avatar);
  row.appendChild(bubble);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  thinkingRowEl = row;

  let dotCount = 0;
  const tick = () => {
    dotCount = (dotCount % 3) + 1;
    bubble.textContent = `Jarvis is thinking${'.'.repeat(dotCount)}`;
  };
  tick();
  thinkingIntervalId = setInterval(tick, 450);
}

function hideThinkingIndicator() {
  if (thinkingIntervalId !== null) {
    clearInterval(thinkingIntervalId);
    thinkingIntervalId = null;
  }
  if (thinkingRowEl) {
    thinkingRowEl.remove();
    thinkingRowEl = null;
  }
}

function addMessage(role, text, debug = null) {
  const thread = state.threads.find((item) => item.id === state.currentThreadId);
  if (!thread) {
    return;
  }

  thread.messages.push({ role, text, debug });
  renderMessages();
  notifyStateChanged();
}

function buildDebugSnapshot() {
  return {
    currentThreadId: state.currentThreadId,
    threads: state.threads.map((thread) => ({
      id: thread.id,
      title: thread.title,
      messages: thread.messages
        .filter((message) => message.role === 'assistant' && message.debug)
        .map((message, index) => ({
          index,
          answer: message.text,
          debug: message.debug,
        })),
    })),
  };
}

function publishDebugState() {
  if (window.debugBridge && typeof window.debugBridge.updateDebugState === 'function') {
    window.debugBridge.updateDebugState(buildDebugSnapshot());
  }
}

function persistThreads() {
  if (window.threadsBridge && typeof window.threadsBridge.save === 'function') {
    window.threadsBridge.save({
      threads: state.threads,
      currentThreadId: state.currentThreadId,
    });
  }
}

function notifyStateChanged() {
  publishDebugState();
  persistThreads();
}

async function openDebugWindow() {
  if (window.debugBridge && typeof window.debugBridge.openDebugWindow === 'function') {
    await window.debugBridge.openDebugWindow();
    publishDebugState();
  }
}

async function generateThreadTitle(thread, userText, assistantText) {
  if (!thread || thread.title !== DEFAULT_THREAD_TITLE) {
    return;
  }

  try {
    const response = await fetch(`${DEFAULT_AGENT_BASE_URL}/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversationId: `title-${thread.id}`,
        user: 'user',
        message:
          'Write a short chat title (3-6 words, no quotes, no trailing punctuation) that summarizes this exchange:\n' +
          `User: ${userText}\nAssistant: ${assistantText}`,
        attachments: [],
        metadata: {
          tenant: 'desktop-electron',
          language: 'en',
          extra: { source: 'title-generation' },
        },
      }),
    });

    if (!response.ok) {
      return;
    }

    const payload = await response.json();
    const title = (payload.result || '').trim().replace(/^["'“”]+|["'“”]+$/g, '');

    if (!title || thread.title !== DEFAULT_THREAD_TITLE) {
      return;
    }

    thread.title = title.length > 60 ? `${title.slice(0, 57)}...` : title;
    renderThreads();
    notifyStateChanged();
  } catch {
    // Keep the default title if generation fails.
  }
}

async function sendTextMessage() {
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }

  if (!state.currentThreadId) {
    createThread();
  }

  const threadId = state.currentThreadId;
  addMessage('user', text);
  inputEl.value = '';
  showThinkingIndicator();

  try {
    const response = await fetch(`${DEFAULT_AGENT_BASE_URL}/agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversationId: state.currentThreadId,
        user: 'user',
        message: text,
        attachments: [],
        metadata: {
          tenant: 'desktop-electron',
          language: 'en',
          extra: { source: 'electron-ui' },
        },
      }),
    });

    if (!response.ok) {
      throw new Error(`Agent request failed: ${response.status}`);
    }

    const payload = await response.json();
    const answer = payload.result || 'No response';
    hideThinkingIndicator();
    addMessage('assistant', answer, payload.debug || null);

    const thread = state.threads.find((item) => item.id === threadId);
    if (thread && thread.messages.length === 2) {
      generateThreadTitle(thread, text, answer);
    }
  } catch (error) {
    hideThinkingIndicator();
    addMessage('assistant', `Error: ${error.message}`);
  }
}

async function recordAudio() {
  if (state.isProcessingRecording) {
    return;
  }

  if (state.isRecording && state.mediaRecorder) {
    state.mediaRecorder.stop();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    addMessage('assistant', 'Microphone access is not available in this browser.');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];

    state.mediaRecorder = recorder;
    state.mediaStream = stream;
    state.isRecording = true;
    setRecordingUi();

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };

    recorder.onstop = async () => {
      state.isRecording = false;
      state.isProcessingRecording = true;
      setProcessingUi();

      const blob = new Blob(chunks, { type: mimeType });
      const file = new File([blob], 'recording.webm', { type: mimeType });

      try {
        const formData = new FormData();
        formData.append('file', file, file.name);
        formData.append('language', 'en');

        inputEl.value = 'Transcribing audio...';
        const response = await fetch(`${DEFAULT_TRANSCRIBE_BASE_URL}/transcribe/audio`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Transcription failed: ${response.status}`);
        }

        const payload = await response.json();
        const transcript = (payload.text || '').trim();
        if (!transcript) {
          addMessage('assistant', 'No speech was detected.');
          return;
        }

        inputEl.value = transcript;
        await sendTextMessage();
      } catch (error) {
        addMessage('assistant', `Voice input error: ${error.message}`);
      } finally {
        if (state.mediaStream) {
          state.mediaStream.getTracks().forEach((track) => track.stop());
        }
        state.mediaRecorder = null;
        state.mediaStream = null;
        state.isProcessingRecording = false;
        setIdleRecordUi();
        inputEl.value = inputEl.value === 'Transcribing audio...' ? '' : inputEl.value;
      }
    };

    recorder.onerror = (event) => {
      state.isRecording = false;
      state.isProcessingRecording = false;
      addMessage('assistant', `Recorder error: ${event.error?.message || 'unknown error'}`);
      if (state.mediaStream) {
        state.mediaStream.getTracks().forEach((track) => track.stop());
      }
      state.mediaRecorder = null;
      state.mediaStream = null;
      setIdleRecordUi();
    };

    recorder.start();
  } catch (error) {
    state.isRecording = false;
    state.isProcessingRecording = false;
    setIdleRecordUi();
    addMessage('assistant', `Microphone error: ${error.message}`);
  }
}

async function initThreads() {
  let loaded = null;
  if (window.threadsBridge && typeof window.threadsBridge.load === 'function') {
    try {
      loaded = await window.threadsBridge.load();
    } catch {
      loaded = null;
    }
  }

  if (loaded && Array.isArray(loaded.threads) && loaded.threads.length > 0) {
    state.threads = loaded.threads;
    const hasCurrent = state.threads.some((thread) => thread.id === loaded.currentThreadId);
    state.currentThreadId = hasCurrent ? loaded.currentThreadId : state.threads[0].id;
    renderThreads();
    renderMessages();
    publishDebugState();
  } else {
    createThread();
  }
}

sendButton.addEventListener('click', sendTextMessage);
inputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    sendTextMessage();
  }
});
recordButton.addEventListener('click', recordAudio);
debugButton.addEventListener('click', openDebugWindow);
newChatButton.addEventListener('click', () => {
  createThread();
});

initThreads();
setIdleRecordUi();
refreshServiceStatus();
setInterval(refreshServiceStatus, HEALTH_CHECK_INTERVAL_MS);
