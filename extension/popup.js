/**
 * Popup script for Personal AI Assistant Extension.
 * Handles both:
 * 1. Verified Job Capture (auto-match on /jobs/view/*)
 * 2. Quick Capture (Manual Review on arbitrary linkedin.com pages)
 *
 * v2 changes:
 * - Quick Capture is immediately DISABLED on known listing/index pages (/search/*, /feed/ root, etc.)
 * - Quick Capture respects { ok: false, reason } from content script — never sends junk
 * - Completely removed title/tab.title fallback that caused "Search | LinkedIn" entries
 * - Multi-layer validation before any POST request is submitted
 */

document.addEventListener("DOMContentLoaded", async () => {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const warningBox = document.getElementById("warningBox");
  const modeBadge = document.getElementById("modeBadge");
  const pageTitle = document.getElementById("pageTitle");
  const pageCompany = document.getElementById("pageCompany");
  const verifiedActionArea = document.getElementById("verifiedActionArea");
  const captureBtn = document.getElementById("captureBtn");
  const quickCaptureArea = document.getElementById("quickCaptureArea");
  const quickCaptureBtn = document.getElementById("quickCaptureBtn");
  const openDashboard = document.getElementById("openDashboard");
  const openOptions = document.getElementById("openOptions");

  let frontendUrl = "http://localhost:5173";
  let backendUrl = "http://localhost:8000";
  let extensionToken = "";

  chrome.storage.sync.get(
    ["backendUrl", "frontendUrl", "extensionToken"],
    (items) => {
      if (items.backendUrl) backendUrl = items.backendUrl;
      if (items.frontendUrl) frontendUrl = items.frontendUrl;
      if (items.extensionToken) extensionToken = items.extensionToken;

      checkConfigAndStatus();
    }
  );

  openDashboard.addEventListener("click", (e) => {
    e.preventDefault();
    chrome.tabs.create({ url: `${frontendUrl.replace(/\/+$/, "")}/jobs` });
  });

  openOptions.addEventListener("click", (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  async function checkConfigAndStatus() {
    if (!extensionToken) {
      statusDot.className = "dot offline";
      statusText.textContent = "Token Required";
      warningBox.className = "msg-box msg-warning";
      warningBox.innerHTML = `Extension token missing. <a href="#" id="cfgLink" style="color:#ffffff;text-decoration:underline;">Configure in Settings</a>.`;
      document
        .getElementById("cfgLink")
        ?.addEventListener("click", (e) => {
          e.preventDefault();
          chrome.runtime.openOptionsPage();
        });
      disableAllButtons("Token Required");
      return;
    }

    try {
      const res = await fetch(`${backendUrl}/health`);
      if (res.ok) {
        statusDot.className = "dot online";
        statusText.textContent = "Connected";
      } else {
        statusDot.className = "dot offline";
        statusText.textContent = "Backend Error";
      }
    } catch {
      statusDot.className = "dot offline";
      statusText.textContent = "Server Offline";
    }

    inspectCurrentTab();
  }

  function disableAllButtons(reason) {
    captureBtn.className = "btn btn-primary btn-disabled";
    captureBtn.disabled = true;
    disableQuickCaptureBtn(reason || "Not available on this page");
  }

  function disableQuickCaptureBtn(labelText) {
    quickCaptureBtn.className = "btn btn-secondary btn-disabled";
    quickCaptureBtn.disabled = true;
    if (labelText) quickCaptureBtn.textContent = labelText;
  }

  function resetQuickCaptureBtn() {
    quickCaptureBtn.className = "btn btn-secondary";
    quickCaptureBtn.disabled = false;
    quickCaptureBtn.textContent = "Quick Capture (Manual Review)";
  }

  // ---------------------------------------------------------------------------
  // URL check for multi-item / search pages
  // ---------------------------------------------------------------------------

  function isUncapturableUrl(urlStr) {
    try {
      const u = new URL(urlStr);
      const path = u.pathname;
      const search = u.search;
      const patterns = [
        /^\/search\//,
        /^\/feed\/?$/,
        /^\/notifications\//,
        /^\/jobs\/?$/,
        /^\/jobs\/search\//,
        /^\/jobs\/collections\//,
        /^\/mynetwork\//,
        /^\/messaging\/?$/,
        /^\/?$/,
      ];
      if (path.startsWith("/jobs/") && search.includes("keywords=")) return true;
      return patterns.some((re) => re.test(path));
    } catch {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // Tab inspection
  // ---------------------------------------------------------------------------

  async function inspectCurrentTab() {
    try {
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (!tab || !tab.url) return;

      const url = tab.url;

      if (!url.includes("linkedin.com")) {
        modeBadge.className = "badge-tag badge-unverified";
        modeBadge.textContent = "Not LinkedIn";
        pageTitle.textContent = "LinkedIn Not Detected";
        pageCompany.textContent =
          "Open linkedin.com to capture jobs or posts.";
        verifiedActionArea.style.display = "none";
        disableAllButtons("Not LinkedIn");
        return;
      }

      // -----------------------------------------------------------------------
      // Case 1: Verified Job View (/jobs/view/*)
      // -----------------------------------------------------------------------
      if (url.startsWith("https://www.linkedin.com/jobs/view/")) {
        modeBadge.className = "badge-tag badge-verified";
        modeBadge.textContent = "Verified Job Listing";
        verifiedActionArea.style.display = "block";

        chrome.tabs.sendMessage(
          tab.id,
          { action: "GET_PAGE_STATUS" },
          (response) => {
            if (!chrome.runtime.lastError && response?.jobData) {
              pageTitle.textContent =
                response.jobData.job_title || "LinkedIn Job Posting";
              pageCompany.textContent =
                response.jobData.company_name || "Company detected";
            } else {
              pageTitle.textContent = "LinkedIn Job View";
              pageCompany.textContent = "Ready for verified auto-match";
            }
          }
        );

        enableVerifiedCapture(tab.id);
        enableQuickCapture(tab.id, tab);
        return;
      }

      // -----------------------------------------------------------------------
      // Case 2: Multi-item listing / search page -> Refuse immediately
      // -----------------------------------------------------------------------
      if (isUncapturableUrl(url)) {
        modeBadge.className = "badge-tag badge-unverified";
        modeBadge.textContent = "Listing / Search Page";
        verifiedActionArea.style.display = "none";
        pageTitle.textContent = tab.title
          ? tab.title.slice(0, 50) + (tab.title.length > 50 ? "…" : "")
          : "LinkedIn Search / Listing";
        pageCompany.textContent =
          "Quick Capture not available on multi-item search or listing pages.";
        disableQuickCaptureBtn("Not Available on Listing Pages");
        showPopupError(
          "Quick Capture is disabled on search results and listing pages. Please open an individual post or article to capture."
        );
        return;
      }

      // -----------------------------------------------------------------------
      // Case 3: Arbitrary individual post / article / update page
      // -----------------------------------------------------------------------
      modeBadge.className = "badge-tag badge-unverified";
      verifiedActionArea.style.display = "none";

      chrome.tabs.sendMessage(
        tab.id,
        { action: "GET_QUICK_CAPTURE_PAGE_STATUS" },
        (res) => {
          if (!chrome.runtime.lastError && res?.isUncapturable) {
            modeBadge.textContent = "Listing / Search Page";
            pageTitle.textContent = "LinkedIn Listing";
            pageCompany.textContent =
              "Quick Capture not available on listing pages.";
            disableQuickCaptureBtn("Not Available on Listing Pages");
            showPopupError("Quick Capture is disabled on listing pages.");
          } else {
            modeBadge.textContent = "Unverified Post / Page";
            pageTitle.textContent = tab.title
              ? tab.title.slice(0, 45) + (tab.title.length > 45 ? "…" : "")
              : "LinkedIn Post";
            pageCompany.textContent =
              "Individual post/article • Staged for manual review";
            enableQuickCapture(tab.id, tab);
          }
        }
      );
    } catch (err) {
      console.warn("Popup inspection error:", err);
    }
  }

  // ---------------------------------------------------------------------------
  // Verified Capture
  // ---------------------------------------------------------------------------

  function enableVerifiedCapture(tabId) {
    if (!extensionToken) return;
    captureBtn.className = "btn btn-primary";
    captureBtn.disabled = false;
    captureBtn.onclick = () => {
      captureBtn.disabled = true;
      captureBtn.textContent = "Ingesting...";
      chrome.tabs.sendMessage(tabId, { action: "TRIGGER_CAPTURE" }, () => {
        setTimeout(() => window.close(), 600);
      });
    };
  }

  // ---------------------------------------------------------------------------
  // Quick Capture
  // ---------------------------------------------------------------------------

  function enableQuickCapture(tabId, tab) {
    if (!extensionToken) return;
    resetQuickCaptureBtn();

    quickCaptureBtn.onclick = async () => {
      quickCaptureBtn.disabled = true;
      quickCaptureBtn.textContent = "Extracting content...";

      // 1. Ask content script to extract content. Returns { ok, data } or { ok: false, reason }
      chrome.tabs.sendMessage(
        tabId,
        { action: "EXTRACT_QUICK_CAPTURE_DATA" },
        async (res) => {
          if (chrome.runtime.lastError || !res) {
            resetQuickCaptureBtn();
            showPopupError(
              "Page not accessible. Try refreshing the LinkedIn page and clicking again."
            );
            return;
          }

          // Content script explicitly refused (e.g. uncapturable page or no substantive block)
          if (!res.ok) {
            resetQuickCaptureBtn();
            showPopupError(res.reason || "Couldn't find job content on this page.");
            return;
          }

          const payload = res.data;
          const rawText = (payload?.raw_text || "").trim();
          const pageTitleStr = (payload?.page_title || "").trim();

          // Client-side guard: MUST be >= 50 characters and not equal to title
          if (rawText.length < 50) {
            resetQuickCaptureBtn();
            showPopupError("Extracted text was too short (< 50 characters). Try selecting the text first.");
            return;
          }

          if (rawText.toLowerCase() === pageTitleStr.toLowerCase() || rawText.toLowerCase() === "search | linkedin") {
            resetQuickCaptureBtn();
            showPopupError("Couldn't find job content on this page (only page title found).");
            return;
          }

          quickCaptureBtn.textContent = "Staging for review...";

          try {
            const apiRes = await fetch(
              `${backendUrl}/api/v1/jobs/extension-quick-capture`,
              {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "X-API-Key": extensionToken,
                },
                body: JSON.stringify(payload),
              }
            );

            if (apiRes.ok) {
              quickCaptureBtn.textContent = "✓ Staged for Review!";
              chrome.tabs.sendMessage(tabId, {
                action: "SHOW_QUICK_CAPTURE_TOAST",
                payload: {
                  type: "success",
                  title: "Quick Capture Staged",
                  message:
                    "Staged in Job Agent dashboard. Review and finalize in the manual modal before matching.",
                },
              });
              setTimeout(() => window.close(), 900);
            } else if (apiRes.status === 422) {
              const errJson = await apiRes.json().catch(() => ({}));
              resetQuickCaptureBtn();
              const msg =
                errJson.detail?.[0]?.msg ||
                errJson.detail ||
                "Couldn't find job content on this page.";
              showPopupError(typeof msg === "string" ? msg : JSON.stringify(msg));
            } else if (apiRes.status === 429) {
              resetQuickCaptureBtn();
              showPopupError(
                "Maximum rate limit reached (20 req/min). Please wait a moment."
              );
            } else {
              const errJson = await apiRes.json().catch(() => ({}));
              resetQuickCaptureBtn();
              showPopupError(errJson.detail || "Failed to stage quick capture.");
            }
          } catch (fetchErr) {
            resetQuickCaptureBtn();
            showPopupError("Cannot reach backend. Check your settings.");
          }
        }
      );
    };
  }

  // ---------------------------------------------------------------------------
  // Inline popup error / warning display
  // ---------------------------------------------------------------------------

  function showPopupError(message) {
    let box = document.getElementById("popup-error-box");
    if (!box) {
      box = document.createElement("div");
      box.id = "popup-error-box";
      box.style.cssText =
        "margin:8px 0 0;padding:8px 10px;background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;font-size:11px;color:#b91c1c;line-height:1.5;";
      const area =
        document.getElementById("quickCaptureArea") || document.body;
      area.parentElement
        ? area.parentElement.insertBefore(box, area.nextSibling)
        : document.body.appendChild(box);
    }
    box.textContent = message;
    clearTimeout(box._clearTimer);
    box._clearTimer = setTimeout(() => box.remove(), 7000);
  }
});
