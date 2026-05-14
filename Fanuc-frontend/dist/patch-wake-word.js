/**
 * Wake Word Toggle UI Patch
 * Injects a wake word control button into the chat UI
 * Communicates with backend to toggle wake word detection
 */

(function() {
  'use strict';

  // Force the app to use the Python Whisper backend instead of the browser mic.
  // This keeps the voice button from wiring up SpeechRecognition in Electron/Firefox-style runtimes.
  try {
    Object.defineProperty(window, 'SpeechRecognition', { value: undefined, configurable: true });
  } catch (error) {
    window.SpeechRecognition = undefined;
  }
  try {
    Object.defineProperty(window, 'webkitSpeechRecognition', { value: undefined, configurable: true });
  } catch (error) {
    window.webkitSpeechRecognition = undefined;
  }

  window.__fanucVoiceBackendOnly = true;
  setInterval(() => {
    try {
      delete window.SpeechRecognition;
      delete window.webkitSpeechRecognition;
      window.SpeechRecognition = undefined;
      window.webkitSpeechRecognition = undefined;
    } catch (error) {
      window.SpeechRecognition = undefined;
      window.webkitSpeechRecognition = undefined;
    }
  }, 250);

  // State
  let wakeWordEnabled = false;
  let voiceRunning = false;

  // Styles for wake word toggle
  const styles = `
    .wake-word-container {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 12px 0;
      margin: 12px 0;
      border-top: 1px solid #444;
      border-bottom: 1px solid #444;
      font-size: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      width: 100%;
      box-sizing: border-box;
    }

    .wake-word-label {
      font-weight: 500;
      color: #999;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-size: 11px;
      width: 100%;
    }

    .wake-word-control-row {
      display: flex;
      align-items: center;
      gap: 8px;
      justify-content: space-between;
      width: 100%;
    }

    .wake-word-toggle {
      position: relative;
      display: inline-flex;
      width: 40px;
      height: 20px;
      background: #444;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      padding: 0;
      transition: background-color 0.3s ease;
      outline: none;
      flex-shrink: 0;
    }

    .wake-word-toggle.enabled {
      background: #4CAF50;
    }

    .wake-word-toggle:hover:not(:disabled) {
      opacity: 0.9;
    }

    .wake-word-toggle:disabled {
      cursor: not-allowed;
      opacity: 0.4;
    }

    .wake-word-toggle::after {
      content: '';
      position: absolute;
      width: 16px;
      height: 16px;
      background: white;
      border-radius: 50%;
      top: 2px;
      left: 2px;
      transition: left 0.3s ease;
    }

    .wake-word-toggle.enabled::after {
      left: 22px;
    }

    .wake-word-status {
      font-size: 11px;
      color: #999;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .wake-word-status.active {
      color: #4CAF50;
      font-weight: 500;
    }

    .wake-word-status.disabled {
      color: #666;
    }
  `;

  // Inject styles
  function injectStyles() {
    if (document.getElementById('wake-word-styles')) return;
    const styleEl = document.createElement('style');
    styleEl.id = 'wake-word-styles';
    styleEl.textContent = styles;
    document.head.appendChild(styleEl);
  }

  // Create wake word control UI
  function createWakeWordControl() {
    const container = document.createElement('div');
    container.className = 'wake-word-container';
    container.id = 'wake-word-control';

    container.innerHTML = `
      <div class="wake-word-label">Wake Word</div>
      <div class="wake-word-control-row">
        <button class="wake-word-toggle" id="wake-word-btn" disabled>
        </button>
        <span class="wake-word-status" id="wake-word-status">Off</span>
      </div>
    `;

    const btn = container.querySelector('#wake-word-btn');
    btn.addEventListener('click', handleWakeWordToggle);

    return container;
  }

  // Handle wake word toggle button click
  function handleWakeWordToggle() {
    if (!voiceRunning) return;

    // Find websocket connection (from React app or our shim)
    const ws = findActiveWebSocket();
    if (!ws) {
      console.warn('[Wake Word] WebSocket not found');
      return;
    }

    wakeWordEnabled = !wakeWordEnabled;
    updateWakeWordUI();

    // Send toggle command
    try {
      ws.send(JSON.stringify({
        type: 'control',
        action: 'wake_word_set',
        enabled: wakeWordEnabled
      }));
    } catch (e) {
      console.error('[Wake Word] Send error:', e);
    }
  }

  // Update UI to reflect current state
  function updateWakeWordUI() {
    const btn = document.getElementById('wake-word-btn');
    const status = document.getElementById('wake-word-status');

    if (!btn || !status) return;

    if (voiceRunning) {
      btn.disabled = false;
      btn.classList.toggle('enabled', wakeWordEnabled);
      status.textContent = wakeWordEnabled ? 'Enabled' : 'Off';
      status.classList.remove('disabled');
      status.classList.toggle('active', wakeWordEnabled);
    } else {
      btn.disabled = true;
      btn.classList.remove('enabled');
      status.textContent = 'Off';
      status.classList.add('disabled');
      status.classList.remove('active');
    }
  }

  // Find the active WebSocket used by React app
  function findActiveWebSocket() {
    // Check if we can access window-level or global WebSocket storage
    if (window._debugWebSocket) return window._debugWebSocket;
    
    // Try to find through a marker we set in the patch-typing.js shim
    if (window.__appWebSocket) return window.__appWebSocket;
    
    // Fallback: create a new connection (less ideal but fallback option)
    return null;
  }

  // Listen for voice_state changes - could be from WebSocket or from DOM changes
  function hookWebSocketForVoiceState() {
    const OriginalWebSocket = window.WebSocket;
    
    if (window.WebSocket.__wakeWordHooked) return; // Avoid double-hooking
    
    window.WebSocket = function(...args) {
      const ws = new OriginalWebSocket(...args);
      
      // Store reference for our patch
      window.__appWebSocket = ws;

      // Track outgoing control messages so the toggle stays in sync without heavy DOM polling.
      const originalSend = ws.send.bind(ws);
      ws.send = function(data) {
        try {
          const payload = typeof data === 'string' ? JSON.parse(data) : null;
          if (payload && payload.type === 'control') {
            if (payload.action === 'voice_on') {
              // Ensure voice_on includes the current wake word preference
              try {
                payload.use_wake_word = Boolean(wakeWordEnabled);
                data = JSON.stringify(payload);
              } catch (e) {
                // ignore
              }
              voiceRunning = true;
              if (typeof payload.use_wake_word === 'boolean') {
                wakeWordEnabled = payload.use_wake_word;
              }
              updateWakeWordUI();
            } else if (payload.action === 'voice_off') {
              voiceRunning = false;
              updateWakeWordUI();
            } else if (payload.action === 'wake_word_set') {
              if (typeof payload.enabled === 'boolean') {
                wakeWordEnabled = payload.enabled;
                updateWakeWordUI();
              }
            }
          }
        } catch (err) {
          // Ignore malformed payloads and continue.
        }
        return originalSend(data);
      };
      
      // Wrap addEventListener for message events
      const originalAddEventListener = ws.addEventListener.bind(ws);
      ws.addEventListener = function(event, handler, options) {
        if (event === 'message') {
          const wrappedHandler = function(e) {
            try {
              const data = JSON.parse(e.data);
              
              // Update wake word state based on voice_state messages
              if (data.type === 'voice_state') {
                const newVoiceRunning = data.data?.recording ?? false;
                const newWakeWordEnabled = data.data?.wake_word_enabled ?? false;
                
                if (voiceRunning !== newVoiceRunning || wakeWordEnabled !== newWakeWordEnabled) {
                  voiceRunning = newVoiceRunning;
                  wakeWordEnabled = newWakeWordEnabled;
                  updateWakeWordUI();
                }
              }
            } catch (err) {
              // Ignore JSON parse errors for non-JSON messages
            }
            
            // Call original handler
            return handler.call(this, e);
          };
          
          return originalAddEventListener(event, wrappedHandler, options);
        }
        return originalAddEventListener(event, handler, options);
      };
      
      return ws;
    };
    
    // Copy properties to maintain compatibility
    window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
    window.WebSocket.OPEN = OriginalWebSocket.OPEN;
    window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
    window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
    
    window.WebSocket.__wakeWordHooked = true;
  }

  // Mount wake word control to UI - target VOICE section on left sidebar
  function mountWakeWordControl() {
    // Check if already mounted
    if (document.getElementById('wake-word-control')) {
      const existing = document.getElementById('wake-word-control');
      // Check if it's in the right place
      if (existing.parentElement.tagName !== 'HTML') {
        return true; // Already properly mounted
      }
      // If it's still on HTML, remove it and remount
      existing.remove();
    }

    // Find the VOICE section - look for elements containing both "VOICE" and "MIC READY"
    let voiceContainer = null;
    const allElements = document.querySelectorAll('*');
    
    for (const el of allElements) {
      const text = el.textContent;
      // Look for a container that has "VOICE", "MIC READY" but NOT the entire page
      if (text.includes('VOICE') && text.includes('MIC READY') && !text.includes('RUN CONTROL')) {
        // This is likely the VOICE section container
        voiceContainer = el;
        break;
      }
    }

    // If still not found, try a different approach - find the VOICE label and go up the tree
    if (!voiceContainer) {
      const voiceLabels = Array.from(allElements).filter(el => el.textContent.trim() === 'VOICE');
      for (const label of voiceLabels) {
        // Go up to find a reasonable parent container (usually 3-5 levels up)
        let parent = label.parentElement;
        for (let i = 0; i < 5 && parent; i++) {
          if (parent.textContent.includes('VOICE ENGINE: PYTHON WHISPER')) {
            voiceContainer = parent;
            break;
          }
          parent = parent.parentElement;
        }
        if (voiceContainer) break;
      }
    }

    if (!voiceContainer) {
      console.warn('[Wake Word] Could not find VOICE section');
      return false;
    }

    const control = createWakeWordControl();
    voiceContainer.appendChild(control);
    console.log('[Wake Word] Mounted to sidebar');

    return true;
  }

  // Initialize on DOM ready
  function initialize() {
    injectStyles();
    hookWebSocketForVoiceState();
    
    // Try to mount immediately if DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        setTimeout(mountWakeWordControl, 100);
      });
    } else {
      setTimeout(mountWakeWordControl, 100);
    }

    // Retry a few times in case the sidebar renders slightly later than the script.
    let attempts = 0;
    const retry = setInterval(() => {
      attempts += 1;
      if (mountWakeWordControl() || attempts >= 10) {
        clearInterval(retry);
      }
    }, 300);
  }

  // Start when ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }
})();
