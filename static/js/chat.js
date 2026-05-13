/* global chat.js */
(function () {
  'use strict';

  const messagesEl = document.getElementById('messages');
  const form       = document.getElementById('chat-form');
  const input      = document.getElementById('chat-input');
  const pdfList    = document.getElementById('pdf-list');
  const pdfCount   = document.getElementById('pdf-count');

  // ── Chart helpers ─────────────────────────────────────────────────────────

  let _chartSeq = 0;

  const PALETTE = [
    '#4f46e5','#06b6d4','#10b981','#f59e0b','#ef4444',
    '#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1',
  ];

  function _chartColors(n, alpha) {
    return Array.from({length: n}, (_, i) => {
      const hex = PALETTE[i % PALETTE.length];
      if (!alpha) return hex;
      const r = parseInt(hex.slice(1,3),16);
      const g = parseInt(hex.slice(3,5),16);
      const b = parseInt(hex.slice(5,7),16);
      return `rgba(${r},${g},${b},${alpha})`;
    });
  }

  function initChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;

    const isSlice = data.chart_type === 'pie' || data.chart_type === 'doughnut';
    new Chart(canvas, {
      type: data.chart_type,
      data: {
        labels: data.labels,
        datasets: [{
          label: data.dataset_label,
          data: data.data,
          backgroundColor: isSlice ? _chartColors(data.labels.length, 0.8) : _chartColors(1, 0.75),
          borderColor:     isSlice ? _chartColors(data.labels.length)       : PALETTE[0],
          borderWidth: 1,
          fill: data.chart_type === 'line',
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { position: isSlice ? 'right' : 'top', labels: { boxWidth: 12, font: { size: 12 } } },
          title:  { display: false },
        },
        scales: isSlice ? {} : { y: { beginAtZero: true, ticks: { font: { size: 11 } } }, x: { ticks: { font: { size: 11 } } } },
      },
    });
  }

  // ── helpers ──────────────────────────────────────────────────────────────

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** Very small Markdown renderer: **bold**, *italic*, bullet lists, tables, line breaks.
   *  NOTE: text must already be HTML-escaped before calling this function. */
  function renderMarkdown(text) {
    // Convert markdown tables to <table> HTML
    const lines = text.split('\n');
    const out   = [];
    let tbl     = [];

    const flushTable = () => {
      if (tbl.length < 2) { out.push(...tbl); tbl = []; return; }
      const isSep  = l => /^\s*\|[-\s|:]+\|\s*$/.test(l);
      const parseRow = l => l.replace(/^\s*\||\|\s*$/g, '').split('|').map(c => c.trim());
      const rows   = tbl.filter(l => !isSep(l));
      if (!rows.length) { out.push(...tbl); tbl = []; return; }
      const [hdr, ...body] = rows;
      const ths = parseRow(hdr).map(c => `<th>${c}</th>`).join('');
      const trs = body.map(r =>
        `<tr>${parseRow(r).map(c => `<td>${c}</td>`).join('')}</tr>`
      ).join('');
      out.push(`<table class="chat-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`);
      tbl = [];
    };

    for (const line of lines) {
      if (line.trim().startsWith('|')) {
        tbl.push(line);
      } else {
        if (tbl.length) flushTable();
        out.push(line);
      }
    }
    if (tbl.length) flushTable();

    return out.join('\n')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/^[-•]\s(.+)/gm, '<li>$1</li>')
      .replace(/(<li>[\s\S]+?<\/li>)/g, '<ul>$1</ul>')
      .replace(/\n/g, '<br/>');
  }

  // ── message rendering ─────────────────────────────────────────────────────

  function appendMessage(role, html) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `<div class="bubble">${html}</div>`;
    messagesEl.appendChild(div);
    scrollBottom();
    return div;
  }

  function showTyping() {
    const div = document.createElement('div');
    div.className = 'message bot typing';
    div.innerHTML = '<div class="bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    messagesEl.appendChild(div);
    scrollBottom();
    return div;
  }

  function renderResponse(data) {
    if (data.type === 'error') {
      let html = `<span class="status-error">${escHtml(data.message || 'An error occurred.')}</span>`;
      if (data.suggestions && data.suggestions.length) {
        html += '<p class="suggest-label">Try asking:</p><div class="suggest-btns">' +
          data.suggestions.map(s =>
            `<button class="suggest-btn" data-suggest="${escHtml(s)}">${escHtml(s)}</button>`
          ).join('') +
          '</div>';
      }
      return html;
    }

    if (data.type === 'text' || data.type === 'attendance') {
      const cls = data.status === 'error' ? 'status-error' : data.status === 'success' ? 'status-success' : '';
      const msg = renderMarkdown(escHtml(data.message));
      return cls ? `<span class="${cls}">${msg}</span>` : msg;
    }

    if (data.type === 'chart') {
      const id = `chart-canvas-${++_chartSeq}`;
      data._canvasId = id;
      return `<div class="chart-wrapper">
        <strong>${escHtml(data.title)}</strong>
        <div class="chart-canvas-box"><canvas id="${id}"></canvas></div>
      </div>`;
    }

    if (data.type === 'sales_table') {
      const rows = data.data.map(r =>
        `<tr>
          <td>${escHtml(r.name)}</td>
          <td>${escHtml(String(r.total_quantity))}</td>
          <td>$${parseFloat(r.total_amount).toFixed(2)}</td>
          <td>${escHtml(String(r.total_transactions))}</td>
        </tr>`
      ).join('');
      return `
        <strong>Sales for "${escHtml(data.product)}" — ${escHtml(data.month)}</strong>
        <table class="chat-table">
          <thead><tr><th>Product</th><th>Units Sold</th><th>Revenue</th><th>Transactions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    }

    if (data.type === 'attendance_table') {
      const rows = data.data.map(r =>
        `<tr>
          <td>${escHtml(r.name)}</td>
          <td>${escHtml(r.department || '—')}</td>
          <td>${escHtml(r.date)}</td>
          <td>${escHtml(r.check_in  || '—')}</td>
          <td>${escHtml(r.check_out || '—')}</td>
          <td><span class="badge badge-${r.status === 'present' ? 'employee' : 'admin'}">${escHtml(r.status)}</span></td>
        </tr>`
      ).join('');
      return `
        <strong>Attendance Report</strong>
        <table class="chat-table">
          <thead><tr><th>Name</th><th>Dept</th><th>Date</th><th>Check-in</th><th>Check-out</th><th>Status</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    }

    if (data.error) return `<span class="status-error">${escHtml(data.error)}</span>`;
    return escHtml(JSON.stringify(data));
  }

  // ── send message ──────────────────────────────────────────────────────────

  async function sendMessage(text) {
    if (!text.trim()) return;

    input.value = '';
    input.disabled = true;
    appendMessage('user', escHtml(text));

    const typingEl = showTyping();
    let typingGone = false;
    const clearTyping = () => { if (!typingGone) { typingGone = true; typingEl.remove(); } };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000); // 3-min timeout

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (!res.ok) {
        clearTyping();
        appendMessage('bot', '<span class="status-error">Server error. Please try again.</span>');
        return;
      }

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer      = '';
      let streamBubble = null;
      let streamText   = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';   // keep the last incomplete line

        for (const line of lines) {
          if (!line.trim()) continue;
          let evt;
          try { evt = JSON.parse(line); } catch { continue; }

          if (evt.status !== undefined) {
            // Update typing indicator text while tools run
            if (!typingGone) {
              typingEl.querySelector('.bubble').innerHTML =
                `<span class="status-muted">${escHtml(evt.status)}</span>`;
            }

          } else if (evt.token !== undefined) {
            // First token: replace typing indicator with a live bubble
            if (!streamBubble) {
              clearTyping();
              streamBubble = appendMessage('bot', '');
            }
            streamText += evt.token;
            streamBubble.querySelector('.bubble').innerHTML = renderMarkdown(escHtml(streamText));
            scrollBottom();

          } else if (evt.done !== undefined) {
            clearTyping();
            if (evt.data) {
              // Structured response (chart, table, attendance, error, or text after tool use)
              const html = renderResponse(evt.data);
              if (streamBubble) {
                streamBubble.querySelector('.bubble').innerHTML = html;
              } else {
                appendMessage('bot', html);
              }
              scrollBottom();
              // Initialise Chart.js after the canvas is in the DOM
              if (evt.data.type === 'chart' && evt.data._canvasId) {
                initChart(evt.data._canvasId, evt.data);
              }
            }
            // If no data, streamBubble already holds the complete streamed text
          }
        }
      }

      // Safety: clear typing if stream ended without a done event
      clearTyping();

    } catch (err) {
      clearTimeout(timer);
      clearTyping();
      const msg = err.name === 'AbortError'
        ? 'Request timed out. The model may be overloaded — please try again.'
        : 'Network error. Please try again.';
      appendMessage('bot', `<span class="status-error">${msg}</span>`);
    } finally {
      input.disabled = false;
      input.focus();
    }
  }

  form.addEventListener('submit', e => {
    e.preventDefault();
    sendMessage(input.value.trim());
  });

  // ── quick buttons ─────────────────────────────────────────────────────────

  document.querySelectorAll('.quick-btn[data-msg]').forEach(btn => {
    btn.addEventListener('click', () => sendMessage(btn.dataset.msg));
  });

  // ── suggestion buttons (dynamically injected into chat bubbles) ───────────

  messagesEl.addEventListener('click', e => {
    const btn = e.target.closest('[data-suggest]');
    if (btn) sendMessage(btn.dataset.suggest);
  });

  // ── reload PDFs (admin) ───────────────────────────────────────────────────

  const reloadBtn = document.getElementById('reload-pdfs-btn');
  if (reloadBtn) {
    reloadBtn.addEventListener('click', async () => {
      reloadBtn.disabled = true;
      reloadBtn.textContent = 'Reloading…';
      try {
        const res  = await fetch('/api/reload-pdfs', { method: 'POST' });
        const data = await res.json();
        appendMessage('bot', renderMarkdown(escHtml(data.message || data.error)));
        loadPdfList();
      } catch {
        appendMessage('bot', '<span class="status-error">Failed to reload PDFs.</span>');
      } finally {
        reloadBtn.disabled = false;
        reloadBtn.textContent = 'Reload PDFs';
      }
    });
  }

  // ── PDF list sidebar ──────────────────────────────────────────────────────

  async function loadPdfList() {
    try {
      const res  = await fetch('/api/pdfs');
      const data = await res.json();
      const pdfs = data.pdfs || [];
      pdfCount.textContent = `(${pdfs.length})`;
      if (pdfs.length === 0) {
        pdfList.innerHTML = '<li class="pdf-empty">No PDFs loaded</li>';
      } else {
        pdfList.innerHTML = pdfs.map(f => `<li title="${escHtml(f)}">${escHtml(f)}</li>`).join('');
      }
    } catch {
      pdfList.innerHTML = '<li class="pdf-empty">Could not load list</li>';
    }
  }

  loadPdfList();
  input.focus();
})();
