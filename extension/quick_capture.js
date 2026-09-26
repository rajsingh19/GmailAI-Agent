/**
 * Quick Capture Content Script for arbitrary LinkedIn pages (posts, feed, articles).
 * Extracts raw visible text without auto-parsing or auto-matching.
 *
 * STRICT SECURITY CONSTRAINTS:
 * - Never reads cookies, credentials, or localStorage.
 * - Captures only visible DOM text or user selection.
 *
 * EXTRACTION RULES (v2):
 * - Must find a substantive content block (>= 50 chars) in a recognised container.
 * - NEVER falls back to document.title or full body scrape as a capture payload.
 * - Refuses immediately on multi-item listing/search pages.
 * - Returns { ok: false, reason: '...' } when content cannot be found and displays inline toast.
 */

(function () {
  if (window.__jobAgentQuickCaptureLoaded) return;
  window.__jobAgentQuickCaptureLoaded = true;

  const MIN_CONTENT_LENGTH = 50;

  // ---------------------------------------------------------------------------
  // Page-type classification
  // ---------------------------------------------------------------------------

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
  // Content extraction
  // ---------------------------------------------------------------------------

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

  function extractPageContent() {
    const pageUrl = window.location.href;
    const pageTitle = document.title || "";
    const path = window.location.pathname;

    // 0. Bail immediately on known uncapturable pages
    if (isUncapturablePage()) {
      const refusalMsg = "Quick Capture not available on search or listing pages. Open a specific post or article.";
      showQuickCaptureToast({
        title: "Quick Capture Unavailable",
        message: refusalMsg,
        type: "error",
      });
      return {
        ok: false,
        reason: refusalMsg,
      };
    }

    // 1. User text selection (highest priority)
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
      // Disqualify outer wrapper containers that bundle comments or sidebars
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

    // 6. No substantive block found -> hard refusal (no body fallback)
    const errorMsg = "Couldn't find job content on this page. Try selecting the post text first, or open the individual post.";
    showQuickCaptureToast({
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
  // Toast
  // ---------------------------------------------------------------------------

  function showQuickCaptureToast(options) {
    const existing = document.getElementById("job-agent-quick-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "job-agent-quick-toast";
    toast.className = `job-agent-toast ${options.type || "success"}`;

    const icon = options.type === "error" ? "⚠️" : options.type === "warn" ? "⚠️" : "📝";
    toast.innerHTML = `
      <div class="job-agent-toast-content">
        <span class="job-agent-toast-icon">${icon}</span>
        <div>
          <div class="job-agent-toast-title">${options.title || "Quick Capture"}</div>
          <div class="job-agent-toast-msg">${
            options.message || "Captured for manual review in your Job Agent dashboard."
          }</div>
        </div>
      </div>
    `;

    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("visible"));

    setTimeout(() => {
      toast.classList.remove("visible");
      setTimeout(() => toast.remove(), 400);
    }, options.duration || 5500);
  }

  // ---------------------------------------------------------------------------
  // Message listener
  // ---------------------------------------------------------------------------

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "EXTRACT_QUICK_CAPTURE_DATA") {
      const result = extractPageContent();
      sendResponse(result);
      return true;
    } else if (request.action === "SHOW_QUICK_CAPTURE_TOAST") {
      showQuickCaptureToast(request.payload || {});
      sendResponse({ success: true });
      return true;
    } else if (request.action === "GET_QUICK_CAPTURE_PAGE_STATUS") {
      sendResponse({ isUncapturable: isUncapturablePage() });
      return true;
    }
  });
})();
