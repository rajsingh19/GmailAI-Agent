import React, { useState } from 'react';
import { ExternalLink, ChevronDown, ChevronUp, Mail } from 'lucide-react';
import { decodeHtmlEntitiesAndEscapes } from '../chat/MarkdownRenderer';

interface EmailBodyViewerProps {
  content: string;
}

/**
 * Shortens a URL into a friendly, readable label.
 */
export function getFriendlyUrlLabel(url: string, contextHint?: string): string {
  if (contextHint && /view\s+(?:this\s+email\s+)?in\s+browser/i.test(contextHint)) {
    return 'View in browser';
  }
  if (contextHint && /unsubscribe/i.test(contextHint)) {
    return 'Unsubscribe Link';
  }
  if (contextHint && /manage\s+preferences/i.test(contextHint)) {
    return 'Manage Preferences';
  }

  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, '');
    const path = parsed.pathname.length > 1 ? parsed.pathname : '';

    // If tracking link (e.g. utm, token, redirect, long path, click redirect)
    if (
      url.length > 45 ||
      parsed.searchParams.has('utm_source') ||
      parsed.searchParams.has('trk') ||
      path.includes('/click') ||
      path.includes('/redirect') ||
      path.includes('/e/c/')
    ) {
      if (path && path.length < 20 && path !== '/') {
        return `${host}${path}`;
      }
      return `${host}/...`;
    }

    // Short readable URL
    if (url.length <= 40) {
      return url.replace(/^https?:\/\//, '');
    }
    return `${host}${path.slice(0, 15)}...`;
  } catch {
    if (url.length > 40) {
      return url.slice(0, 35) + '...';
    }
    return url;
  }
}

/**
 * Splits email content into main body and promotional/newsletter footer.
 */
export function splitEmailBody(rawContent: string): { mainBody: string; footer: string | null } {
  if (!rawContent) return { mainBody: '', footer: null };

  const cleaned = decodeHtmlEntitiesAndEscapes(rawContent);

  // Common patterns indicating newsletter / marketing / legal footers
  const footerRegex = /\n(?:[-_=*]{2,}\s*)?\n*(?=(?:To unsubscribe|Unsubscribe|Manage preferences|Manage your email preferences|Email preferences|You are receiving this email because|This email was sent to|View this email in your browser|View in browser|If you no longer wish to receive|©\s*\d{4}|Copyright\s*©|Sent with love by|Sent by:\s*|Privacy Policy\s*\|\s*Terms))/i;

  const match = footerRegex.exec(cleaned);
  if (match && match.index > 50) {
    const mainBody = cleaned.slice(0, match.index).trim();
    const footer = cleaned.slice(match.index).trim();
    if (mainBody.length > 0 && footer.length > 0) {
      return { mainBody, footer };
    }
  }

  return { mainBody: cleaned, footer: null };
}

/**
 * Safely renders text with shortened, clickable link badges.
 */
export function renderTextWithLinks(text: string, keyPrefix: string): React.ReactNode[] {
  const urlRegex = /(https?:\/\/[^\s<>"'`]+)/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = urlRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.substring(lastIndex, match.index));
    }

    const rawUrl = match[0];
    const prevText = text.substring(Math.max(0, match.index - 40), match.index);
    const friendlyLabel = getFriendlyUrlLabel(rawUrl, prevText);
    const nodeKey = `${keyPrefix}-url-${match.index}`;

    // Clean trailing punctuation if accidentally captured
    let cleanUrl = rawUrl;
    let trailingPunct = '';
    const punctMatch = rawUrl.match(/[.,;:)\]]+$/);
    if (punctMatch) {
      trailingPunct = punctMatch[0];
      cleanUrl = rawUrl.slice(0, -trailingPunct.length);
    }

    nodes.push(
      <a
        key={nodeKey}
        href={cleanUrl}
        target="_blank"
        rel="noopener noreferrer"
        title={cleanUrl}
        className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-800 font-medium underline underline-offset-2 hover:bg-indigo-50/80 px-1 py-0.5 rounded transition-colors text-[11px] sm:text-xs break-all"
        style={{ wordBreak: 'break-all' }}
      >
        <span>{friendlyLabel}</span>
        <ExternalLink className="w-3 h-3 inline-block flex-shrink-0 text-indigo-500" />
      </a>
    );

    if (trailingPunct) {
      nodes.push(trailingPunct);
    }

    lastIndex = urlRegex.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.substring(lastIndex));
  }

  return nodes;
}

export const EmailBodyViewer: React.FC<EmailBodyViewerProps> = ({ content }) => {
  const [showFullEmail, setShowFullEmail] = useState<boolean>(false);
  const { mainBody, footer } = splitEmailBody(content);

  // Split into paragraphs for natural readability
  const paragraphs = (mainBody || content || '').split(/\n{2,}/);

  return (
    <div className="space-y-4 font-sans text-gray-800 text-xs sm:text-sm leading-relaxed break-words overflow-hidden">
      {/* Main Email Content */}
      <div className="space-y-3">
        {paragraphs.map((para, pIdx) => {
          const trimmed = para.trim();
          if (!trimmed) return null;

          // Blockquote detection
          if (trimmed.startsWith('>')) {
            const quoteLines = trimmed.split('\n').map((l) => l.replace(/^>\s?/, '')).join('\n');
            return (
              <blockquote
                key={`p-${pIdx}`}
                className="pl-3.5 py-1 border-l-2 border-indigo-300 bg-indigo-50/30 text-gray-700 italic rounded-r-md"
              >
                {renderTextWithLinks(quoteLines, `quote-${pIdx}`)}
              </blockquote>
            );
          }

          // Horizontal divider detection
          if (/^[-_=*]{3,}$/.test(trimmed)) {
            return <hr key={`p-${pIdx}`} className="border-gray-200 my-2" />;
          }

          return (
            <p key={`p-${pIdx}`} className="whitespace-pre-wrap leading-relaxed">
              {renderTextWithLinks(trimmed, `para-${pIdx}`)}
            </p>
          );
        })}
      </div>

      {/* Collapsible Newsletter / Promotional Footer */}
      {footer && (
        <div className="mt-4 pt-3 border-t border-gray-100">
          <button
            type="button"
            onClick={() => setShowFullEmail(!showFullEmail)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 bg-gray-100/80 hover:bg-gray-200/80 border border-gray-200 px-3 py-1.5 rounded-lg transition-all shadow-2xs cursor-pointer"
          >
            {showFullEmail ? (
              <>
                <ChevronUp className="w-3.5 h-3.5 text-gray-500" />
                <span>Hide promotional footer & tracking links</span>
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
                <span>Show full email (newsletter footer & unsubscribe links)</span>
              </>
            )}
          </button>

          {showFullEmail && (
            <div className="mt-3 p-3.5 bg-gray-50/80 border border-gray-200 rounded-xl text-xs text-gray-600 space-y-2.5 leading-relaxed animate-fade-in">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                <Mail className="w-3.5 h-3.5 text-gray-400" />
                <span>Newsletter Footer & Unsubscribe Details</span>
              </div>
              <div className="whitespace-pre-wrap font-mono text-[11px] text-gray-600 bg-white p-3 rounded-lg border border-gray-200/70 overflow-hidden break-words">
                {renderTextWithLinks(footer, 'footer')}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
