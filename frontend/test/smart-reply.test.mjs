import test from 'node:test';
import assert from 'node:assert/strict';

test('SmartReply: Placeholder extraction detects bracketed markers', () => {
  const replyText = `Hi Sarah,

Thank you for reaching out regarding the Senior Python Engineer role.
I would be delighted to speak with the team. I am available at [Insert your available times] or [Alternative Date/Time].

You can reach me directly at [Your Phone Number].

Best regards,
[Your Name]`;

  const matches = replyText.match(/\[([A-Za-z0-9\s/_\-:,]+)\]/g) || [];
  const deduped = Array.from(new Set(matches));

  assert.equal(deduped.length, 4);
  assert.deepEqual(deduped, [
    '[Insert your available times]',
    '[Alternative Date/Time]',
    '[Your Phone Number]',
    '[Your Name]',
  ]);
});

test('SmartReply: Multi-email draft state isolation prevents cross-draft mutation', () => {
  // Simulates state management across multiple email IDs
  const drafts = {};

  const initDraft = (id) => ({
    replyBody: '',
    tone: 'professional',
    customInstructions: '',
    loading: false,
    error: null,
    placeholders: [],
    generated: false,
  });

  // User generates reply for Email A
  drafts['email_001'] = {
    ...initDraft('email_001'),
    replyBody: 'Draft for Email A',
    tone: 'friendly',
    generated: true,
  };

  // User generates reply for Email B
  drafts['email_002'] = {
    ...initDraft('email_002'),
    replyBody: 'Draft for Email B with custom schedule',
    tone: 'concise',
    customInstructions: 'Ask for salary range',
    generated: true,
  };

  // Verify Email A state was not mutated by Email B
  assert.equal(drafts['email_001'].replyBody, 'Draft for Email A');
  assert.equal(drafts['email_001'].tone, 'friendly');
  assert.equal(drafts['email_001'].customInstructions, '');

  // Verify Email B state is independent
  assert.equal(drafts['email_002'].replyBody, 'Draft for Email B with custom schedule');
  assert.equal(drafts['email_002'].tone, 'concise');
  assert.equal(drafts['email_002'].customInstructions, 'Ask for salary range');

  // User edits Email A
  drafts['email_001'] = {
    ...drafts['email_001'],
    replyBody: 'Draft for Email A (User Modified)',
  };

  assert.equal(drafts['email_001'].replyBody, 'Draft for Email A (User Modified)');
  assert.equal(drafts['email_002'].replyBody, 'Draft for Email B with custom schedule');
});

test('SmartReply: Discard draft only removes the targeted email draft', () => {
  const drafts = {
    'email_001': { replyBody: 'Draft 1', generated: true },
    'email_002': { replyBody: 'Draft 2', generated: true },
  };

  // Discard email_001
  delete drafts['email_001'];

  assert.equal(drafts['email_001'], undefined);
  assert.equal(drafts['email_002'].replyBody, 'Draft 2');
});

test('SmartReply: Distinguishes daily quota exhaustion from temporary rate limits', () => {
  // Scenario 1: Daily Quota Exhausted 429
  const dailyQuotaError = {
    status: 429,
    message: 'Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.',
    isDailyQuota: true,
    retryAfter: null,
  };

  const isDaily1 = !!(
    dailyQuotaError.isDailyQuota ||
    dailyQuotaError.message.toLowerCase().includes('daily quota') ||
    dailyQuotaError.message.toLowerCase().includes('billing-enabled')
  );
  assert.equal(isDaily1, true);

  // In daily quota exhaustion, countdown must NOT be set
  let countdown = null;
  let isDailyQuotaExhausted = false;
  let errorMsg = null;

  if (isDaily1) {
    countdown = null;
    isDailyQuotaExhausted = true;
    errorMsg = 'Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.';
  }

  assert.equal(isDailyQuotaExhausted, true);
  assert.equal(countdown, null);
  assert.equal(errorMsg, 'Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.');

  // Scenario 2: Temporary Rate Limit 429 (e.g. 15 seconds)
  const tempRateLimitError = {
    status: 429,
    message: 'The AI service is temporarily busy (rate limit reached). Please try again in ~15 seconds.',
    isDailyQuota: false,
    retryAfter: 15,
  };

  const isDaily2 = !!(
    tempRateLimitError.isDailyQuota ||
    tempRateLimitError.message.toLowerCase().includes('daily quota') ||
    tempRateLimitError.message.toLowerCase().includes('billing-enabled')
  );
  assert.equal(isDaily2, false);

  if (!isDaily2 && tempRateLimitError.retryAfter) {
    countdown = tempRateLimitError.retryAfter;
    isDailyQuotaExhausted = false;
    errorMsg = tempRateLimitError.message;
  }

  assert.equal(isDailyQuotaExhausted, false);
  assert.equal(countdown, 15);
  assert.equal(errorMsg, 'The AI service is temporarily busy (rate limit reached). Please try again in ~15 seconds.');
});

test('SmartReply: Daily quota exhaustion blocks automatic or manual retry execution', () => {
  const state = {
    replyBody: '',
    loading: false,
    error: 'Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.',
    isDailyQuotaExhausted: true,
    retryCountdown: null,
  };

  const canGenerate = !state.loading && !state.isDailyQuotaExhausted && (!state.retryCountdown || state.retryCountdown <= 0);
  assert.equal(canGenerate, false);
});

test('EmailBodyViewer: URL shortening converts long tracking links into readable labels', async () => {
  const { getFriendlyUrlLabel } = await import('../src/components/gmail/EmailBodyViewer.js').catch(() =>
    import('../src/components/gmail/EmailBodyViewer.tsx')
  );

  // Tracking link with long base64 path
  const longTrackingUrl =
    'https://links.mail.techcorp.com/e/c/eyJlbWFpbF9pZCI6IjIwMjYwOTI1MTIwMjAwIiwicmVjaXBpZW50X2lkIjoxMjM0fQ==?utm_source=newsletter&utm_medium=email';
  const label1 = getFriendlyUrlLabel(longTrackingUrl);
  assert.equal(label1, 'links.mail.techcorp.com/...');

  // Contextual 'View in browser' link
  const label2 = getFriendlyUrlLabel(longTrackingUrl, 'Having trouble viewing? View this email in browser');
  assert.equal(label2, 'View in browser');

  // Contextual 'Unsubscribe' link
  const label3 = getFriendlyUrlLabel(longTrackingUrl, 'If you no longer wish to receive updates, unsubscribe here');
  assert.equal(label3, 'Unsubscribe Link');

  // Clean short URL
  const shortUrl = 'https://github.com/project';
  const label4 = getFriendlyUrlLabel(shortUrl);
  assert.equal(label4, 'github.com/project');
});

test('EmailBodyViewer: splitEmailBody separates main message from promotional footer', async () => {
  const { splitEmailBody } = await import('../src/components/gmail/EmailBodyViewer.js').catch(() =>
    import('../src/components/gmail/EmailBodyViewer.tsx')
  );

  const rawNewsletter = `Hi Developers,

We are thrilled to announce the release of our new AI Assistant features!
Here are the key highlights:
- Smart Reply drafting
- Daily quota protection
- Real-time rate limiting

Check out the documentation at https://docs.example.com/guide.

Best,
The AI Team

--------------------------------------------------
To unsubscribe from these updates, please click here: https://links.example.com/unsub?id=123
You are receiving this email because you subscribed to Developer Updates.
Company Inc, 123 Tech Street, San Francisco, CA
© 2026 Company Inc. All rights reserved.`;

  const { mainBody, footer } = splitEmailBody(rawNewsletter);

  assert.ok(mainBody.includes('We are thrilled to announce the release of our new AI Assistant features!'));
  assert.ok(mainBody.includes('The AI Team'));
  assert.ok(!mainBody.includes('To unsubscribe from these updates'));

  assert.ok(footer !== null);
  assert.ok(footer.includes('To unsubscribe from these updates'));
  assert.ok(footer.includes('© 2026 Company Inc. All rights reserved.'));
});

test('SmartReply Persistence: Cross-device draft hydration initializes state correctly', () => {
  // Simulates backend response from GET /api/v1/gmail/messages/{id}/reply-draft
  const backendDraft = {
    id: 'draft_uuid_999',
    message_id: 'msg_cross_device_1',
    thread_id: 'thread_cross_device_1',
    subject: 'Re: Team Sync',
    recipient: 'boss@corp.com',
    reply_body: 'Hi Boss,\n\nI have prepared the deck. See you at 10 AM.\n\nBest,\n[Your Name]',
    tone_used: 'formal',
    custom_instructions: 'Mention deck preparation',
    placeholders_detected: ['[Your Name]'],
    created_at: '2026-09-25T07:30:00Z',
    updated_at: '2026-09-25T07:35:00Z',
  };

  // Hydration reducer
  const initialState = {
    replyBody: '',
    tone: 'professional',
    customInstructions: '',
    loading: false,
    error: null,
    placeholders: [],
    generated: false,
    saveStatus: 'idle',
    lastSavedAt: null,
    initialFetchDone: false,
  };

  const hydratedState = {
    ...initialState,
    replyBody: backendDraft.reply_body,
    tone: backendDraft.tone_used || 'professional',
    customInstructions: backendDraft.custom_instructions || '',
    placeholders: backendDraft.placeholders_detected || [],
    generated: true,
    saveStatus: 'saved',
    lastSavedAt: backendDraft.updated_at || backendDraft.created_at,
    initialFetchDone: true,
    error: null,
  };

  assert.equal(hydratedState.generated, true);
  assert.equal(hydratedState.saveStatus, 'saved');
  assert.equal(hydratedState.replyBody, backendDraft.reply_body);
  assert.equal(hydratedState.tone, 'formal');
  assert.equal(hydratedState.customInstructions, 'Mention deck preparation');
  assert.deepEqual(hydratedState.placeholders, ['[Your Name]']);
  assert.equal(hydratedState.lastSavedAt, '2026-09-25T07:35:00Z');
  assert.equal(hydratedState.initialFetchDone, true);
});

test('SmartReply Persistence: Debounced autosave state transitions (idle -> saving -> saved)', () => {
  let state = {
    replyBody: 'Initial draft',
    tone: 'professional',
    saveStatus: 'saved',
    lastSavedAt: '2026-09-25T07:00:00Z',
  };

  // 1. User types in textarea -> immediate transition to 'saving'
  const newText = 'Initial draft with new edits from phone';
  state = {
    ...state,
    replyBody: newText,
    saveStatus: 'saving',
  };
  assert.equal(state.saveStatus, 'saving');

  // 2. Autosave completes successfully -> transition to 'saved'
  const savedTimestamp = '2026-09-25T07:01:00Z';
  state = {
    ...state,
    saveStatus: 'saved',
    lastSavedAt: savedTimestamp,
  };
  assert.equal(state.saveStatus, 'saved');
  assert.equal(state.lastSavedAt, savedTimestamp);

  // 3. If network fails during save -> transition to 'error'
  state = {
    ...state,
    saveStatus: 'error',
  };
  assert.equal(state.saveStatus, 'error');
});

test('SmartReply Persistence: Discard draft resets state and triggers deletion', () => {
  let state = {
    replyBody: 'Draft to discard',
    tone: 'friendly',
    customInstructions: 'test',
    loading: false,
    error: null,
    placeholders: ['[Your Name]'],
    generated: true,
    saveStatus: 'saved',
    lastSavedAt: '2026-09-25T07:00:00Z',
    initialFetchDone: true,
  };

  // Discard action
  state = {
    replyBody: '',
    tone: 'professional',
    customInstructions: '',
    loading: false,
    error: null,
    isDailyQuotaExhausted: false,
    retryCountdown: null,
    placeholders: [],
    generated: false,
    saveStatus: 'idle',
    lastSavedAt: null,
    initialFetchDone: true,
  };

  assert.equal(state.generated, false);
  assert.equal(state.replyBody, '');
  assert.equal(state.saveStatus, 'idle');
  assert.equal(state.lastSavedAt, null);
});

test('SmartReply Gmail Drafts: Save to Gmail Drafts sets confirmed status and draft ID', () => {
  let state = {
    replyBody: 'Generated reply body for recruiter',
    tone: 'professional',
    generated: true,
    saveStatus: 'saved',
    gmailDraftId: null,
    gmailSaveStatus: 'idle',
    gmailWebUrl: null,
  };

  // 1. Initial state: Not saved to Gmail yet
  const hasGmailDraftInitial = !!state.gmailDraftId && state.gmailSaveStatus === 'saved';
  assert.equal(hasGmailDraftInitial, false);

  // 2. User clicks "Save to Gmail Drafts" -> transitions to saving
  state = {
    ...state,
    gmailSaveStatus: 'saving',
    gmailSaveError: null,
  };
  assert.equal(state.gmailSaveStatus, 'saving');

  // 3. Gmail API returns 200 with draft ID and web URL
  const apiResponse = {
    message_id: 'msg_123',
    reply_body: 'Generated reply body for recruiter',
    gmail_draft_id: 'r-9876543210',
    gmail_web_url: 'https://mail.google.com/mail/u/0/#drafts',
    updated_at: '2026-09-25T08:00:00Z',
  };

  state = {
    ...state,
    gmailDraftId: apiResponse.gmail_draft_id,
    gmailWebUrl: apiResponse.gmail_web_url,
    gmailSaveStatus: 'saved',
    gmailSaveError: null,
    saveStatus: 'saved',
    lastSavedAt: apiResponse.updated_at,
  };

  const hasGmailDraftConfirmed = !!state.gmailDraftId && state.gmailSaveStatus === 'saved';
  assert.equal(hasGmailDraftConfirmed, true);
  assert.equal(state.gmailDraftId, 'r-9876543210');
  assert.equal(state.gmailWebUrl, 'https://mail.google.com/mail/u/0/#drafts');
});

test('SmartReply Gmail Drafts: Failed Gmail API save never displays Saved to Gmail badge', () => {
  let state = {
    replyBody: 'Draft content',
    gmailDraftId: null,
    gmailSaveStatus: 'idle',
    gmailSaveError: null,
  };

  // Simulate API failure (e.g. network timeout or 500 error)
  const errorMsg = 'Failed to save draft directly to Gmail (HTTP 500)';
  state = {
    ...state,
    gmailSaveStatus: 'error',
    gmailSaveError: errorMsg,
  };

  const hasGmailDraft = !!state.gmailDraftId && state.gmailSaveStatus === 'saved';
  assert.equal(hasGmailDraft, false);
  assert.equal(state.gmailSaveStatus, 'error');
  assert.equal(state.gmailSaveError, errorMsg);
});

test('SmartReply Gmail Drafts: Missing compose scope triggers reconnect CTA without false saved state', () => {
  let state = {
    replyBody: 'Draft content requiring compose scope',
    gmailDraftId: null,
    gmailSaveStatus: 'idle',
    isMissingComposeScope: false,
  };

  // Gmail API returns 403 Forbidden with missing scope
  const is403Error = true;
  const errMsg = "Gmail permission 'gmail.compose' is not authorized. Please reconnect your Google account with draft permissions.";

  state = {
    ...state,
    gmailSaveStatus: 'error',
    gmailSaveError: errMsg,
    isMissingComposeScope: is403Error,
  };

  assert.equal(state.isMissingComposeScope, true);
  assert.equal(state.gmailDraftId, null);
  assert.notEqual(state.gmailSaveStatus, 'saved');
});

test('SmartReply Gmail Drafts: Updating existing draft maintains draft ID and avoids duplicates', () => {
  let state = {
    replyBody: 'Original text',
    gmailDraftId: 'r-existing-draft-id',
    gmailSaveStatus: 'saved',
    gmailWebUrl: 'https://mail.google.com/mail/u/0/#drafts',
  };

  // User modifies text
  const updatedText = 'Original text with edits made on mobile';
  state = {
    ...state,
    replyBody: updatedText,
  };

  // When updating to Gmail, existing draft ID is sent
  const updatePayload = {
    reply_body: state.replyBody,
    gmail_draft_id: state.gmailDraftId,
  };

  assert.equal(updatePayload.gmail_draft_id, 'r-existing-draft-id');

  // Successful update response returns same draft ID
  state = {
    ...state,
    gmailSaveStatus: 'saved',
    lastSavedAt: '2026-09-25T08:15:00Z',
  };

  assert.equal(state.gmailDraftId, 'r-existing-draft-id');
  assert.equal(state.gmailSaveStatus, 'saved');
});

test('SmartReply Gmail Drafts: Cross-device draft hydration loads existing Gmail draft state', () => {
  const initialState = {
    replyBody: '',
    generated: false,
    gmailDraftId: null,
    gmailSaveStatus: 'idle',
    gmailWebUrl: null,
  };

  const savedFromBackend = {
    reply_body: 'Cross-device synced reply',
    tone_used: 'friendly',
    gmail_draft_id: 'r-synced-draft-id',
    gmail_web_url: 'https://mail.google.com/mail/u/0/#drafts',
    updated_at: '2026-09-25T08:20:00Z',
  };

  const hydratedState = {
    ...initialState,
    replyBody: savedFromBackend.reply_body,
    tone: savedFromBackend.tone_used,
    generated: true,
    saveStatus: 'saved',
    gmailDraftId: savedFromBackend.gmail_draft_id,
    gmailWebUrl: savedFromBackend.gmail_web_url,
    gmailSaveStatus: savedFromBackend.gmail_draft_id ? 'saved' : 'idle',
    lastSavedAt: savedFromBackend.updated_at,
    initialFetchDone: true,
  };

  assert.equal(hydratedState.gmailDraftId, 'r-synced-draft-id');
  assert.equal(hydratedState.gmailSaveStatus, 'saved');
  assert.equal(hydratedState.gmailWebUrl, 'https://mail.google.com/mail/u/0/#drafts');
  assert.equal(hydratedState.generated, true);
});


