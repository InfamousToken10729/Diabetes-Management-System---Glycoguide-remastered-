/* ====================================================================
   GlycoGuide Remastered — Canvas Glucose Chart Engine
   ==================================================================== */

class GlucoseChart {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.dataPoints = [];
    this.unit = 'mg/dL';
    this.hoverPoint = null;

    // Attach resize listener
    window.addEventListener('resize', () => this.render());

    // Attach hover listener
    this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
    this.canvas.addEventListener('mouseleave', () => {
      this.hoverPoint = null;
      this.render();
    });
  }

  setData(entries, unit = 'mg/dL') {
    this.unit = unit;
    this.dataPoints = entries
      .filter(e => e.bg_value !== null && e.occurred_at)
      .map(e => ({
        ts: new Date(e.occurred_at).getTime(),
        bg: parseFloat(e.bg_value),
        displayBg: e.display_bg || e.bg_value,
        dose: e.insulin_units,
        carbs: e.carbs
      }))
      .sort((a, b) => a.ts - b.ts);

    this.render();
  }

  onMouseMove(e) {
    if (!this.dataPoints || this.dataPoints.length === 0) return;
    const rect = this.canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Find closest point by x-coordinate
    let closest = null;
    let minDiff = 30; // 30px proximity threshold

    for (const pt of this.computedPoints || []) {
      const diff = Math.hypot(pt.x - mouseX, pt.y - mouseY);
      if (diff < minDiff) {
        minDiff = diff;
        closest = pt;
      }
    }

    if (closest !== this.hoverPoint) {
      this.hoverPoint = closest;
      this.render();
    }
  }

  render() {
    if (!this.canvas) return;
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    ctx.resetTransform();
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    // Clear
    ctx.clearRect(0, 0, w, h);

    if (!this.dataPoints || this.dataPoints.length === 0) {
      ctx.fillStyle = '#64748b';
      ctx.font = '14px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No glucose readings in selected timeframe', w / 2, h / 2);
      return;
    }

    const padLeft = 45;
    const padRight = 20;
    const padTop = 25;
    const padBottom = 35;
    const plotW = w - padLeft - padRight;
    const plotH = h - padTop - padBottom;

    // Clinical Y Range (40 to 350 mg/dL or scaled for data)
    let minBg = 40;
    let maxBg = 320;
    for (const p of this.dataPoints) {
      if (p.bg > maxBg - 20) maxBg = Math.min(450, p.bg + 30);
    }

    // Time X Range
    const minTs = this.dataPoints[0].ts;
    const maxTs = Math.max(this.dataPoints[this.dataPoints.length - 1].ts, minTs + 3600000);

    const getY = (bg) => padTop + plotH - ((bg - minBg) / (maxBg - minBg)) * plotH;
    const getX = (ts) => padLeft + ((ts - minTs) / (maxTs - minTs)) * plotW;

    // 1. Target Band Shading (70 to 180 mg/dL)
    const yTargetLow = getY(70);
    const yTargetHigh = getY(180);
    const bandHeight = yTargetLow - yTargetHigh;

    ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
    ctx.fillRect(padLeft, yTargetHigh, plotW, bandHeight);

    // Target Range boundary lines
    ctx.strokeStyle = 'rgba(16, 185, 129, 0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    ctx.beginPath();
    ctx.moveTo(padLeft, yTargetHigh);
    ctx.lineTo(padLeft + plotW, yTargetHigh);
    ctx.moveTo(padLeft, yTargetLow);
    ctx.lineTo(padLeft + plotW, yTargetLow);
    ctx.stroke();

    // Red Hypo Boundary (70 mg/dL)
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.35)';
    ctx.beginPath();
    ctx.moveTo(padLeft, yTargetLow);
    ctx.lineTo(padLeft + plotW, yTargetLow);
    ctx.stroke();
    ctx.setLineDash([]); // reset dash

    // 2. Y-Axis labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    const yLevels = [70, 110, 180, 250];
    for (const lvl of yLevels) {
      if (lvl >= minBg && lvl <= maxBg) {
        const y = getY(lvl);
        const label = this.unit === 'mmol/L' ? (lvl / 18.0182).toFixed(1) : lvl;
        ctx.fillText(label, padLeft - 8, y);
      }
    }

    // 3. Compute Coordinates
    this.computedPoints = this.dataPoints.map(p => ({
      x: getX(p.ts),
      y: getY(p.bg),
      ...p
    }));

    // 4. Draw Connecting Trend Line
    if (this.computedPoints.length > 1) {
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(14, 165, 233, 0.7)';
      ctx.lineWidth = 2.2;
      ctx.lineJoin = 'round';

      ctx.moveTo(this.computedPoints[0].x, this.computedPoints[0].y);
      for (let i = 1; i < this.computedPoints.length; i++) {
        ctx.lineTo(this.computedPoints[i].x, this.computedPoints[i].y);
      }
      ctx.stroke();
    }

    // 5. Draw Points with Color Coding
    for (const pt of this.computedPoints) {
      let color = '#10b981'; // target
      if (pt.bg < 70) color = '#ef4444'; // hypo
      else if (pt.bg > 250) color = '#ec4899'; // severe
      else if (pt.bg > 180) color = '#f59e0b'; // high

      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = '#080c14';
      ctx.stroke();
    }

    // 6. Draw Hover Tooltip
    if (this.hoverPoint) {
      const pt = this.hoverPoint;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 7, 0, Math.PI * 2);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      const dateStr = new Date(pt.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const tipText = `${pt.displayBg} ${this.unit} (${dateStr})`;
      ctx.font = 'bold 12px -apple-system, sans-serif';
      const textW = ctx.measureText(tipText).width;
      const boxW = textW + 20;
      const boxH = 26;
      let boxX = pt.x - boxW / 2;
      let boxY = pt.y - boxH - 12;

      if (boxX < padLeft) boxX = padLeft;
      if (boxX + boxW > w - padRight) boxX = w - padRight - boxW;
      if (boxY < 5) boxY = pt.y + 12;

      ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(boxX, boxY, boxW, boxH, 6);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(tipText, boxX + boxW / 2, boxY + boxH / 2);
    }
  }
}

window.GlucoseChart = GlucoseChart;
