/**
 * KHYRA AI - REALTIME LIVEKIT VOICE DEMO CLIENT
 *
 * Implements browser microphone capture, WebRTC LiveKit room connectivity,
 * bidirectional audio streaming, mute/unmute controls, and real-time visualizer.
 */

(function () {
  'use strict';

  // --- DOM Elements ---
  const startBtn = document.getElementById('start-btn');
  const endBtn = document.getElementById('end-btn');
  const muteBtn = document.getElementById('mute-btn');
  const micOnIcon = document.getElementById('mic-on-icon');
  const micOffIcon = document.getElementById('mic-off-icon');
  const muteLabel = document.getElementById('mute-label');

  const connectionPill = document.getElementById('connection-pill');
  const connectionStatusText = document.getElementById('connection-status-text');
  const agentStatePill = document.getElementById('agent-state-pill');
  const agentStateText = document.getElementById('agent-state-text');

  const roomTag = document.getElementById('room-tag');
  const roomIdVal = document.getElementById('room-id-val');
  const latencyTag = document.getElementById('latency-tag');
  const latencyVal = document.getElementById('latency-val');

  const voiceOrb = document.getElementById('voice-orb');
  const agentCaption = document.getElementById('agent-caption');
  const canvas = document.getElementById('audio-visualizer-canvas');
  const canvasCtx = canvas.getContext('2d');

  const errorBanner = document.getElementById('error-banner');
  const errorTitle = document.getElementById('error-title');
  const errorMessage = document.getElementById('error-message');
  const errorDismissBtn = document.getElementById('error-dismiss-btn');

  const activityLog = document.getElementById('activity-log');
  const agentAudioSink = document.getElementById('agent-audio-sink');

  // --- Session State ---
  let room = null;
  let isMuted = false;
  let currentRoomName = null;
  let audioContext = null;
  let analyserNode = null;
  let visualizerSource = null;
  let animationFrameId = null;
  let pingIntervalId = null;

  // --- Logging Helper ---
  function appendLog(message, type = 'info') {
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;
    const timestamp = new Date().toLocaleTimeString();
    entry.textContent = `[${timestamp}] ${message}`;
    activityLog.appendChild(entry);
    activityLog.scrollTop = activityLog.scrollHeight;
  }

  // --- Error Handling ---
  function showError(title, message) {
    errorTitle.textContent = title;
    errorMessage.textContent = message;
    errorBanner.classList.remove('hidden');
    appendLog(`ERROR: ${title} - ${message}`, 'error');
  }

  function hideError() {
    errorBanner.classList.add('hidden');
  }

  errorDismissBtn.addEventListener('click', hideError);

  // --- Status UI Helpers ---
  function setConnectionStatus(status, text) {
    connectionPill.className = `status-pill status-${status}`;
    connectionStatusText.textContent = text;
  }

  function setAgentState(state, text, caption) {
    agentStatePill.className = `status-pill status-${state}`;
    agentStateText.textContent = text;
    voiceOrb.className = `voice-orb orb-${state}`;
    if (caption) {
      agentCaption.textContent = caption;
    }
  }

  // --- Web Audio Visualizer ---
  function setupAudioVisualizer(mediaStream) {
    try {
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioContext.state === 'suspended') {
        audioContext.resume();
      }

      analyserNode = audioContext.createAnalyser();
      analyserNode.fftSize = 64;
      analyserNode.smoothingTimeConstant = 0.8;

      if (visualizerSource) {
        visualizerSource.disconnect();
      }
      visualizerSource = audioContext.createMediaStreamSource(mediaStream);
      visualizerSource.connect(analyserNode);

      drawVisualizer();
    } catch (e) {
      console.warn('Audio visualizer setup skipped:', e);
    }
  }

  function drawVisualizer() {
    if (!analyserNode) return;

    const bufferLength = analyserNode.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const render = () => {
      animationFrameId = requestAnimationFrame(render);
      analyserNode.getByteFrequencyData(dataArray);

      canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

      const barWidth = (canvas.width / bufferLength) * 1.5;
      let barHeight;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        barHeight = (dataArray[i] / 255) * canvas.height * 0.9;

        // Dynamic gradient based on agent speaking vs listening
        const gradient = canvasCtx.createLinearGradient(0, canvas.height, 0, 0);
        if (voiceOrb.classList.contains('orb-speaking')) {
          gradient.addColorStop(0, '#6366f1');
          gradient.addColorStop(1, '#a5b4fc');
        } else {
          gradient.addColorStop(0, '#06b6d4');
          gradient.addColorStop(1, '#67e8f9');
        }

        canvasCtx.fillStyle = gradient;
        canvasCtx.fillRect(x, canvas.height - barHeight, barWidth - 2, barHeight);
        x += barWidth;
      }
    };
    render();
  }

  function stopVisualizer() {
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
    canvasCtx.clearRect(0, 0, canvas.width, canvas.height);
    if (visualizerSource) {
      visualizerSource.disconnect();
      visualizerSource = null;
    }
  }

  // --- Start Conversation Flow ---
  async function startConversation() {
    hideError();
    startBtn.disabled = true;
    setConnectionStatus('connecting', 'Connecting...');
    setAgentState('idle', 'Initializing...', 'Requesting microphone access and joining session...');
    appendLog('Starting new conversation session...', 'info');

    // Step 1: Ensure LiveKit Client SDK is loaded
    const Livekit = window.LivekitClient;
    if (!Livekit) {
      showError(
        'LiveKit SDK Missing',
        'The LiveKit WebRTC client library could not be loaded. Check network connectivity or local vendor bundle.'
      );
      resetUI();
      return;
    }

    // Step 2: Request microphone permission explicitly on user action
    try {
      appendLog('Requesting microphone permissions from browser...', 'info');
      const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Keep tracks alive or let LiveKit manage its own; stop test tracks
      testStream.getTracks().forEach((track) => track.stop());
      appendLog('Microphone access granted by user.', 'success');
    } catch (permErr) {
      console.error('Microphone error:', permErr);
      let msg = 'Microphone permission was denied. Please allow microphone access in your browser settings to speak with the AI.';
      if (permErr.name === 'NotFoundError' || permErr.name === 'DevicesNotFoundError') {
        msg = 'No microphone device was detected on your system. Please connect a microphone and try again.';
      }
      showError('Microphone Access Required', msg);
      resetUI();
      return;
    }

    // Step 3: Fetch access token from backend server
    let tokenData;
    try {
      appendLog('Requesting session token from /api/token...', 'info');
      const res = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ participant_name: 'Web User' }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server responded with status ${res.status}`);
      }

      tokenData = await res.json();
      currentRoomName = tokenData.roomName;
      appendLog(`Acquired token for room: ${tokenData.roomName} (${tokenData.participantIdentity})`, 'success');
    } catch (tokenErr) {
      console.error('Token fetch error:', tokenErr);
      showError(
        'Session Initialization Failed',
        tokenErr.message || 'Could not obtain a session token from backend.'
      );
      resetUI();
      return;
    }

    // Step 4: Initialize LiveKit Room & Wire WebRTC Handlers
    try {
      room = new Livekit.Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      // Handle Connected
      room.on(Livekit.RoomEvent.Connected, async () => {
        setConnectionStatus('connected', 'Connected');
        setAgentState('listening', 'Agent Listening', 'Agent is listening. Start speaking now!');
        appendLog(`Connected to LiveKit room: ${room.name}`, 'success');

        roomIdVal.textContent = room.name.replace('web-demo-', '');
        roomTag.classList.remove('hidden');
        latencyTag.classList.remove('hidden');

        // Publish local microphone
        try {
          appendLog('Publishing microphone audio stream...', 'info');
          await room.localParticipant.setMicrophoneEnabled(true);
          appendLog('Microphone published successfully.', 'success');

          // Hook local mic to visualizer if available
          const localAudioPub = Array.from(room.localParticipant.audioTrackPublications.values())[0];
          if (localAudioPub && localAudioPub.track && localAudioPub.track.mediaStream) {
            setupAudioVisualizer(localAudioPub.track.mediaStream);
          }
        } catch (pubErr) {
          appendLog(`Failed to publish microphone: ${pubErr.message}`, 'error');
          showError('Microphone Publish Error', 'Connected to room, but could not publish microphone audio.');
        }

        // Setup UI buttons
        startBtn.classList.add('hidden');
        endBtn.classList.remove('hidden');
        endBtn.disabled = false;
        muteBtn.classList.remove('hidden');
        muteBtn.disabled = false;
      });

      // Handle Disconnected
      room.on(Livekit.RoomEvent.Disconnected, (reason) => {
        appendLog(`Disconnected from LiveKit room (${reason || 'user ended'})`, 'warn');
        resetUI();
      });

      // Handle Reconnecting
      room.on(Livekit.RoomEvent.Reconnecting, () => {
        setConnectionStatus('connecting', 'Reconnecting...');
        appendLog('Connection interrupted. Reconnecting to LiveKit...', 'warn');
      });

      // Handle Reconnected
      room.on(Livekit.RoomEvent.Reconnected, () => {
        setConnectionStatus('connected', 'Connected');
        appendLog('Reconnected to LiveKit.', 'success');
      });

      // Handle Subscribed Agent Audio Track
      room.on(Livekit.RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Livekit.Track.Kind.Audio) {
          appendLog(`Subscribed to audio track from agent: ${participant.identity}`, 'success');
          // Attach track to HTMLAudioElement for playback
          track.attach(agentAudioSink);

          // Connect agent audio to the visualizer
          if (track.mediaStream) {
            setupAudioVisualizer(track.mediaStream);
          }
        }
      });

      // Handle Unsubscribed
      room.on(Livekit.RoomEvent.TrackUnsubscribed, (track) => {
        track.detach(agentAudioSink);
        appendLog('Agent audio track unsubscribed.', 'info');
      });

      // Handle Active Speakers (Speaking / Listening Indicator)
      room.on(Livekit.RoomEvent.ActiveSpeakersChanged, (speakers) => {
        if (!speakers || speakers.length === 0) {
          if (!isMuted) {
            setAgentState('listening', 'Agent Listening', 'Agent is listening...');
          }
          return;
        }

        const agentSpeaking = speakers.some((spk) => spk !== room.localParticipant);
        const userSpeaking = speakers.some((spk) => spk === room.localParticipant);

        if (agentSpeaking) {
          setAgentState('speaking', 'Agent Speaking', 'Agent is speaking...');
        } else if (userSpeaking && !isMuted) {
          setAgentState('listening', 'You are speaking', 'Hearing your voice...');
        } else if (!isMuted) {
          setAgentState('listening', 'Agent Listening', 'Agent is listening...');
        }
      });

      // Connect to LiveKit server
      appendLog(`Connecting WebRTC to ${tokenData.serverUrl}...`, 'info');
      await room.connect(tokenData.serverUrl, tokenData.participantToken);

      // Start periodic RTT telemetry
      pingIntervalId = setInterval(async () => {
        if (room && room.engine && room.engine.publisher) {
          const stats = await room.engine.publisher.getStats().catch(() => null);
          if (stats) {
            stats.forEach((report) => {
              if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.currentRoundTripTime) {
                const rtt = Math.round(report.currentRoundTripTime * 1000);
                latencyVal.textContent = `${rtt}ms`;
              }
            });
          }
        }
      }, 2000);
    } catch (connErr) {
      console.error('Connection error:', connErr);
      showError(
        'Connection Failed',
        connErr.message || 'Could not establish WebRTC connection to LiveKit server.'
      );
      resetUI();
    }
  }

  // --- End Conversation Flow ---
  async function endConversation() {
    appendLog('Ending conversation...', 'info');
    endBtn.disabled = true;
    setConnectionStatus('connecting', 'Disconnecting...');

    const roomToEnd = currentRoomName;

    if (room) {
      try {
        await room.disconnect();
      } catch (e) {
        console.warn('Disconnect error:', e);
      }
      room = null;
    }

    // Call backend to release room resources
    if (roomToEnd) {
      try {
        await fetch('/api/session/end', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ room_name: roomToEnd }),
        });
        appendLog(`Released room resources on server: ${roomToEnd}`, 'info');
      } catch (e) {
        console.warn('Session end API notice:', e);
      }
    }

    resetUI();
    appendLog('Conversation ended cleanly.', 'success');
  }

  // --- Mute / Unmute Control ---
  async function toggleMute() {
    if (!room || !room.localParticipant) return;

    try {
      isMuted = !isMuted;
      await room.localParticipant.setMicrophoneEnabled(!isMuted);

      if (isMuted) {
        micOnIcon.classList.add('hidden');
        micOffIcon.classList.remove('hidden');
        muteLabel.textContent = 'Unmuted';
        muteBtn.classList.add('btn-muted-active');
        setAgentState('idle', 'Microphone Muted', 'Your microphone is currently muted.');
        appendLog('Microphone muted by user.', 'warn');
      } else {
        micOnIcon.classList.remove('hidden');
        micOffIcon.classList.add('hidden');
        muteLabel.textContent = 'Mute';
        muteBtn.classList.remove('btn-muted-active');
        setAgentState('listening', 'Agent Listening', 'Microphone active. Agent is listening...');
        appendLog('Microphone unmuted.', 'info');
      }
    } catch (muteErr) {
      console.error('Mute toggle error:', muteErr);
      appendLog(`Failed to toggle microphone mute: ${muteErr.message}`, 'error');
    }
  }

  // --- Reset UI to Idle ---
  function resetUI() {
    stopVisualizer();

    if (pingIntervalId) {
      clearInterval(pingIntervalId);
      pingIntervalId = null;
    }

    setConnectionStatus('disconnected', 'Disconnected');
    setAgentState('idle', 'Ready to Connect', 'Click "Start Conversation" to begin.');

    startBtn.classList.remove('hidden');
    startBtn.disabled = false;
    endBtn.classList.add('hidden');
    endBtn.disabled = true;

    muteBtn.classList.add('hidden');
    muteBtn.disabled = true;
    muteBtn.classList.remove('btn-muted-active');
    micOnIcon.classList.remove('hidden');
    micOffIcon.classList.add('hidden');
    muteLabel.textContent = 'Mute';

    roomTag.classList.add('hidden');
    latencyTag.classList.add('hidden');

    isMuted = false;
    currentRoomName = null;
  }

  // --- Event Listeners ---
  startBtn.addEventListener('click', startConversation);
  endBtn.addEventListener('click', endConversation);
  muteBtn.addEventListener('click', toggleMute);

  // Clean disconnection when user closes or reloads page
  window.addEventListener('beforeunload', () => {
    if (room) {
      room.disconnect();
    }
  });

  appendLog('Khyra Voice AI Demo interface ready.', 'system');
})();
