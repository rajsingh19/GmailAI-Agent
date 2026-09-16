import React, { useState, useRef, useEffect } from 'react';
import {
  Bot,
  Send,
  Sparkles,
  ShieldCheck,
  AlertTriangle,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Terminal,
  Wrench,
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
        "Hello! I am your AI Assistant powered by Google Gemini and our safe tool-calling core. I can securely inspect your Gmail, search your Calendar, manage your tasks, and schedule reminders. All actions are executed securely under your session, and dangerous write actions require your explicit cryptographic confirmation. How can I help you today?",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [inputText, setInputText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<ConfirmationChallenge | null>(null);
  const [configuredModel, setConfiguredModel] = useState<string>('Gemini');
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

      if (response.metadata && response.metadata.model) {
        setConfiguredModel(response.metadata.model);
      }

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

      if (response.metadata && response.metadata.model) {
        setConfiguredModel(response.metadata.model);
      }

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
              <h3 className="text-base font-bold text-white tracking-tight">AI Agent Core</h3>
              <span className="inline-flex items-center gap-1 text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 px-2 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Active
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Safe reasoning engine &bull; Model: <span className="text-slate-300 font-mono text-[11px]">{configuredModel}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-lg border border-slate-700/50">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Cryptographic Guardrails</span>
          </div>
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
      <div className="flex-1 p-6 overflow-y-auto space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
          >
            <div
              className={`max-w-[85%] sm:max-w-[75%] rounded-2xl p-4 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-tr-none shadow-md shadow-blue-600/20'
                  : 'bg-slate-800/90 text-slate-200 border border-slate-700/70 rounded-tl-none shadow-sm'
              }`}
            >
              {/* Message Header */}
              <div className="flex items-center gap-2 mb-1.5 opacity-70 text-[11px]">
                {msg.role === 'assistant' ? (
                  <span className="font-semibold text-indigo-300 flex items-center gap-1">
                    <Bot className="w-3.5 h-3.5" /> AI Assistant
                  </span>
                ) : (
                  <span className="font-semibold text-blue-200">You</span>
                )}
                <span>&bull;</span>
                <span>{msg.timestamp}</span>
              </div>

              {/* Message Content */}
              <div className="whitespace-pre-wrap font-sans text-sm">{msg.content}</div>

              {/* M12 Personalization Chip */}
              {msg.personalization?.applied_keys && msg.personalization.applied_keys.length > 0 && (
                <div className="mt-2 flex items-center gap-1.5">
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/35 px-2 py-0.5 rounded-full"
                    title={msg.personalization.reason || 'Personalized preferences applied'}
                  >
                    <Sparkles className="w-3 h-3 text-indigo-400" />
                    <span>Personalized ✦</span>
                    <span className="text-indigo-400/80 lowercase font-mono">({msg.personalization.applied_keys.join(', ')})</span>
                  </span>
                </div>
              )}

              {/* Tool Execution Badges */}
              {msg.toolsCalled && msg.toolsCalled.length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-700/60 space-y-1.5">
                  <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1">
                    <Terminal className="w-3 h-3 text-blue-400" />
                    <span>Tools Executed ({msg.toolsCalled.length})</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {msg.toolsCalled.map((tool, idx) => (
                      <div
                        key={idx}
                        className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border ${
                          tool.status === 'completed'
                            ? 'bg-slate-900/80 border-slate-700 text-slate-300'
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
                        <span className="text-[10px] text-slate-400 font-sans">{tool.summary}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Confirmation Challenge Card */}
              {msg.requiresConfirmation && msg.confirmation && (
                <div className="mt-3 p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 space-y-2.5">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                    <div className="space-y-1 text-xs">
                      <div className="font-semibold text-amber-300 flex items-center gap-1.5">
                        <span>Confirmation Required</span>
                        <span className="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded text-[10px] font-mono">
                          {msg.confirmation.action}
                        </span>
                      </div>
                      <p className="text-amber-200/90">{msg.confirmation.message}</p>
                      <div className="text-[11px] text-amber-300/70 font-mono">
                        Target Resource ID: <span className="text-amber-100">{msg.confirmation.target_id}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={() => handleConfirmAction(msg.confirmation!)}
                      disabled={loading}
                      className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold text-xs transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-50"
                    >
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span>Authorize Operation</span>
                    </button>
                    <button
                      onClick={handleCancelConfirmation}
                      disabled={loading}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex items-start gap-2">
            <div className="bg-slate-800/90 border border-slate-700/70 rounded-2xl rounded-tl-none p-4 text-sm text-slate-400 flex items-center gap-2 shadow-sm">
              <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
              <span>AI is reasoning and executing tools...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold">Request Error</p>
              <p className="mt-0.5 opacity-90">{error}</p>
            </div>
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
            <ShieldCheck className="w-3 h-3 text-emerald-500" /> High-risk tools require one-time HMAC tokens
          </span>
        </div>
      </div>
    </div>
  );
};
