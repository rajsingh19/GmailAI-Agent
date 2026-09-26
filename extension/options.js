/**
 * Options page script for Personal AI Assistant Extension.
 */

document.addEventListener("DOMContentLoaded", () => {
  const tokenInput = document.getElementById("extensionToken");
  const backendUrlInput = document.getElementById("backendUrl");
  const frontendUrlInput = document.getElementById("frontendUrl");
  const settingsLink = document.getElementById("settingsLink");
  const form = document.getElementById("optionsForm");
  const testBtn = document.getElementById("testBtn");
  const alertEl = document.getElementById("statusAlert");

  // Load saved options
  chrome.storage.sync.get(["backendUrl", "frontendUrl", "extensionToken"], (items) => {
    if (items.backendUrl) backendUrlInput.value = items.backendUrl;
    if (items.frontendUrl) {
      frontendUrlInput.value = items.frontendUrl;
      settingsLink.href = `${items.frontendUrl.replace(/\/+$/, "")}/settings`;
    }
    if (items.extensionToken) tokenInput.value = items.extensionToken;
  });

  frontendUrlInput.addEventListener("input", () => {
    const val = frontendUrlInput.value.trim().replace(/\/+$/, "");
    if (val) {
      settingsLink.href = `${val}/settings`;
    }
  });

  function showAlert(msg, isError = false) {
    alertEl.textContent = msg;
    alertEl.className = `alert ${isError ? "alert-error" : "alert-success"}`;
    alertEl.style.display = "block";
  }

  // Handle Save
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const backendUrl = backendUrlInput.value.trim().replace(/\/+$/, "");
    const frontendUrl = frontendUrlInput.value.trim().replace(/\/+$/, "");
    const extensionToken = tokenInput.value.trim();

    if (!extensionToken) {
      showAlert("Please enter an Extension Token starting with ext_", true);
      return;
    }

    // If backend URL is custom (not localhost or 127.0.0.1), dynamically request host permission
    if (!backendUrl.includes("localhost") && !backendUrl.includes("127.0.0.1")) {
      try {
        const originPattern = `${backendUrl}/*`;
        const granted = await chrome.permissions.request({
          origins: [originPattern],
        });
        if (!granted) {
          showAlert(`Permission to connect to ${backendUrl} was denied by user.`, true);
          return;
        }
      } catch (err) {
        console.warn("Dynamic permission request warning:", err);
      }
    }

    chrome.storage.sync.set(
      {
        backendUrl,
        frontendUrl,
        extensionToken,
      },
      () => {
        showAlert("Settings saved successfully!");
      }
    );
  });

  // Handle Test Connection
  testBtn.addEventListener("click", async () => {
    const backendUrl = backendUrlInput.value.trim().replace(/\/+$/, "");
    const extensionToken = tokenInput.value.trim();

    if (!extensionToken) {
      showAlert("Please provide an Extension Token to test.", true);
      return;
    }

    testBtn.disabled = true;
    testBtn.textContent = "Testing...";

    try {
      // Test health first
      const healthRes = await fetch(`${backendUrl}/health`);
      if (!healthRes.ok) {
        showAlert(`Backend reachable but returned error HTTP ${healthRes.status}.`, true);
        return;
      }

      // Test extension token auth
      const tokenRes = await fetch(`${backendUrl}/auth/extension-token`, {
        headers: {
          "Authorization": `Bearer ${extensionToken}`,
          "X-API-Key": extensionToken,
        },
      });

      if (tokenRes.ok) {
        const data = await tokenRes.json();
        showAlert(`Connection successful! Token authenticated (prefix: ${data.token_prefix || "ext_..."}).`, false);
      } else if (tokenRes.status === 401) {
        showAlert("Connection reached backend, but Extension Token was rejected (invalid or revoked).", true);
      } else {
        showAlert(`Backend returned status ${tokenRes.status}.`, true);
      }
    } catch (err) {
      showAlert(`Failed to connect to backend at ${backendUrl}: ${err.message}`, true);
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = "Test Connection";
    }
  });
});
