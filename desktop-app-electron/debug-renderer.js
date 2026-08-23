const detailsTitleEl = document.getElementById('detailsTitle');
const entriesEl = document.getElementById('entries');

const state = {
  currentThreadId: null,
  threads: [],
};

function formatTrace(debug) {
  const skills = Array.isArray(debug?.skillsRead) ? debug.skillsRead : [];
  const tools = Array.isArray(debug?.toolsUsed) ? debug.toolsUsed : [];

  const lines = [];
  lines.push('Skills read:');
  if (skills.length === 0) {
    lines.push('- none');
  } else {
    for (const skill of skills) {
      lines.push(`- ${skill}`);
    }
  }

  lines.push('');
  lines.push('Tools used:');
  if (tools.length === 0) {
    lines.push('- none');
  } else {
    tools.forEach((tool, index) => {
      lines.push(`${index + 1}. ${tool.tool}`);
      lines.push(JSON.stringify(tool.arguments || {}, null, 2));
    });
  }

  return lines.join('\n');
}

function renderDetails() {
  const thread = state.threads.find((item) => item.id === state.currentThreadId);
  entriesEl.innerHTML = '';

  if (!thread) {
    detailsTitleEl.textContent = 'No thread selected';
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No debug data available.';
    entriesEl.appendChild(empty);
    return;
  }

  detailsTitleEl.textContent = thread.title;

  if (!Array.isArray(thread.messages) || thread.messages.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No assistant debug traces in this thread yet.';
    entriesEl.appendChild(empty);
    return;
  }

  for (const message of thread.messages) {
    const card = document.createElement('div');
    card.className = 'entry';

    const header = document.createElement('div');
    header.className = 'entry-header';
    header.textContent = `Assistant response #${message.index + 1}`;

    const body = document.createElement('pre');
    body.className = 'entry-body';
    body.textContent = formatTrace(message.debug);

    card.appendChild(header);
    card.appendChild(body);
    entriesEl.appendChild(card);
  }
}

function setState(next) {
  state.currentThreadId = next?.currentThreadId || null;
  state.threads = Array.isArray(next?.threads) ? next.threads : [];
  renderDetails();
}

if (window.debugBridge && typeof window.debugBridge.onDebugState === 'function') {
  window.debugBridge.onDebugState((incoming) => {
    setState(incoming);
  });
}

if (window.debugBridge && typeof window.debugBridge.getDebugState === 'function') {
  window.debugBridge.getDebugState().then((incoming) => {
    setState(incoming);
  });
}
