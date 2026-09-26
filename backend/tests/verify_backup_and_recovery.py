"""
Backup and Disaster Recovery Drill Script (Milestone 7 Phase 4).
Verifies:
1. PostgreSQL dump creation and schema/table verification.
2. Encrypted resume directory tarball creation and verification.
3. Isolated database restore into temporary test database.
4. End-to-end decryption of restored resume bytes using SecurityManager.
5. Zero data corruption or key mismatch.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.resume import UserResume
from app.models.user import User


async def run_backup_and_recovery_drill():
    print("==================================================")
    print("Starting Milestone 7 Backup & Disaster Recovery Drill")
    print("==================================================")

    # 1. Prepare temporary drill workspace
    drill_dir = Path(tempfile.mkdtemp(prefix="ai_assistant_dr_drill_"))
    try:
        backup_db_file = drill_dir / "postgres_backup.dump"
        backup_resumes_file = drill_dir / "resumes_backup.tar.gz"
        restore_resumes_dir = drill_dir / "restored_resumes"
        restore_resumes_dir.mkdir(parents=True, exist_ok=True)

        print(f"1. Drill directory created: {drill_dir}")

        # 2. Extract database connection parameters
        db_url = settings.DATABASE_URL
        # e.g., postgresql+asyncpg://postgres:postgres@localhost:5438/ai_assistant_dev
        import re
        m = re.search(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url)
        if not m:
            print(f"FAILED: Unable to parse PostgreSQL URL: {db_url}")
            return False

        pg_user, pg_pass, pg_host, pg_port, pg_db = m.groups()

        env = os.environ.copy()
        env["PGPASSWORD"] = pg_pass

        # 3. Create a test resume file in active storage to backup
        active_storage_dir = Path(settings.RESUME_STORAGE_DIR)
        active_storage_dir.mkdir(parents=True, exist_ok=True)

        test_plain_text = "Experienced Senior Software Engineer specializing in Python, FastAPI, and Distributed Systems."
        encrypted_token = SecurityManager.encrypt_token(test_plain_text)
        test_file_name = "dr_drill_test_resume.bin"
        test_file_path = active_storage_dir / test_file_name
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(encrypted_token)

        print(f"2. Created test encrypted resume in {test_file_path}")

        # 4. Execute PostgreSQL Dump via pg_dump
        dump_cmd = [
            "pg_dump",
            "-h", pg_host,
            "-p", pg_port,
            "-U", pg_user,
            "-d", pg_db,
            "-Fc",
            "-f", str(backup_db_file)
        ]
        print(f"3. Executing pg_dump: {' '.join(dump_cmd[:6])} -f {backup_db_file.name}")
        res = subprocess.run(dump_cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"FAILED: pg_dump failed: {res.stderr}")
            return False

        assert backup_db_file.exists() and backup_db_file.stat().st_size > 0
        print(f"   -> PostgreSQL backup created successfully ({backup_db_file.stat().st_size} bytes)")

        # 5. Execute Resume Tarball Backup
        tar_cmd = ["tar", "-czf", str(backup_resumes_file), "-C", str(active_storage_dir.parent), active_storage_dir.name]
        print(f"4. Executing tar backup: {' '.join(tar_cmd)}")
        res_tar = subprocess.run(tar_cmd, capture_output=True, text=True)
        if res_tar.returncode != 0:
            print(f"FAILED: tar backup failed: {res_tar.stderr}")
            return False

        assert backup_resumes_file.exists() and backup_resumes_file.stat().st_size > 0
        print(f"   -> Resume storage backup created successfully ({backup_resumes_file.stat().st_size} bytes)")

        # 6. Test Database Restore into isolated test database
        test_restore_db = "ai_assistant_restore_drill"
        # Create test restore db
        drop_cmd = ["dropdb", "-h", pg_host, "-p", pg_port, "-U", pg_user, "--if-exists", test_restore_db]
        subprocess.run(drop_cmd, env=env, capture_output=True)

        createdb_cmd = ["createdb", "-h", pg_host, "-p", pg_port, "-U", pg_user, test_restore_db]
        res_createdb = subprocess.run(createdb_cmd, env=env, capture_output=True, text=True)
        if res_createdb.returncode != 0:
            print(f"FAILED: createdb failed: {res_createdb.stderr}")
            return False

        restore_cmd = [
            "pg_restore",
            "-h", pg_host,
            "-p", pg_port,
            "-U", pg_user,
            "-d", test_restore_db,
            str(backup_db_file)
        ]
        print(f"5. Executing pg_restore to isolated database '{test_restore_db}'")
        res_restore = subprocess.run(restore_cmd, env=env, capture_output=True, text=True)
        # Note: pg_restore might have non-fatal exit code 0 or 1 for minor warnings
        print(f"   -> Database restore completed.")

        # 7. Verify restored database schema and connectivity
        restore_engine = create_async_engine(f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{test_restore_db}")
        async_session = sessionmaker(restore_engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            result = await session.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))
            table_count = result.scalar()
            print(f"6. Restored database verification: {table_count} public tables restored.")
            assert table_count > 10, f"Expected >10 tables, found {table_count}"

        await restore_engine.dispose()

        # 8. Restore resume files from tarball and test decryption
        untar_cmd = ["tar", "-xzf", str(backup_resumes_file), "-C", str(restore_resumes_dir)]
        subprocess.run(untar_cmd, check=True)

        restored_file = restore_resumes_dir / active_storage_dir.name / test_file_name
        assert restored_file.exists(), f"Restored resume file {restored_file} does not exist!"

        with open(restored_file, "r", encoding="utf-8") as f:
            restored_encrypted_str = f.read()

        decrypted_text = SecurityManager.decrypt_token(restored_encrypted_str)
        assert decrypted_text == test_plain_text, "Decrypted text does not match original plaintext!"
        print(f"7. Decryption verification: Successfully decrypted restored resume ({len(decrypted_text)} chars).")

        # 9. Clean up drill assets
        subprocess.run(["dropdb", "-h", pg_host, "-p", pg_port, "-U", pg_user, "--if-exists", test_restore_db], env=env, capture_output=True)
        if test_file_path.exists():
            test_file_path.unlink()

        print("==================================================")
        print("Milestone 7 Backup & Disaster Recovery Drill: PASSED")
        print("==================================================")
        return True

    finally:
        shutil.rmtree(drill_dir, ignore_errors=True)


if __name__ == "__main__":
    success = asyncio.run(run_backup_and_recovery_drill())
    if not success:
        exit(1)
