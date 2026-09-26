import React, { useState, useRef, useEffect } from 'react';
import {
  Bot,
  Send,
  Sparkles,
  AlertTriangle,
  ShieldCheck,
  RotateCcw,
  Loader2,
  Mail,
  Calendar as CalendarIcon,
  CheckSquare,
  Bell,
} from 'lucide-react';
import {
  sendAgentMessage,
  AgentChatMessage,
  AgentChatResponse,
  ConfirmationChallenge,
  ToolActivityInfo,
} from '../services/api';
import { VoiceControls } from './VoiceControls';
import { sendVoiceChat, cancelVoiceExecution, VoiceChatResponse } from '../services/voiceApi';
import { ChatMessageBubble } from './chat/ChatMessageBubble';

interface AgentChatProps {
  isAuthenticated: boolean;
}

interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolsCalled?: ToolActivityInfo[];
  confirmation?: ConfirmationChallenge | null;
  requiresConfirmation?: boolean;
  personalization?: any | null;
}

const QUICK_PROMPTS = [
  { label: 'Summarize Tasks', text: 'What tasks do I currently have pending?', icon: CheckSquare },
  { label: 'Check Unread Emails', text: 'Search my inbox for unread messages and summarize the recent ones.', icon: Mail },
  { label: 'Upcoming Calendar', text: 'What events or meetings are scheduled on my calendar this week?', icon: CalendarIcon },
  { label: 'Create Priority Task', text: 'Create a high-priority task titled "Prepare product roadmap presentation".', icon: Sparkles },
  { label: 'Recent Notifications', text: 'List my recent notifications and alerts.', icon: Bell },
];

export const AgentChat: React.FC<AgentChatProps> = ({ isAuthenticated }) => {
  const [messages, setMessages] = useState<DisplayMessage[]>([
    {
      id: 'welcome-1',
      role: 'assistant',
      content:
        "Hello! I am your AI Assistant powered by Google Gemini. I can help you search and summarize your Gmail, check upcoming Calendar events, organize daily tasks, and schedule reminders. How can I help you today?",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [inputText, setInputText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<ConfirmationChallenge | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };
  const [lastAudioBase64, setLastAudioBase64] = useState<string | null>(null);
  const [lastAudioMimeType, setLastAudioMimeType] = useState<string | null>(null);
  const [ttsStatus, setTtsStatus] = useState<'success' | 'degraded' | 'disabled' | undefined>(undefined);
  const [activeVoiceExecutionId, setActiveVoiceExecutionId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSendMessage = async (textToSend?: string, confirmationToken?: string | null) => {
    const text = (textToSend ?? inputText).trim();
    if (!text && !confirmationToken) return;

    if (!isAuthenticated) {
      setError('Please sign in or connect your account to interact with the AI Assistant.');
      return;
    }

    setError(null);
    const userMsgId = `user-${Date.now()}`;
    const newHistory: DisplayMessage[] = [
      ...messages,
      {
        id: userMsgId,
        role: 'user',
        content: confirmationToken ? `[Confirmed Action: ${pendingConfirmation?.action ?? 'Operation'}]` : text,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ];

    setMessages(newHistory);
    setInputText('');
    setLoading(true);

    try {
      // Build conversation history excluding initial welcome message for the API
      const apiHistory: AgentChatMessage[] = newHistory
        .filter((m) => m.id !== 'welcome-1')
        .slice(-8)
        .map((m) => ({
          role: m.role,
          content: m.content,
        }));

      const response: AgentChatResponse = await sendAgentMessage({
        message: text || 'Confirmed action execution',
        history: apiHistory.slice(0, -1),
        confirmation_token: confirmationToken || null,
      });

      const assistantMsgId = `asst-${Date.now()}`;
      const pMeta = response.personalization_metadata || response.metadata?.personalization_metadata;
      const assistantMsg: DisplayMessage = {
        id: assistantMsgId,
        role: 'assistant',
        content: response.message,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolsCalled: response.tool_activities,
        requiresConfirmation: Boolean(response.confirmation_required),
        confirmation: response.confirmation_required,
        personalization: pMeta,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      if (response.tool_activities && response.tool_activities.length > 0) {
        window.dispatchEvent(new CustomEvent('assistant-data-updated', { detail: { tools: response.tool_activities } }));
      }

      if (response.confirmation_required) {
        setPendingConfirmation(response.confirmation_required);
      } else {
        setPendingConfirmation(null);
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred while communicating with the AI Assistant.');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmAction = (challenge: ConfirmationChallenge) => {
    handleSendMessage('I confirm this action', challenge.confirmation_token);
  };

  const handleCancelConfirmation = () => {
    setPendingConfirmation(null);
    setMessages((prev) => [
      ...prev,
      {
        id: `cancel-${Date.now()}`,
        role: 'assistant',
        content: 'Action cancelled. No modifications were made.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  };

  const handleClearChat = () => {
    setMessages([
      {
        id: 'welcome-reset',
        role: 'assistant',
        content: "Conversation history cleared. How can I help you next?",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
    setPendingConfirmation(null);
    setError(null);
  };

  const handleVoiceRecorded = async (audioBlob: Blob) => {
    if (!isAuthenticated) {
      setError('Please sign in or connect your account to interact with the AI Assistant.');
      return;
    }

    setError(null);
    setLoading(true);
    const executionId = `voice-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
    setActiveVoiceExecutionId(executionId);

    try {
      const apiHistory: AgentChatMessage[] = messages
        .filter((m) => m.id !== 'welcome-1')
        .slice(-8)
        .map((m) => ({
          role: m.role,
          content: m.content,
        }));

      const response: VoiceChatResponse = await sendVoiceChat(audioBlob, {
        history: apiHistory,
      });

      // Add user transcript message
      const userMsg: DisplayMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: response.transcript || '(voice input)',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      // Add assistant response message
      const asstMsg: DisplayMessage = {
        id: `asst-${Date.now()}`,
        role: 'assistant',
        content: response.message,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolsCalled: response.tool_activities,
        requiresConfirmation: Boolean(response.confirmation_required),
        confirmation: response.confirmation_required,
      };

      setMessages((prev) => [...prev, userMsg, asstMsg]);

      if (response.tool_activities && response.tool_activities.length > 0) {
        window.dispatchEvent(new CustomEvent('assistant-data-updated', { detail: { tools: response.tool_activities } }));
      }

      if (response.confirmation_required) {
        setPendingConfirmation(response.confirmation_required);
      } else {
        setPendingConfirmation(null);
      }

      if (response.audio_base64) {
        setLastAudioBase64(response.audio_base64);
        setLastAudioMimeType(response.audio_content_type || 'audio/wav');
      }
      setTtsStatus(response.tts_status);
    } catch (err: any) {
      setError(err.message || 'An error occurred during voice processing.');
    } finally {
      setLoading(false);
      setActiveVoiceExecutionId(null);
    }
  };

  const handleCancelVoice = async () => {
    if (activeVoiceExecutionId) {
      try {
        await cancelVoiceExecution(activeVoiceExecutionId);
      } catch (err) {
        console.warn('Voice cancellation error:', err);
      }
    }
    setLoading(false);
    setActiveVoiceExecutionId(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="glass-panel rounded-2xl border border-slate-800 bg-slate-900/60 shadow-2xl flex flex-col h-[700px] overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-800/80 bg-slate-950/40 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-cyan-400 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-white tracking-tight">AI Assistant</h3>
              <span className="inline-flex items-center gap-1 text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 px-2 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Ready
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Personal Intelligent Assistant &bull; Powered by Google Gemini
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleClearChat}
            className="text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 px-2.5 py-1.5 rounded-lg border border-slate-800 transition-colors flex items-center gap-1 cursor-pointer"
            title="Clear Chat History"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset</span>
          </button>
        </div>
      </div>

      {/* Quick Prompts Bar */}
      <div className="px-6 py-2.5 border-b border-slate-800/60 bg-slate-950/20 flex items-center gap-2 overflow-x-auto no-scrollbar">
        <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1 whitespace-nowrap">
          <Sparkles className="w-3 h-3 text-indigo-400" /> Quick Actions:
        </span>
        {QUICK_PROMPTS.map((prompt, idx) => {
          const Icon = prompt.icon;
          return (
            <button
              key={idx}
              disabled={loading || !isAuthenticated}
              onClick={() => handleSendMessage(prompt.text)}
              className="inline-flex items-center gap-1.5 text-xs bg-slate-800/70 hover:bg-slate-700/80 text-slate-300 hover:text-white px-2.5 py-1 rounded-full border border-slate-700/60 whitespace-nowrap transition-all duration-150 disabled:opacity-50 cursor-pointer"
            >
              <Icon className="w-3 h-3 text-blue-400" />
              <span>{prompt.label}</span>
            </button>
          );
        })}
      </div>

      {/* Messages Container */}
      <div className="flex-1 p-6 overflow-y-auto space-y-3">
        {messages.map((msg) => (
          <ChatMessageBubble
            key={msg.id}
            message={msg}
            loading={loading}
            copiedId={copiedId}
            onCopy={handleCopy}
            onConfirmAction={handleConfirmAction}
            onCancelConfirmation={handleCancelConfirmation}
          />
        ))}

        {loading && (
          <div className="flex items-start gap-2">
            <div className="bg-slate-800/90 border border-slate-700/70 rounded-2xl rounded-tl-none p-4 text-sm text-slate-400 flex items-center gap-2 shadow-sm">
              <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
              <span>AI is thinking and processing tools...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Assistant Notice</p>
                <p className="mt-0.5 opacity-90">{error}</p>
              </div>
            </div>
            <button
              onClick={() => handleSendMessage()}
              disabled={loading}
              className="px-2.5 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/40 text-xs cursor-pointer flex-shrink-0"
            >
              Retry
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Form */}
      <div className="p-4 border-t border-slate-800/80 bg-slate-950/60">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-end gap-2"
        >
          <div className="flex-1 relative">
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading || !isAuthenticated}
              placeholder={
                isAuthenticated
                  ? "Ask your assistant to manage tasks, check emails, view events..."
                  : "Connect your Google account above to use AI Assistant"
              }
              rows={2}
              className="w-full bg-slate-900 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all resize-none disabled:opacity-50"
            />
          </div>
          <VoiceControls
            onAudioRecorded={handleVoiceRecorded}
            disabled={loading || !isAuthenticated}
            isProcessing={Boolean(activeVoiceExecutionId)}
            onCancelProcessing={handleCancelVoice}
            lastAudioBase64={lastAudioBase64}
            lastAudioMimeType={lastAudioMimeType}
            ttsStatus={ttsStatus}
          />
          <button
            type="submit"
            disabled={loading || !inputText.trim() || !isAuthenticated}
            className="h-[52px] px-5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-600/20 disabled:opacity-50 disabled:hover:bg-blue-600 cursor-pointer"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <span>Send</span>
                <Send className="w-4 h-4" />
              </>
            )}
          </button>
        </form>
        <div className="flex items-center justify-between text-[11px] text-slate-500 mt-2 px-1">
          <span>Press Enter to send, Shift+Enter for new line</span>
          <span className="flex items-center gap-1">
            <ShieldCheck className="w-3 h-3 text-emerald-500" /> Actions that modify data require your confirmation
          </span>
        </div>
      </div>
    </div>
  );
};
