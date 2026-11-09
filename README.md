# GlycoGuide Remastered — Type 1 Diabetes Assistant

A remastered, high-performance, ultra-lightweight Type 1 Diabetes assistant engineered specifically for **Raspberry Pi self-hosting** and **local Windows testing**.

---

## 🌟 Why Remastered?

| Feature | Legacy v3 (Next.js / Node / PGlite) | **GlycoGuide Remastered** |
| :--- | :--- | :--- |
| **Language & Engine** | Node.js + Next.js + React | **Python 3 + SQLite + Modern CSS/JS** |
| **Storage & Database** | Heavy PostgreSQL / PGlite WASM | **Local SQLite with WAL Mode (Zero-Config)** |
| **Total Project Size** | > 800 MB (large `node_modules` & cache) | **< 1 MB (Ultra-compact, pure source)** |
| **Memory / RAM Usage** | 450 MB – 650 MB RAM | **~25 MB RAM (Runs on any Raspberry Pi)** |
| **Server Boot Time** | ~10 – 15 seconds | **< 0.1 seconds (Instantaneous startup)** |
| **Reliability** | Prone to WASM / hydration crashes | **Rock solid, zero external service dependencies** |
| **Windows Testing** | Requires complex builds | **Double-click `run.bat` or `GlycoGuide.exe`** |

---

## ⚡ Quick Start: Windows

1. Double-click **`run.bat`** in the `remastered/` folder.
2. The server starts at `http://localhost:8081` and automatically opens your web browser.

### Building Standalone Windows `.exe`:
Double-click **`build-exe.bat`** to produce a self-contained **`GlycoGuide.exe`** that runs on any Windows computer with no Python required!

---

## 🍓 Quick Start: Raspberry Pi (1-Command Install)

Clone the repository to your Raspberry Pi, enter `remastered`, and run:
```bash
chmod +x install.sh
./install.sh
```

The script automatically:
* Installs dependencies (`python3`, `pip`, `flask`, `requests`).
* Sets up a **systemd service** (`glycoguide.service`) that automatically starts on system boot.
* Launches on port **8081** (accessible at `http://<YOUR_PI_IP>:8081`).

### Useful Commands on Raspberry Pi:
* Check service status: `sudo systemctl status glycoguide`
* View live server logs: `sudo journalctl -u glycoguide -f`
* Restart server: `sudo systemctl restart glycoguide`
* Update to latest version: `./update.sh`
* Backup local database: `./backup.sh`

---

## 🌐 Remote Access via DuckDNS & Port Forwarding

To access GlycoGuide from your smartphone anywhere in the world:

1. **Set up DuckDNS**:
   * Create an account at [duckdns.org](https://www.duckdns.org) and register a domain (e.g. `my-glycoguide.duckdns.org`).
   * Follow DuckDNS Pi instructions to set up the 5-minute cron updater script.

2. **Router Port Forwarding**:
   * Log into your home router's admin panel.
   * Add a Port Forwarding rule:
     * **External Port**: `8081`
     * **Internal IP**: Your Raspberry Pi's local IP (e.g. `192.168.1.150`)
     * **Internal Port**: `8081`
     * **Protocol**: `TCP`

3. **Access Anywhere**:
   * Open `http://my-glycoguide.duckdns.org:8081` from any browser worldwide!
   * All clinical data is securely stored on your Raspberry Pi's local SQLite database.

---

## 🩺 Clinical Features & Capabilities

* **Dual Units**: Seamless switching between `mg/dL` and `mmol/L` everywhere.
* **Insulin on Board (IOB)**: Real Mudaliar pharmacokinetic exponential decay curve for Rapid-Acting (NovoRapid, Humalog, Apidra) and Ultra-Fast (Fiasp, Lyumjev) insulins.
* **Smart Bolus Calculator**:
  * Meal bolus ($Carbs / ICR$) + Correction bolus ($(BG - Target) / ISF$).
  * Automatic active IOB subtraction to prevent insulin stacking and hypoglycemia.
  * Context adjustments: Exercise (-20%), Sickness (+20%), Stress (+10%).
  * High-fat meal split bolus (60% upfront, 40% after 2 hours).
* **AI Meal Macro Scanner**: Snap a photo or type a description to get instant carbohydrate, protein, fat, and sugar breakdowns via Google Gemini API with a 1-click "Send to Bolus" button.
* **The Rule of 15 Hypo Rescue**: Full-screen emergency modal with a 15-minute countdown timer, synthesized audio alert beeps, fast-carb recommendations, and glucagon safety warnings.
* **Time In Range (TIR) & eA1c**:
  * 5-minute linear interpolated continuous glucose statistics.
  * ADAG Estimated HbA1c formula ($eA1c = (mean\_bg + 46.7) / 28.7$) with IFCC mmol/mol conversion.
  * Glycemic Variability ($CV\%$).
* **Automatic ICR & ISF Ratio Suggestions**: Detects post-prandial spikes and correction-drop underperformance over your history and suggests safer ratios.
* **Security & Inactivity Lock**: Master account password for new devices and automatic 15-minute inactivity lock.
* **5 Modern Color Themes**: Obsidian Slate, Emerald Mint, Sunset Amber, Cyber Synthwave, and Polar Light.
* **Doctor Clinical Report**: Printable, professionally formatted summary for endocrinologists with 1-click PDF printing.
