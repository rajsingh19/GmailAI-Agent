"""
Test PWA Dashboard Service Worker Global Registration.
Verifies that the Service Worker is registered on application startup (main.tsx),
reuses the existing pushManager implementation, prevents duplicate registrations,
and maintains manifest/service worker integrity.
"""
import json
import re
from pathlib import Path


def test_main_entrypoint_initiates_service_worker_registration():
    """Verify that main.tsx imports and executes registerServiceWorker on startup."""
    main_path = Path("/home/raj/AI-ASSISTANT/frontend/src/main.tsx")
    assert main_path.exists(), "main.tsx must exist as application entry point"
    
    content = main_path.read_text(encoding="utf-8")
    
    # Must import registerServiceWorker from utils/pushManager
    assert re.search(
        r"import\s+\{\s*registerServiceWorker\s*\}\s+from\s+['\"]./utils/pushManager['\"]",
        content,
    ), "main.tsx must import registerServiceWorker from ./utils/pushManager"
    
    # Must invoke registerServiceWorker on startup
    assert re.search(
        r"registerServiceWorker\s*\(\s*\)",
        content,
    ), "main.tsx must invoke registerServiceWorker() on startup"


def test_push_manager_prevents_duplicate_registration():
    """Verify that pushManager.ts memoizes the registration promise to prevent duplicate calls."""
    pm_path = Path("/home/raj/AI-ASSISTANT/frontend/src/utils/pushManager.ts")
    assert pm_path.exists(), "pushManager.ts must exist"
    
    content = pm_path.read_text(encoding="utf-8")
    
    # Must define registration promise memoization variable
    assert "_registrationPromise" in content, (
        "pushManager.ts must define _registrationPromise to cache the active registration"
    )
    
    # Must check _registrationPromise before calling navigator.serviceWorker.register
    assert re.search(
        r"if\s*\(\s*_registrationPromise\s*\)\s*\{\s*return\s+_registrationPromise;\s*\}",
        content,
    ), "registerServiceWorker must return cached promise to prevent duplicate registrations"


def test_manifest_pwa_spec_compliance():
    """Verify that manifest.json contains all required PWA manifest fields."""
    manifest_path = Path("/home/raj/AI-ASSISTANT/frontend/public/manifest.json")
    assert manifest_path.exists(), "manifest.json must exist in public/"
    
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    assert data.get("name"), "manifest.json must define name"
    assert data.get("short_name"), "manifest.json must define short_name"
    assert data.get("start_url") == "/", "start_url must be root '/'"
    assert data.get("display") == "standalone", "display mode must be standalone"
    
    icons = data.get("icons", [])
    assert len(icons) >= 2, "Must contain at least 192px and 512px icons"
    
    sizes = [i.get("sizes") for i in icons]
    assert "192x192" in sizes, "Must include 192x192 icon"
    assert "512x512" in sizes, "Must include 512x512 icon"


def test_service_worker_script_integrity():
    """Verify that sw.js exists and contains expected event listeners."""
    sw_path = Path("/home/raj/AI-ASSISTANT/frontend/public/sw.js")
    assert sw_path.exists(), "sw.js must exist in public/"
    
    content = sw_path.read_text(encoding="utf-8")
    
    assert "install" in content, "sw.js must handle install event"
    assert "activate" in content, "sw.js must handle activate event"
    assert "push" in content, "sw.js must handle push event"
    assert "notificationclick" in content, "sw.js must handle notificationclick event"


def test_single_service_worker_registration_source():
    """Verify that no duplicate/secondary registration functions exist across the codebase."""
    src_dir = Path("/home/raj/AI-ASSISTANT/frontend/src")
    registration_definitions = []
    
    for ts_file in src_dir.rglob("*.ts*"):
        content = ts_file.read_text(encoding="utf-8")
        matches = re.findall(r"export\s+async\s+function\s+registerServiceWorker", content)
        if matches:
            registration_definitions.append(ts_file.name)
            
    assert registration_definitions == ["pushManager.ts"], (
        f"Only pushManager.ts should define registerServiceWorker, found in: {registration_definitions}"
    )
