import React from 'react';
import {
  Bot,
  User,
  Sparkles,
  Terminal,
  Wrench,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ShieldCheck,
  ThumbsUp,
  ThumbsDown,
  Copy,
  Check,
} from 'lucide-react';
import { ConfirmationChallenge, ToolActivityInfo } from '../../services/api';
import { MarkdownRenderer } from './MarkdownRenderer';

export interface ChatMessageData {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolsCalled?: ToolActivityInfo[];
  confirmation?: ConfirmationChallenge | null;
  requiresConfirmation?: boolean;
  personalization?: any | null;
}

interface ChatMessageBubbleProps {
  message: ChatMessageData;
  loading?: boolean;
  copiedId?: string | null;
  onCopy?: (text: string, id: string) => void;
  onConfirmAction?: (challenge: ConfirmationChallenge) => void;
  onCancelConfirmation?: () => void;
  onOpenEmail?: (id?: string) => void;
}

export const ChatMessageBubble: React.FC<ChatMessageBubbleProps> = ({
  message,
  loading = false,
  copiedId,
  onCopy,
  onConfirmAction,
  onCancelConfirmation,
  onOpenEmail,
}) => {
  const isUser = message.role === 'user';
  const isCopied = copiedId === message.id;

  return (
    <div className={`flex flex-col my-3 transition-all ${isUser ? 'items-end' : 'items-start'}`}>
      <div
        className={`max-w-[92%] sm:max-w-[85%] lg:max-w-[80%] rounded-2xl p-4 sm:p-5 text-sm leading-relaxed transition-all shadow-md ${
          isUser
            ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-tr-xs shadow-blue-600/10'
            : 'bg-slate-900/90 text-slate-100 border border-slate-700/60 rounded-tl-xs shadow-black/20 backdrop-blur-md'
        }`}
      >
        {/* Header with Avatar & Timestamp */}
        <div className="flex items-center justify-between gap-3 mb-2.5 pb-2 border-b border-white/10 opacity-80 text-[11px]">
          <div className="flex items-center gap-2">
            {isUser ? (
              <span className="font-semibold text-blue-100 flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-full bg-blue-500/40 border border-white/30 flex items-center justify-center">
                  <User className="w-3 h-3 text-white" />
                </div>
                You
              </span>
            ) : (
              <span className="font-semibold text-indigo-300 flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-md bg-gradient-to-tr from-indigo-500 to-blue-500 flex items-center justify-center shadow-xs">
                  <Bot className="w-3 h-3 text-white" />
                </div>
                AI Assistant
              </span>
            )}
          </div>
          <span className="text-[10px] text-slate-400 font-mono">{message.timestamp}</span>
        </div>

        {/* Message Body with Rich Markdown & Entity Decoding */}
        <div className="text-xs sm:text-sm">
          <MarkdownRenderer
            content={message.content}
            isUser={isUser}
            onOpenEmail={onOpenEmail}
          />
        </div>

        {/* Personalization Chip */}
        {message.personalization?.applied_keys && message.personalization.applied_keys.length > 0 && (
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center gap-1.5 flex-wrap">
            <span
              className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 px-2.5 py-0.5 rounded-full"
              title={message.personalization.reason || 'Personalized preferences applied'}
            >
              <Sparkles className="w-3 h-3 text-indigo-400" />
              <span>Personalized ✦</span>
              <span className="text-indigo-300/80 font-mono lowercase">
                ({message.personalization.applied_keys.join(', ')})
              </span>
            </span>
          </div>
        )}

        {/* Tool Execution Badges */}
        {message.toolsCalled && message.toolsCalled.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-800 space-y-1.5">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1">
              <Terminal className="w-3 h-3 text-indigo-400" />
              <span>Tools Executed ({message.toolsCalled.length})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {message.toolsCalled.map((tool, idx) => (
                <div
                  key={idx}
                  className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg border ${
                    tool.status === 'completed'
                      ? 'bg-slate-950/80 border-slate-700/80 text-slate-300'
                      : tool.status === 'confirmation_required'
                      ? 'bg-amber-950/40 border-amber-800/60 text-amber-300'
                      : 'bg-rose-950/40 border-rose-800/60 text-rose-300'
                  }`}
                >
                  <Wrench className="w-3 h-3 text-slate-400" />
                  <span className="font-mono text-[11px] font-medium">{tool.name}</span>
                  {tool.status === 'completed' ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  ) : tool.status === 'confirmation_required' ? (
                    <AlertTriangle className="w-3 h-3 text-amber-400" />
                  ) : (
                    <XCircle className="w-3 h-3 text-rose-400" />
                  )}
                  <span className="text-[10px] text-slate-400 font-sans max-w-xs truncate" title={tool.summary}>
                    {tool.summary}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Confirmation Challenge Box */}
        {message.requiresConfirmation && message.confirmation && (
          <div className="mt-3 p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 space-y-2.5">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="space-y-1 text-xs">
                <div className="font-semibold text-amber-300 flex items-center gap-1.5">
                  <span>Confirmation Required</span>
                  <span className="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded text-[10px] font-medium">
                    {message.confirmation.action}
                  </span>
                </div>
                <p className="text-amber-200/90">{message.confirmation.message}</p>
              </div>
            </div>

            <div className="flex items-center gap-2 pt-1">
              {onConfirmAction && (
                <button
                  onClick={() => onConfirmAction(message.confirmation!)}
                  disabled={loading}
                  className="px-3.5 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold text-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Confirm & Execute</span>
                </button>
              )}
              {onCancelConfirmation && (
                <button
                  onClick={onCancelConfirmation}
                  disabled={loading}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        )}

        {/* Assistant Actions Footer */}
        {!isUser && (
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-slate-400 text-[11px]">
            <div className="flex items-center gap-2">
              <button
                className="p-1 hover:text-slate-200 hover:bg-slate-800/60 rounded transition-colors"
                title="Helpful response"
              >
                <ThumbsUp className="w-3 h-3" />
              </button>
              <button
                className="p-1 hover:text-slate-200 hover:bg-slate-800/60 rounded transition-colors"
                title="Needs improvement"
              >
                <ThumbsDown className="w-3 h-3" />
              </button>
            </div>

            {onCopy && (
              <button
                onClick={() => onCopy(message.content, message.id)}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded hover:bg-slate-800 hover:text-slate-200 transition-colors cursor-pointer"
                title="Copy message to clipboard"
              >
                {isCopied ? (
                  <>
                    <Check className="w-3 h-3 text-emerald-400" />
                    <span className="text-emerald-400 font-medium">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    <span>Copy</span>
                  </>
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
