/**
 * Personal AI Assistant - LinkedIn Job & Quick Capture Content Script
 * Runs across linkedin.com to support:
 * 1. Verified Job Capture on /jobs/view/* (auto-match with resume)
 * 2. Quick Capture on individual posts, articles, and updates (staged for manual review)
 *
 * STRICT SECURITY CONSTRAINTS:
 * - Extracts only visible DOM content or user selection.
 * - Never accesses cookies, credentials, session tokens, or private user data.
 * - Refuses to capture on multi-item listing/search pages.
 * - Refuses if substantive content (>= 50 chars) is not found, never falling back to document.title.
 */

(function () {
  "use strict";

  const BUTTON_ID = "ai-job-agent-capture-btn";
  const CONTAINER_CLASS = "ai-job-agent-btn-container";
  const TOAST_ID = "ai-job-agent-toast-container";
  const MIN_CONTENT_LENGTH = 50;

  // ---------------------------------------------------------------------------
  // Page classification
  // ---------------------------------------------------------------------------

  function isJobViewPage() {
    return window.location.pathname.startsWith("/jobs/view/");
  }

  function isUncapturablePage() {
    const path = window.location.pathname;
    const search = window.location.search;

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
  }

  // ---------------------------------------------------------------------------
  // Helper functions
  // ---------------------------------------------------------------------------

  function getCleanText(selector) {
    const el = document.querySelector(selector);
    if (!el) return "";
    return el.innerText ? el.innerText.trim() : el.textContent.trim();
  }

  function isTitleFallback(text, pageTitle) {
    if (!text) return true;
    const t = text.toLowerCase().replace(/\s+/g, " ").trim();
    const junkTitles = [
      "search | linkedin",
      "feed | linkedin",
      "linkedin",
      "notifications | linkedin",
      "jobs | linkedin",
      "my network | linkedin",
      "messaging | linkedin",
    ];
    if (junkTitles.includes(t)) return true;
    if (!pageTitle) return false;
    const p = pageTitle.toLowerCase().replace(/\s+/g, " ").trim();
    if (t === p) return true;
    if (Math.abs(t.length - p.length) < 15 && (t.startsWith(p) || p.startsWith(t))) return true;
    return false;
  }

  function detectAuthor() {
    const selectors = [
      ".update-components-actor__name span[dir='ltr']",
      ".update-components-actor__name",
      ".feed-shared-actor__name span[dir='ltr']",
      ".feed-shared-actor__name",
      ".feed-shared-actor__title",
      "a[href*='/in/'] .update-components-actor__name",
      "a[href*='/in/'] span[dir='ltr']",
      ".article-main__author",
      ".reader-author-info__title",
      "h1.feed-shared-actor__name",
      "h2.feed-shared-actor__name",
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const name = (el.innerText || el.textContent || "").split("\n")[0].trim();
        if (name && name.length > 1 && name.length < 100) return name;
      }
    }
    const meta = document.querySelector("meta[name='author']");
    if (meta) return meta.getAttribute("content") || "";

    // Fallback: extract username from URL on /posts/<username>_<slug>-activity-<id>
    const match = window.location.pathname.match(/\/posts\/([a-zA-Z0-9.-]+)_/);
    if (match && match[1]) {
      const rawUser = match[1].replace(/[-.]/g, " ");
      return rawUser.charAt(0).toUpperCase() + rawUser.slice(1);
    }

    return "";
  }

  // ---------------------------------------------------------------------------
  // Verified Job View Extraction (/jobs/view/*)
  // ---------------------------------------------------------------------------

  function extractJobData() {
    if (!isJobViewPage()) return null;

    const titleSelectors = [
      ".job-details-jobs-unified-top-card__job-title h1",
      ".job-details-jobs-unified-top-card__job-title",
      ".jobs-unified-top-card__job-title",
      "h1.t-24",
      "h1.job-title",
      ".jobs-details__main-content h1",
      ".jobs-search__job-details--container h1",
    ];
    let jobTitle = "";
    for (const sel of titleSelectors) {
      jobTitle = getCleanText(sel);
      if (jobTitle) break;
    }

    const companySelectors = [
      ".job-details-jobs-unified-top-card__company-name a",
      ".job-details-jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__company-name a",
      ".jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__subtitle-primary-grouping a",
      "a[href*='/company/']",
    ];
    let companyName = "";
    for (const sel of companySelectors) {
      companyName = getCleanText(sel);
      if (companyName) break;
    }

    const locationSelectors = [
      ".job-details-jobs-unified-top-card__primary-description-container",
      ".jobs-unified-top-card__bullet",
      ".jobs-unified-top-card__primary-description",
      ".jobs-unified-top-card__workplace-type",
    ];
    let location = "";
    for (const sel of locationSelectors) {
      location = getCleanText(sel);
      if (location) break;
    }

    const jdSelectors = [
      "#job-details",
      ".jobs-description__content",
      ".jobs-box__html-content",
      ".jobs-description",
      ".jobs-details__main-content",
    ];
    let rawJdText = "";
    for (const sel of jdSelectors) {
      rawJdText = getCleanText(sel);
      if (rawJdText && rawJdText.length >= 20) break;
    }

    const canonicalLink = document.querySelector("link[rel='canonical']");
    const jobUrl = canonicalLink && canonicalLink.href ? canonicalLink.href : window.location.href.split("?")[0];

    return {
      job_url: jobUrl,
      job_title: jobTitle || null,
      company_name: companyName || null,
      location: location || null,
      raw_jd_text: rawJdText || "",
      metadata: {
        page_title: document.title,
        captured_at: new Date().toISOString(),
      },
    };
  }

  // ---------------------------------------------------------------------------
  // Quick Capture Content Extraction (Posts, Articles, Updates)
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Text Sanitization (Safety net: strips comments, sidebars, footers)
  // ---------------------------------------------------------------------------

  function sanitizeExtractedPostText(raw) {
    if (!raw) return "";
    let clean = raw.trim();

    // 1. Strip trailing footer navigation links & corporate copyright
    clean = clean.replace(/\n\s*About\s*\n\s*Accessibility[\s\S]*$/i, "");
    clean = clean.replace(/\n\s*LinkedIn Corporation\s*©[\s\S]*$/i, "");

    // 2. Strip comment section, reaction counts, and reply threads
    const commentMarkers = [
      /\n\s*Most relevant\b[\s\S]*$/i,
      /\n\s*All comments\b[\s\S]*$/i,
      /\n\s*Top comments\b[\s\S]*$/i,
      /\n\s*Add a comment[\s\S]*$/i,
      /\n\s*\d+\s+reactions\b[\s\S]*$/i,
      /\n\s*\d+\s+comments\b[\s\S]*$/i,
      /\n\s*(?:Like\s*\n+\s*Comment\s*\n+\s*Repost\s*\n+\s*Send)[\s\S]*$/i,
      /\n\s*Reaction button state:[\s\S]*$/i,
    ];
    for (const marker of commentMarkers) {
      clean = clean.replace(marker, "").trim();
    }

    // 3. Strip leading profile sidebar / actor metadata if inadvertently captured
    if (/(?:Profile viewers|Post impressions)/i.test(clean)) {
      clean = clean.replace(/^[\s\S]*?\n\s*Follow\s*\n+/i, "").trim();
    } else {
      clean = clean.replace(/^[\s\S]*?\n\s*Follow\s*\n+/i, "").trim();
    }

    return clean;
  }

  // ---------------------------------------------------------------------------
  // Quick Capture Content Extraction (Posts, Articles, Updates)
  // ---------------------------------------------------------------------------

  function extractQuickCaptureContent() {
    const pageUrl = window.location.href;
    const pageTitle = document.title || "";
    const path = window.location.pathname;

    // 0. Bail immediately on multi-item listing or search pages
    if (isUncapturablePage()) {
      const refusalMsg = "Quick Capture not available on search or listing pages. Open a specific post or article.";
      showToast({
        title: "Quick Capture Unavailable",
        message: refusalMsg,
        type: "error",
      });
      return {
        ok: false,
        reason: refusalMsg,
      };
    }

    // 1. User text selection (highest priority if substantive)
    let selectedText = "";
    if (window.getSelection) {
      selectedText = window.getSelection().toString().trim();
    }

    if (selectedText.length >= MIN_CONTENT_LENGTH && !isTitleFallback(selectedText, pageTitle)) {
      const sanitizedSelection = sanitizeExtractedPostText(selectedText);
      if (sanitizedSelection.length >= MIN_CONTENT_LENGTH) {
        return {
          ok: true,
          data: {
            page_url: pageUrl,
            page_title: pageTitle,
            author_name: detectAuthor() || undefined,
            raw_text: sanitizedSelection.slice(0, 8000),
            metadata: {
              is_selection: true,
              extraction_mode: "user_selection",
              captured_at: new Date().toISOString(),
            },
          },
        };
      }
    }

    // 2. Identify the active single post container specifically (NEVER whole main layout or page body)
    const postSelectors = [
      "div.feed-shared-update-v2",
      "div[data-urn*='activity']",
      "div[data-urn*='ugcPost']",
      "div[data-view-name*='feed-update']",
      "article.feed-shared-update-v2",
      "article",
    ];

    let activeContainer = null;
    const allPosts = Array.from(document.querySelectorAll(postSelectors.join(", ")));

    if (allPosts.length === 1) {
      activeContainer = allPosts[0];
    } else if (allPosts.length > 1) {
      // Multiple posts (feed): find post closest to viewport center
      const viewportCenterY = window.innerHeight / 2;
      let minDistance = Infinity;
      for (const card of allPosts) {
        const rect = card.getBoundingClientRect();
        if (rect.height < 50) continue;
        if (rect.top <= viewportCenterY && rect.bottom >= viewportCenterY) {
          activeContainer = card;
          break;
        }
        const cardCenterY = rect.top + rect.height / 2;
        const dist = Math.abs(cardCenterY - viewportCenterY);
        if (dist < minDistance) {
          minDistance = dist;
          activeContainer = card;
        }
      }
    }

    if (!activeContainer) {
      activeContainer =
        document.querySelector(".core-rail") ||
        document.querySelector("main") ||
        document.querySelector(".scaffold-layout__main");
    }

    if (!activeContainer) {
      activeContainer = document.body;
    }

    // 3. Check for and click any "...see more" / "see more" truncation toggle within the container
    try {
      const seeMoreSelectors = [
        "button.feed-shared-inline-show-more-text__button",
        "button.feed-shared-inline-show-more-text__see-more-less-toggle",
        "button[id*='line-clamp-show-more-button']",
        "button[aria-label*='see more' i]",
        "button[aria-label*='more' i]",
        ".feed-shared-inline-show-more-text button",
        "button.see-more",
      ];
      for (const sel of seeMoreSelectors) {
        const buttons = activeContainer.querySelectorAll(sel);
        buttons.forEach((btn) => {
          if (
            btn &&
            typeof btn.click === "function" &&
            !btn.closest("nav") &&
            !btn.closest("header") &&
            !btn.closest(".comments-comments-list")
          ) {
            btn.click();
          }
        });
      }
    } catch (_) {}

    // 4. PRIORITY: Directly query the post commentary block inside the active container
    // This isolates the post body from comments, sidebars, and reaction bars upfront.
    const commentarySelectors = [
      ".feed-shared-update-v2__commentary",
      ".update-components-update-v2__commentary",
      ".update-components-text",
      ".feed-shared-inline-show-more-text",
      ".attributed-text-segment-list__content",
      "div[data-ad-preview='message']",
      ".feed-shared-text-view",
      ".reader-article-content",
      ".article-main__body",
    ];

    for (const sel of commentarySelectors) {
      try {
        const elements = activeContainer.querySelectorAll(sel);
        for (const el of elements) {
          if (
            el.closest(".comments-comments-list") ||
            el.closest(".comments-comment-box") ||
            el.closest("aside") ||
            el.closest("footer") ||
            el.closest("nav")
          ) {
            continue;
          }

          const raw = (el.innerText || el.textContent || "").trim();
          const clean = sanitizeExtractedPostText(raw);
          if (clean.length >= MIN_CONTENT_LENGTH && !isTitleFallback(clean, pageTitle)) {
            return {
              ok: true,
              data: {
                page_url: pageUrl,
                page_title: pageTitle,
                author_name: detectAuthor() || undefined,
                raw_text: clean.slice(0, 8000),
                metadata: {
                  is_selection: false,
                  extraction_mode: "post_commentary_block",
                  captured_at: new Date().toISOString(),
                },
              },
            };
          }
        }
      } catch (_) {}
    }

    // 5. Try existing targeted selector list
    const candidateSelectors = [
      "span.break-words",
      ".feed-shared-update-v2__description .feed-shared-text",
      ".feed-shared-update-v2__description",
      ".feed-shared-text",
      "[data-view-name='feed-update'] .break-words",
      "div[data-urn*='activity'] .break-words",
      "div[data-urn*='ugcPost'] .break-words",
    ];

    let bestCandidateText = "";

    for (const sel of candidateSelectors) {
      try {
        const elements = activeContainer.querySelectorAll(sel);
        for (const el of elements) {
          if (
            el.closest(".comments-comments-list") ||
            el.closest(".comments-comment-box") ||
            el.closest(".feed-shared-social-actions") ||
            el.closest(".feed-shared-social-action-bar") ||
            el.closest(".feed-shared-actor") ||
            el.closest("header") ||
            el.closest("nav") ||
            el.closest("aside") ||
            el.closest("footer")
          ) {
            continue;
          }

          const raw = (el.innerText || el.textContent || "").trim();
          const clean = sanitizeExtractedPostText(raw);
          if (
            clean.length >= MIN_CONTENT_LENGTH &&
            !isTitleFallback(clean, pageTitle) &&
            clean.length > bestCandidateText.length
          ) {
            bestCandidateText = clean;
          }
        }
      } catch (_) {}
    }

    if (bestCandidateText.length >= MIN_CONTENT_LENGTH) {
      return {
        ok: true,
        data: {
          page_url: pageUrl,
          page_title: pageTitle,
          author_name: detectAuthor() || undefined,
          raw_text: bestCandidateText.slice(0, 8000),
          metadata: {
            is_selection: false,
            extraction_mode: "targeted_selectors",
            captured_at: new Date().toISOString(),
          },
        },
      };
    }

    // 6. Generic Fallback Heuristic with Strict Exclusion & No Excluded Descendants
    const excludedTags = [
      "nav",
      "header",
      "footer",
      "aside",
      "form",
      "button",
      ".global-nav",
      ".global-footer",
      ".scaffold-layout__footer",
      ".scaffold-layout__aside",
      ".scaffold-layout__sidebar",
      ".scaffold-layout__rail",
      ".feed-identity-module",
      ".feed-identity-module__actor-meta",
      "[data-view-name*='profile-card']",
      ".identity-headline",
      ".feed-shared-social-actions",
      ".feed-shared-social-action-bar",
      ".social-details-social-counts",
      ".feed-shared-social-counts",
      ".comments-comments-list",
      ".comments-comment-box",
      ".comments-comment-item",
      ".feed-shared-comments-list",
      "section.comments",
      "div[id*='comments']",
      ".comments-reply-item",
      ".comments-comment-entity",
      ".comments-sort-order-toggle",
      ".comments-comments-list__header",
      ".feed-shared-actor",
      ".update-components-actor",
      ".share-box",
      ".feed-shared-share-box",
    ];

    function isExcluded(el) {
      for (const sel of excludedTags) {
        if (el.matches && el.matches(sel)) return true;
        if (el.closest && el.closest(sel)) return true;
      }
      return false;
    }

    function containsExcludedDescendants(el) {
      for (const sel of excludedTags) {
        if (el.querySelector && el.querySelector(sel)) return true;
      }
      return false;
    }

    const genericCandidates = activeContainer.querySelectorAll("div, article, section, p, span");
    let fallbackText = "";

    for (const el of genericCandidates) {
      if (isExcluded(el)) continue;
      // CRITICAL: Disqualify outer wrapper containers that bundle comments or sidebars
      if (containsExcludedDescendants(el)) continue;

      if (el.offsetParent === null && el.offsetWidth === 0 && el.offsetHeight === 0) {
        continue;
      }

      const raw = (el.innerText || el.textContent || "").trim();
      const clean = sanitizeExtractedPostText(raw);
      if (clean.length < MIN_CONTENT_LENGTH) continue;
      if (isTitleFallback(clean, pageTitle)) continue;

      if (clean.length > fallbackText.length) {
        const hasChildWithSameText = Array.from(el.children).some((c) => {
          if (isExcluded(c) || containsExcludedDescendants(c)) return false;
          const ct = sanitizeExtractedPostText((c.innerText || c.textContent || "").trim());
          return ct === clean || (ct.length >= MIN_CONTENT_LENGTH && clean.length - ct.length < 15);
        });

        if (!hasChildWithSameText) {
          fallbackText = clean;
        }
      }
    }

    // Final safety checks: >= 50 chars AND not title fallback
    if (fallbackText.length >= MIN_CONTENT_LENGTH && !isTitleFallback(fallbackText, pageTitle)) {
      return {
        ok: true,
        data: {
          page_url: pageUrl,
          page_title: pageTitle,
          author_name: detectAuthor() || undefined,
          raw_text: fallbackText.slice(0, 8000),
          metadata: {
            is_selection: false,
            extraction_mode: "generic_heuristic",
            captured_at: new Date().toISOString(),
          },
        },
      };
    }

    // 7. No substantive content block found -> refuse to submit, show inline toast
    const errorMsg = "Couldn't find job content on this page. Try selecting the post text first, or open the individual post.";
    showToast({
      title: "Content Not Found",
      message: errorMsg,
      type: "error",
      duration: 6000,
    });

    return {
      ok: false,
      reason: errorMsg,
    };
  }

  // ---------------------------------------------------------------------------
  // Rich Toast Notifications
  // ---------------------------------------------------------------------------

  function showToast({ title, message, type = "info", linkUrl = null, linkText = "Open in Job Agent", duration = 6000 }) {
    let existing = document.getElementById(TOAST_ID);
    if (existing) {
      existing.remove();
    }

    const toast = document.createElement("div");
    toast.id = TOAST_ID;
    toast.className = "ai-job-agent-toast";

    const titleClass = type === "success" ? "success" : type === "error" ? "error" : "info";
    const icon = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";

    let actionsHtml = "";
    if (linkUrl) {
      actionsHtml = `
        <div class="ai-toast-actions">
          <a href="${linkUrl}" target="_blank" rel="noopener noreferrer" class="ai-toast-link">${linkText} →</a>
        </div>
      `;
    }

    toast.innerHTML = `
      <div class="ai-toast-header">
        <span class="ai-toast-title ${titleClass}">${icon} ${title}</span>
        <button class="ai-toast-close" title="Close">×</button>
      </div>
      <div class="ai-toast-body">${message}</div>
      ${actionsHtml}
    `;

    document.body.appendChild(toast);

    toast.querySelector(".ai-toast-close").addEventListener("click", () => {
      toast.remove();
    });

    if (duration > 0) {
      setTimeout(() => {
        if (toast.parentNode) {
          toast.style.opacity = "0";
          toast.style.transform = "translateY(10px)";
          setTimeout(() => toast.remove(), 300);
        }
      }, duration);
    }
  }

  // ---------------------------------------------------------------------------
  // Verified Ingestion (/jobs/view/*)
  // ---------------------------------------------------------------------------

  async function sendJobToAssistant(buttonEl) {
    if (!isJobViewPage()) {
      showToast({
        title: "Wrong Page",
        message: "Please open an individual LinkedIn job view page (https://www.linkedin.com/jobs/view/...).",
        type: "error",
      });
      return;
    }

    const jobData = extractJobData();
    if (!jobData || !jobData.raw_jd_text || jobData.raw_jd_text.length < 20) {
      showToast({
        title: "Could Not Extract JD",
        message: "The job description is still loading or could not be found. Please wait a second and try again.",
        type: "error",
      });
      return;
    }

    chrome.storage.sync.get(["backendUrl", "extensionToken", "frontendUrl"], async (stored) => {
      const backendUrl = (stored.backendUrl || "http://localhost:8000").replace(/\/+$/, "");
      const frontendUrl = (stored.frontendUrl || "http://localhost:5173").replace(/\/+$/, "");
      const extensionToken = (stored.extensionToken || "").trim();

      if (!extensionToken) {
        showToast({
          title: "Extension Token Required",
          message: "Please configure your Extension Token in the extension options or Assistant Settings before capturing jobs.",
          type: "error",
          linkUrl: `${frontendUrl}/settings`,
          linkText: "Configure in Settings",
          duration: 10000,
        });
        return;
      }

      if (buttonEl) {
        buttonEl.classList.add("ai-loading");
        buttonEl.innerHTML = `
          <svg class="ai-job-agent-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-opacity="0.25"></circle>
            <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor"></path>
          </svg>
          Ingesting...
        `;
      }

      try {
        const response = await fetch(`${backendUrl}/api/v1/jobs/extension-ingest`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${extensionToken}`,
            "X-API-Key": extensionToken,
          },
          body: JSON.stringify(jobData),
        });

        const data = await response.json();

        if (response.ok) {
          if (buttonEl) {
            buttonEl.classList.remove("ai-loading");
            buttonEl.classList.add(data.is_duplicate ? "ai-duplicate" : "ai-success");
            buttonEl.innerHTML = `
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg>
              ${data.is_duplicate ? "Updated in Agent" : "Saved to Agent"}
            `;
          }

          let toastMsg = data.message;
          if (data.match_analysis && data.match_analysis.evidence_coverage_percentage !== undefined) {
            toastMsg += `<br><span class="ai-toast-match-badge">🎯 ${data.match_analysis.evidence_coverage_percentage}% Resume Match</span>`;
          }

          showToast({
            title: data.is_duplicate ? "Job Updated" : "Job Ingested Successfully",
            message: toastMsg,
            type: "success",
            linkUrl: `${frontendUrl}/jobs`,
            linkText: "View in Job Agent",
            duration: 8000,
          });
        } else if (response.status === 429) {
          if (buttonEl) resetBtn(buttonEl);
          showToast({
            title: "Rate Limit Exceeded",
            message: "You have reached the maximum rate limit (20 captures/min). Please wait a moment before trying again.",
            type: "error",
          });
        } else if (response.status === 401) {
          if (buttonEl) resetBtn(buttonEl);
          showToast({
            title: "Authentication Failed",
            message: "Your Extension Token is invalid or has been revoked. Please update it in Assistant Settings.",
            type: "error",
            linkUrl: `${frontendUrl}/settings`,
            linkText: "Open Settings",
          });
        } else {
          if (buttonEl) resetBtn(buttonEl);
          const detail = data.detail || (data.message ? data.message : "Server error occurred.");
          showToast({
            title: "Ingestion Failed",
            message: typeof detail === "string" ? detail : JSON.stringify(detail),
            type: "error",
          });
        }
      } catch (err) {
        if (buttonEl) resetBtn(buttonEl);
        showToast({
          title: "Connection Error",
          message: `Could not connect to backend at ${backendUrl}. Ensure the Assistant server is running.`,
          type: "error",
        });
      }
    });
  }

  function resetBtn(buttonEl) {
    buttonEl.classList.remove("ai-loading", "ai-success", "ai-duplicate");
    buttonEl.innerHTML = `
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path d="M10 2a8 8 0 100 16 8 8 0 000-16zm1 11H9v-2h2v2zm0-4H9V5h2v4z"/>
      </svg>
      Send to Job Agent
    `;
  }

  // ---------------------------------------------------------------------------
  // Button Injection on /jobs/view/*
  // ---------------------------------------------------------------------------

  function injectButton() {
    if (!isJobViewPage()) return;
    if (document.getElementById(BUTTON_ID)) return;

    const targetSelectors = [
      ".jobs-apply-button--top-card",
      ".jobs-s-apply",
      ".jobs-unified-top-card__content--two-pane .display-flex",
      ".job-details-jobs-unified-top-card__container--two-pane .display-flex",
      ".jobs-unified-top-card .display-flex.align-items-center",
      ".jobs-details__main-content .display-flex",
    ];

    let targetEl = null;
    for (const sel of targetSelectors) {
      const el = document.querySelector(sel);
      if (el && el.parentElement) {
        targetEl = el.parentElement;
        break;
      }
    }

    if (!targetEl) {
      const saveBtn = document.querySelector(".jobs-save-button, button[data-control-name='save_job']");
      if (saveBtn && saveBtn.parentElement) {
        targetEl = saveBtn.parentElement;
      }
    }

    if (!targetEl) return;

    const container = document.createElement("div");
    container.className = CONTAINER_CLASS;

    const btn = document.createElement("button");
    btn.id = BUTTON_ID;
    btn.type = "button";
    btn.className = "ai-job-agent-btn";
    btn.innerHTML = `
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z" clip-rule="evenodd" />
      </svg>
      Send to Job Agent
    `;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      sendJobToAssistant(btn);
    });

    container.appendChild(btn);
    targetEl.appendChild(container);
  }

  // ---------------------------------------------------------------------------
  // Message Listener
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "GET_PAGE_STATUS") {
      sendResponse({
        isJobView: isJobViewPage(),
        isUncapturable: isUncapturablePage(),
        jobData: isJobViewPage() ? extractJobData() : null,
      });
      return true;
    } else if (request.action === "GET_QUICK_CAPTURE_PAGE_STATUS") {
      sendResponse({
        isUncapturable: isUncapturablePage(),
      });
      return true;
    } else if (request.action === "TRIGGER_CAPTURE") {
      const btn = document.getElementById(BUTTON_ID);
      sendJobToAssistant(btn);
      sendResponse({ success: true });
      return true;
    } else if (request.action === "EXTRACT_QUICK_CAPTURE_DATA") {
      const result = extractQuickCaptureContent();
      sendResponse(result);
      return true;
    } else if (request.action === "SHOW_QUICK_CAPTURE_TOAST") {
      showToast(request.payload || {});
      sendResponse({ success: true });
      return true;
    }
  });

  // Observe DOM for dynamic page navigation
  const observer = new MutationObserver(() => {
    if (isJobViewPage()) {
      injectButton();
    }
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (isJobViewPage()) injectButton();
    });
  } else {
    if (isJobViewPage()) injectButton();
  }
})();
