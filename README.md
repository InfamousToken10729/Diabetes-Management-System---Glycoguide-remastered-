# GlycoGuide Remastered — Type 1 Diabetes Assistant

A remastered, high-performance, ultra-lightweight Type 1 Diabetes assistant engineered specifically for **Raspberry Pi self-hosting** and **Windows desktop / local hosting**.

* **GitHub Repository**: [`InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-`](https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-)

---

## 🌟 Why Remastered?

| Feature | Legacy (Next.js / Node / PGlite) | **GlycoGuide Remastered** |
| :--- | :--- | :--- |
| **Language & Engine** | Node.js + Next.js + React | **Python 3 + SQLite + Modern CSS/JS** |
| **Storage & Database** | Heavy PostgreSQL / PGlite WASM | **Local SQLite with WAL Mode (Zero-Config)** |
| **Repository Size** | > 800 MB (heavy `node_modules` & cache) | **< 1 MB (Ultra-compact, pure source)** |
| **Memory / RAM Usage** | 450 MB – 650 MB RAM | **~25 MB RAM (Runs on any Raspberry Pi)** |
| **Server Boot Time** | ~10 – 15 seconds | **< 0.1 seconds (Instantaneous startup)** |
| **Reliability** | Prone to WASM / hydration crashes | **Rock solid, zero external service dependencies** |
| **Windows Testing** | Requires Node builds | **Double-click `run.bat` or `GlycoGuide.exe`** |

---

## 🍓 Quick Start: Raspberry Pi / Linux

### Option 1: 1-Line Automatic Install (Fresh Raspberry Pi)
Run this single command on your Raspberry Pi or Debian/Ubuntu machine:
```bash
curl -fsSL https://raw.githubusercontent.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-/main/install.sh | bash
```

### Option 2: Git Clone Install
```bash
git clone https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git
cd Diabetes-Management-System---Glycoguide-remastered-
./install.sh
```

The installer automatically:
* Installs `python3`, `python3-venv`, `git`, and `sqlite3` if missing.
* Creates an isolated `.venv` virtual environment and installs `flask` and `requests`.
* Initializes `data/` and `backups/` locally (preserving any existing data).
* Installs and starts **`glycoguide.service`** (`systemd`) so GlycoGuide auto-starts on boot at `http://<YOUR_PI_IP>:8081`.

### Useful Raspberry Pi / Linux Commands
* Check service status: `sudo systemctl status glycoguide`
* View live server logs: `sudo journalctl -u glycoguide -f`
* Restart server: `sudo systemctl restart glycoguide`
* Update cleanly (with auto DB backup): `./update.sh`
* Create manual DB backup: `./backup.sh`

---

## ⚡ Quick Start: Windows

1. Clone or download this repository:
   ```cmd
   git clone https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git
   cd Diabetes-Management-System---Glycoguide-remastered-
   ```
2. Double-click **`run.bat`**.
   * First run automatically creates `.venv`, installs dependencies, initializes your local SQLite database, and opens `http://localhost:8081`.
   * Subsequent runs boot instantaneously!
3. Double-click **`update.bat`** anytime to create an automatic database backup and pull the latest updates from GitHub (or use the in-app **Update Now** notification!).

### Building Standalone Windows `.exe`
Double-click **`build-exe.bat`** to compile a self-contained **`GlycoGuide.exe`** that runs on any Windows PC without Python installed.

---

## 🌐 Remote Access via DuckDNS & Port Forwarding

To access GlycoGuide from your smartphone anywhere in the world:

1. **Set up DuckDNS**:
   * Create an account at [duckdns.org](https://www.duckdns.org) and register a domain (e.g. `my-glycoguide.duckdns.org`).
   * Follow the DuckDNS Pi setup instructions for automatic IP updates.
2. **Router Port Forwarding**:
   * Log into your router admin panel and add a Port Forwarding rule:
     * **External Port**: `8081`
     * **Internal IP**: Your Raspberry Pi's local IP (e.g. `192.168.1.150`)
     * **Internal Port**: `8081`
     * **Protocol**: `TCP`
3. **Access Anywhere**:
   * Open `http://my-glycoguide.duckdns.org:8081` from any browser!
   * Note: Only devices authenticated with your master password can access clinical data, and sessions auto-lock after 15 minutes of inactivity.

---

## 🩺 Clinical Features & Capabilities

* **Dual Units**: Seamless switching between `mg/dL` and `mmol/L` everywhere.
* **Insulin on Board (IOB)**: Mudaliar pharmacokinetic decay curves for Rapid-Acting (`NovoRapid`, `Humalog`, `Apidra`, `Admelog`) and Ultra-Fast (`Fiasp`, `Lyumjev`) insulins.
* **Smart Bolus Calculator & Correction Assistant**:
  * Meal bolus ($Carbs / ICR$) + Correction bolus ($(BG - Target) / ISF$).
  * Automatic active IOB subtraction + overdose hypoglycemic carbohydrate warnings.
  * Context adjustments: Exercise (`-20%`), Sickness (`+20%`), Stress (`+10%`).
  * High-fat meal split bolus recommendation (`60%` upfront / `40%` extended).
* **AI Meal Macro Scanner**: Upload or snap a plate photo with provider presets (Google Gemini, OpenAI, Groq, OpenRouter, Ollama, or Custom) and 1-click "Send to Bolus".
* **Rule of 15 Hypo Rescue**: Auto-triggered full-screen rescue protocol with persistent 15-minute countdown timer, audio alerts, fast-carb guide, and recovery BG verification.
* **Time In Range (TIR) & Estimated HbA1c (ADAG)**: Interpolated TIR stats, ADAG eA1c in `%` & `mmol/mol`, glycemic variability ($CV\%$), and ratio adjustment insights.
* **Full-Page Security & Audit Logs**: Master password gatekeeping, auto-lock after 15 minutes of inactivity, activity audit trail, and safe auto-update checks every hour.
* **Data Backup & Restore Hub**:
  * **Host Server Backups**: Save timestamped SQLite database backups directly on the server machine (e.g. Raspberry Pi or local PC) with 1 click.
  * **Client Device Download**: Download an instant hot `.db` snapshot straight to your phone, tablet, or PC browser downloads.
  * **Restore from Server or Device**: Restore from existing server backups or upload a `.db` backup from your phone/PC with automatic pre-restore safety snapshots and master password verification.
* **5 Modern Color Themes & Printable Doctor Reports**: Obsidian Slate, Obsidian Emerald, Midnight Sunset, Cyber Synth, and Polar Light, plus 1-click CSV & Doctor Report exports.
