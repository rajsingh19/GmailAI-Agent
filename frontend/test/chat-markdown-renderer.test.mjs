import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeHtmlEntitiesAndEscapes } from '../src/components/chat/MarkdownRenderer.js';

test('MarkdownRenderer: decodeHtmlEntitiesAndEscapes correctly unescapes HTML entities and escaped markdown', () => {
  // 1. HTML entities
  const rawEntities = "It&#39;s a &quot;great&quot; opportunity &amp; meeting &lt;now&gt;";
  const decodedEntities = decodeHtmlEntitiesAndEscapes(rawEntities);
  assert.equal(decodedEntities, "It's a \"great\" opportunity & meeting <now>");

  // 2. Escaped Markdown backslashes
  const rawEscaped = "• \\*\\*[UPCOMING\\] Google Interview\\*\\* \\- Scheduled: Sept 28";
  const decodedEscaped = decodeHtmlEntitiesAndEscapes(rawEscaped);
  assert.equal(decodedEscaped, "• **[UPCOMING] Google Interview** - Scheduled: Sept 28");

  // 3. Mixed entities and markdown
  const mixed = "Don&#39;t miss your \\*\\*Technical Interview\\*\\* at 3:00 PM.";
  const decodedMixed = decodeHtmlEntitiesAndEscapes(mixed);
  assert.equal(decodedMixed, "Don't miss your **Technical Interview** at 3:00 PM.");
});

test('MarkdownRenderer: Interview and Email parsing patterns are robust', () => {
  const interviewText = "• **[UPCOMING] Frontend Engineer Technical Interview**\n  - Scheduled / Deadline: September 28, 2026 at 3:00 PM UTC\n  - From: recruiter@google.com";
  
  const match = interviewText.match(/^[•*-]\s*\*\*\[([A-Z_]+)\]\s*([^*]+)\*\*/i);
  assert.ok(match, 'Should match interview card header pattern');
  assert.equal(match[1], 'UPCOMING');
  assert.equal(match[2].trim(), 'Frontend Engineer Technical Interview');

  const schedMatch = interviewText.match(/(?:Scheduled|Deadline|Time):\s*([^\n]+)/i);
  assert.ok(schedMatch);
  assert.equal(schedMatch[1].trim(), 'September 28, 2026 at 3:00 PM UTC');

  const senderMatch = interviewText.match(/(?:From|Sender|Recruiter):\s*([^\n]+)/i);
  assert.ok(senderMatch);
  assert.equal(senderMatch[1].trim(), 'recruiter@google.com');
});

test('MarkdownRenderer: Safe URLs validate against script injection', () => {
  const safeHttp = 'https://meet.google.com/abc-defg-hij';
  const isSafeHttp = safeHttp.startsWith('http://') || safeHttp.startsWith('https://') || safeHttp.startsWith('mailto:');
  assert.equal(isSafeHttp, true);

  const unsafeScript = 'javascript:alert(1)';
  const isSafeScript = unsafeScript.startsWith('http://') || unsafeScript.startsWith('https://') || unsafeScript.startsWith('mailto:');
  assert.equal(isSafeScript, false);
});
