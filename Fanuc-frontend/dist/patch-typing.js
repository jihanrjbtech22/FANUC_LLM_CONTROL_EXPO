(function () {
  const OriginalWebSocket = window.WebSocket;
  const INDICATOR_ID = 'llm-typing-indicator';

  function ensureStyles() {
    if (document.getElementById('llm-typing-style')) {
      return;
    }

    const style = document.createElement('style');
    style.id = 'llm-typing-style';
    style.textContent = `
      #${INDICATOR_ID} {
        display: none;
        margin-top: 6px;
        align-self: flex-start;
      }

      #${INDICATOR_ID} .assistant-wrap {
        display: flex;
        align-items: flex-start;
        gap: 10px;
      }

      #${INDICATOR_ID} .assistant-avatar {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        background: linear-gradient(180deg, #ffd92a 0%, #f1b800 100%);
        color: #111;
        box-shadow: 0 8px 18px rgba(0, 0, 0, 0.08);
        flex: 0 0 auto;
      }

      #${INDICATOR_ID} .typing {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        min-height: 28px;
        padding: 10px 14px;
        border-radius: 18px 18px 18px 6px;
        background: #222222;
        box-shadow: 0 8px 18px rgba(0, 0, 0, 0.08);
      }

      #${INDICATOR_ID} .typing-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: #d7d7d7;
        opacity: 0.36;
        animation: llmTypingPulse 1s infinite ease-in-out;
      }

      #${INDICATOR_ID} .typing-dot:nth-child(2) {
        animation-delay: 0.15s;
      }

      #${INDICATOR_ID} .typing-dot:nth-child(3) {
        animation-delay: 0.3s;
      }

      @keyframes llmTypingPulse {
        0%, 80%, 100% {
          transform: translateY(0);
          opacity: 0.26;
        }
        40% {
          transform: translateY(-4px);
          opacity: 1;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function getMessagesArea() {
    return document.querySelector('.messages-area');
  }

  function ensureIndicator() {
    ensureStyles();

    let indicator = document.getElementById(INDICATOR_ID);
    if (indicator) {
      return indicator;
    }

    const container = document.createElement('div');
    container.id = INDICATOR_ID;
    container.innerHTML = '<div class="assistant-wrap"><div class="assistant-avatar">⚙</div><div class="typing" aria-label="LLM is thinking" role="status"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div></div>';

    const mount = () => {
      const messagesArea = getMessagesArea();
      if (!messagesArea) {
        return false;
      }
      messagesArea.appendChild(container);
      return true;
    };

    if (!mount()) {
      const observer = new MutationObserver(() => {
        if (mount()) {
          observer.disconnect();
        }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }

    return container;
  }

  function setTypingVisible(visible) {
    const indicator = ensureIndicator();
    if (indicator) {
      indicator.style.display = visible ? 'block' : 'none';
    }
  }

  function shouldShowTyping(payload) {
    return payload && payload.type === 'user_input';
  }

  function shouldHideTyping(payload) {
    return payload && (payload.type === 'engine_output' || payload.type === 'engine_error');
  }

  window.WebSocket = function (url, protocols) {
    const ws = protocols ? new OriginalWebSocket(url, protocols) : new OriginalWebSocket(url);
    const originalSend = ws.send;
    let suppressNextUserTranscript = false;

    ws.send = function (data) {
      try {
        const payload = typeof data === 'string' ? JSON.parse(data) : null;
        if (shouldShowTyping(payload)) {
          setTypingVisible(true);
          suppressNextUserTranscript = true;
        }
      } catch (e) {}
      return originalSend.apply(ws, arguments);
    };

    ws.addEventListener('message', function (event) {
      try {
        const data = JSON.parse(event.data);
        if (data && data.type === 'user_transcript' && suppressNextUserTranscript) {
          event.stopImmediatePropagation();
          suppressNextUserTranscript = false;
          return;
        }
        if (data && data.type === 'user_transcript') {
          setTypingVisible(true);
        }
        if (shouldShowTyping(data)) {
          setTypingVisible(true);
        } else if (shouldHideTyping(data)) {
          setTypingVisible(false);
          suppressNextUserTranscript = false;
        }
      } catch (e) {}
    });

    ws.addEventListener('close', function () {
      setTypingVisible(false);
    });

    ws.addEventListener('error', function () {
      setTypingVisible(false);
    });

    return ws;
  };

  window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
  window.WebSocket.OPEN = OriginalWebSocket.OPEN;
  window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
  window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
})();
