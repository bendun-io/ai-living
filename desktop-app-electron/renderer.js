const DEFAULT_AGENT_BASE_URL = 'http://localhost:8000';
const DEFAULT_TRANSCRIBE_BASE_URL = 'http://localhost:3010';

const threadListEl = document.getElementById('threadList');
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const recordButton = document.getElementById('recordButton');
const recordingStatusEl = document.getElementById('recordingStatus');
const serviceStatusDotEl = document.getElementById('serviceStatusDot');
const serviceStatusTextEl = document.getElementById('serviceStatusText');
const newChatButton = document.getElementById('newChatButton');

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

function setIdleRecordUi() {
  recordButton.textContent = 'Record';
  recordButton.disabled = false;
  setRecordingStatus('', '');
}

function setRecordingUi() {
  recordButton.textContent = 'Stop';
  recordButton.disabled = false;
  setRecordingStatus('Recording... click Stop when you are done.', 'recording');
}

function setProcessingUi() {
  recordButton.textContent = 'Transcribing...';
  recordButton.disabled = true;
  setRecordingStatus('Transcribing and sending your message...', 'processing');
}

function createThread(title = 'New chat') {
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
  return thread;
}

function renderThreads() {
  threadListEl.innerHTML = '';
  state.threads.forEach((thread) => {
    const item = document.createElement('li');
    item.textContent = thread.title;
    item.dataset.threadId = thread.id;
    item.addEventListener('click', () => {
      state.currentThreadId = thread.id;
      renderMessages();
    });
    threadListEl.appendChild(item);
  });
}

function renderMessages() {
  messagesEl.innerHTML = '';
  const thread = state.threads.find((item) => item.id === state.currentThreadId);
  if (!thread) {
    return;
  }

  for (const message of thread.messages) {
    const el = document.createElement('div');
    el.className = `message ${message.role}`;
    el.textContent = `${message.role}: ${message.text}`;
    messagesEl.appendChild(el);
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role, text) {
  const thread = state.threads.find((item) => item.id === state.currentThreadId);
  if (!thread) {
    return;
  }

  thread.messages.push({ role, text });
  renderMessages();
}

async function sendTextMessage() {
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }

  if (!state.currentThreadId) {
    createThread('New chat');
  }

  addMessage('user', text);
  inputEl.value = '';

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
    addMessage('assistant', answer);
  } catch (error) {
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

sendButton.addEventListener('click', sendTextMessage);
inputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    sendTextMessage();
  }
});
recordButton.addEventListener('click', recordAudio);
newChatButton.addEventListener('click', () => {
  createThread('New chat');
});

createThread('New chat');
setIdleRecordUi();
refreshServiceStatus();
setInterval(refreshServiceStatus, HEALTH_CHECK_INTERVAL_MS);
