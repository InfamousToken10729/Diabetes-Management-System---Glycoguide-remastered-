import os
import io
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from flask import (
    Flask, render_template, request, jsonify, make_response, send_from_directory, redirect, url_for
)
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import database
import t1d_engine
import auth_service
import ai_service
import update_service
import backup_service

static_dir = str(config.BUNDLE_DIR / "static")
template_dir = str(config.BUNDLE_DIR / "templates")

app = Flask(__name__, static_folder=static_dir, template_folder=template_dir)
app.config["SECRET_KEY"] = config.SECRET_KEY
# Ensure proxy headers (DuckDNS / Caddy / Nginx / Reverse Proxy) work accurately
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Initialize SQLite database on startup
database.init_db()

# --- Security Helper ---
def check_auth(req) -> tuple:
    cookie_token = req.cookies.get(config.SESSION_COOKIE_NAME)
    is_valid, reason = auth_service.validate_session(cookie_token)
    return is_valid, reason

# --- Frontend Routes ---
@app.route("/")
@app.route("/dashboard")
@app.route("/history")
@app.route("/meal")
@app.route("/settings")
def index():
    # If no master account has been configured yet, redirect to setup
    if not auth_service.is_password_configured():
        return redirect("/login?mode=setup")
        
    # If password is configured, enforce server-side authentication
    is_valid, _ = check_auth(request)
    if not is_valid:
        return redirect("/login")
        
    return render_template("index.html")

@app.route("/login")
def login_page():
    # If already authenticated and account configured, go directly to dashboard
    is_valid, _ = check_auth(request)
    if auth_service.is_password_configured() and is_valid:
        return redirect("/")
        
    mode = request.args.get("mode", "")
    if not auth_service.is_password_configured():
        mode = "setup"
    reason = request.args.get("reason", "")
    main_user = database.get_main_user() or {}
    prof = database.get_profile() or {}
    
    return render_template(
        "login.html",
        mode=mode,
        reason=reason,
        display_name=main_user.get("display_name") or prof.get("username") or "Main Account",
        password_configured=auth_service.is_password_configured()
    )

@app.route("/setup")
def setup_page():
    return redirect("/login?mode=setup")

@app.route("/report")
def clinical_report():
    if auth_service.is_password_configured():
        is_valid, _ = check_auth(request)
        if not is_valid:
            return redirect("/login")
            
    days = int(request.args.get("days", 14))
    prof = database.get_profile() or {}
    entries = database.get_log_entries(days=days, limit=1000)
    analytics = t1d_engine.calculate_time_in_range(entries)
    
    # Unit formatting
    unit = prof.get("glucose_unit", "mg/dL")
    formatted_entries = []
    for e in entries:
        ed = dict(e)
        bg = ed.get("bg_value")
        ed["formatted_bg"] = t1d_engine.format_bg(bg, unit) if bg is not None else None
        formatted_entries.append(ed)
        
    return render_template(
        "report.html",
        profile=prof,
        analytics=analytics,
        entries=formatted_entries,
        days=days,
        unit=unit,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )

# --- Authentication APIs ---
@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    is_set = auth_service.is_password_configured()
    cookie_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    is_valid, reason = auth_service.validate_session(cookie_token)
    main_user = database.get_main_user() or {}
    has_rec = bool(main_user.get("recovery_key_hash"))
    display_name = main_user.get("display_name") or "Main Account"
    return jsonify({
        "password_configured": is_set,
        "is_authenticated": is_valid,
        "has_recovery_key": has_rec,
        "display_name": display_name,
        "inactivity_reason": reason,
        "timeout_seconds": config.INACTIVITY_TIMEOUT_SECONDS
    })

@app.route("/api/auth/unlock", methods=["POST"])
def auth_unlock():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    
    if not auth_service.is_password_configured():
        # First time unlock / setup
        sess = auth_service.create_device_session()
        database.add_audit_log("USER_LOGIN", "Initial setup access without password.")
        resp = make_response(jsonify({"success": True, "message": "Unlocked without password."}))
        resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
        return resp

    if auth_service.authenticate_master_password(password):
        sess = auth_service.create_device_session()
        database.add_audit_log("USER_LOGIN", "Master password validated. Session unlocked.")
        resp = make_response(jsonify({"success": True, "message": "Authenticated successfully."}))
        resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
        return resp
    else:
        database.add_audit_log("LOGIN_FAILED", "Failed unlock attempt with incorrect password.")
        return jsonify({"success": False, "error": "Incorrect master password."}), 401

@app.route("/api/auth/set-password", methods=["POST"])
def auth_set_password():
    data = request.get_json(silent=True) or {}
    cur_pwd = data.get("current_password", "")
    new_pwd = data.get("new_password", "")
    rec_key = data.get("recovery_key")
    
    # If a password is already configured, verify current password OR require active session
    if auth_service.is_password_configured():
        is_valid_session, _ = check_auth(request)
        is_pwd_correct = auth_service.authenticate_master_password(cur_pwd)
        
        if not is_valid_session and not is_pwd_correct:
            database.add_audit_log("SECURITY_ALERT", "Failed attempt to change master password: Incorrect current password.")
            return jsonify({"error": "Current password is incorrect or session is locked."}), 401
            
    try:
        auth_service.set_master_credentials(new_pwd, rec_key)
        sess = auth_service.create_device_session()
        database.add_audit_log("PASSWORD_CHANGED", "Master security password successfully updated.")
        resp = make_response(jsonify({"success": True, "message": "Master password updated successfully."}))
        resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/reset-password", methods=["POST"])
def auth_reset_password():
    data = request.get_json(silent=True) or {}
    key = data.get("recovery_key", "")
    new_pwd = data.get("new_password", "")
    
    if not key or not key.strip():
        return jsonify({"error": "Emergency recovery key is required."}), 400
    if not new_pwd or len(new_pwd) < 6:
        return jsonify({"error": "New password must be at least 6 characters."}), 400
        
    if not auth_service.reset_password_with_recovery_key(key, new_pwd):
        database.add_audit_log("SECURITY_ALERT", "Failed password reset attempt with invalid recovery key.")
        return jsonify({"error": "Invalid or unrecognized emergency recovery key."}), 401
        
    sess = auth_service.create_device_session()
    database.add_audit_log("PASSWORD_RESET", "Master password successfully reset using emergency recovery key.")
    resp = make_response(jsonify({"success": True, "message": "Password successfully reset! You are now logged in."}))
    resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
    return resp

@app.route("/api/auth/emergency-reset", methods=["POST"])
def auth_emergency_reset():
    data = request.get_json(silent=True) or {}
    confirmation = data.get("confirmation", "").strip().upper()
    new_pwd = data.get("new_password", "")
    recovery_key = data.get("recovery_key")
    
    if confirmation != "RESET":
        return jsonify({"error": "Type RESET in uppercase to confirm emergency override."}), 400
    if not new_pwd or len(new_pwd) < 6:
        return jsonify({"error": "New password must be at least 6 characters."}), 400
        
    auth_service.emergency_reset_credentials(new_pwd, recovery_key)
    sess = auth_service.create_device_session()
    database.add_audit_log("SECURITY_ALERT", "Emergency local master credential override performed.")
    resp = make_response(jsonify({"success": True, "message": "Emergency reset complete. New credentials activated."}))
    resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
    return resp

@app.route("/api/auth/register-new", methods=["POST"])
def auth_register_new():
    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name", "Main Account")
    pwd = data.get("password", "")
    rec_key = data.get("recovery_key")
    unit = data.get("glucose_unit", "mg/dL")
    wipe = bool(data.get("wipe_data", True))
    
    if not pwd or len(pwd) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
        
    try:
        sess = auth_service.create_or_reset_account(
            display_name=display_name,
            password=pwd,
            recovery_key=rec_key,
            glucose_unit=unit,
            wipe_data=wipe
        )
        database.add_audit_log(
            "ACCOUNT_CREATED",
            f"Created new master account for '{display_name}' (unit={unit}, wiped_old={wipe})."
        )
        resp = make_response(jsonify({
            "success": True,
            "message": f"Welcome, {display_name}! Your new account was successfully created."
        }))
        resp.set_cookie(config.SESSION_COOKIE_NAME, sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    cookie_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    if cookie_token:
        database.delete_session(cookie_token)
    database.add_audit_log("USER_LOGOUT", "User signed out / locked device session.")
    resp = make_response(jsonify({"success": True}))
    resp.delete_cookie(config.SESSION_COOKIE_NAME)
    return resp

# --- Profile APIs ---
@app.route("/api/profile", methods=["GET"])
def get_profile_api():
    prof = database.get_profile() or {}
    return jsonify(prof)

@app.route("/api/profile", methods=["PUT"])
def update_profile_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
    data = request.get_json(silent=True) or {}
    prof = database.update_profile("family-shared-device", data)
    database.add_audit_log("SETTINGS_UPDATED", "Clinical settings and user profile updated.")
    return jsonify(prof)

# --- Active IOB & Bolus Calculator APIs ---
@app.route("/api/iob", methods=["GET"])
def get_iob_api():
    prof = database.get_profile() or {}
    dia = float(prof.get("insulin_duration_hours") or 4.0)
    itype = prof.get("insulin_type") or "NovoRapid"
    
    # Look back over DIA hours
    recent_doses = database.get_log_entries(days=1, limit=50)
    total_iob, breakdown = t1d_engine.calculate_active_iob(recent_doses, dia, itype)
    
    return jsonify({
        "active_iob": total_iob,
        "dia_hours": dia,
        "insulin_type": itype,
        "doses": breakdown
    })

@app.route("/api/calculate-bolus", methods=["POST"])
def calculate_bolus_api():
    data = request.get_json(silent=True) or {}
    prof = database.get_profile() or {}
    unit = prof.get("glucose_unit", "mg/dL")
    
    raw_bg = data.get("bg")
    bg_mgdl = None
    if raw_bg is not None and str(raw_bg).strip() != "":
        bg_mgdl = t1d_engine.parse_bg_input(float(raw_bg), unit)

    target_bg_mgdl = float(prof.get("target_bg") or 110.0)
    icr = float(prof.get("icr")) if prof.get("icr") else None
    isf = float(prof.get("isf")) if prof.get("isf") else None
    
    carbs = float(data.get("carbs") or 0.0)
    sugar = float(data.get("sugar") or 0.0)
    fat = float(data.get("fat") or 0.0)
    tags = data.get("tags") or []
    
    # Current active IOB
    dia = float(prof.get("insulin_duration_hours") or 4.0)
    itype = prof.get("insulin_type") or "NovoRapid"
    recent_doses = database.get_log_entries(days=1, limit=50)
    active_iob, _ = t1d_engine.calculate_active_iob(recent_doses, dia, itype)
    
    result = t1d_engine.calculate_bolus(
        bg_mgdl=bg_mgdl,
        target_bg_mgdl=target_bg_mgdl,
        icr=icr,
        isf=isf,
        carbs=carbs,
        sugar=sugar,
        fat=fat,
        current_iob=active_iob,
        tags=tags
    )
    result["target_bg"] = round(target_bg_mgdl, 1)
    result["isf"] = isf
    result["icr"] = icr
    result["active_iob"] = round(active_iob, 2)
    result["recommended_dose"] = result.get("total_units", 0.0)
    
    return jsonify(result)

# --- Log Entries APIs ---
@app.route("/api/logs", methods=["GET"])
def get_logs_api():
    days = request.args.get("days", type=int)
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")
    limit = request.args.get("limit", 200, type=int)
    
    entries = database.get_log_entries(days=days, start_date=start_date, end_date=end_date, limit=limit)
    prof = database.get_profile() or {}
    unit = prof.get("glucose_unit", "mg/dL")
    
    # Augment with display formatted values
    for e in entries:
        bg = e.get("bg_value")
        e["display_bg"] = t1d_engine.format_bg(bg, unit) if bg is not None else None
        
    return jsonify(entries)

@app.route("/api/logs", methods=["POST"])
def add_log_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
        
    data = request.get_json(silent=True) or {}
    prof = database.get_profile() or {}
    unit = prof.get("glucose_unit", "mg/dL")

    raw_bg = data.get("bg_value")
    bg_mgdl = None
    if raw_bg is not None and str(raw_bg).strip() != "":
        bg_mgdl = int(round(t1d_engine.parse_bg_input(float(raw_bg), unit)))

    entry_data = {
        "occurred_at": data.get("occurred_at"),
        "bg_value": bg_mgdl,
        "ketone_level": data.get("ketone_level"),
        "insulin_units": float(data["insulin_units"]) if data.get("insulin_units") else None,
        "meal_relation": data.get("meal_relation"),
        "meal_offset_value": data.get("meal_offset_value"),
        "meal_offset_unit": data.get("meal_offset_unit"),
        "tags": data.get("tags") or [],
        "carbs": float(data["carbs"]) if data.get("carbs") else None,
        "protein": float(data["protein"]) if data.get("protein") else None,
        "fat": float(data["fat"]) if data.get("fat") else None,
        "sugar": float(data["sugar"]) if data.get("sugar") else None,
        "meal_description": data.get("meal_description"),
        "dose_kind": data.get("dose_kind") or ("meal" if data.get("carbs") else "correction"),
        "notes": data.get("notes"),
        "spoiled_insulin": data.get("spoiled_insulin", False)
    }

    row_id = database.add_log_entry(entry_data)
    database.add_audit_log(
        "LOG_CREATED",
        f"Recorded new entry #{row_id}: BG={bg_mgdl or '--'} mg/dL, Insulin={entry_data['insulin_units'] or '--'} U, Carbs={entry_data['carbs'] or '--'} g"
    )

    # Smart Reminder: if meal carbs or meal insulin logged, create a 2h post-meal reminder
    if (entry_data.get("carbs") and entry_data["carbs"] > 0) or entry_data.get("dose_kind") == "meal":
        now_dt = datetime.now(timezone.utc)
        due_dt = now_dt + timedelta(hours=2)
        desc = entry_data.get("meal_description") or "meal"
        database.add_reminder(
            device_id="family-shared-device",
            due_at=due_dt.isoformat(),
            title=f"Check 2-hour post-meal BG for {desc[:25]}"
        )

    return jsonify({"success": True, "id": row_id})

@app.route("/api/logs/<int:entry_id>", methods=["PUT"])
def update_log_api(entry_id: int):
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
        
    data = request.get_json(silent=True) or {}
    prof = database.get_profile() or {}
    unit = prof.get("glucose_unit", "mg/dL")

    raw_bg = data.get("bg_value")
    bg_mgdl = None
    if raw_bg is not None and str(raw_bg).strip() != "":
        bg_mgdl = int(round(t1d_engine.parse_bg_input(float(raw_bg), unit)))

    update_data = {
        "bg_value": bg_mgdl,
        "insulin_units": float(data["insulin_units"]) if data.get("insulin_units") is not None and str(data["insulin_units"]).strip() != "" else None,
        "carbs": float(data["carbs"]) if data.get("carbs") is not None and str(data["carbs"]).strip() != "" else None,
        "fat": float(data["fat"]) if data.get("fat") is not None and str(data["fat"]).strip() != "" else None,
        "sugar": float(data["sugar"]) if data.get("sugar") is not None and str(data["sugar"]).strip() != "" else None,
        "meal_description": data.get("meal_description"),
        "dose_kind": data.get("dose_kind"),
        "notes": data.get("notes"),
        "tags": data.get("tags") or []
    }
    if "occurred_at" in data and data["occurred_at"]:
        update_data["occurred_at"] = data["occurred_at"]
    if "spoiled_insulin" in data:
        update_data["spoiled_insulin"] = bool(data["spoiled_insulin"])

    success = database.update_log_entry(entry_id, update_data)
    if success:
        database.add_audit_log(
            "LOG_EDITED",
            f"Edited log entry #{entry_id}: BG={bg_mgdl or '--'} mg/dL, Insulin={update_data['insulin_units'] or '--'} U, Carbs={update_data['carbs'] or '--'} g"
        )
    return jsonify({"success": success})

@app.route("/api/logs/<int:entry_id>", methods=["DELETE"])
def delete_log_api(entry_id: int):
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
    entry = database.get_log_entry(entry_id)
    success = database.delete_log_entry(entry_id)
    if success:
        bg_info = f"BG: {entry.get('bg_value')}" if entry else f"ID: {entry_id}"
        database.add_audit_log("LOG_DELETED", f"Deleted log record #{entry_id} ({bg_info})")
    return jsonify({"success": success})

@app.route("/api/logs/<int:entry_id>/spoiled", methods=["PUT"])
def toggle_spoiled_api(entry_id: int):
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
    data = request.get_json(silent=True) or {}
    spoiled = bool(data.get("spoiled", True))
    success = database.toggle_spoiled_insulin(entry_id, spoiled)
    return jsonify({"success": success})

# --- Analytics & TIR APIs ---
@app.route("/api/analytics", methods=["GET"])
def get_analytics_api():
    days = request.args.get("days", 14, type=int)
    entries = database.get_log_entries(days=days, limit=1000)
    prof = database.get_profile() or {}
    
    tir_data = t1d_engine.calculate_time_in_range(entries)
    
    # Calculate ratio suggestions
    current_icr = float(prof["icr"]) if prof.get("icr") else None
    current_isf = float(prof["isf"]) if prof.get("isf") else None
    suggestions = t1d_engine.analyze_ratio_suggestions(entries, current_icr, current_isf)
    
    unit = prof.get("glucose_unit", "mg/dL")
    if tir_data["mean_bg"] > 0:
        tir_data["display_mean_bg"] = t1d_engine.format_bg(tir_data["mean_bg"], unit)
    else:
        tir_data["display_mean_bg"] = "--"

    return jsonify({
        "timeframe_days": days,
        "tir": tir_data,
        "suggestions": suggestions,
        "unit": unit
    })

# --- AI Meal Nutrition Analysis API ---
@app.route("/api/analyze-meal", methods=["POST"])
def analyze_meal_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    description = data.get("description", "")
    image_b64 = data.get("image")
    
    prof = database.get_profile() or {}
    api_key = prof.get("ai_api_key")
    model = prof.get("ai_model") or "gemini-2.5-flash"
    base_url = prof.get("ai_base_url") or "https://generativelanguage.googleapis.com"
    
    if not api_key:
        return jsonify({
            "error": "AI API Key is missing. Please configure your Gemini or OpenAI API Key in Settings."
        }), 400

    try:
        nutrition = ai_service.analyze_meal_nutrition(
            description=description,
            image_base64=image_b64,
            api_key=api_key,
            model=model,
            base_url=base_url
        )
        return jsonify(nutrition)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Reminders APIs ---
@app.route("/api/reminders", methods=["GET"])
def get_reminders_api():
    rems = database.get_reminders(include_done=False)
    return jsonify(rems)

@app.route("/api/reminders/<int:reminder_id>/done", methods=["PUT"])
def mark_reminder_api(reminder_id: int):
    success = database.mark_reminder_done(reminder_id)
    return jsonify({"success": success})

# --- System Updates & Maintenance APIs ---
@app.route("/api/system/update/check", methods=["GET"])
def check_update_api():
    repo = request.args.get("repo")
    status = update_service.check_for_github_update(repo)
    return jsonify(status)

@app.route("/api/system/update/apply", methods=["POST"])
def apply_update_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    repo = data.get("repo")
    res = update_service.perform_update(repo)
    if res.get("success"):
        database.add_audit_log("SYSTEM_UPDATE", res.get("message") or "System updated from GitHub.")
        if res.get("restarting"):
            import threading
            managed_by = os.environ.get("GLYCO_MANAGED_BY", "").strip().lower()
            exit_code = 42 if managed_by == "run_bat" else 0

            def _delayed_restart():
                time.sleep(0.8)
                os._exit(exit_code)

            threading.Thread(target=_delayed_restart, daemon=True).start()
    return jsonify(res)

# --- Backup & Restore APIs ---
@app.route("/api/system/backups", methods=["GET"])
def get_backups_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
    backups = backup_service.list_backups()
    return jsonify({"success": True, "backups": backups})

@app.route("/api/system/backups/create", methods=["POST"])
def create_backup_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
    try:
        dest_path = backup_service.create_backup("glycoguide_backup")
        database.add_audit_log("BACKUP_CREATED", f"Created server backup '{dest_path.name}'.")
        return jsonify({
            "success": True,
            "filename": dest_path.name,
            "message": f"Server backup '{dest_path.name}' created successfully."
        })
    except Exception as e:
        return jsonify({"error": f"Failed to create backup: {str(e)}"}), 500

@app.route("/api/system/backups/download/<filename>", methods=["GET"])
def download_backup_api(filename: str):
    is_valid, _ = check_auth(request)
    if not is_valid:
        return redirect("/login")
    target = backup_service.get_backup_path(filename)
    if not target:
        return jsonify({"error": "Backup file not found."}), 404
    return send_from_directory(
        str(config.BACKUP_DIR),
        target.name,
        as_attachment=True,
        download_name=target.name
    )

@app.route("/api/system/backups/download-live", methods=["GET"])
def download_live_backup_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return redirect("/login")
    try:
        snapshot_path = backup_service.create_backup("live_download")
        database.add_audit_log("BACKUP_DOWNLOADED", f"Live database snapshot downloaded ({snapshot_path.name}).")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_name = f"glycoguide_backup_{ts}.db"
        return send_from_directory(
            str(config.BACKUP_DIR),
            snapshot_path.name,
            as_attachment=True,
            download_name=download_name
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate backup: {str(e)}"}), 500

@app.route("/api/system/backups/restore-server", methods=["POST"])
def restore_server_backup_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    password = data.get("password", "")

    if auth_service.is_password_configured():
        if not password or not auth_service.authenticate_master_password(password):
            database.add_audit_log("SECURITY_ALERT", f"Unauthorized restore attempt for '{filename}': Incorrect password.")
            return jsonify({"error": "Incorrect master password. Database was NOT restored."}), 403

    target = backup_service.get_backup_path(filename)
    if not target:
        return jsonify({"error": "Backup file not found on server."}), 404

    success, msg = backup_service.restore_backup(target)
    if not success:
        return jsonify({"error": msg}), 400

    new_sess = auth_service.create_device_session()
    database.add_audit_log("DATA_RESTORED", f"Database restored from server backup '{target.name}'.")

    resp = make_response(jsonify({
        "success": True,
        "message": f"Successfully restored database from '{target.name}'."
    }))
    resp.set_cookie(config.SESSION_COOKIE_NAME, new_sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
    return resp

@app.route("/api/system/backups/restore-upload", methods=["POST"])
def restore_uploaded_backup_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401

    password = request.form.get("password", "")
    if auth_service.is_password_configured():
        if not password or not auth_service.authenticate_master_password(password):
            database.add_audit_log("SECURITY_ALERT", "Unauthorized restore attempt from uploaded file: Incorrect password.")
            return jsonify({"error": "Incorrect master password. Database was NOT restored."}), 403

    file = request.files.get("backup_file")
    if not file or not file.filename:
        return jsonify({"error": "No file was uploaded."}), 400

    safe_name = os.path.basename(file.filename)
    if not (safe_name.endswith(".db") or safe_name.endswith(".sqlite") or safe_name.endswith(".sqlite3")):
        return jsonify({"error": "Invalid file extension. Please upload a .db, .sqlite, or .sqlite3 file."}), 400

    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    saved_archive_path = config.BACKUP_DIR / f"uploaded_{ts}_{safe_name}"

    try:
        file.save(str(saved_archive_path))
    except Exception as e:
        return jsonify({"error": f"Failed to save uploaded file: {str(e)}"}), 500

    success, msg = backup_service.restore_backup(saved_archive_path)
    if not success:
        try:
            saved_archive_path.unlink()
        except Exception:
            pass
        return jsonify({"error": msg}), 400

    new_sess = auth_service.create_device_session()
    database.add_audit_log("DATA_RESTORED", f"Database restored from uploaded file '{safe_name}'.")

    resp = make_response(jsonify({
        "success": True,
        "message": f"Successfully restored database from uploaded file '{safe_name}'."
    }))
    resp.set_cookie(config.SESSION_COOKIE_NAME, new_sess, max_age=86400*30, httponly=True, samesite=config.SESSION_COOKIE_SAMESITE)
    return resp

@app.route("/api/system/backups/<filename>", methods=["DELETE"])
def delete_backup_api(filename: str):
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if auth_service.is_password_configured():
        if not password or not auth_service.authenticate_master_password(password):
            return jsonify({"error": "Incorrect master password. Backup was NOT deleted."}), 403

    success = backup_service.delete_backup(filename)
    if success:
        database.add_audit_log("BACKUP_DELETED", f"Deleted server backup file '{filename}'.")
        return jsonify({"success": True, "message": f"Deleted backup '{filename}'."})
    return jsonify({"error": "Backup file not found or could not be deleted."}), 404

@app.route("/api/system/clear-data", methods=["POST"])
def clear_data_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
        
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    
    if auth_service.is_password_configured():
        if not auth_service.authenticate_master_password(password):
            database.add_audit_log("SECURITY_ALERT", "Unauthorized wipe attempt blocked: Incorrect master password.")
            return jsonify({"error": "Incorrect master password. Your data was NOT deleted."}), 403

    database.clear_all_clinical_data()
    database.add_audit_log("DATA_WIPED", "All clinical logs and reminders wiped by authorized user.")
    return jsonify({"success": True, "message": "All clinical records and reminders cleared."})

@app.route("/api/system/delete-account", methods=["POST"])
def delete_account_api():
    is_valid, _ = check_auth(request)
    if not is_valid:
        return jsonify({"error": "Authentication required"}), 401
        
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    confirmation = str(data.get("confirmation", "")).strip().upper()
    
    if confirmation != "DELETE":
        return jsonify({"error": "You must type 'DELETE' in capital letters to confirm permanent deletion."}), 400
        
    if auth_service.is_password_configured():
        if not password or not auth_service.authenticate_master_password(password):
            database.add_audit_log("SECURITY_ALERT", "Unauthorized account deletion attempt blocked: Incorrect password.")
            return jsonify({"error": "Incorrect master password. Account was NOT deleted."}), 403

    database.factory_reset_all_data_and_accounts()
    database.add_audit_log("ACCOUNT_DELETED", "Master account and all health records permanently deleted by user.")
    
    resp = make_response(jsonify({
        "success": True,
        "message": "Account permanently deleted. System reset to factory state.",
        "redirect": "/login?mode=setup"
    }))
    resp.delete_cookie(config.SESSION_COOKIE_NAME)
    return resp

@app.route("/api/system/audit-logs", methods=["GET"])
def get_audit_logs_api():
    logs = database.get_audit_logs(limit=100)
    return jsonify({"audit_logs": logs})

@app.route("/api/export/csv", methods=["GET"])
def export_csv_api():
    entries = database.get_log_entries(limit=5000)
    prof = database.get_profile() or {}
    unit = prof.get("glucose_unit", "mg/dL")
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Date & Time (UTC)", f"Blood Glucose ({unit})", "Insulin Units", "Carbs (g)",
        "Protein (g)", "Fat (g)", "Sugar (g)", "Dose Type", "Meal Description",
        "Tags", "Spoiled Insulin", "Notes"
    ])
    
    for e in entries:
        bg = e.get("bg_value")
        disp_bg = t1d_engine.format_bg(bg, unit) if bg is not None else ""
        writer.writerow([
            e.get("id"),
            e.get("occurred_at"),
            disp_bg,
            e.get("insulin_units") or "",
            e.get("carbs") or "",
            e.get("protein") or "",
            e.get("fat") or "",
            e.get("sugar") or "",
            e.get("dose_kind") or "",
            e.get("meal_description") or "",
            ", ".join(e.get("tags") or []),
            "Yes" if e.get("spoiled_insulin") else "No",
            e.get("notes") or ""
        ])
        
    csv_str = output.getvalue()
    response = make_response(csv_str)
    response.headers["Content-Disposition"] = f"attachment; filename=glycoguide_export_{datetime.now().strftime('%Y%m%d')}.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response

if __name__ == "__main__":
    import sys
    import socket
    import threading
    import webbrowser

    def _is_port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except Exception:
            return False

    def _should_open_browser() -> bool:
        if os.environ.get("GLYCO_NO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
            return False
        if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        return True

    def _open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(f"http://localhost:{config.PORT}")
        except Exception:
            pass

    managed_by = os.environ.get("GLYCO_MANAGED_BY", "").strip().lower()
    restarted = os.environ.get("GLYCO_RESTARTED", "").strip().lower() in ("1", "true", "yes")

    # Wait briefly if we just self-restarted so previous socket closes cleanly
    if restarted:
        for _ in range(10):
            if not _is_port_open(config.PORT):
                break
            time.sleep(0.3)

    if managed_by != "systemd" and not restarted and _is_port_open(config.PORT):
        print(f"\n  [INFO] GlycoGuide is already running at http://localhost:{config.PORT}")
        if _should_open_browser():
            webbrowser.open(f"http://localhost:{config.PORT}")
        sys.exit(0)

    if _should_open_browser():
        threading.Thread(target=_open_browser, daemon=True).start()

    print(f"""
    ====================================================================
           GlycoGuide Remastered — Type 1 Diabetes Assistant
    ====================================================================
    - Server running on: http://localhost:{config.PORT}
    - Network / DuckDNS: http://0.0.0.0:{config.PORT}
    - Database:          {config.DB_PATH}
    ====================================================================
    """)
    try:
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)
    except OSError as e:
        print(f"\n  [ERROR] Could not bind to port {config.PORT}: {e}")
        print("  Another instance of GlycoGuide (or another service) may already be using this port.")
        if getattr(sys, "frozen", False) or os.name == "nt":
            time.sleep(4)
        sys.exit(1)
