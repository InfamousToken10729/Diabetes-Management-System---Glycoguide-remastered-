import os
import sys
import json
import time
import tempfile
from datetime import datetime, timezone
import config

from pathlib import Path

# Isolate test database and backups from real user data
test_tmp_dir = tempfile.mkdtemp()
config.DB_PATH = Path(test_tmp_dir) / "test_glycoguide.db"
config.BACKUP_DIR = Path(test_tmp_dir) / "test_backups"
config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

import database
import t1d_engine
import auth_service
import update_service
import backup_service
import app

def run_tests():
    print("====================================================================")
    print("      Running GlycoGuide Remastered Comprehensive Unit & API Tests   ")
    print("====================================================================")

    # 1. Test Database Init & Seeding
    database.init_db()
    database.update_main_user_password(None, None)  # Reset for clean test state
    prof = database.get_profile()
    assert prof is not None, "Profile should be seeded"
    print(f"[PASS] Database initialized. Target BG: {prof['target_bg']} {prof['glucose_unit']}")

    # 2. Test t1d_engine IOB calculation
    now = time.time()
    # Dose of 4 units given 60 minutes ago with 4h DIA
    doses = [{
        "id": 1,
        "insulin_units": 4.0,
        "occurred_at": datetime.fromtimestamp(now - 3600, timezone.utc).isoformat(),
        "spoiled_insulin": False
    }]
    active_iob, breakdown = t1d_engine.calculate_active_iob(doses, duration_hours=4.0, insulin_type="NovoRapid", reference_time=now)
    assert active_iob > 0, "IOB should be positive for recent dose"
    assert active_iob < 4.0, "IOB should have decayed partially after 1 hour"
    print(f"[PASS] IOB Mudaliar Curve calculation: 4.0 U dose 1 hr ago -> {active_iob} U active remaining")

    # 3. Test Bolus Calculation with IOB subtraction
    bolus_result = t1d_engine.calculate_bolus(
        bg_mgdl=180.0,
        target_bg_mgdl=110.0,
        icr=10.0,
        isf=50.0,
        carbs=50.0, # 5.0 U meal
        sugar=10.0,
        fat=25.0,  # Trigger high-fat split
        current_iob=active_iob,
        tags=["exercise"] # 0.8x
    )
    assert bolus_result["status"] == "ok"
    assert bolus_result["split_bolus"] is not None, "High fat (>20g) should recommend split bolus"
    print(f"[PASS] Bolus calculation: Recommended dose = {bolus_result['total_units']} U (Split: {bolus_result['split_bolus']['upfront_units']}U now / {bolus_result['split_bolus']['later_units']}U later)")

    # 4. Test Hypo Blocking Guard
    hypo_result = t1d_engine.calculate_bolus(
        bg_mgdl=58.0,
        target_bg_mgdl=110.0,
        icr=10.0,
        isf=50.0,
        carbs=40.0,
        sugar=5.0,
        fat=0.0,
        current_iob=0.0,
        tags=[]
    )
    assert hypo_result["status"] == "blocked", "Dose must be blocked for blood glucose < 70"
    print(f"[PASS] Hypo safety guard: Dose correctly blocked when BG = 58 mg/dL")

    # 5. Test ADAG Estimated HbA1c
    test_readings = [
        {"bg_value": 110, "occurred_at": datetime.fromtimestamp(now - 86400*3, timezone.utc).isoformat()},
        {"bg_value": 130, "occurred_at": datetime.fromtimestamp(now - 86400*2, timezone.utc).isoformat()},
        {"bg_value": 120, "occurred_at": datetime.fromtimestamp(now - 86400*1, timezone.utc).isoformat()},
    ]
    tir_data = t1d_engine.calculate_time_in_range(test_readings)
    assert tir_data["count"] == 3
    assert tir_data["estimated_a1c"]["percent"] > 5.0
    print(f"[PASS] ADAG eA1c calculation: Mean BG = {tir_data['mean_bg']} mg/dL -> eA1c = {tir_data['estimated_a1c']['percent']}% ({tir_data['estimated_a1c']['mmol_mol']} mmol/mol)")

    # 6. Test Unit Conversions
    mmol = t1d_engine.mg_dl_to_mmol_l(180)
    assert abs(mmol - 10.0) < 0.2
    mgdl = t1d_engine.mmol_l_to_mg_dl(10.0)
    assert abs(mgdl - 180) < 2
    print(f"[PASS] Unit conversions: 180 mg/dL <-> {mmol} mmol/L")

    # 7. Test Flask Test Client (HTTP Endpoints)
    with app.app.test_client() as client:
        # GET /login (Dedicated auth page loads)
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"GlycoGuide" in resp.data
        print("[PASS] GET /login (Dedicated full-screen login & setup page loads)")

        # GET / when unauthenticated redirects to /login?mode=setup
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        print("[PASS] GET / server-side gatekeeping correctly redirects unauthenticated visitors to /login")

        # GET /api/profile
        resp = client.get("/api/profile")
        assert resp.status_code == 200
        p = json.loads(resp.data)
        assert p["target_bg"] == 110
        print("[PASS] GET /api/profile returns JSON profile")

        # PUT /api/profile with birth_date -> auto-computes age
        put_prof_resp = client.put("/api/profile", json={"birth_date": "1998-05-15", "username": "Test Patient"})
        assert put_prof_resp.status_code == 200
        updated_prof = json.loads(put_prof_resp.data)
        assert updated_prof["birth_date"] == "1998-05-15"
        assert updated_prof["age"] is not None and updated_prof["age"] >= 25
        print(f"[PASS] PUT /api/profile with birth_date='1998-05-15' auto-calculated age={updated_prof['age']}")

        # GET /api/iob
        resp = client.get("/api/iob")
        assert resp.status_code == 200
        iob_json = json.loads(resp.data)
        assert "active_iob" in iob_json
        print(f"[PASS] GET /api/iob returns active IOB ({iob_json['active_iob']} U)")

        # POST /api/calculate-bolus
        resp = client.post("/api/calculate-bolus", json={"bg": 150, "carbs": 40, "tags": []})
        assert resp.status_code == 200
        calc_json = json.loads(resp.data)
        assert calc_json["status"] == "ok"
        print(f"[PASS] POST /api/calculate-bolus returns {calc_json['total_units']} U")

        # POST /api/logs (Correction Bolus with tied BG reading)
        corr_resp = client.post("/api/logs", json={
            "dose_kind": "correction",
            "insulin_units": 3.0,
            "bg_value": 220,
            "tags": ["correction"]
        })
        assert corr_resp.status_code == 200
        corr_id = json.loads(corr_resp.data)["id"]
        corr_entry = database.get_log_entry(corr_id)
        assert corr_entry["bg_value"] == 220
        assert corr_entry["insulin_units"] == 3.0
        assert corr_entry["dose_kind"] == "correction"
        print(f"[PASS] POST /api/logs saved tied correction bolus (BG=220 mg/dL, Insulin=3.0 U) #{corr_id}")

        # POST /api/logs (Add reading)
        resp = client.post("/api/logs", json={"bg_value": 145, "carbs": 30, "tags": ["pre-meal"]})
        assert resp.status_code == 200
        added_log = json.loads(resp.data)
        log_id = added_log["id"]
        print(f"[PASS] POST /api/logs created entry #{log_id}")

        # PUT /api/logs/<id> (Edit reading)
        resp = client.put(f"/api/logs/{log_id}", json={"bg_value": 140, "meal_description": "Updated meal notes"})
        assert resp.status_code == 200
        updated_log = json.loads(resp.data)
        assert updated_log["success"] is True
        print(f"[PASS] PUT /api/logs/{log_id} successfully edited reading in-place")

        # GET /api/system/audit-logs
        resp = client.get("/api/system/audit-logs")
        assert resp.status_code == 200
        audit_json = json.loads(resp.data)
        assert "audit_logs" in audit_json
        assert len(audit_json["audit_logs"]) >= 2
        print(f"[PASS] GET /api/system/audit-logs returned {len(audit_json['audit_logs'])} audit trail records")

        # POST /api/system/clear-data password protection test
        # 1. Set a master password
        auth_service.set_master_password("Secret123")

        # 2. Unlock device session first
        unlock_resp = client.post("/api/auth/unlock", json={"password": "Secret123"})
        assert unlock_resp.status_code == 200

        # 3. Try clearing data with WRONG password -> Expect 403 Forbidden
        resp = client.post("/api/system/clear-data", json={"password": "wrongpassword"})
        assert resp.status_code == 403
        err_json = json.loads(resp.data)
        assert "Incorrect master password" in err_json["error"]
        print("[PASS] POST /api/system/clear-data: Rejected wrong password with 403 and kept data safe")

        # 4. Try clearing data with CORRECT password -> Expect 200 OK
        resp = client.post("/api/system/clear-data", json={"password": "Secret123"})
        assert resp.status_code == 200
        ok_json = json.loads(resp.data)
        assert ok_json["success"] is True
        print("[PASS] POST /api/system/clear-data: Accepted correct password and cleared clinical data")

        # 5. Test Register New Account From Beginning
        reg_resp = client.post("/api/auth/register-new", json={
            "display_name": "Test User",
            "password": "Password123!",
            "recovery_key": "GLYCO-TEST-KEY-1234",
            "glucose_unit": "mg/dL",
            "wipe_data": True
        })
        assert reg_resp.status_code == 200
        assert json.loads(reg_resp.data)["success"] is True
        print("[PASS] POST /api/auth/register-new created fresh account and session")

        # 6. Test Reset Password with Recovery Key
        reset_resp = client.post("/api/auth/reset-password", json={
            "recovery_key": "GLYCO-TEST-KEY-1234",
            "new_password": "NewSecretPassword!"
        })
        assert reset_resp.status_code == 200
        assert json.loads(reset_resp.data)["success"] is True
        print("[PASS] POST /api/auth/reset-password reset credentials via recovery key")

        # 7. Test Emergency Local Override
        emerg_resp = client.post("/api/auth/emergency-reset", json={
            "confirmation": "RESET",
            "new_password": "FinalPassword789!"
        })
        assert emerg_resp.status_code == 200
        assert json.loads(emerg_resp.data)["success"] is True
        print("[PASS] POST /api/auth/emergency-reset performed local emergency override")

        # 8a. Test Delete Account: Rejects missing DELETE confirmation
        del_fail_1 = client.post("/api/system/delete-account", json={
            "password": "FinalPassword789!",
            "confirmation": "WRONG"
        })
        assert del_fail_1.status_code == 400
        print("[PASS] POST /api/system/delete-account correctly rejected missing DELETE confirmation (400)")

        # 8b. Test Delete Account: Rejects wrong password
        del_fail_2 = client.post("/api/system/delete-account", json={
            "password": "WrongPassword!",
            "confirmation": "DELETE"
        })
        assert del_fail_2.status_code == 403
        print("[PASS] POST /api/system/delete-account correctly rejected wrong password (403)")

        # 8c. Test Delete Account: Accepts correct password AND DELETE confirmation
        del_acc_resp = client.post("/api/system/delete-account", json={
            "password": "FinalPassword789!",
            "confirmation": "DELETE"
        })
        assert del_acc_resp.status_code == 200
        del_acc_json = json.loads(del_acc_resp.data)
        assert del_acc_json["success"] is True
        assert "setup" in del_acc_json["redirect"]
        assert auth_service.is_password_configured() is False
        print("[PASS] POST /api/system/delete-account successfully factory-reset system to brand new state")

        # GET /report
        resp = client.get("/report?days=14")
        assert resp.status_code == 200
        assert b"Clinical Diabetes Summary" in resp.data
        print("[PASS] GET /report (Printable Doctor Report loads)")

        # GET /api/export/csv
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["Content-Type"]
        print("[PASS] GET /api/export/csv returns valid CSV download")

        # Test Default GitHub Repo Seed & Legacy Migration
        prof_now = database.get_profile()
        assert prof_now["github_repo"] == config.DEFAULT_GITHUB_REPO, f"Unexpected repo: {prof_now['github_repo']}"
        database.update_profile("family-shared-device", {
            "github_repo": "https://github.com/InfamousToken10729/Diabetes-Management-System-v2"
        })
        database.init_db()
        migrated_prof = database.get_profile()
        assert migrated_prof["github_repo"] == config.DEFAULT_GITHUB_REPO, "Legacy v2 repo URL should auto-migrate"
        print("[PASS] Database automatically seeds and migrates legacy repo URL to Remastered GitHub repo")

        # Test GitHub URL parsing in update_service
        assert update_service.parse_github_owner_repo(
            "https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git"
        ) == ("InfamousToken10729", "Diabetes-Management-System---Glycoguide-remastered-")
        assert update_service.parse_github_owner_repo(
            "https://github.com/InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-"
        ) == ("InfamousToken10729", "Diabetes-Management-System---Glycoguide-remastered-")
        assert update_service.parse_github_owner_repo(
            "git@github.com:InfamousToken10729/Diabetes-Management-System---Glycoguide-remastered-.git"
        ) == ("InfamousToken10729", "Diabetes-Management-System---Glycoguide-remastered-")
        print("[PASS] update_service parses HTTPS, .git, web URL, and SSH GitHub URLs accurately")

        # Test Backup & Restore Service and APIs
        print("--- Testing Backup & Restore Service & APIs ---")
        
        # 1. Validation tests
        # Missing file
        valid, msg = backup_service.validate_backup_database(config.BACKUP_DIR / "non_existent.db")
        assert not valid, "Missing file should fail validation"

        # Corrupt file
        corrupt_path = config.BACKUP_DIR / "corrupt.db"
        with open(corrupt_path, "wb") as f:
            f.write(b"not a valid sqlite file")
        valid, msg = backup_service.validate_backup_database(corrupt_path)
        assert not valid, "Corrupt file should fail validation"
        corrupt_path.unlink()

        # Valid live db
        valid, msg = backup_service.validate_backup_database(config.DB_PATH)
        assert valid, f"Live DB should be valid: {msg}"
        print("[PASS] backup_service.validate_backup_database validates SQLite files correctly")

        # 2. Create server backup
        backup_path = backup_service.create_backup("test_manual")
        assert backup_path.exists()
        valid, msg = backup_service.validate_backup_database(backup_path)
        assert valid, "Created backup should be valid SQLite DB"
        print(f"[PASS] backup_service created valid backup: {backup_path.name}")

        # 3. List backups
        all_backups = backup_service.list_backups()
        assert any(b["filename"] == backup_path.name for b in all_backups)
        print(f"[PASS] backup_service.list_backups found {len(all_backups)} backup(s)")

        # 4. Path traversal protection
        assert backup_service.get_backup_path("../secret.db") is None
        assert backup_service.get_backup_path(backup_path.name) is not None
        print("[PASS] Path traversal protection works as expected")

        # 5. API Tests
        # Re-authenticate client session
        auth_service.set_master_password("TestBackupPass123")
        client.post("/api/auth/unlock", json={"password": "TestBackupPass123"})

        # GET /api/system/backups
        resp = client.get("/api/system/backups")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("success") is True
        assert len(data.get("backups", [])) >= 1
        print("[PASS] GET /api/system/backups returns backup list")

        # POST /api/system/backups/create
        resp = client.post("/api/system/backups/create")
        assert resp.status_code == 200
        new_backup_name = json.loads(resp.data)["filename"]
        assert (config.BACKUP_DIR / new_backup_name).exists()
        print(f"[PASS] POST /api/system/backups/create generated {new_backup_name}")

        # GET /api/system/backups/download/<filename>
        resp = client.get(f"/api/system/backups/download/{new_backup_name}")
        assert resp.status_code == 200
        assert resp.data.startswith(b"SQLite format 3\000")
        print("[PASS] GET /api/system/backups/download/<filename> streams valid SQLite database")

        # GET /api/system/backups/download-live
        resp = client.get("/api/system/backups/download-live")
        assert resp.status_code == 200
        assert resp.data.startswith(b"SQLite format 3\000")
        print("[PASS] GET /api/system/backups/download-live streams live SQLite database snapshot")

        # Restore from server: wrong password
        resp = client.post("/api/system/backups/restore-server", json={"filename": new_backup_name, "password": "WrongPassword"})
        assert resp.status_code == 403
        print("[PASS] POST /api/system/backups/restore-server rejected wrong password (403)")

        # Restore from server: correct password
        resp = client.post("/api/system/backups/restore-server", json={"filename": new_backup_name, "password": "TestBackupPass123"})
        assert resp.status_code == 200
        assert json.loads(resp.data)["success"] is True
        safety_backups = [b for b in backup_service.list_backups() if "pre_restore_" in b["filename"]]
        assert len(safety_backups) >= 1
        print("[PASS] POST /api/system/backups/restore-server restored DB and created safety snapshot")

        # Restore from upload: invalid file
        import io
        fake_file = (io.BytesIO(b"garbage content not sqlite"), "test_corrupt.db")
        resp = client.post(
            "/api/system/backups/restore-upload",
            data={"backup_file": fake_file, "password": "TestBackupPass123"},
            content_type="multipart/form-data"
        )
        assert resp.status_code == 400
        print("[PASS] POST /api/system/backups/restore-upload rejected corrupt file (400)")

        # Restore from upload: valid file
        with open(backup_path, "rb") as f:
            valid_bytes = f.read()
        valid_upload = (io.BytesIO(valid_bytes), "my_valid_backup.db")
        resp = client.post(
            "/api/system/backups/restore-upload",
            data={"backup_file": valid_upload, "password": "TestBackupPass123"},
            content_type="multipart/form-data"
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)["success"] is True
        print("[PASS] POST /api/system/backups/restore-upload restored valid uploaded backup (200)")

        # DELETE /api/system/backups/<filename>
        auth_service.set_master_password("TestBackupPass123")
        # Wrong password
        resp = client.delete(f"/api/system/backups/{new_backup_name}", json={"password": "WrongPassword"})
        assert resp.status_code == 403
        # Correct password
        resp = client.delete(f"/api/system/backups/{new_backup_name}", json={"password": "TestBackupPass123"})
        assert resp.status_code == 200
        assert not (config.BACKUP_DIR / new_backup_name).exists()
        print(f"[PASS] DELETE /api/system/backups/{new_backup_name} deleted backup successfully")

        # Clean up test temp database
        database.factory_reset_all_data_and_accounts()
        try:
            import shutil
            shutil.rmtree(test_tmp_dir, ignore_errors=True)
        except Exception:
            pass

    print("====================================================================")
    print("         ALL UNIT & INTEGRATION TESTS PASSED 100%!                  ")
    print("====================================================================")

if __name__ == "__main__":
    run_tests()
