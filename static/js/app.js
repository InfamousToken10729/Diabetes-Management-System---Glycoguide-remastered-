/* ====================================================================
   GlycoGuide Remastered — Reactive SPA Application Engine
   ==================================================================== */

class GlycoApp {
  constructor() {
    this.profile = {};
    this.logs = [];
    this.analytics = {};
    this.iobData = { active_iob: 0, doses: [] };
    this.chart = null;
    this.audioAlert = new AudioAlertService();
    this.hypoTimer = null;
    this.currentTab = 'dashboard';
    this.currentHistoryDays = 14;
    this.currentDashboardDays = 1;
    this.authStatus = { is_authenticated: true, password_configured: false };
    this.lastAutoHypoModalId = null;

    this.init();
  }

  async init() {
    this.chart = new GlucoseChart('bgTrendChart');
    this.hypoTimer = new HypoRescueTimer(
      (timeStr, prog) => this.onHypoTick(timeStr, prog),
      () => this.onHypoComplete()
    );

    this.bindEvents();
    this.setupInactivityWatcher();

    // Check Auth Status first
    await this.checkAuthStatus();

    // Load initial profile and clinical data
    await this.loadProfile();
    await this.refreshData();

    // Background update check (hourly)
    this.checkForUpdates(false);
    setInterval(() => this.checkForUpdates(false), 3600000);

    // 60-second periodic IOB refresh
    setInterval(() => this.fetchIOB(), 60000);
  }

  // ==========================================
  // Auth & Session Management
  // ==========================================
  async checkAuthStatus() {
    try {
      const res = await fetch('/api/auth/status');
      const data = await res.json();
      this.authStatus = data;

      if (!data.is_authenticated) {
        window.location.href = '/login';
      }
    } catch (e) {
      console.warn('Auth check error:', e);
    }
  }

  setupInactivityWatcher() {
    // 15-minute inactivity auto-logout: navigates to /login?reason=inactivity
    new InactivityWatcher(15, async () => {
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch (e) {
        console.warn('Inactivity logout fetch failed:', e);
      }
      window.location.href = '/login?reason=inactivity';
    });
  }

  async signOut() {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.warn('Signout failed:', e);
    }
    window.location.replace('/login?reason=signedout');
  }

  async unlockDevice(password) {
    const errorBanner = document.getElementById('unlockErrorBanner');
    if (errorBanner) errorBanner.style.display = 'none';

    try {
      const res = await fetch('/api/auth/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });
      const data = await res.json();
      if (data.success) {
        this.closeModal('unlockModal');
        this.showToast('Device unlocked. Welcome back!', 'success');
        const pwdInput = document.getElementById('unlockPwdInput');
        if (pwdInput) pwdInput.value = '';
        if (errorBanner) errorBanner.style.display = 'none';
        await this.checkAuthStatus();
        await this.refreshData();
      } else {
        const msg = data.error || 'Incorrect master password.';
        if (errorBanner) {
          errorBanner.textContent = msg;
          errorBanner.style.display = 'block';
        } else {
          alert(msg);
        }
      }
    } catch (e) {
      if (errorBanner) {
        errorBanner.textContent = 'Unlock failed: ' + e.message;
        errorBanner.style.display = 'block';
      } else {
        alert('Unlock failed: ' + e.message);
      }
    }
  }

  // --- Account Creation & Password Recovery Helpers ---
  generateRandomRecoveryKey() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    let code = 'GLYCO';
    for (let g = 0; g < 3; g++) {
      code += '-';
      for (let i = 0; i < 4; i++) {
        code += chars.charAt(Math.floor(Math.random() * chars.length));
      }
    }
    return code;
  }

  generateNewRecoveryKey() {
    const input = document.getElementById('newAccRecoveryKey');
    if (input) input.value = this.generateRandomRecoveryKey();
  }

  copyRecoveryKey(inputId) {
    const el = document.getElementById(inputId);
    if (!el || !el.value) return;
    navigator.clipboard.writeText(el.value).then(() => {
      this.showToast('Recovery key copied to clipboard! Save it somewhere safe.', 'success');
    }).catch(() => {
      el.select();
      document.execCommand('copy');
      this.showToast('Recovery key copied to clipboard!', 'success');
    });
  }

  openCreateAccountModal() {
    this.closeModal('unlockModal');
    this.closeModal('resetPasswordModal');
    this.closeModal('changePasswordModal');

    const err = document.getElementById('createAccountErrorBanner');
    if (err) err.style.display = 'none';

    // Populate pre-generated recovery key if empty
    const recInput = document.getElementById('newAccRecoveryKey');
    if (recInput && !recInput.value) {
      recInput.value = this.generateRandomRecoveryKey();
    }

    const nameInput = document.getElementById('newAccDisplayName');
    if (nameInput && !nameInput.value && this.profile.username) {
      nameInput.value = this.profile.username;
    }

    this.openModal('createAccountModal');
  }

  async submitCreateAccount() {
    const name = document.getElementById('newAccDisplayName')?.value?.trim();
    const unit = document.getElementById('newAccUnit')?.value || 'mg/dL';
    const pwd = document.getElementById('newAccPassword')?.value;
    const confirmPwd = document.getElementById('newAccPasswordConfirm')?.value;
    const recKey = document.getElementById('newAccRecoveryKey')?.value?.trim();
    const wipe = document.getElementById('newAccWipeLogs')?.checked;
    const errBanner = document.getElementById('createAccountErrorBanner');

    if (!name) {
      if (errBanner) { errBanner.textContent = 'Please enter a patient display name.'; errBanner.style.display = 'block'; }
      return;
    }
    if (!pwd || pwd.length < 6) {
      if (errBanner) { errBanner.textContent = 'Master password must be at least 6 characters.'; errBanner.style.display = 'block'; }
      return;
    }
    if (pwd !== confirmPwd) {
      if (errBanner) { errBanner.textContent = 'Passwords do not match. Please verify.'; errBanner.style.display = 'block'; }
      return;
    }

    try {
      const res = await fetch('/api/auth/register-new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_name: name,
          password: pwd,
          recovery_key: recKey,
          glucose_unit: unit,
          wipe_data: wipe
        })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Failed to create account.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('createAccountModal');
      this.closeModal('unlockModal');
      this.showToast(data.message || 'Account successfully created!', 'success');
      
      // Clean password inputs
      document.getElementById('newAccPassword').value = '';
      document.getElementById('newAccPasswordConfirm').value = '';

      await this.checkAuthStatus();
      await this.loadProfile();
      await this.refreshData();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Network error: ' + e.message;
        errBanner.style.display = 'block';
      }
    }
  }

  openResetPasswordModal() {
    this.closeModal('unlockModal');
    this.closeModal('createAccountModal');
    this.closeModal('changePasswordModal');

    this.switchRecoveryTab('key');

    const err1 = document.getElementById('resetKeyErrorBanner');
    if (err1) err1.style.display = 'none';
    const err2 = document.getElementById('emergencyResetErrorBanner');
    if (err2) err2.style.display = 'none';

    this.openModal('resetPasswordModal');
  }

  switchRecoveryTab(tab) {
    const btnKey = document.getElementById('btnRecTabKey');
    const btnEmerg = document.getElementById('btnRecTabEmergency');
    const viewKey = document.getElementById('recView-key');
    const viewEmerg = document.getElementById('recView-emergency');

    if (tab === 'key') {
      if (btnKey) btnKey.classList.add('active');
      if (btnEmerg) btnEmerg.classList.remove('active');
      if (viewKey) viewKey.style.display = 'block';
      if (viewEmerg) viewEmerg.style.display = 'none';
    } else {
      if (btnKey) btnKey.classList.remove('active');
      if (btnEmerg) btnEmerg.classList.add('active');
      if (viewKey) viewKey.style.display = 'none';
      if (viewEmerg) viewEmerg.style.display = 'block';
    }
  }

  async submitResetWithKey() {
    const key = document.getElementById('resetRecKeyInput')?.value?.trim();
    const pwd = document.getElementById('resetNewPwdInput')?.value;
    const confirmPwd = document.getElementById('resetNewPwdConfirm')?.value;
    const errBanner = document.getElementById('resetKeyErrorBanner');

    if (!key) {
      if (errBanner) { errBanner.textContent = 'Please enter your emergency recovery key.'; errBanner.style.display = 'block'; }
      return;
    }
    if (!pwd || pwd.length < 6) {
      if (errBanner) { errBanner.textContent = 'New password must be at least 6 characters.'; errBanner.style.display = 'block'; }
      return;
    }
    if (pwd !== confirmPwd) {
      if (errBanner) { errBanner.textContent = 'Passwords do not match.'; errBanner.style.display = 'block'; }
      return;
    }

    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recovery_key: key, new_password: pwd })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Invalid recovery key.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('resetPasswordModal');
      this.closeModal('unlockModal');
      this.showToast('Password reset successfully! Device unlocked.', 'success');

      document.getElementById('resetRecKeyInput').value = '';
      document.getElementById('resetNewPwdInput').value = '';
      document.getElementById('resetNewPwdConfirm').value = '';

      await this.checkAuthStatus();
      await this.refreshData();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Error: ' + e.message;
        errBanner.style.display = 'block';
      }
    }
  }

  async submitEmergencyReset() {
    const confirmVal = document.getElementById('emergencyResetConfirmInput')?.value?.trim();
    const pwd = document.getElementById('emergencyNewPwdInput')?.value;
    const confirmPwd = document.getElementById('emergencyNewPwdConfirm')?.value;
    const errBanner = document.getElementById('emergencyResetErrorBanner');

    if (confirmVal !== 'RESET') {
      if (errBanner) { errBanner.textContent = 'Please type RESET in uppercase to confirm local override.'; errBanner.style.display = 'block'; }
      return;
    }
    if (!pwd || pwd.length < 6) {
      if (errBanner) { errBanner.textContent = 'New password must be at least 6 characters.'; errBanner.style.display = 'block'; }
      return;
    }
    if (pwd !== confirmPwd) {
      if (errBanner) { errBanner.textContent = 'Passwords do not match.'; errBanner.style.display = 'block'; }
      return;
    }

    try {
      const res = await fetch('/api/auth/emergency-reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation: confirmVal, new_password: pwd })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Emergency reset failed.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('resetPasswordModal');
      this.closeModal('unlockModal');
      this.showToast('Emergency reset complete! Master password updated.', 'success');

      document.getElementById('emergencyResetConfirmInput').value = '';
      document.getElementById('emergencyNewPwdInput').value = '';
      document.getElementById('emergencyNewPwdConfirm').value = '';

      await this.checkAuthStatus();
      await this.refreshData();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Error: ' + e.message;
        errBanner.style.display = 'block';
      }
    }
  }

  openChangePasswordModal() {
    const err = document.getElementById('changePasswordErrorBanner');
    if (err) err.style.display = 'none';
    const cur = document.getElementById('changePwdCurrent');
    if (cur) cur.value = '';
    const nw = document.getElementById('changePwdNew');
    if (nw) nw.value = '';
    const cnf = document.getElementById('changePwdConfirm');
    if (cnf) cnf.value = '';
    const rec = document.getElementById('changePwdRecKey');
    if (rec) rec.value = '';

    this.openModal('changePasswordModal');
  }

  async submitChangePassword() {
    const cur = document.getElementById('changePwdCurrent')?.value;
    const nw = document.getElementById('changePwdNew')?.value;
    const cnf = document.getElementById('changePwdConfirm')?.value;
    const rec = document.getElementById('changePwdRecKey')?.value?.trim();
    const errBanner = document.getElementById('changePasswordErrorBanner');

    if (!nw || nw.length < 6) {
      if (errBanner) { errBanner.textContent = 'New password must be at least 6 characters.'; errBanner.style.display = 'block'; }
      return;
    }
    if (nw !== cnf) {
      if (errBanner) { errBanner.textContent = 'New passwords do not match.'; errBanner.style.display = 'block'; }
      return;
    }

    try {
      const res = await fetch('/api/auth/set-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: cur,
          new_password: nw,
          recovery_key: rec || null
        })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Failed to update password.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('changePasswordModal');
      this.closeModal('unlockModal');
      this.showToast('Master password successfully updated!', 'success');
      await this.checkAuthStatus();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Error: ' + e.message;
        errBanner.style.display = 'block';
      }
    }
  }

  // ==========================================
  // Profile & Theme Customization
  // ==========================================
  async loadProfile() {
    try {
      const res = await fetch('/api/profile');
      this.profile = await res.json();
      this.applyTheme(this.profile.theme || 'obsidian');
      this.updateProfileUI();
    } catch (e) {
      console.error('Failed to load profile:', e);
    }
  }

  applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('.theme-card').forEach(card => {
      if (card.dataset.themeId === theme) {
        card.classList.add('active');
      } else {
        card.classList.remove('active');
      }
    });
  }

  async selectTheme(themeId) {
    this.applyTheme(themeId);
    try {
      await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: themeId })
      });
      this.showToast(`Switched theme to ${themeId}`, 'info');
    } catch (e) {
      console.warn('Failed to save theme preference:', e);
    }
  }

  updateProfileUI() {
    const unitPills = document.querySelectorAll('.unit-display-pill');
    unitPills.forEach(p => p.textContent = this.profile.glucose_unit || 'mg/dL');

    const unitLabels = document.querySelectorAll('.dynamic-unit-label');
    unitLabels.forEach(l => l.textContent = this.profile.glucose_unit || 'mg/dL');

    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && val !== undefined && val !== null) el.value = val;
    };

    setVal('setUnit', this.profile.glucose_unit);
    setVal('setTargetBg', this.profile.target_bg);
    setVal('setTargetLow', this.profile.target_low);
    setVal('setTargetHigh', this.profile.target_high);
    setVal('setIcr', this.profile.icr);
    setVal('setIsf', this.profile.isf);
    setVal('setInsulinType', this.profile.insulin_type);
    setVal('setDia', this.profile.insulin_duration_hours);
    setVal('setAiKey', this.profile.ai_api_key);
    setVal('setAiUrl', this.profile.ai_base_url);
    setVal('setGithubRepo', this.profile.github_repo);
    setVal('setDisplayName', this.profile.username);

    // Birth date & real-time calculated age display
    if (this.profile.birth_date) {
      setVal('setBirthDate', this.profile.birth_date);
      this.onBirthDateChange(this.profile.birth_date);
    } else if (this.profile.age) {
      const ageBox = document.getElementById('calculatedAgeDisplay');
      if (ageBox) ageBox.textContent = `${this.profile.age} years old`;
    }

    // AI Provider preset & model setup
    let detectedPreset = 'gemini';
    const baseUrl = this.profile.ai_base_url || '';
    if (baseUrl.includes('api.openai.com')) detectedPreset = 'openai';
    else if (baseUrl.includes('api.groq.com')) detectedPreset = 'groq';
    else if (baseUrl.includes('openrouter.ai')) detectedPreset = 'openrouter';
    else if (baseUrl.includes('11434') || baseUrl.includes('ollama')) detectedPreset = 'ollama';
    else if (baseUrl && !baseUrl.includes('googleapis.com')) detectedPreset = 'custom';

    const presetSelect = document.getElementById('aiPresetSelect');
    if (presetSelect) presetSelect.value = detectedPreset;
    this.onAiPresetChange(detectedPreset, this.profile.ai_model);
  }

  // ==========================================
  // Reactive Data Refresh & Sync
  // ==========================================
  async refreshData() {
    await Promise.all([
      this.fetchLogs(),
      this.fetchIOB(),
      this.fetchAnalytics(this.currentHistoryDays),
      this.fetchReminders()
    ]);
  }

  async fetchLogs() {
    try {
      const res = await fetch('/api/logs?limit=150');
      this.logs = await res.json();
      this.updateDashboardHero();
      this.renderLogTable();
      if (this.chart) {
        this.chart.setData(this.logs, this.profile.glucose_unit || 'mg/dL');
      }
    } catch (e) {
      console.error('Failed to fetch logs:', e);
    }
  }

  async fetchIOB() {
    try {
      const res = await fetch('/api/iob');
      this.iobData = await res.json();
      this.updateIobUI();
    } catch (e) {
      console.error('Failed to fetch IOB:', e);
    }
  }

  updateIobUI() {
    const valEl = document.getElementById('iobValue');
    if (valEl) {
      valEl.textContent = this.iobData.active_iob.toFixed(2);
    }

    const subEl = document.getElementById('iobSubtext');
    if (subEl) {
      subEl.textContent = `${this.iobData.insulin_type || 'Rapid'} (${this.iobData.dia_hours}h DIA)`;
    }

    const circle = document.getElementById('iobRingCircle');
    if (circle) {
      const maxExpected = 8.0;
      const pct = Math.min(1.0, this.iobData.active_iob / maxExpected);
      const circumference = 2 * Math.PI * 42;
      circle.style.strokeDashoffset = circumference * (1 - pct);
    }
  }

  updateDashboardHero() {
    const heroVal = document.getElementById('heroBgValue');
    const heroStatus = document.getElementById('heroBgStatus');
    const heroTime = document.getElementById('heroBgTime');
    const ketoneCard = document.getElementById('ketoneAlertCard');
    const hypoBanner = document.getElementById('hypoRescueBanner');

    const latest = this.logs.find(e => e.bg_value !== null);

    // If no readings exist at all (e.g., after deletion or wipe)
    if (!latest) {
      if (heroVal) heroVal.textContent = '--';
      if (heroStatus) {
        heroStatus.textContent = 'No Data';
        heroStatus.className = 'bg-status-badge status-target';
      }
      if (heroTime) heroTime.textContent = 'Awaiting log...';
      if (hypoBanner) hypoBanner.style.display = 'none';
      if (ketoneCard) ketoneCard.style.display = 'none';
      if (this.hypoTimer) this.hypoTimer.reset();
      return;
    }

    const bg = latest.bg_value;
    const disp = latest.display_bg || bg;
    if (heroVal) heroVal.textContent = disp;

    const dt = new Date(latest.occurred_at);
    if (heroTime) heroTime.textContent = `Logged ${dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

    // Status classification & Reactive Alert Management
    if (bg < 70) {
      heroStatus.textContent = 'Hypoglycemia';
      heroStatus.className = 'bg-status-badge status-low';
      if (hypoBanner) hypoBanner.style.display = 'flex';
      if (ketoneCard) ketoneCard.style.display = 'none';

      // Auto-start hypo timer
      if (!this.hypoTimer.isRunning) {
        this.hypoTimer.start();
      }

      // Automatically launch Hypo Rescue Protocol modal on low reading detection
      if (this.lastAutoHypoModalId !== latest.id) {
        this.lastAutoHypoModalId = latest.id;
        this.openHypoRescue();
      }

      if (bg < 54) this.audioAlert.playHypoAlarm();
    } else if (bg > 250) {
      heroStatus.textContent = 'Very High';
      heroStatus.className = 'bg-status-badge status-severe';
      if (hypoBanner) hypoBanner.style.display = 'none';
      if (ketoneCard) ketoneCard.style.display = 'flex';
      if (this.hypoTimer && this.hypoTimer.isRunning) this.hypoTimer.reset();
    } else if (bg > 180) {
      heroStatus.textContent = 'High';
      heroStatus.className = 'bg-status-badge status-high';
      if (hypoBanner) hypoBanner.style.display = 'none';
      if (ketoneCard) ketoneCard.style.display = 'none';
      if (this.hypoTimer && this.hypoTimer.isRunning) this.hypoTimer.reset();
    } else {
      heroStatus.textContent = 'In Range';
      heroStatus.className = 'bg-status-badge status-target';
      if (hypoBanner) hypoBanner.style.display = 'none';
      if (ketoneCard) ketoneCard.style.display = 'none';
      if (this.hypoTimer && this.hypoTimer.isRunning) this.hypoTimer.reset();
    }
  }

  // ==========================================
  // Analytics & Clinical Equations
  // ==========================================
  async fetchAnalytics(days = 14) {
    try {
      this.currentHistoryDays = days;
      const res = await fetch(`/api/analytics?days=${days}`);
      this.analytics = await res.json();
      this.updateAnalyticsUI();
    } catch (e) {
      console.error('Failed to fetch analytics:', e);
    }
  }

  updateAnalyticsUI() {
    const tir = this.analytics.tir || {};

    // Header Estimated HbA1c Pill
    const headerA1c = document.getElementById('headerEa1cValue');
    if (headerA1c) {
      headerA1c.textContent = tir.estimated_a1c ? `${tir.estimated_a1c.percent}%` : '--%';
    }

    // Dashboard & History eA1c Cards
    const a1cEl = document.getElementById('statEa1c');
    if (a1cEl) {
      if (tir.estimated_a1c) {
        a1cEl.textContent = `${tir.estimated_a1c.percent}%`;
      } else {
        a1cEl.textContent = '--%';
      }
    }

    // Average BG & CV
    const meanEl = document.getElementById('statMeanBg');
    if (meanEl) meanEl.textContent = `${tir.display_mean_bg || '--'} ${this.analytics.unit || 'mg/dL'}`;

    const cvEl = document.getElementById('statCv');
    if (cvEl) cvEl.textContent = `${tir.cv_percent || 0}%`;

    // Multi-segment TIR Bar
    const inRangeBar = document.getElementById('tirBarInRange');
    if (inRangeBar) inRangeBar.style.width = `${tir.in_range || 0}%`;
    const lowBar = document.getElementById('tirBarLow');
    if (lowBar) lowBar.style.width = `${(tir.low || 0) + (tir.very_low || 0)}%`;
    const highBar = document.getElementById('tirBarHigh');
    if (highBar) highBar.style.width = `${(tir.high || 0) + (tir.very_high || 0)}%`;

    const tirPctText = document.getElementById('tirInRangePctText');
    if (tirPctText) tirPctText.textContent = `${tir.in_range || 0}%`;

    // Clinical Ratio Suggestions
    this.renderSuggestions(this.analytics.suggestions || []);
  }

  renderSuggestions(suggestions) {
    const container = document.getElementById('suggestionsList');
    if (!container) return;

    if (!suggestions || suggestions.length === 0) {
      container.innerHTML = `
        <div style="color: var(--text-muted); font-size: 0.88rem; padding: 0.5rem 0;">
          All insulin-to-carb ratios and correction factors match clinical glycemic response targets.
        </div>
      `;
      return;
    }

    container.innerHTML = suggestions.map(s => `
      <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 0.75rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
          <strong style="color: var(--accent-primary); font-size: 0.95rem;">${s.title}</strong>
          <span class="pill">${s.type}</span>
        </div>
        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">${s.description}</p>
        <div style="display: flex; align-items: center; gap: 0.75rem;">
          <span style="font-size: 0.85rem; color: var(--text-muted);">Current: <b>${s.current}</b></span>
          <span>&rarr;</span>
          <span style="font-size: 0.85rem; color: var(--color-target); font-weight: bold;">Suggested: ${s.suggested}</span>
          <button class="btn btn-secondary btn-sm" onclick="app.applySuggestion('${s.type}', ${s.suggested})">Apply</button>
        </div>
      </div>
    `).join('');
  }

  async applySuggestion(type, value) {
    const update = type === 'ICR' ? { icr: value } : { isf: value };
    await fetch('/api/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update)
    });
    this.showToast(`Applied suggested ${type}: ${value}`, 'success');
    await this.loadProfile();
    await this.fetchAnalytics(this.currentHistoryDays);
  }

  // ==========================================
  // Range Button Filter Helpers
  // ==========================================
  setDashboardRange(days) {
    this.currentDashboardDays = days;
    document.querySelectorAll('.btn-range[data-dash-range]').forEach(btn => {
      if (parseInt(btn.dataset.dashRange) === days) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    if (this.chart) {
      // Filter logs within requested days
      const cutoff = new Date(Date.now() - days * 24 * 3600 * 1000);
      const filtered = this.logs.filter(e => new Date(e.occurred_at) >= cutoff);
      this.chart.setData(filtered, this.profile.glucose_unit || 'mg/dL');
    }
  }

  setHistoryRange(days) {
    this.currentHistoryDays = days;
    document.querySelectorAll('.btn-range[data-hist-range]').forEach(btn => {
      if (parseInt(btn.dataset.histRange) === days) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
    this.fetchAnalytics(days);
  }

  // ==========================================
  // Log Table & Interactive History (Inline Edit & Delete)
  // ==========================================
  renderLogTable() {
    const tbody = document.getElementById('logTableBody');
    if (!tbody) return;

    if (!this.logs || this.logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">No logs recorded yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = this.logs.map(e => {
      const dt = new Date(e.occurred_at);
      const dateStr = dt.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      const tags = (e.tags || []).map(t => `<span class="pill" style="font-size: 0.7rem;">${t}</span>`).join(' ');
      const spoiled = e.spoiled_insulin ? `<span class="pill" style="color: #ef4444; border-color: rgba(239,68,68,0.4);">Spoiled</span>` : '';

      return `
        <tr>
          <td>${dateStr}</td>
          <td><b>${e.display_bg || '--'}</b></td>
          <td>${e.insulin_units ? e.insulin_units + ' U' : '--'}</td>
          <td>${e.carbs ? e.carbs + ' g' : '--'}</td>
          <td>${e.meal_description || e.dose_kind || '--'} ${spoiled}</td>
          <td>${tags}</td>
          <td style="text-align: right; white-space: nowrap;">
            <button class="btn btn-secondary btn-sm" onclick="app.openEditLogModal(${e.id})" title="Edit Reading" style="margin-right: 0.35rem;">&#9998; Edit</button>
            <button class="btn btn-secondary btn-sm" onclick="app.deleteLog(${e.id})" title="Delete Reading">&times;</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  openEditLogModal(id) {
    const entry = this.logs.find(e => e.id === id);
    if (!entry) return;

    document.getElementById('editLogId').value = entry.id;
    document.getElementById('editBgVal').value = entry.display_bg || entry.bg_value || '';
    document.getElementById('editInsulinVal').value = entry.insulin_units || '';
    document.getElementById('editCarbsVal').value = entry.carbs || '';
    document.getElementById('editDoseKind').value = entry.dose_kind || 'meal';
    document.getElementById('editDescVal').value = entry.meal_description || '';
    document.getElementById('editSpoiledVal').checked = !!entry.spoiled_insulin;

    this.openModal('editLogModal');
  }

  async submitEditLog() {
    const id = document.getElementById('editLogId').value;
    const bg = document.getElementById('editBgVal').value;
    const insulin = document.getElementById('editInsulinVal').value;
    const carbs = document.getElementById('editCarbsVal').value;
    const doseKind = document.getElementById('editDoseKind').value;
    const desc = document.getElementById('editDescVal').value;
    const spoiled = document.getElementById('editSpoiledVal').checked;

    try {
      const res = await fetch(`/api/logs/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bg_value: bg !== '' ? parseFloat(bg) : null,
          insulin_units: insulin !== '' ? parseFloat(insulin) : null,
          carbs: carbs !== '' ? parseFloat(carbs) : null,
          dose_kind: doseKind,
          meal_description: desc,
          spoiled_insulin: spoiled
        })
      });

      if (!res.ok) {
        const err = await res.json();
        alert('Failed to update log: ' + (err.error || 'Server error'));
        return;
      }

      this.closeModal('editLogModal');
      this.showToast('Reading updated successfully.', 'success');
      // Full reactive refresh without page reload
      await this.refreshData();
    } catch (e) {
      alert('Error updating reading: ' + e.message);
    }
  }

  async deleteLog(id) {
    if (!confirm('Are you sure you want to delete this reading?')) return;
    try {
      await fetch(`/api/logs/${id}`, { method: 'DELETE' });
      this.showToast('Reading deleted.', 'info');
      // Immediate reactive refresh: updates hero, hides warning banner, recalculates eA1c
      await this.refreshData();
    } catch (e) {
      console.error('Delete log failed:', e);
    }
  }

  // ==========================================
  // Hypo Rescue Protocol Engine & Re-Test
  // ==========================================
  openHypoRescue() {
    this.openModal('hypoModal');
    if (!this.hypoTimer.isRunning) {
      this.hypoTimer.start();
    }
    this.audioAlert.playHypoAlarm();
  }

  onHypoTick(timeStr, prog) {
    const timerEl = document.getElementById('hypoCountdown');
    if (timerEl) timerEl.textContent = timeStr;

    // Also update banner countdown button text
    const bannerText = document.getElementById('bannerHypoTimeText');
    if (bannerText) bannerText.textContent = timeStr;
  }

  onHypoComplete() {
    this.audioAlert.playHypoAlarm();
    this.showToast('15-minute hypo recovery window elapsed! Please re-test glucose immediately.', 'error');
    const recInput = document.getElementById('hypoRecoveryBg');
    if (recInput) recInput.focus();
  }

  async submitHypoRecovery() {
    const val = document.getElementById('hypoRecoveryBg').value;
    if (!val) {
      alert('Please enter your recovery blood glucose reading.');
      return;
    }

    try {
      await fetch('/api/logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bg_value: parseFloat(val),
          dose_kind: 'hypo-recovery',
          tags: ['hypo-recovery']
        })
      });

      // Stop timer and close modal
      this.hypoTimer.reset();
      this.closeModal('hypoModal');
      document.getElementById('hypoRecoveryBg').value = '';

      // Immediately refresh all data reactively
      await this.refreshData();
      this.showToast('Recovery reading logged. Hypo protocol concluded.', 'success');
    } catch (e) {
      alert('Failed to log recovery glucose: ' + e.message);
    }
  }

  // ==========================================
  // Settings Subtabs, AI Presets & Audit Logs
  // ==========================================
  switchSettingsSubTab(subTabId) {
    document.querySelectorAll('.settings-subtab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.settings-subview').forEach(v => v.style.display = 'none');

    const activeBtn = document.getElementById(`subTabBtn-${subTabId}`);
    if (activeBtn) activeBtn.classList.add('active');

    const activeView = document.getElementById(`subView-${subTabId}`);
    if (activeView) activeView.style.display = 'block';

    if (subTabId === 'audit') {
      this.fetchAuditLogs();
    }
    if (subTabId === 'themes') {
      this.fetchServerBackups();
    }
  }

  // Birth Date & Age Calculator
  onBirthDateChange(dateStr) {
    const display = document.getElementById('calculatedAgeDisplay');
    if (!display) return;
    if (!dateStr) {
      display.textContent = '-- years old';
      return;
    }
    const birth = new Date(dateStr);
    const now = new Date();
    let age = now.getFullYear() - birth.getFullYear();
    const m = now.getMonth() - birth.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < birth.getDate())) {
      age--;
    }
    if (isNaN(age) || age < 0) {
      display.textContent = '--';
    } else {
      display.textContent = `${age} years old`;
    }
  }

  // Provider-Specific AI Vision Models Catalog
  onAiPresetChange(preset, currentModel = null) {
    const modelsByProvider = {
      gemini: {
        url: 'https://generativelanguage.googleapis.com',
        defaultModel: 'gemini-2.5-flash',
        models: [
          { id: 'gemini-2.5-flash', label: 'gemini-2.5-flash (Recommended — Fast Multimodal)' },
          { id: 'gemini-2.5-pro', label: 'gemini-2.5-pro (High Precision Multimodal)' },
          { id: 'gemini-2.0-flash', label: 'gemini-2.0-flash (Flash Multimodal)' },
          { id: 'gemini-1.5-flash', label: 'gemini-1.5-flash (Standard Production)' },
          { id: 'gemini-1.5-pro', label: 'gemini-1.5-pro (Deep Analysis)' },
          { id: '__custom__', label: 'Custom / Other Gemini Model...' }
        ]
      },
      openai: {
        url: 'https://api.openai.com/v1/chat/completions',
        defaultModel: 'gpt-4o-mini',
        models: [
          { id: 'gpt-4o-mini', label: 'gpt-4o-mini (Recommended — Fast Multimodal)' },
          { id: 'gpt-4o', label: 'gpt-4o (Omni Multimodal Vision)' },
          { id: 'gpt-4-turbo', label: 'gpt-4-turbo (Vision Capable)' },
          { id: '__custom__', label: 'Custom / Other OpenAI Model...' }
        ]
      },
      groq: {
        url: 'https://api.groq.com/openai/v1/chat/completions',
        defaultModel: 'llama-3.2-11b-vision-preview',
        models: [
          { id: 'llama-3.2-11b-vision-preview', label: 'llama-3.2-11b-vision-preview (Ultra-Fast Vision)' },
          { id: 'llama-3.2-90b-vision-preview', label: 'llama-3.2-90b-vision-preview (Large Vision)' },
          { id: 'llama-3.3-70b-versatile', label: 'llama-3.3-70b-versatile (Text & Reasoning)' },
          { id: '__custom__', label: 'Custom / Other Groq Model...' }
        ]
      },
      openrouter: {
        url: 'https://openrouter.ai/api/v1/chat/completions',
        defaultModel: 'google/gemini-2.5-flash',
        models: [
          { id: 'google/gemini-2.5-flash', label: 'google/gemini-2.5-flash' },
          { id: 'google/gemini-2.0-flash-001', label: 'google/gemini-2.0-flash-001' },
          { id: 'openai/gpt-4o-mini', label: 'openai/gpt-4o-mini' },
          { id: 'anthropic/claude-3.5-sonnet', label: 'anthropic/claude-3.5-sonnet' },
          { id: 'meta-llama/llama-3.2-11b-vision-instruct', label: 'meta-llama/llama-3.2-11b-vision-instruct' },
          { id: '__custom__', label: 'Custom / Other OpenRouter Model...' }
        ]
      },
      ollama: {
        url: 'http://localhost:11434/v1/chat/completions',
        defaultModel: 'llama3.2-vision',
        models: [
          { id: 'llama3.2-vision', label: 'llama3.2-vision (Local Vision)' },
          { id: 'llava:latest', label: 'llava:latest (Local Multimodal)' },
          { id: 'bakllava', label: 'bakllava (Fast Local Vision)' },
          { id: '__custom__', label: 'Custom / Other Local Ollama Model...' }
        ]
      },
      custom: {
        url: '',
        defaultModel: '__custom__',
        models: [
          { id: '__custom__', label: 'Custom / Self-Hosted Model...' }
        ]
      }
    };

    const prov = modelsByProvider[preset] || modelsByProvider.custom;
    const modelSelect = document.getElementById('aiModelSelect');
    const urlInput = document.getElementById('setAiUrl');
    const customGroup = document.getElementById('customModelGroup');
    const customInput = document.getElementById('setAiModelCustom');

    if (urlInput && prov.url) {
      urlInput.value = prov.url;
    }

    if (modelSelect) {
      modelSelect.innerHTML = prov.models.map(m => `<option value="${m.id}">${m.label}</option>`).join('');

      const targetModel = currentModel || prov.defaultModel;
      const exists = prov.models.some(m => m.id === targetModel);

      if (exists && targetModel !== '__custom__') {
        modelSelect.value = targetModel;
        if (customGroup) customGroup.style.display = 'none';
      } else {
        modelSelect.value = '__custom__';
        if (customGroup) customGroup.style.display = 'block';
        if (customInput && targetModel && targetModel !== '__custom__') {
          customInput.value = targetModel;
        }
      }
    }
  }

  onAiModelChange(modelId) {
    const customGroup = document.getElementById('customModelGroup');
    const customInput = document.getElementById('setAiModelCustom');
    if (modelId === '__custom__') {
      if (customGroup) customGroup.style.display = 'block';
      if (customInput) customInput.focus();
    } else {
      if (customGroup) customGroup.style.display = 'none';
    }
  }

  getSelectedAiModel() {
    const modelSelect = document.getElementById('aiModelSelect');
    if (!modelSelect) return null;
    if (modelSelect.value === '__custom__') {
      return document.getElementById('setAiModelCustom')?.value?.trim() || null;
    }
    return modelSelect.value || null;
  }

  // ==========================================
  // Correction Bolus & Overdose Safety Guard
  // ==========================================
  onDoseKindChange(kind) {
    const corrSection = document.getElementById('correctionDetailsSection');
    const overdoseWarn = document.getElementById('correctionOverdoseWarning');
    const bgInput = document.getElementById('correctionBgInput');

    if (kind === 'correction') {
      if (corrSection) corrSection.style.display = 'block';

      // Pre-fill with recent current BG if available
      if (this.currentBg && bgInput && !bgInput.value) {
        bgInput.value = this.currentBg;
      }
      this.recomputeCorrectionRecommendation();
    } else {
      if (corrSection) corrSection.style.display = 'none';
      if (overdoseWarn) overdoseWarn.style.display = 'none';
      this._recommendedCorrectionDose = null;
    }
  }

  async recomputeCorrectionRecommendation() {
    const bgVal = parseFloat(document.getElementById('correctionBgInput')?.value);
    const recBox = document.getElementById('correctionRecommendationBox');
    const recDoseEl = document.getElementById('correctionDoseValue');
    const recNoteEl = document.getElementById('correctionDetailsNote');

    if (isNaN(bgVal) || bgVal <= 0) {
      if (recBox) recBox.style.display = 'none';
      this._recommendedCorrectionDose = null;
      this.checkCorrectionOverdose();
      return;
    }

    try {
      const res = await fetch('/api/calculate-bolus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bg: bgVal, carbs: 0, tags: ['correction'] })
      });
      const data = await res.json();

      if (recBox) recBox.style.display = 'block';

      if (data.status === 'blocked') {
        this._recommendedCorrectionDose = 0;
        if (recDoseEl) {
          recDoseEl.textContent = '0.0 U';
          recDoseEl.style.color = 'var(--color-hypo)';
        }
        if (recNoteEl) {
          recNoteEl.textContent = '⚠️ Blood glucose is low (< 70 mg/dL). Do not administer correction insulin!';
          recNoteEl.style.color = 'var(--color-hypo)';
        }
      } else if (data.status === 'missing_isf' || !data.isf) {
        this._recommendedCorrectionDose = null;
        if (recDoseEl) {
          recDoseEl.textContent = '-- U';
          recDoseEl.style.color = 'var(--text-muted)';
        }
        if (recNoteEl) {
          recNoteEl.innerHTML = `<span style="color: #fbbf24;">⚠️ <strong>ISF Not Configured:</strong> Please enter your Insulin Sensitivity Factor (ISF) in <a href="#settings" onclick="app.switchTab('settings'); app.switchSettingsSubTab('clinical'); app.closeModal('logInsulinModal');" style="color: var(--accent-primary); text-decoration: underline;">Settings → Clinical Targets</a> to calculate correction doses.</span>`;
        }
      } else {
        const dose = parseFloat(data.recommended_dose ?? data.total_units ?? data.correction_bolus) || 0;
        this._recommendedCorrectionDose = dose;
        this._currentIcr = parseFloat(data.icr) || parseFloat(this.profile?.icr) || null;

        if (recDoseEl) {
          recDoseEl.textContent = `${dose.toFixed(1)} U`;
          recDoseEl.style.color = 'var(--accent-primary)';
        }
        if (recNoteEl) {
          const unit = this.profile?.glucose_unit || 'mg/dL';
          recNoteEl.textContent = `Target: ${data.target_bg || 110} ${unit} · ISF: ${data.isf} ${unit}/U · Active IOB: ${data.active_iob || 0} U`;
          recNoteEl.style.color = 'var(--text-secondary)';
        }
      }

      this.checkCorrectionOverdose();
    } catch (e) {
      console.warn('Failed to calculate correction recommendation:', e);
    }
  }

  applyRecommendedCorrection() {
    if (this._recommendedCorrectionDose !== undefined && this._recommendedCorrectionDose !== null) {
      const unitsInput = document.getElementById('quickUnitsVal');
      if (unitsInput) {
        unitsInput.value = this._recommendedCorrectionDose.toFixed(1);
        this.checkCorrectionOverdose();
      }
    }
  }

  checkCorrectionOverdose() {
    const kind = document.getElementById('quickDoseKind')?.value;
    const warnBox = document.getElementById('correctionOverdoseWarning');
    const warnText = document.getElementById('correctionOverdoseText');

    if (kind !== 'correction' || this._recommendedCorrectionDose === null || this._recommendedCorrectionDose === undefined) {
      if (warnBox) warnBox.style.display = 'none';
      return;
    }

    const entered = parseFloat(document.getElementById('quickUnitsVal')?.value) || 0;
    const rec = this._recommendedCorrectionDose;
    const icr = this._currentIcr || parseFloat(this.profile?.icr) || null;

    // Trigger warning if entered dose is significantly higher than recommended (> 0.2 U difference)
    if (entered > rec + 0.2) {
      const excessUnits = entered - rec;
      let carbRecommendation = '';
      if (icr && icr > 0) {
        const carbsNeeded = Math.round(excessUnits * icr);
        carbRecommendation = `To prevent hypoglycemia, recommend consuming approximately <strong style="color: #ffffff; text-decoration: underline;">${carbsNeeded}g of fast-acting carbs</strong> (based on ICR of ${icr} g/U).`;
      } else {
        carbRecommendation = `To prevent hypoglycemia, consider consuming fast-acting carbohydrates or adjusting your dose.`;
      }

      if (warnBox && warnText) {
        warnText.innerHTML = `Entered dose (<strong>${entered.toFixed(1)} U</strong>) exceeds recommended correction (<strong>${rec.toFixed(1)} U</strong>) by <strong>${excessUnits.toFixed(1)} U</strong>.<br>${carbRecommendation}`;
        warnBox.style.display = 'block';
      }
    } else {
      if (warnBox) warnBox.style.display = 'none';
    }
  }

  async fetchAuditLogs() {
    const tbody = document.getElementById('auditLogTableBody');
    if (!tbody) return;

    try {
      const res = await fetch('/api/system/audit-logs');
      const data = await res.json();
      const logs = data.audit_logs || [];

      if (logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">No activity recorded yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = logs.map(l => {
        const dt = new Date(l.occurred_at);
        const timeStr = dt.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        let badgeColor = 'var(--accent-primary)';
        if (l.event_type.includes('delete') || l.event_type.includes('clear')) badgeColor = 'var(--color-hypo)';
        if (l.event_type.includes('auth')) badgeColor = 'var(--color-target)';

        return `
          <tr>
            <td style="font-size: 0.8rem; color: var(--text-secondary);">${timeStr}</td>
            <td><span class="pill" style="color: ${badgeColor}; border-color: ${badgeColor}33;">${l.event_type}</span></td>
            <td style="font-size: 0.85rem;">${l.description}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      console.warn('Failed to fetch audit logs:', e);
    }
  }

  // ==========================================
  // Secure 2-Step Wipe Clinical Data
  // ==========================================
  async executeWipeData() {
    const pwd = document.getElementById('wipeDataPasswordInput')?.value;
    const errorBanner = document.getElementById('wipeErrorBanner');

    if (!pwd) {
      if (errorBanner) {
        errorBanner.textContent = 'Please enter your master password.';
        errorBanner.style.display = 'block';
      }
      return;
    }

    try {
      const res = await fetch('/api/system/clear-data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        // If password is wrong: DO NOT delete data and prompt user to re-enter!
        if (errorBanner) {
          errorBanner.textContent = data.error || 'Incorrect master password. Clinical data was NOT deleted.';
          errorBanner.style.display = 'block';
        }
        return;
      }

      // Success
      if (errorBanner) errorBanner.style.display = 'none';
      document.getElementById('wipeDataPasswordInput').value = '';
      this.closeModal('wipeDataModal');
      this.showToast('Clinical records wiped successfully.', 'success');
      await this.refreshData();
    } catch (e) {
      if (errorBanner) {
        errorBanner.textContent = 'Server communication error: ' + e.message;
        errorBanner.style.display = 'block';
      }
    }
  }

  // ==========================================
  // Password Visibility Toggle Utility
  // ==========================================
  togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === 'password') {
      input.type = 'text';
      btn.innerHTML = `<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
    } else {
      input.type = 'password';
      btn.innerHTML = `<svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
    }
  }

  // ==========================================
  // Permanently Delete Master Account & Factory Reset
  // ==========================================
  async executeDeleteAccount() {
    const pwd = document.getElementById('deleteAccountPasswordInput')?.value;
    const confirmVal = document.getElementById('deleteAccountConfirmInput')?.value?.trim();
    const errBanner = document.getElementById('deleteAccountErrorBanner');

    if (!pwd) {
      if (errBanner) {
        errBanner.textContent = 'Please enter your master password.';
        errBanner.style.display = 'block';
      }
      return;
    }

    if (confirmVal !== 'DELETE') {
      if (errBanner) {
        errBanner.textContent = 'Type "DELETE" in capital letters to confirm permanent deletion.';
        errBanner.style.display = 'block';
      }
      return;
    }

    try {
      const res = await fetch('/api/system/delete-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd, confirmation: confirmVal })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Incorrect master password. Account was NOT deleted.';
          errBanner.style.display = 'block';
        }
        return;
      }

      // Success
      this.closeModal('deleteAccountModal');
      // Direct immediately to fresh setup as a brand new user
      window.location.href = data.redirect || '/login?mode=setup';
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Server communication error: ' + e.message;
        errBanner.style.display = 'block';
      }
    }
  }

  // ==========================================
  // Bolus Calculator Engine
  // ==========================================
  async recalculateBolus() {
    const bg = document.getElementById('calcBgInput')?.value;
    const carbs = document.getElementById('calcCarbsInput')?.value || 0;
    const fat = document.getElementById('calcFatInput')?.value || 0;
    const sugar = document.getElementById('calcSugarInput')?.value || 0;

    const tags = [];
    if (document.getElementById('tagExercise')?.checked) tags.push('exercise');
    if (document.getElementById('tagSick')?.checked) tags.push('sick');
    if (document.getElementById('tagStress')?.checked) tags.push('stress');

    try {
      const res = await fetch('/api/calculate-bolus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bg, carbs, fat, sugar, tags })
      });
      const data = await res.json();
      this.renderBolusResult(data);
    } catch (e) {
      console.error('Bolus calculation error:', e);
    }
  }

  renderBolusResult(data) {
    const totalEl = document.getElementById('calcRecommendedTotal');
    const breakdownEl = document.getElementById('calcBreakdownBox');
    const warningEl = document.getElementById('calcWarningBox');

    if (data.status === 'blocked') {
      if (totalEl) totalEl.textContent = '0.0 U';
      if (warningEl) {
        warningEl.style.display = 'block';
        warningEl.textContent = data.message;
      }
      return;
    }

    if (warningEl) warningEl.style.display = 'none';
    if (totalEl) totalEl.textContent = `${data.total_units} U`;

    if (breakdownEl) {
      let splitText = '';
      if (data.split_bolus) {
        splitText = `<div style="margin-top: 0.5rem; color: var(--color-hyper); font-size: 0.82rem;">${data.split_bolus.reason} (Give ${data.split_bolus.upfront_units}U now, ${data.split_bolus.later_units}U in 2h)</div>`;
      }

      breakdownEl.innerHTML = `
        <div style="font-size: 0.85rem; color: var(--text-secondary); display: flex; flex-direction: column; gap: 0.35rem;">
          <div>Meal Bolus: <b>${data.meal_bolus} U</b> | Correction: <b>${data.correction_bolus} U</b></div>
          <div>Active IOB Subtracted: <b style="color: var(--accent-primary);">${data.iob_subtracted} U</b> | Context Factor: <b>${data.tag_factor}x</b></div>
          ${splitText}
        </div>
      `;
    }
  }

  async submitBolusLog() {
    const bg = document.getElementById('calcBgInput')?.value;
    const carbs = document.getElementById('calcCarbsInput')?.value;
    const fat = document.getElementById('calcFatInput')?.value;
    const sugar = document.getElementById('calcSugarInput')?.value;
    const units = document.getElementById('calcRecommendedTotal')?.textContent.replace(' U', '');
    const desc = document.getElementById('calcDescInput')?.value;

    const tags = [];
    if (document.getElementById('tagExercise')?.checked) tags.push('exercise');
    if (document.getElementById('tagSick')?.checked) tags.push('sick');
    if (document.getElementById('tagStress')?.checked) tags.push('stress');

    await fetch('/api/logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bg_value: bg || null,
        insulin_units: parseFloat(units) || null,
        carbs: parseFloat(carbs) || null,
        fat: parseFloat(fat) || null,
        sugar: parseFloat(sugar) || null,
        meal_description: desc || null,
        dose_kind: carbs > 0 ? 'meal' : 'correction',
        tags
      })
    });

    this.showToast('Insulin dose logged successfully! 2-hour reminder scheduled.', 'success');
    await this.refreshData();
  }

  // ==========================================
  // AI Meal Image & Text Nutrition Scanner
  // ==========================================
  async analyzeMealImage() {
    const desc = document.getElementById('mealDescInput')?.value || '';
    const fileInput = document.getElementById('mealFileInput');
    const btn = document.getElementById('btnAnalyzeMeal');

    let imageB64 = null;
    if (fileInput && fileInput.files && fileInput.files[0]) {
      imageB64 = await this.fileToBase64(fileInput.files[0]);
    }

    if (!desc && !imageB64) {
      alert('Please provide a meal description or select a photo.');
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Analyzing Nutritional Composition...';

    try {
      const res = await fetch('/api/analyze-meal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc, image: imageB64 })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to analyze');

      this.renderMealAnalysis(data);
    } catch (e) {
      alert('Meal analysis error: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Analyze Meal with AI';
    }
  }

  fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  renderMealAnalysis(data) {
    const box = document.getElementById('mealAnalysisResult');
    if (!box) return;

    box.style.display = 'block';
    const totals = data.totals || {};

    box.innerHTML = `
      <div style="background: rgba(14, 165, 233, 0.08); border: 1px solid var(--border-highlight); border-radius: var(--radius-md); padding: 1.25rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
          <strong style="font-size: 1.1rem; color: var(--accent-primary);">AI Nutritional Breakdown</strong>
          <span class="pill">Confidence: ${data.confidence || 'Medium'}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; text-align: center; margin-bottom: 1rem;">
          <div style="background: rgba(0,0,0,0.3); padding: 0.6rem; border-radius: var(--radius-sm);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">CARBS</div>
            <div style="font-size: 1.4rem; font-weight: bold; color: var(--accent-primary);">${totals.carbs || 0}g</div>
          </div>
          <div style="background: rgba(0,0,0,0.3); padding: 0.6rem; border-radius: var(--radius-sm);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">SUGAR</div>
            <div style="font-size: 1.4rem; font-weight: bold; color: #f43f5e;">${totals.sugar || 0}g</div>
          </div>
          <div style="background: rgba(0,0,0,0.3); padding: 0.6rem; border-radius: var(--radius-sm);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">PROTEIN</div>
            <div style="font-size: 1.4rem; font-weight: bold; color: #10b981;">${totals.protein || 0}g</div>
          </div>
          <div style="background: rgba(0,0,0,0.3); padding: 0.6rem; border-radius: var(--radius-sm);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">FAT</div>
            <div style="font-size: 1.4rem; font-weight: bold; color: #f59e0b;">${totals.fat || 0}g</div>
          </div>
        </div>
        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">${data.notes || ''}</p>
        <button class="btn btn-primary" style="width: 100%;" onclick="app.sendToBolusCalculator(${totals.carbs || 0}, ${totals.fat || 0}, ${totals.sugar || 0})">
          Send to Bolus Calculator &rarr;
        </button>
      </div>
    `;
  }

  sendToBolusCalculator(carbs, fat, sugar) {
    const cInput = document.getElementById('calcCarbsInput');
    const fInput = document.getElementById('calcFatInput');
    const sInput = document.getElementById('calcSugarInput');
    if (cInput) cInput.value = carbs;
    if (fInput) fInput.value = fat;
    if (sInput) sInput.value = sugar;
    this.recalculateBolus();
  }

  // ==========================================
  // Reminders
  // ==========================================
  async fetchReminders() {
    try {
      const res = await fetch('/api/reminders');
      const rems = await res.json();
      const listEl = document.getElementById('remindersList');
      if (!listEl) return;

      if (!rems || rems.length === 0) {
        listEl.innerHTML = `<span style="color: var(--text-muted); font-size: 0.85rem;">No active reminders.</span>`;
        return;
      }

      listEl.innerHTML = rems.map(r => {
        const dt = new Date(r.due_at);
        return `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border-subtle);">
            <div>
              <div style="font-size: 0.88rem; font-weight: 600;">${r.title}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">Due at ${dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="app.completeReminder(${r.id})">Done</button>
          </div>
        `;
      }).join('');
    } catch (e) {
      console.error('Failed to fetch reminders:', e);
    }
  }

  async completeReminder(id) {
    await fetch(`/api/reminders/${id}/done`, { method: 'PUT' });
    await this.fetchReminders();
  }

  // ==========================================
  // System Updates (GitHub Releases)
  // ==========================================
  async saveGithubRepo(silent = false) {
    const input = document.getElementById('setGithubRepo');
    if (!input) return false;
    const repoUrl = input.value.trim();
    if (!repoUrl) {
      if (!silent) this.showToast('Please enter a GitHub repository URL.', 'warning');
      return false;
    }
    try {
      const res = await fetch('/api/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ github_repo: repoUrl })
      });
      if (res.ok) {
        this.profile = await res.json();
        if (!silent) this.showToast('GitHub repository URL saved!', 'success');
        return true;
      }
    } catch (e) {
      if (!silent) this.showToast('Failed to save repository URL.', 'danger');
    }
    return false;
  }

  async checkForUpdates(showToastIfNone = true) {
    try {
      const repoInput = document.getElementById('setGithubRepo');
      let queryUrl = '/api/system/update/check';
      if (showToastIfNone && repoInput && repoInput.value.trim()) {
        const entered = repoInput.value.trim();
        if (entered !== (this.profile.github_repo || '').trim()) {
          await this.saveGithubRepo(true);
        }
        queryUrl += '?repo=' + encodeURIComponent(entered);
      }

      const res = await fetch(queryUrl);
      const data = await res.json();
      const banner = document.getElementById('systemUpdateFloatingCard');
      const statusEl = document.getElementById('githubRepoStatusText');

      if (statusEl) {
        if (data.error) {
          statusEl.style.color = '#f87171';
          statusEl.textContent = data.message || 'Could not verify updates.';
        } else if (data.has_update) {
          statusEl.style.color = 'var(--accent-primary)';
          statusEl.textContent = `Update available (${data.current_commit || '?'} -> ${data.latest_commit}): "${data.message}"`;
        } else {
          statusEl.style.color = 'var(--text-muted)';
          const commitText = data.current_commit ? `Current: ${data.current_commit}` : (data.latest_commit ? `Latest: ${data.latest_commit}` : '');
          statusEl.textContent = `${data.repo ? 'Repo: ' + data.repo + ' · ' : ''}${commitText ? commitText + ' · ' : ''}${data.message || 'Up to date'}`;
        }
      }

      if (data.has_update) {
        if (banner) {
          banner.style.display = 'flex';
          const msgEl = document.getElementById('updateBannerMessage');
          if (msgEl) msgEl.textContent = `New Version Available (${data.latest_commit}): "${data.message}"`;
        }
        if (showToastIfNone) {
          this.showToast(`Update available (${data.latest_commit})! Use the banner above to install.`, 'info');
        }
      } else {
        if (banner) banner.style.display = 'none';
        if (showToastIfNone) {
          if (data.error) {
            this.showToast(data.message || 'Could not check GitHub updates right now.', 'warning');
          } else {
            this.showToast(data.message || 'Your system is up-to-date!', 'success');
          }
        }
      }
    } catch (e) {
      console.warn('Update check failed:', e);
      if (showToastIfNone) {
        this.showToast('Update check failed: unable to reach server.', 'danger');
      }
    }
  }

  async waitForServerRestart(maxWaitMs = 20000) {
    const start = Date.now();
    while (Date.now() - start < maxWaitMs) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const probe = await fetch('/api/auth/status', { cache: 'no-store' });
        if (probe.ok) return true;
      } catch (_) {
        // Server still restarting; keep polling
      }
    }
    return false;
  }

  async applySystemUpdate() {
    const btn = document.getElementById('btnApplyUpdate');
    const msgEl = document.getElementById('updateBannerMessage');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Updating...';
    }
    if (msgEl) msgEl.textContent = 'Creating database backup and pulling latest files...';

    try {
      const repoInput = document.getElementById('setGithubRepo');
      const payload = repoInput && repoInput.value.trim() ? { repo: repoInput.value.trim() } : {};
      const res = await fetch('/api/system/update/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        if (data.restarting) {
          if (msgEl) msgEl.textContent = 'Update installed! Restarting GlycoGuide server...';
          this.showToast('Update installed! Waiting for server restart...', 'info');
          await new Promise(r => setTimeout(r, 1200));
          const cameBack = await this.waitForServerRestart(20000);
          if (cameBack) {
            window.location.reload();
          } else {
            this.showToast('Update installed. Refresh the page if it does not reload automatically.', 'warning');
          }
        } else {
          this.showToast(data.message || 'Application updated successfully!', 'success');
          setTimeout(() => window.location.reload(), 900);
        }
      } else {
        this.showToast('Update notice: ' + (data.message || data.output || 'Update did not apply.'), 'warning');
      }
    } catch (e) {
      this.showToast('Update failed: ' + e.message, 'danger');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Update Now';
      }
    }
  }

  // ==========================================
  // Data Backup & Restore Hub
  // ==========================================
  escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
  }

  async fetchServerBackups() {
    const tbody = document.getElementById('serverBackupsTableBody');
    if (!tbody) return;

    try {
      const res = await fetch('/api/system/backups');
      const data = await res.json();
      if (!res.ok) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #fca5a5; padding: 1.25rem;">Failed to load backups: ${this.escapeHtml(data.error || 'Server error')}</td></tr>`;
        return;
      }

      const backups = data.backups || [];
      this._serverBackups = backups;

      if (backups.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 1.25rem;">No server backups found. Click "Save Backup on Server" above to create one.</td></tr>`;
        return;
      }

      tbody.innerHTML = backups.map(b => {
        let badgeColor = 'var(--accent-primary)';
        let badgeBg = 'rgba(14, 165, 233, 0.12)';
        let badgeBorder = 'rgba(14, 165, 233, 0.3)';
        if (b.kind && (b.kind.includes('Pre-Restore') || b.kind.includes('Safety'))) {
          badgeColor = '#fbbf24';
          badgeBg = 'rgba(251, 191, 36, 0.12)';
          badgeBorder = 'rgba(251, 191, 36, 0.3)';
        } else if (b.kind && b.kind.includes('Uploaded')) {
          badgeColor = 'var(--color-target)';
          badgeBg = 'rgba(16, 185, 129, 0.12)';
          badgeBorder = 'rgba(16, 185, 129, 0.3)';
        }

        const safeFilename = this.escapeHtml(b.filename);
        const safeSize = this.escapeHtml(b.size_formatted);
        const safeCreated = this.escapeHtml(b.created_at);
        const argFilename = encodeURIComponent(b.filename);

        return `
          <tr>
            <td style="font-family: monospace; font-size: 0.8rem; color: var(--text-primary);">${safeFilename}</td>
            <td><span class="pill" style="color: ${badgeColor}; background: ${badgeBg}; border-color: ${badgeBorder}; font-size: 0.7rem; padding: 0.15rem 0.5rem;">${this.escapeHtml(b.kind)}</span></td>
            <td style="color: var(--text-muted); font-size: 0.8rem;">${safeSize}</td>
            <td style="color: var(--text-muted); font-size: 0.8rem;">${safeCreated}</td>
            <td style="text-align: right; white-space: nowrap;">
              <button type="button" class="btn btn-secondary btn-sm" style="padding: 0.25rem 0.6rem; font-size: 0.78rem; margin-right: 0.35rem;" onclick="app.openRestoreServerModal('${argFilename}')" title="Restore this backup">
                Restore
              </button>
              <button type="button" class="btn btn-secondary btn-sm" style="padding: 0.25rem 0.6rem; font-size: 0.78rem; margin-right: 0.35rem;" onclick="app.downloadServerBackup('${argFilename}')" title="Download backup file">
                Download
              </button>
              <button type="button" class="btn btn-danger btn-sm" style="padding: 0.25rem 0.55rem; font-size: 0.78rem;" onclick="app.openDeleteBackupModal('${argFilename}')" title="Delete backup">
                Delete
              </button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      console.error('Failed to load server backups:', e);
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #fca5a5; padding: 1.25rem;">Error loading backups: ${this.escapeHtml(e.message)}</td></tr>`;
    }
  }

  async createServerBackup() {
    try {
      this.showToast('Creating server backup...', 'info');
      const res = await fetch('/api/system/backups/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prefix: 'glycoguide_backup' })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        this.showToast(data.error || 'Failed to create backup.', 'danger');
        return;
      }
      this.showToast(data.message || 'Server backup created successfully!', 'success');
      await this.fetchServerBackups();
    } catch (e) {
      this.showToast('Error creating backup: ' + e.message, 'danger');
    }
  }

  downloadLiveBackup() {
    this.showToast('Generating live database snapshot...', 'info');
    window.location.href = '/api/system/backups/download-live';
  }

  downloadServerBackup(encodedFilename) {
    const filename = decodeURIComponent(encodedFilename);
    window.location.href = '/api/system/backups/download/' + encodeURIComponent(filename);
  }

  openRestoreServerModal(encodedFilename) {
    const filename = decodeURIComponent(encodedFilename);
    const backup = (this._serverBackups || []).find(b => b.filename === filename);
    const fileNameEl = document.getElementById('restoreServerFileName');
    const metaRow = document.getElementById('restoreServerMetaRow');
    const errBanner = document.getElementById('restoreServerErrorBanner');
    const pwdInput = document.getElementById('restoreServerPasswordInput');

    if (fileNameEl) fileNameEl.textContent = filename;
    if (metaRow) {
      metaRow.textContent = backup 
        ? `Size: ${backup.size_formatted} · Created: ${backup.created_at} · Type: ${backup.kind}` 
        : '';
    }
    if (errBanner) {
      errBanner.textContent = '';
      errBanner.style.display = 'none';
    }
    if (pwdInput) {
      pwdInput.value = '';
    }
    this.openModal('restoreServerModal');
  }

  async executeRestoreServer() {
    const filename = document.getElementById('restoreServerFileName')?.textContent?.trim();
    const pwd = document.getElementById('restoreServerPasswordInput')?.value;
    const errBanner = document.getElementById('restoreServerErrorBanner');
    const btn = document.getElementById('btnConfirmRestoreServer');

    if (!filename || filename === '--') {
      if (errBanner) {
        errBanner.textContent = 'No backup file selected.';
        errBanner.style.display = 'block';
      }
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Restoring...';
    }

    try {
      const res = await fetch('/api/system/backups/restore-server', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, password: pwd })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Failed to restore database.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('restoreServerModal');
      this.showToast(data.message || 'Database successfully restored from server backup!', 'success');
      await this.loadProfile();
      await this.refreshData();
      await this.fetchServerBackups();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Server communication error: ' + e.message;
        errBanner.style.display = 'block';
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Confirm & Restore';
      }
    }
  }

  onBackupFileSelected(input) {
    const btn = document.getElementById('btnUploadRestore');
    if (!btn) return;
    if (input.files && input.files.length > 0) {
      btn.disabled = false;
      btn.classList.remove('btn-secondary');
      btn.classList.add('btn-primary');
    } else {
      btn.disabled = true;
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-secondary');
    }
  }

  openRestoreUploadModal() {
    const fileInput = document.getElementById('backupFileInput');
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      this.showToast('Please select a .db backup file first.', 'warning');
      return;
    }
    const file = fileInput.files[0];
    const fileNameEl = document.getElementById('restoreUploadFileName');
    const metaRow = document.getElementById('restoreUploadMetaRow');
    const errBanner = document.getElementById('restoreUploadErrorBanner');
    const pwdInput = document.getElementById('restoreUploadPasswordInput');

    if (fileNameEl) fileNameEl.textContent = file.name;
    if (metaRow) metaRow.textContent = `Size: ${this.formatBytes(file.size)} · Type: ${file.type || 'SQLite Database'}`;
    if (errBanner) {
      errBanner.textContent = '';
      errBanner.style.display = 'none';
    }
    if (pwdInput) {
      pwdInput.value = '';
    }
    this.openModal('restoreUploadModal');
  }

  async executeRestoreUpload() {
    const fileInput = document.getElementById('backupFileInput');
    const pwd = document.getElementById('restoreUploadPasswordInput')?.value;
    const errBanner = document.getElementById('restoreUploadErrorBanner');
    const btn = document.getElementById('btnConfirmRestoreUpload');

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
      if (errBanner) {
        errBanner.textContent = 'No file selected. Please choose a backup file.';
        errBanner.style.display = 'block';
      }
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('backup_file', file);
    formData.append('password', pwd || '');

    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Uploading & Restoring...';
    }

    try {
      const res = await fetch('/api/system/backups/restore-upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Failed to restore uploaded database.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('restoreUploadModal');
      fileInput.value = '';
      this.onBackupFileSelected(fileInput);
      this.showToast(data.message || 'Database restored from uploaded file!', 'success');
      await this.loadProfile();
      await this.refreshData();
      await this.fetchServerBackups();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Upload error: ' + e.message;
        errBanner.style.display = 'block';
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Confirm & Restore';
      }
    }
  }

  openDeleteBackupModal(encodedFilename) {
    const filename = decodeURIComponent(encodedFilename);
    const fileNameEl = document.getElementById('deleteBackupFileName');
    const errBanner = document.getElementById('deleteBackupErrorBanner');
    const pwdInput = document.getElementById('deleteBackupPasswordInput');

    if (fileNameEl) fileNameEl.textContent = filename;
    if (errBanner) {
      errBanner.textContent = '';
      errBanner.style.display = 'none';
    }
    if (pwdInput) {
      pwdInput.value = '';
    }
    this.openModal('deleteBackupModal');
  }

  async executeDeleteBackup() {
    const filename = document.getElementById('deleteBackupFileName')?.textContent?.trim();
    const pwd = document.getElementById('deleteBackupPasswordInput')?.value;
    const errBanner = document.getElementById('deleteBackupErrorBanner');
    const btn = document.getElementById('btnConfirmDeleteBackup');

    if (!filename || filename === '--') {
      if (errBanner) {
        errBanner.textContent = 'No backup selected.';
        errBanner.style.display = 'block';
      }
      return;
    }

    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Deleting...';
    }

    try {
      const res = await fetch('/api/system/backups/' + encodeURIComponent(filename), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pwd || '' })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        if (errBanner) {
          errBanner.textContent = data.error || 'Failed to delete backup.';
          errBanner.style.display = 'block';
        }
        return;
      }

      this.closeModal('deleteBackupModal');
      this.showToast(data.message || 'Backup deleted successfully.', 'success');
      await this.fetchServerBackups();
    } catch (e) {
      if (errBanner) {
        errBanner.textContent = 'Error: ' + e.message;
        errBanner.style.display = 'block';
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Delete Backup';
      }
    }
  }

  // ==========================================
  // UI Helpers, Modals & Tabs
  // ==========================================
  openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('open');

    if (modalId === 'logInsulinModal') {
      const kindSelect = document.getElementById('quickDoseKind');
      if (kindSelect) {
        kindSelect.value = 'meal';
        this.onDoseKindChange('meal');
      }
      const bgInput = document.getElementById('correctionBgInput');
      if (bgInput) bgInput.value = '';
      const unitsInput = document.getElementById('quickUnitsVal');
      if (unitsInput) unitsInput.value = '';
      const overdoseWarn = document.getElementById('correctionOverdoseWarning');
      if (overdoseWarn) overdoseWarn.style.display = 'none';
    }
  }

  closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('open');
  }

  switchTab(tabId) {
    this.currentTab = tabId;
    document.querySelectorAll('.tab-view').forEach(v => v.style.display = 'none');
    document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));

    const activeView = document.getElementById(`tabView-${tabId}`);
    if (activeView) activeView.style.display = 'block';

    const activeBtn = document.getElementById(`navTab-${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');

    window.location.hash = tabId;

    if (tabId === 'history') {
      this.fetchAnalytics(this.currentHistoryDays);
    }
    if (this.chart) {
      setTimeout(() => this.chart.render(), 50);
    }
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ==========================================
  // Event Bindings
  // ==========================================
  bindEvents() {
    // Nav tabs
    document.querySelectorAll('.nav-tab').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.dataset.tab;
        this.switchTab(tab);
      });
    });

    // Close modals on clicking overlay background (except security modals)
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay && overlay.id !== 'unlockModal' && overlay.id !== 'wipeDataModal') {
          overlay.classList.remove('open');
        }
      });
    });

    // Unit toggle pill in header
    const unitTogglePill = document.getElementById('unitTogglePill');
    if (unitTogglePill) {
      unitTogglePill.addEventListener('click', async () => {
        const newUnit = this.profile.glucose_unit === 'mg/dL' ? 'mmol/L' : 'mg/dL';
        await fetch('/api/profile', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ glucose_unit: newUnit })
        });
        await this.loadProfile();
        await this.refreshData();
        this.showToast(`Switched units to ${newUnit}`, 'success');
      });
    }

    // Bolus calculator dynamic inputs
    ['calcBgInput', 'calcCarbsInput', 'calcFatInput', 'calcSugarInput'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', () => this.recalculateBolus());
    });
    ['tagExercise', 'tagSick', 'tagStress'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', () => this.recalculateBolus());
    });

    // Hash router
    const hash = window.location.hash.replace('#', '');
    if (['dashboard', 'history', 'meal', 'settings'].includes(hash)) {
      this.switchTab(hash);
    }
  }
}

// Global App Instance
window.app = new GlycoApp();
