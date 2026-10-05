/**
 * KHYRA AI - REALTIME LIVE VOICE DEMO CLIENT
 *
 * Implements browser microphone capture, WebRTC LiveKit room connectivity,
 * bidirectional audio streaming, animated Siri-style visualizer orb,
 * dynamic persona configuration (role, industry, language, voice), and error handling.
 */

(function () {
  'use strict';

  // --- Configuration Datasets ------------------------------------------------
  const DEMO_ROLES = [
    {
      id: "front_desk",
      label: "Front Desk",
      domains: [
        { id: "dental_clinic", label: "Dental Clinic" },
        { id: "veterinary_clinic", label: "Veterinary Clinic" },
        { id: "spa_salon", label: "Spa & Salon" },
        { id: "therapist_clinic", label: "Therapist & Wellness" },
        { id: "hotel_resort", label: "Hotel & Resort" },
        { id: "cosmetic_clinic", label: "Cosmetic Clinic" },
        { id: "general_clinic", label: "General Clinic" },
      ],
    },
    {
      id: "lead_followup",
      label: "Lead Follow-Up",
      domains: [
        { id: "ai_voice_services", label: "AI Voice Services" },
        { id: "real_estate", label: "Real Estate" },
        { id: "it_projects", label: "IT Projects" },
      ],
    },
    {
      id: "support_line",
      label: "Support Line",
      domains: [
        { id: "devops_support", label: "DevOps Support" },
        { id: "access_management_support", label: "Access Management" },
        { id: "saas_product_support", label: "SaaS Product Support" },
      ],
    },
  ];

  const DEMO_LANGUAGES = [
    { code: "en-IN", label: "English" },
    { code: "hi-IN", label: "Hindi" },
    { code: "kn-IN", label: "Kannada" },
    { code: "ta-IN", label: "Tamil" },
    { code: "te-IN", label: "Telugu" },
    { code: "ml-IN", label: "Malayalam" },
    { code: "bn-IN", label: "Bengali" },
    { code: "gu-IN", label: "Gujarati" },
    { code: "mr-IN", label: "Marathi" },
    { code: "pa-IN", label: "Punjabi" },
    { code: "od-IN", label: "Odia" },
  ];

  const DEMO_VOICES = [
    { id: "voice_2", label: "Kavya", gender: "Female" },
    { id: "voice_1", label: "Priya", gender: "Female" },
    { id: "voice_3", label: "Neha", gender: "Female" },
    { id: "voice_4", label: "Simran", gender: "Female" },
    { id: "voice_5", label: "Pooja", gender: "Female" },
    { id: "voice_6", label: "Rahul", gender: "Male" },
    { id: "voice_7", label: "Rohan", gender: "Male" },
    { id: "voice_8", label: "Aditya", gender: "Male" },
    { id: "voice_9", label: "Amit", gender: "Male" },
    { id: "voice_10", label: "Ratan", gender: "Male" },
  ];

  // --- DOM Elements ----------------------------------------------------------
  const configPanel = document.getElementById('config-panel');
  const roleSelect = document.getElementById('role-select');
  const domainSelect = document.getElementById('domain-select');
  const languageSelect = document.getElementById('language-select');
  const voiceSelect = document.getElementById('voice-select');

  const pillRole = document.getElementById('pill-role');
  const pillDomain = document.getElementById('pill-domain');
  const pillLanguage = document.getElementById('pill-language');
  const pillVoice = document.getElementById('pill-voice');

  const startBtn = document.getElementById('start-btn');
  const connectingBtn = document.getElementById('connecting-btn');
  const activeControls = document.getElementById('active-controls');
  const endBtn = document.getElementById('end-btn');
  const muteBtn = document.getElementById('mute-btn');
  const micOnIcon = document.getElementById('mic-on-icon');
  const micOffIcon = document.getElementById('mic-off-icon');
  const reconfigureBtn = document.getElementById('reconfigure-btn');

  const siriCanvas = document.getElementById('siri-orb-canvas');
  const statusMessage = document.getElementById('status-message');
  const agentDisplayTitle = document.getElementById('agent-display-title');
  const agentDisplayIndustry = document.getElementById('agent-display-industry');

  const roomTag = document.getElementById('room-tag');
  const roomIdVal = document.getElementById('room-id-val');
  const latencyTag = document.getElementById('latency-tag');
  const latencyVal = document.getElementById('latency-val');
  const activityLog = document.getElementById('activity-log');
  const agentAudioSink = document.getElementById('agent-audio-sink');

  // --- Session & State Variables --------------------------------------------
  let room = null;
  let isMuted = false;
  let currentRoomName = null;
  let pingIntervalId = null;

  // Web Audio Context for Orb visualization
  let audioContext = null;
  let analyserNode = null;
  let visualizerSource = null;
  let micVolume = 0;
  let smoothVol = 0;

  // Orb animation
  let orbAnimId = null;
  let currentOrbState = 'idle'; // 'idle' | 'connecting' | 'listening' | 'speaking' | 'thinking' | 'error'

  const ORB_PALETTES = {
    connecting: ["#2d6a4f", "#52b788", "#74c69d", "#40916c"],
    idle: ["#1f4a3f", "#2d6a4f", "#40916c", "#52b788"],
    listening: ["#40916c", "#52b788", "#74c69d", "#95d5b2"],
    thinking: ["#1f4a3f", "#2d6a4f", "#40916c", "#52b788"],
    speaking: ["#52b788", "#1f4a3f", "#40916c", "#74c69d"],
    error: ["#1f4a3f", "#2d6a4f", "#40916c", "#52b788"],
  };

  // --- Logging Helper --------------------------------------------------------
  function appendLog(message, type = 'info') {
    if (!activityLog) return;
    const row = document.createElement('div');
    row.className = `log-row log-${type}`;
    const timestamp = new Date().toLocaleTimeString();
    row.textContent = `[${timestamp}] ${message}`;
    activityLog.appendChild(row);
    activityLog.scrollTop = activityLog.scrollHeight;
  }

  // --- Initialize Dropdowns & Form State -------------------------------------
  function initDropdowns() {
    // Populate Roles
    roleSelect.innerHTML = DEMO_ROLES.map(
      (r) => `<option value="${r.id}">${r.label}</option>`
    ).join('');
    roleSelect.value = "front_desk";

    // Populate Languages
    languageSelect.innerHTML = DEMO_LANGUAGES.map(
      (l) => `<option value="${l.code}">${l.label}</option>`
    ).join('');
    languageSelect.value = "en-IN";

    // Populate Voices
    voiceSelect.innerHTML = DEMO_VOICES.map(
      (v) => `<option value="${v.id}">${v.label} · ${v.gender}</option>`
    ).join('');
    voiceSelect.value = "voice_2";

    // Populate Domains for initial role
    updateDomainsForRole(roleSelect.value);

    // Update active badges & display headings
    updatePillsAndTitles();

    // Event listeners
    roleSelect.addEventListener('change', () => {
      updateDomainsForRole(roleSelect.value);
      updatePillsAndTitles();
    });

    domainSelect.addEventListener('change', updatePillsAndTitles);
    languageSelect.addEventListener('change', updatePillsAndTitles);
    voiceSelect.addEventListener('change', updatePillsAndTitles);
  }

  function updateDomainsForRole(roleId) {
    const selectedRole = DEMO_ROLES.find((r) => r.id === roleId) || DEMO_ROLES[0];
    domainSelect.innerHTML = selectedRole.domains.map(
      (d) => `<option value="${d.id}">${d.label}</option>`
    ).join('');
    // Default to dental_clinic if available, else first domain
    if (selectedRole.domains.some((d) => d.id === "dental_clinic")) {
      domainSelect.value = "dental_clinic";
    } else {
      domainSelect.value = selectedRole.domains[0].id;
    }
  }

  function updatePillsAndTitles() {
    const selectedRole = DEMO_ROLES.find((r) => r.id === roleSelect.value) || DEMO_ROLES[0];
    const selectedDomain = selectedRole.domains.find((d) => d.id === domainSelect.value) || selectedRole.domains[0];
    const selectedLanguage = DEMO_LANGUAGES.find((l) => l.code === languageSelect.value) || DEMO_LANGUAGES[0];
    const selectedVoice = DEMO_VOICES.find((v) => v.id === voiceSelect.value) || DEMO_VOICES[0];

    // Update Pill Badges
    pillRole.textContent = selectedRole.label;
    pillDomain.textContent = selectedDomain.label;
    pillLanguage.textContent = selectedLanguage.label;
    pillVoice.textContent = `${selectedVoice.label} · ${selectedVoice.gender}`;

    // Update Right Display Card
    agentDisplayTitle.textContent = `${selectedVoice.label} · ${selectedRole.label}`;
    agentDisplayIndustry.textContent = selectedDomain.label;
  }

  function setFormLocked(locked) {
    roleSelect.disabled = locked;
    domainSelect.disabled = locked;
    languageSelect.disabled = locked;
    voiceSelect.disabled = locked;
    if (locked) {
      configPanel.classList.add('panel-locked');
    } else {
      configPanel.classList.remove('panel-locked');
    }
  }

  // --- Siri-Style Canvas Orb Visualizer --------------------------------------
  function initSiriOrb() {
    if (!siriCanvas) return;
    const ctx = siriCanvas.getContext('2d');
    if (!ctx) return;

    const W = 400;
    const H = 400;
    const cx = 200;
    const cy = 200;

    function drawBlob(x, y, r, color, alpha, blur) {
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.filter = `blur(${blur}px)`;
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, color);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    function animate(ts) {
      ctx.clearRect(0, 0, W, H);

      // Smooth volume with exponential moving average
      smoothVol = smoothVol * 0.88 + micVolume * 0.12;
      const normVol = Math.min(1, Math.max(0, (smoothVol - 0.01) / 0.14));

      const s = currentOrbState;
      const speed = s === "speaking" ? 1.8 : s === "listening" ? 1.4 : s === "thinking" ? 1.0 : 0.45;
      const t = ts * 0.001 * speed;
      const colors = ORB_PALETTES[s] || ORB_PALETTES.idle;
      const volBoost = s === "listening" ? normVol * 48 : 0;
      const spread = (s === "speaking" ? 95 : s === "listening" ? 82 : s === "thinking" ? 68 : 55) + volBoost;
      const alpha = s === "idle" || s === "connecting" ? 0.60 : 0.76 + (s === "listening" ? normVol * 0.14 : 0);

      // Subtle organic wobble
      const wobble = s === "listening" ? normVol * 9 : 0;
      const wobX = cx + Math.sin(ts * 0.0037) * wobble;
      const wobY = cy + Math.cos(ts * 0.0029) * wobble;

      // Rotating coloured blobs
      for (let i = 0; i < colors.length; i++) {
        const phase = (i * Math.PI * 2) / colors.length;
        const angle = t * (0.6 + i * 0.28) + phase;
        const dist = spread + Math.sin(t * (1.1 + i * 0.35) + i * 1.3) * (spread * 0.32);
        const bx = wobX + Math.cos(angle) * dist;
        const by = wobY + Math.sin(angle * 0.88 + i * 0.18) * dist;
        const br = 118 + Math.sin(t * (1.2 + i * 0.45) + i) * 32 + volBoost * 0.5;
        drawBlob(bx, by, br, colors[i], alpha, 32);
      }

      // Soft diffuse centre glow
      const pulse = Math.sin(t * 2.5) * 12;
      const coreR = (s === "speaking" ? 115 : s === "listening" ? 98 : 82) + pulse + volBoost * 0.6;
      const cg = ctx.createRadialGradient(wobX, wobY, 0, wobX, wobY, coreR);
      cg.addColorStop(0, "rgba(255,255,255,0.15)");
      cg.addColorStop(0.3, colors[0] + "44");
      cg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.save();
      ctx.filter = "blur(28px)";
      ctx.fillStyle = cg;
      ctx.beginPath();
      ctx.arc(wobX, wobY, coreR, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      orbAnimId = requestAnimationFrame(animate);
    }

    orbAnimId = requestAnimationFrame(animate);
  }

  // --- Web Audio Analyser for Reactive Volume ---------------------------------
  function attachVisualizerStream(mediaStream) {
    try {
      if (!audioContext || audioContext.state === "closed") {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        audioContext = new AudioCtx();
      }
      if (audioContext.state === "suspended") {
        audioContext.resume().catch(() => {});
      }

      if (visualizerSource) {
        try { visualizerSource.disconnect(); } catch {}
      }

      analyserNode = audioContext.createAnalyser();
      analyserNode.fftSize = 64;
      analyserNode.smoothingTimeConstant = 0.8;

      visualizerSource = audioContext.createMediaStreamSource(mediaStream);
      visualizerSource.connect(analyserNode);

      const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
      const updateVolumeLoop = () => {
        if (!analyserNode) return;
        analyserNode.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        micVolume = sum / (dataArray.length * 255);
        requestAnimationFrame(updateVolumeLoop);
      };
      updateVolumeLoop();
    } catch (e) {
      console.warn("Audio analyser attach notice:", e);
    }
  }

  function detachVisualizer() {
    if (visualizerSource) {
      try { visualizerSource.disconnect(); } catch {}
      visualizerSource = null;
    }
    if (analyserNode) {
      try { analyserNode.disconnect(); } catch {}
      analyserNode = null;
    }
    micVolume = 0;
    smoothVol = 0;
  }

  // --- Status & UI Update Helpers --------------------------------------------
  function setStatus(state, message) {
    currentOrbState = state;
    statusMessage.textContent = message;
    statusMessage.className = `status-message status-${state}`;
  }

  function showIdleUI() {
    setFormLocked(false);
    setStatus('idle', 'Ready to connect');

    startBtn.classList.remove('hidden');
    connectingBtn.classList.add('hidden');
    activeControls.classList.add('hidden');
    reconfigureBtn.classList.add('hidden');

    roomTag.classList.add('hidden');
    latencyTag.classList.add('hidden');
    isMuted = false;
    micOnIcon.classList.remove('hidden');
    micOffIcon.classList.add('hidden');
    muteBtn.classList.remove('muted-active');
  }

  function showConnectingUI() {
    setFormLocked(true);
    setStatus('connecting', 'Connecting...');

    startBtn.classList.add('hidden');
    connectingBtn.classList.remove('hidden');
    activeControls.classList.add('hidden');
    reconfigureBtn.classList.add('hidden');
  }

  function showActiveCallUI() {
    setFormLocked(true);
    setStatus('listening', 'Ready — just speak');

    startBtn.classList.add('hidden');
    connectingBtn.classList.add('hidden');
    activeControls.classList.remove('hidden');
    reconfigureBtn.classList.add('hidden');
  }

  function showErrorUI(errorMessage) {
    setFormLocked(true);
    setStatus('error', errorMessage);

    startBtn.classList.add('hidden');
    connectingBtn.classList.add('hidden');
    activeControls.classList.add('hidden');
    reconfigureBtn.classList.remove('hidden');
  }

  // --- Start Conversation Flow -----------------------------------------------
  async function startConversation() {
    showConnectingUI();
    appendLog('Initiating LiveKit conversation session...', 'info');

    // Step 1: Verify LiveKit SDK is present
    const Livekit = window.LivekitClient;
    if (!Livekit) {
      showErrorUI('LIVEKIT CLIENT SDK FAILED TO LOAD.');
      appendLog('LiveKit client bundle missing or inaccessible.', 'error');
      return;
    }

    // Step 2: Request microphone permission explicitly
    try {
      appendLog('Requesting browser microphone access...', 'info');
      const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      testStream.getTracks().forEach((t) => t.stop());
      appendLog('Microphone permission confirmed.', 'success');
    } catch (permErr) {
      console.error('Microphone error:', permErr);
      appendLog(`Microphone access error: ${permErr.name}`, 'error');
      // Matches reference screenshot message
      showErrorUI('MICROPHONE PERMISSION DENIED OR DEVICE NOT FOUND.');
      return;
    }

    // Step 3: Fetch scoped session token from backend (/api/token)
    let tokenData;
    const reqBody = {
      participant_name: "Web Visitor",
      role: roleSelect.value,
      domain: domainSelect.value,
      language: languageSelect.value,
      voice_id: voiceSelect.value,
    };

    try {
      appendLog(`Requesting token for persona: ${reqBody.role}/${reqBody.domain} [${reqBody.language}]...`, 'info');
      const res = await fetch('/api/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqBody),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Server returned status ${res.status}`);
      }

      tokenData = await res.json();
      currentRoomName = tokenData.roomName;
      appendLog(`Acquired token for room: ${tokenData.roomName}`, 'success');
    } catch (tokenErr) {
      console.error('Token fetch error:', tokenErr);
      showErrorUI(tokenErr.message ? tokenErr.message.toUpperCase() : 'COULD NOT OBTAIN DEMO TOKEN.');
      appendLog(`Failed to get session token: ${tokenErr.message}`, 'error');
      return;
    }

    // Step 4: Connect to LiveKit WebRTC room
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

      // On Room Connected
      room.on(Livekit.RoomEvent.Connected, async () => {
        appendLog(`Connected to LiveKit room: ${room.name}`, 'success');
        showActiveCallUI();

        roomIdVal.textContent = room.name.replace('web-demo-', '');
        roomTag.classList.remove('hidden');
        latencyTag.classList.remove('hidden');

        // Publish local microphone
        try {
          appendLog('Publishing microphone audio stream...', 'info');
          await room.localParticipant.setMicrophoneEnabled(true);
          appendLog('Microphone published successfully.', 'success');

          const localAudioPub = Array.from(room.localParticipant.audioTrackPublications.values())[0];
          if (localAudioPub && localAudioPub.track && localAudioPub.track.mediaStreamTrack) {
            attachVisualizerStream(new MediaStream([localAudioPub.track.mediaStreamTrack]));
          }
        } catch (micErr) {
          console.warn('Primary mic publish failed, attempting fallback createLocalAudioTrack...', micErr);
          try {
            const fallbackTrack = await Livekit.createLocalAudioTrack();
            await room.localParticipant.publishTrack(fallbackTrack);
            if (fallbackTrack.mediaStreamTrack) {
              attachVisualizerStream(new MediaStream([fallbackTrack.mediaStreamTrack]));
            }
          } catch (fallbackErr) {
            console.error('Fallback microphone publish error:', fallbackErr);
            showErrorUI('FAILED TO PUBLISH MICROPHONE AUDIO.');
          }
        }
      });

      // On Agent Audio Track Subscribed
      room.on(Livekit.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Livekit.Track.Kind.Audio) {
          appendLog('Agent audio stream subscribed.', 'success');
          if (agentAudioSink) {
            track.attach(agentAudioSink);
            agentAudioSink.play().catch(() => {});
          }
          if (track.mediaStreamTrack) {
            attachVisualizerStream(new MediaStream([track.mediaStreamTrack]));
          }
        }
      });

      // On Agent Track Unsubscribed
      room.on(Livekit.RoomEvent.TrackUnsubscribed, (track) => {
        if (track.kind === Livekit.Track.Kind.Audio && agentAudioSink) {
          track.detach(agentAudioSink);
        }
      });

      // Active Speaker Monitoring
      room.on(Livekit.RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const isAgentSpeaking = speakers.some((s) => !s.isLocal);
        const isUserSpeaking = speakers.some((s) => s.isLocal);

        if (isAgentSpeaking) {
          setStatus('speaking', 'Speaking...');
        } else if (isUserSpeaking) {
          setStatus('listening', 'Listening...');
        } else {
          setStatus('listening', 'Ready — just speak');
        }
      });

      // Room Disconnected
      room.on(Livekit.RoomEvent.Disconnected, (reason) => {
        appendLog(`Disconnected from LiveKit room. Reason: ${reason || 'normal'}`, 'warn');
        detachVisualizer();
        showErrorUI('SESSION ENDED');
      });

      // Connect to LiveKit Cloud via WebRTC
      appendLog(`Connecting WebRTC to ${tokenData.serverUrl}...`, 'info');
      await room.connect(tokenData.serverUrl, tokenData.participantToken);

      // Start periodic RTT latency monitor
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
      console.error('Connection failed:', connErr);
      showErrorUI(connErr.message ? connErr.message.toUpperCase() : 'WEBRTC CONNECTION FAILED.');
      appendLog(`LiveKit WebRTC connection error: ${connErr.message}`, 'error');
    }
  }

  // --- End Conversation Flow -------------------------------------------------
  async function endConversation() {
    appendLog('Ending conversation session...', 'info');

    if (pingIntervalId) {
      clearInterval(pingIntervalId);
      pingIntervalId = null;
    }

    const roomToEnd = currentRoomName;

    if (room) {
      try {
        await room.disconnect();
      } catch (e) {
        console.warn('Disconnect notice:', e);
      }
      room = null;
    }

    detachVisualizer();

    if (roomToEnd) {
      fetch('/api/session/end', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_name: roomToEnd }),
      }).catch(() => {});
      currentRoomName = null;
    }

    showIdleUI();
    appendLog('Conversation terminated cleanly.', 'success');
  }

  // --- Close & Reconfigure Flow ----------------------------------------------
  function closeAndReconfigure() {
    if (pingIntervalId) {
      clearInterval(pingIntervalId);
      pingIntervalId = null;
    }

    if (room) {
      try { room.disconnect(); } catch {}
      room = null;
    }

    detachVisualizer();
    currentRoomName = null;

    showIdleUI();
    appendLog('Reset configuration panel. Ready for next session.', 'info');
  }

  // --- Microphone Mute / Unmute Control --------------------------------------
  async function toggleMute() {
    if (!room || !room.localParticipant) return;

    try {
      isMuted = !isMuted;
      await room.localParticipant.setMicrophoneEnabled(!isMuted);

      if (isMuted) {
        micOnIcon.classList.add('hidden');
        micOffIcon.classList.remove('hidden');
        muteBtn.classList.add('muted-active');
        setStatus('idle', 'Microphone Muted');
        appendLog('Microphone muted by user.', 'warn');
      } else {
        micOnIcon.classList.remove('hidden');
        micOffIcon.classList.add('hidden');
        muteBtn.classList.remove('muted-active');
        setStatus('listening', 'Ready — just speak');
        appendLog('Microphone unmuted.', 'info');
      }
    } catch (muteErr) {
      console.error('Mute toggle error:', muteErr);
      appendLog(`Failed to toggle mic: ${muteErr.message}`, 'error');
    }
  }

  // --- Bootstrapping ---------------------------------------------------------
  initDropdowns();
  initSiriOrb();

  startBtn.addEventListener('click', startConversation);
  endBtn.addEventListener('click', endConversation);
  reconfigureBtn.addEventListener('click', closeAndReconfigure);
  muteBtn.addEventListener('click', toggleMute);

  // Auto clean-up on browser tab close or refresh
  window.addEventListener('beforeunload', () => {
    if (room) {
      try { room.disconnect(); } catch {}
    }
  });

  appendLog('Khyra Voice AI Demo interface ready.', 'system');
})();
