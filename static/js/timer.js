/* ====================================================================
   GlycoGuide Remastered — Timers, Inactivity & Hypo Rescue Sound
   ==================================================================== */

// 1. Inactivity Watcher (15 minutes auto-lock)
class InactivityWatcher {
  constructor(timeoutMinutes = 15, onTimeoutCallback) {
    this.timeoutMs = timeoutMinutes * 60 * 1000;
    this.onTimeout = onTimeoutCallback;
    this.lastActivity = Date.now();
    this.timerId = null;

    const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
    events.forEach(evt => {
      window.addEventListener(evt, () => this.recordActivity(), { passive: true });
    });

    this.startChecking();
  }

  recordActivity() {
    this.lastActivity = Date.now();
  }

  startChecking() {
    if (this.timerId) clearInterval(this.timerId);
    this.timerId = setInterval(() => {
      const elapsed = Date.now() - this.lastActivity;
      if (elapsed >= this.timeoutMs) {
        if (typeof this.onTimeout === 'function') {
          this.onTimeout();
        }
      }
    }, 15000); // Check every 15 seconds
  }
}

// 2. Synthesized Web Audio Beep (Zero external audio files needed!)
class AudioAlertService {
  constructor() {
    this.audioCtx = null;
  }

  init() {
    if (!this.audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        this.audioCtx = new AudioContext();
      }
    }
  }

  playHypoAlarm() {
    try {
      this.init();
      if (!this.audioCtx) return;
      if (this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }

      const now = this.audioCtx.currentTime;
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc.type = 'sine';
      // 3 urgent medical beeps
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.setValueAtTime(440, now + 0.15);
      osc.frequency.setValueAtTime(880, now + 0.3);

      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.5);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.5);
    } catch (e) {
      console.warn('Audio alert not allowed or supported:', e);
    }
  }
}

// 3. Hypo Rescue Countdown Engine
class HypoRescueTimer {
  constructor(onTick, onComplete) {
    this.durationSeconds = 15 * 60; // 15 minutes
    this.remainingSeconds = this.durationSeconds;
    this.intervalId = null;
    this.isRunning = false;
    this.onTick = onTick;
    this.onComplete = onComplete;
  }

  start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.remainingSeconds = this.durationSeconds;
    this.tick();
    this.intervalId = setInterval(() => this.tick(), 1000);
  }

  stop() {
    this.isRunning = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  reset() {
    this.stop();
    this.remainingSeconds = this.durationSeconds;
    if (this.onTick) this.onTick(this.formatTime(this.remainingSeconds), 1.0);
  }

  tick() {
    if (this.remainingSeconds <= 0) {
      this.stop();
      if (this.onComplete) this.onComplete();
      return;
    }
    this.remainingSeconds--;
    const progress = this.remainingSeconds / this.durationSeconds;
    if (this.onTick) {
      this.onTick(this.formatTime(this.remainingSeconds), progress);
    }
  }

  formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
}

window.InactivityWatcher = InactivityWatcher;
window.AudioAlertService = AudioAlertService;
window.HypoRescueTimer = HypoRescueTimer;
