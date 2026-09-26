import React, { useState } from 'react';
import { Copy, Check, ExternalLink, Code2 } from 'lucide-react';
import { InterviewCard, InterviewCardData } from './InterviewCard';
import { EmailCard, EmailCardData } from './EmailCard';

interface MarkdownRendererProps {
  content: string;
  isUser?: boolean;
  onOpenEmail?: (id?: string) => void;
}

/**
 * Safely decodes HTML entities and removes backslash escape characters.
 */
export function decodeHtmlEntitiesAndEscapes(raw: string): string {
  if (!raw) return '';

  let text = raw;

  // 1. Decode numeric & named HTML entities
  text = text
    .replace(/&#39;|&#x27;|&apos;/g, "'")
    .replace(/&quot;|&#34;|&#x22;/g, '"')
    .replace(/&lt;|&#60;|&#x3c;/gi, '<')
    .replace(/&gt;|&#62;|&#x3e;/gi, '>')
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;|&#38;|&#x26;/gi, '&');

  // 2. Remove escaped Markdown backslashes (e.g. \* -> *, \_ -> _, \# -> #)
  text = text
    .replace(/\\(\*|_|#|\[|\]|\(|\)|-|`|>|\+)/g, '$1');

  return text;
}

/**
 * Renders inline markdown: bold, italic, inline code, links, and text.
 */
export function renderInlineMarkdown(text: string, isUser = false): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // Tokenize regex: inline code, bold-italic, bold, italic, links
  const regex = /(`[^`]+`|\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|___[^_]+___|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.substring(lastIndex, match.index));
    }

    const token = match[0];
    const key = `inline-${lastIndex}-${match.index}`;

    if (token.startsWith('`') && token.endsWith('`')) {
      const codeContent = token.slice(1, -1);
      nodes.push(
        <code
          key={key}
          className={`font-mono text-[12px] px-1.5 py-0.5 rounded border ${
            isUser
              ? 'bg-blue-700/60 text-blue-100 border-blue-500/40'
              : 'bg-slate-800/90 text-indigo-300 border-slate-700/70'
          }`}
        >
          {codeContent}
        </code>
      );
    } else if (
      (token.startsWith('***') && token.endsWith('***')) ||
      (token.startsWith('___') && token.endsWith('___'))
    ) {
      const inner = token.slice(3, -3);
      nodes.push(
        <strong key={key} className={`font-semibold italic ${isUser ? 'text-white' : 'text-slate-100'}`}>
          {renderInlineMarkdown(inner, isUser)}
        </strong>
      );
    } else if (
      (token.startsWith('**') && token.endsWith('**')) ||
      (token.startsWith('__') && token.endsWith('__'))
    ) {
      const inner = token.slice(2, -2);
      nodes.push(
        <strong key={key} className={`font-semibold ${isUser ? 'text-white' : 'text-slate-100'}`}>
          {renderInlineMarkdown(inner, isUser)}
        </strong>
      );
    } else if (
      (token.startsWith('*') && token.endsWith('*')) ||
      (token.startsWith('_') && token.endsWith('_'))
    ) {
      const inner = token.slice(1, -1);
      nodes.push(
        <em key={key} className={`italic ${isUser ? 'text-blue-100' : 'text-slate-300'}`}>
          {renderInlineMarkdown(inner, isUser)}
        </em>
      );
    } else if (token.startsWith('[') && token.includes('](') && token.endsWith(')')) {
      const closingBracket = token.indexOf('](');
      const label = token.slice(1, closingBracket);
      const url = token.slice(closingBracket + 2, -1);
      const safeUrl = url.startsWith('http://') || url.startsWith('https://') || url.startsWith('mailto:') ? url : '#';

      nodes.push(
        <a
          key={key}
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={`inline-flex items-center gap-0.5 underline font-medium ${
            isUser ? 'text-blue-100 hover:text-white' : 'text-blue-400 hover:text-blue-300'
          }`}
        >
          <span>{label}</span>
          <ExternalLink className="w-2.5 h-2.5 inline" />
        </a>
      );
    } else {
      nodes.push(token);
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.substring(lastIndex));
  }

  return nodes;
}

/**
 * Code Block Component with language tag and Copy to Clipboard button.
 */
const CodeBlock: React.FC<{ language: string; code: string }> = ({ language, code }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-3 rounded-xl overflow-hidden border border-slate-800 bg-slate-950 shadow-md">
      <div className="flex items-center justify-between px-3.5 py-1.5 bg-slate-900/90 border-b border-slate-800 text-[11px] text-slate-400 font-mono">
        <span className="flex items-center gap-1.5 font-semibold text-slate-300 uppercase">
          <Code2 className="w-3.5 h-3.5 text-indigo-400" />
          {language || 'text'}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] hover:text-slate-200 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 transition-colors cursor-pointer"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-emerald-400 font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3 text-slate-400" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="p-3.5 overflow-x-auto text-xs font-mono text-emerald-300 leading-relaxed bg-slate-950/90">
        <code>{code}</code>
      </pre>
    </div>
  );
};

/**
 * Parses markdown tables into clean React table elements.
 */
function renderMarkdownTable(tableLines: string[], keyPrefix: string): React.ReactNode {
  if (tableLines.length < 2) return null;

  const headerRow = tableLines[0]
    .split('|')
    .map((c) => c.trim())
    .filter((c, idx, arr) => (idx === 0 && c === '' ? false : idx === arr.length - 1 && c === '' ? false : true));

  const bodyRows = tableLines.slice(2).map((row) =>
    row
      .split('|')
      .map((c) => c.trim())
      .filter((c, idx, arr) => (idx === 0 && c === '' ? false : idx === arr.length - 1 && c === '' ? false : true))
  );

  return (
    <div key={keyPrefix} className="my-3 overflow-x-auto rounded-xl border border-slate-800 shadow-xs">
      <table className="min-w-full divide-y divide-slate-800 text-xs text-left">
        <thead className="bg-slate-900/90">
          <tr>
            {headerRow.map((h, i) => (
              <th key={i} className="px-3.5 py-2 font-semibold text-slate-200 border-r border-slate-800 last:border-r-0">
                {renderInlineMarkdown(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60 bg-slate-950/40">
          {bodyRows.map((row, rIdx) => (
            <tr key={rIdx} className="hover:bg-slate-900/40 transition-colors">
              {row.map((cell, cIdx) => (
                <td key={cIdx} className="px-3.5 py-2 text-slate-300 border-r border-slate-800/60 last:border-r-0">
                  {renderInlineMarkdown(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Checks if a block of bullet points represents structured interview items.
 */
function tryParseInterviewCard(text: string): InterviewCardData | null {
  // Pattern: • **[STATUS] Subject** \n - Scheduled / Deadline: ... \n - From: ...
  const match = text.match(/^[•*-]\s*\*\*\[([A-Z_]+)\]\s*([^*]+)\*\*/i);
  if (!match) return null;

  const status = match[1].trim();
  const subject = match[2].trim();

  let scheduledTime: string | undefined;
  let sender: string | undefined;
  let snippet: string | undefined;

  const schedMatch = text.match(/(?:Scheduled|Deadline|Time):\s*([^\n]+)/i);
  if (schedMatch) scheduledTime = schedMatch[1].trim();

  const senderMatch = text.match(/(?:From|Sender|Recruiter):\s*([^\n]+)/i);
  if (senderMatch) sender = senderMatch[1].trim();

  const snippetMatch = text.match(/(?:Summary|Notes|Snippet):\s*([^\n]+)/i);
  if (snippetMatch) snippet = snippetMatch[1].trim();

  return {
    status,
    subject,
    scheduledTime,
    sender,
    snippet,
  };
}

/**
 * Checks if a bullet point represents an email summary card.
 */
function tryParseEmailCard(text: string): EmailCardData | null {
  // Pattern: • **Subject** (From: Sender) - Snippet...
  const match = text.match(/^[•*-]\s*\*\*([^*]+)\*\*(?:\s*\(From:\s*([^)]+)\))?(?:\s*-\s*([^\n]+))?/i);
  if (!match) return null;

  const subject = match[1].trim();
  const sender = match[2]?.trim();
  const snippet = match[3]?.trim();

  // If subject is just generic or interview status, let other handlers process it
  if (subject.startsWith('[') && subject.includes(']')) return null;

  return {
    subject,
    sender,
    snippet,
  };
}

/**
 * Main Markdown & Structured Content Renderer Component.
 */
export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  isUser = false,
  onOpenEmail,
}) => {
  const decodedContent = decodeHtmlEntitiesAndEscapes(content);

  // If user bubble, render inline directly
  if (isUser) {
    return <div className="font-sans text-xs sm:text-sm leading-relaxed">{renderInlineMarkdown(decodedContent, true)}</div>;
  }

  // Parse multi-line blocks
  const lines = decodedContent.split('\n');
  const elements: React.ReactNode[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // 1. Code block start
    if (line.trim().startsWith('```')) {
      const language = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // consume closing ```
      elements.push(
        <CodeBlock key={`code-${i}`} language={language} code={codeLines.join('\n')} />
      );
      continue;
    }

    // 2. Table detection (| col | col |)
    if (line.trim().startsWith('|') && line.trim().endsWith('|') && i + 1 < lines.length && lines[i + 1].includes('---')) {
      const tableLines: string[] = [line, lines[i + 1]];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      elements.push(renderMarkdownTable(tableLines, `table-${i}`));
      continue;
    }

    // 3. Horizontal Rule
    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      elements.push(<hr key={`hr-${i}`} className="my-3 border-slate-800" />);
      i++;
      continue;
    }

    // 4. Headings
    if (line.startsWith('# ')) {
      elements.push(
        <h2 key={`h1-${i}`} className="text-base sm:text-lg font-bold text-white mt-4 mb-2 pb-1 border-b border-slate-800">
          {renderInlineMarkdown(line.slice(2))}
        </h2>
      );
      i++;
      continue;
    }
    if (line.startsWith('## ')) {
      elements.push(
        <h3 key={`h2-${i}`} className="text-sm sm:text-base font-bold text-white mt-3 mb-1.5">
          {renderInlineMarkdown(line.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={`h3-${i}`} className="text-xs sm:text-sm font-semibold text-indigo-300 mt-2.5 mb-1">
          {renderInlineMarkdown(line.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith('#### ')) {
      elements.push(
        <h5 key={`h4-${i}`} className="text-xs font-semibold uppercase tracking-wider text-slate-400 mt-2 mb-1">
          {renderInlineMarkdown(line.slice(5))}
        </h5>
      );
      i++;
      continue;
    }

    // 5. Blockquote
    if (line.startsWith('>')) {
      const quoteLines: string[] = [line.slice(1).trim()];
      i++;
      while (i < lines.length && lines[i].startsWith('>')) {
        quoteLines.push(lines[i].slice(1).trim());
        i++;
      }
      elements.push(
        <blockquote key={`quote-${i}`} className="border-l-4 border-indigo-500 pl-3.5 py-1.5 my-2.5 bg-indigo-950/20 rounded-r-xl text-slate-300 italic text-xs">
          {quoteLines.map((ql, qIdx) => (
            <p key={qIdx}>{renderInlineMarkdown(ql)}</p>
          ))}
        </blockquote>
      );
      continue;
    }

    // 6. Check for structured Interview Card or Email Card in bullet items
    const interviewData = tryParseInterviewCard(line);
    if (interviewData) {
      // Gather any subsequent indented sub-bullets for this card
      let combinedText = line;
      let nextIdx = i + 1;
      while (nextIdx < lines.length && /^\s+[-•*]/.test(lines[nextIdx])) {
        combinedText += '\n' + lines[nextIdx];
        nextIdx++;
      }
      const fullInterview = tryParseInterviewCard(combinedText) || interviewData;
      elements.push(
        <InterviewCard key={`interview-${i}`} data={fullInterview} onOpenEmail={onOpenEmail} />
      );
      i = nextIdx;
      continue;
    }

    const emailData = tryParseEmailCard(line);
    if (emailData && emailData.sender) {
      elements.push(
        <EmailCard key={`email-${i}`} data={emailData} onOpenEmail={onOpenEmail} />
      );
      i++;
      continue;
    }

    // 7. Bullet Lists (Unordered)
    if (/^[•*-]\s+/.test(line.trim())) {
      const listItems: string[] = [];
      while (i < lines.length && /^[•*-]\s+/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^[•*-]\s+/, ''));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="my-2 space-y-1.5 pl-2 list-none">
          {listItems.map((item, lIdx) => (
            <li key={lIdx} className="text-xs sm:text-sm text-slate-200 flex items-start gap-2 leading-relaxed">
              <span className="text-indigo-400 mt-1 select-none font-bold text-xs">•</span>
              <span className="flex-1">{renderInlineMarkdown(item)}</span>
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // 8. Numbered Lists (Ordered)
    if (/^\d+\.\s+/.test(line.trim())) {
      const listItems: { num: string; text: string }[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        const matchNum = lines[i].trim().match(/^(\d+)\.\s+(.*)$/);
        if (matchNum) {
          listItems.push({ num: matchNum[1], text: matchNum[2] });
        }
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="my-2 space-y-1.5 pl-1">
          {listItems.map((item, lIdx) => (
            <li key={lIdx} className="text-xs sm:text-sm text-slate-200 flex items-start gap-2 leading-relaxed">
              <span className="font-semibold text-indigo-400 text-xs min-w-[1.2rem] text-right font-mono mt-0.5">
                {item.num}.
              </span>
              <span className="flex-1">{renderInlineMarkdown(item.text)}</span>
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // 9. Standard Paragraph
    const trimmed = line.trim();
    if (trimmed) {
      elements.push(
        <p key={`p-${i}`} className="text-xs sm:text-sm text-slate-200 my-1.5 leading-relaxed">
          {renderInlineMarkdown(line)}
        </p>
      );
    } else {
      // Empty line spacing
      elements.push(<div key={`sp-${i}`} className="h-1.5" />);
    }

    i++;
  }

  return <div className="space-y-0.5 font-sans leading-relaxed break-words">{elements}</div>;
};
