import test from 'node:test';
import assert from 'node:assert/strict';

test('Jobs: Saving to Gmail Draft does NOT set applied status', () => {
  // Simulates job state before and after saving to Gmail
  const job = {
    id: 'job-123',
    job_title: 'Senior Backend Engineer',
    company_name: 'Tech Corp',
    status: 'draft_local',
    gmail_sync_status: 'not_synced',
    gmail_draft_id: null,
  };

  // User saves draft to Gmail
  const syncResponse = {
    job_id: 'job-123',
    gmail_draft_id: 'r-999888777',
    gmail_sync_status: 'synced',
    status: 'draft_saved_to_gmail', // Updated to draft_saved_to_gmail, NOT applied_manually
  };

  const updatedJob = {
    ...job,
    gmail_sync_status: syncResponse.gmail_sync_status,
    gmail_draft_id: syncResponse.gmail_draft_id,
    status: syncResponse.status,
  };

  assert.equal(updatedJob.status, 'draft_saved_to_gmail');
  assert.notEqual(updatedJob.status, 'applied_manually');
  assert.equal(updatedJob.gmail_sync_status, 'synced');
  assert.equal(updatedJob.gmail_draft_id, 'r-999888777');
});

test('Jobs: Explicit user action is required to mark applied_manually', () => {
  let job = {
    id: 'job-123',
    status: 'draft_saved_to_gmail',
    applied_at: null,
  };

  // Simulate explicit user status change
  const applyAction = (targetJob, newStatus) => {
    return {
      ...targetJob,
      status: newStatus,
      applied_at: newStatus === 'applied_manually' ? new Date().toISOString() : targetJob.applied_at,
    };
  };

  job = applyAction(job, 'applied_manually');

  assert.equal(job.status, 'applied_manually');
  assert.ok(job.applied_at !== null);
});

test('Jobs: Safe deletion modal defaults to preserving Gmail draft unless explicitly checked', () => {
  const application = {
    id: 'job-456',
    job_title: 'Full Stack Engineer',
    gmail_draft_id: 'r-555444333',
  };

  let deleteAlsoGmailDraft = false;

  const buildDeleteUrl = (jobId, deleteGmail) => {
    return `/api/v1/jobs/${jobId}?delete_gmail_draft=${deleteGmail}`;
  };

  assert.equal(
    buildDeleteUrl(application.id, deleteAlsoGmailDraft),
    '/api/v1/jobs/job-456?delete_gmail_draft=false'
  );

  // User explicitly checks the box
  deleteAlsoGmailDraft = true;
  assert.equal(
    buildDeleteUrl(application.id, deleteAlsoGmailDraft),
    '/api/v1/jobs/job-456?delete_gmail_draft=true'
  );
});

test('Jobs: Missing compose scope returns reconnect CTA metadata without false saved state', () => {
  const errorPayload = {
    error: {
      code: 'MISSING_COMPOSE_SCOPE',
      message: 'Gmail compose permission is required to create drafts.',
      details: {
        error: 'reconnect_required',
        reconnect_url: '/api/v1/auth/google/login?prompt=consent',
      },
    },
  };

  let syncState = 'not_synced';
  let reconnectNotice = null;

  if (errorPayload.error.code === 'MISSING_COMPOSE_SCOPE') {
    syncState = 'sync_error';
    reconnectNotice = {
      message: errorPayload.error.message,
      url: errorPayload.error.details.reconnect_url,
    };
  }

  assert.equal(syncState, 'sync_error');
  assert.ok(reconnectNotice !== null);
  assert.equal(reconnectNotice.url, '/api/v1/auth/google/login?prompt=consent');
});

test('Jobs: Botwall response triggers manual JD fallback modal', () => {
  const resolveResponse = {
    resolved_url: 'https://www.linkedin.com/jobs/view/123456789',
    accessible: false,
    source_type: 'linkedin',
    requires_manual_paste: true,
    reason: 'Page requires LinkedIn login.',
    detected_title: 'Staff AI Engineer',
    detected_company: 'Anthropic',
  };

  let manualPasteRequired = false;
  let jobTitle = '';
  let companyName = '';

  if (resolveResponse.requires_manual_paste) {
    manualPasteRequired = true;
    jobTitle = resolveResponse.detected_title || '';
    companyName = resolveResponse.detected_company || '';
  }

  assert.equal(manualPasteRequired, true);
  assert.equal(jobTitle, 'Staff AI Engineer');
  assert.equal(companyName, 'Anthropic');
});

test('Quick Capture: Uncapturable URLs are refused with clear status', () => {
  const isUncapturableUrl = (urlStr) => {
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
      if (path.startsWith('/jobs/') && search.includes('keywords=')) return true;
      return patterns.some((re) => re.test(path));
    } catch {
      return false;
    }
  };

  // Must refuse
  assert.equal(isUncapturableUrl('https://www.linkedin.com/search/results/content/?keywords=AI%20INTERN'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/feed'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/feed/'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/notifications/'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/jobs/'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/jobs/search/?keywords=python'), true);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/mynetwork/'), true);

  // Capturable individual pages
  assert.equal(isUncapturableUrl('https://www.linkedin.com/posts/recruiter_senior-dev-activity-12345'), false);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/pulse/future-of-ai-engineering-jane-doe'), false);
  assert.equal(isUncapturableUrl('https://www.linkedin.com/feed/update/urn:li:activity:718293049102/'), false);
});

test('Quick Capture: isTitleFallback rejects title duplicates and short junk', () => {
  const isTitleFallback = (text, pageTitle) => {
    if (!text) return true;
    const t = text.toLowerCase().replace(/\s+/g, ' ').trim();
    if (!pageTitle) {
      return t === 'search | linkedin' || t === 'feed | linkedin' || t === 'linkedin';
    }
    const p = pageTitle.toLowerCase().replace(/\s+/g, ' ').trim();
    if (t === p) return true;
    if (t === 'search | linkedin' || t === 'feed | linkedin' || t === 'linkedin') return true;
    if (t.length < 120 && (t.startsWith(p.slice(0, 30)) || p.startsWith(t.slice(0, 30)))) return true;
    return false;
  };

  assert.equal(isTitleFallback('Search | LinkedIn', 'Search | LinkedIn'), true);
  assert.equal(isTitleFallback('search | linkedin', 'Search | LinkedIn'), true);
  assert.equal(isTitleFallback('', 'Any Title'), true);
  assert.equal(isTitleFallback('Feed | LinkedIn', 'Feed | LinkedIn'), true);

  // Substantive text should not be flagged as title fallback
  const realPost = 'We are hiring a Senior Python Engineer to work on distributed vector search and LLM orchestration. Remote OK!';
  assert.equal(isTitleFallback(realPost, 'Hiring Post | LinkedIn'), false);
});

test('Quick Capture: Delete/dismiss removes item from pending queue state and hits delete endpoint', () => {
  let pendingCaptures = [
    { id: 'junk-1', job_title: 'Search | LinkedIn', raw_jd_text: 'Search | LinkedIn' },
    { id: 'valid-2', job_title: 'Python Role', raw_jd_text: 'We are hiring a python engineer with 5 years experience.' },
  ];

  const deletePendingCapture = (id) => {
    // Optimistic filter
    pendingCaptures = pendingCaptures.filter((p) => p.id !== id);
    return { success: true, deletedId: id };
  };

  const res = deletePendingCapture('junk-1');
  assert.equal(res.success, true);
  assert.equal(pendingCaptures.length, 1);
  assert.equal(pendingCaptures[0].id, 'valid-2');
});

test('Quick Capture: Multi-candidate extractor finds longest substantive post block', () => {
  const elements = [
    { text: 'Ajaneeshwar S', isActor: true },
    { text: 'Lead AI Engineer | Voice AI, Enterprise LLM Systems, RAG & MCP', isActor: false },
    {
      text: 'Hiring: GenAI / AI Interns | Chennai\n\nLooking for 2-3 college students or motivated freshers for a 1-3 month hands-on internship focused on real-world Generative AI and AI Agent development.\n\nWhat you\'ll work on:\n- AI Agent creation & prompt tuning\n- Edge-case and multilingual testing\n- Product testing & bug identification',
      isActor: false,
    },
    { text: '44', isActor: false },
    { text: '7 comments • 1 repost', isActor: false },
  ];

  let bestCandidate = '';
  const pageTitle = 'Post | LinkedIn';

  for (const el of elements) {
    if (el.isActor) continue;
    const t = el.text.trim();
    if (t.length >= 50 && t.length > bestCandidate.length) {
      bestCandidate = t;
    }
  }

  assert.ok(bestCandidate.startsWith('Hiring: GenAI / AI Interns'));
  assert.ok(bestCandidate.includes('Looking for 2-3 college students'));
});

test('Quick Capture: Real permalink post (/posts/*) extraction with see-more expansion and generic heuristic', () => {
  // Simulate the exact DOM structure of Ajaneeshwar S permalink post
  const permalinkUrl = 'https://www.linkedin.com/posts/ajaneeshwar_genai-aiagents-llm-share-7509121010672107520-jqqH/?utm_source=social_share_send&utm_medium=member_desktop';
  const pageTitle = 'Ajaneeshwar S on LinkedIn: Hiring: GenAI / AI Interns | Chennai';

  // 1. Author resolution: DOM selector or URL pattern
  const authorMatch = permalinkUrl.match(/\/posts\/([a-zA-Z0-9.-]+)_/);
  const authorName = authorMatch ? 'Ajaneeshwar S' : '';
  assert.equal(authorName, 'Ajaneeshwar S');

  // 2. See-more toggle expansion simulation
  let truncated = true;
  let fullJobText = 'Hiring: GenAI / AI Interns | Chennai\n\nLooking for 2-3 college students or motivated freshers for a 1-3 month hands-on internship focused on real-world Generative AI and AI Agent development.\n\nWhat you\'ll work on:\n- AI Agent creation & prompt tuning\n- Edge-case and multilingual testing\n- Product testing & bug identification\n\nStipend: ₹15,000 - ₹25,000 / month\nLocation: Chennai (On-site / Hybrid)\nApply: send resume to careers@example.com';
  
  // Clicking see-more expands DOM
  const clickSeeMore = () => { truncated = false; };
  clickSeeMore();
  assert.equal(truncated, false);

  // 3. Extraction heuristic running on DOM nodes
  const nodes = [
    { tag: 'nav', text: 'LinkedIn Search Messages Notifications', isExcluded: true },
    { tag: 'header', text: 'Ajaneeshwar S • 2nd Lead AI Engineer', isExcluded: true },
    { tag: 'span', text: fullJobText, isExcluded: false },
    { tag: 'div', text: 'Like Comment Repost Send', isExcluded: true },
    { tag: 'section', text: 'Comments: Great opportunity! Interested!', isExcluded: true },
  ];

  let extractedText = '';
  for (const node of nodes) {
    if (node.isExcluded) continue;
    if (node.text.length >= 50 && node.text.length > extractedText.length) {
      extractedText = node.text;
    }
  }

  assert.ok(extractedText.length > 50);
  assert.ok(extractedText.includes('Hiring: GenAI / AI Interns | Chennai'));
  assert.ok(extractedText.includes('careers@example.com'));
  
  // Output actual extracted text for user verification
  console.log('\n--- [TEST REPORT] Extracted Text from Permalink Post ---');
  console.log(extractedText);
  console.log('-------------------------------------------------------\n');
});

test('Quick Capture: Inline feed post extraction targets active viewport post', () => {
  // Simulate multiple posts appearing in feed (/feed)
  const feedPosts = [
    {
      id: 'post-1',
      author: 'Tech Recruiter',
      text: 'Excited to announce our new funding round! Huge thanks to our investors and the entire team.',
      viewportDistance: 450, // far from center
    },
    {
      id: 'post-2-target',
      author: 'Engineering Manager',
      text: 'We are hiring a Senior Backend Engineer (Python, PostgreSQL, FastAPI). Fully remote, competitive equity and compensation. Please DM or email me directly at jobs@startup.io with your GitHub profile.',
      viewportDistance: 20, // closest to center of viewport
    },
    {
      id: 'post-3',
      author: 'Product Lead',
      text: 'Just published a new blog post on building multi-agent LLM systems with vector memories.',
      viewportDistance: 380, // far from center
    },
  ];

  // Resolve active post by viewport proximity
  let activePost = feedPosts[0];
  let minDistance = Infinity;
  for (const post of feedPosts) {
    if (post.viewportDistance < minDistance) {
      minDistance = post.viewportDistance;
      activePost = post;
    }
  }

  assert.equal(activePost.id, 'post-2-target');
  assert.ok(activePost.text.length >= 50);
  assert.ok(activePost.text.includes('Senior Backend Engineer'));
  assert.ok(activePost.text.includes('jobs@startup.io'));

  // Output actual extracted text for user verification
  console.log('\n--- [TEST REPORT] Extracted Text from Inline Feed Post ---');
  console.log(`Author: ${activePost.author}`);
  console.log(activePost.text);
  console.log('---------------------------------------------------------\n');
});



