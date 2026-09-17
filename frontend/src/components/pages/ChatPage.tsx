import React, { useState, useRef, useEffect } from 'react';
import {
  Bot,
  Send,
  Sparkles,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Terminal,
  Wrench,
  Loader2,
  Plus,
  Paperclip,
  ThumbsUp,
  ThumbsDown,
  Copy,
} from 'lucide-react';
import {
  sendAgentMessage,
  AgentChatMessage,
  AgentChatResponse,
  ConfirmationChallenge,
  ToolActivityInfo,
} from '../../services/api';
import { VoiceControls } from '../VoiceControls';
import { sendVoiceChat, VoiceChatResponse } from '../../services/voiceApi';

interface ChatPageProps {
  isAuthenticated: boolean;
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
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

const RECENT_CHATS = [
  { id: '1', title: 'Summarize my unread emails', time: '4:22 PM', prompt: 'Search my inbox for unread messages and summarize the recent ones.' },
  { id: '2', title: 'Plan my study schedule', time: 'Yesterday', prompt: 'Help me plan my study schedule for Cloud Computing and DSA this week.' },
  { id: '3', title: 'Explain RAG architecture', time: 'Sep 15', prompt: 'Explain how personal knowledge RAG retrieval works in this assistant.' },
  { id: '4', title: 'Draft reply to Internshala', time: 'Sep 14', prompt: 'Draft a polite follow-up reply for the Internshala application update.' },
  { id: '5', title: 'Improve my resume', time: 'Sep 13', prompt: 'Give me suggestions to enhance my AI and fullstack projects section on my resume.' },
];

export const ChatPage: React.FC<ChatPageProps> = ({ isAuthenticated }) => {
  const [messages, setMessages] = useState<DisplayMessage[]>([
    {
      id: 'welcome-1',
      role: 'assistant',
      content:
        "Hello Raj! I'm your AI Assistant powered by Google Gemini. I can help you search and summarize emails, organize tasks, check calendar events, and schedule reminders. How can I help you today?",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [inputText, setInputText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<ConfirmationChallenge | null>(null);
  const [lastAudioBase64, setLastAudioBase64] = useState<string | null>(null);
  const [lastAudioMimeType, setLastAudioMimeType] = useState<string | null>(null);
  const [ttsStatus, setTtsStatus] = useState<'success' | 'degraded' | 'disabled' | undefined>(undefined);
  const [activeVoiceExecutionId, setActiveVoiceExecutionId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

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

  const handleNewChat = () => {
    setMessages([
      {
        id: `welcome-${Date.now()}`,
        role: 'assistant',
        content: "New conversation started. How can I help you today?",
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

      const userMsg: DisplayMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: response.transcript || '(voice input)',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

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

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center flex-shrink-0 shadow-xs">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">
                Chat with AI Assistant
              </h1>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                <Sparkles className="w-3 h-3 text-indigo-600" />
                Powered by Google Gemini
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-500">
              Natural language intelligence for tasks, emails, schedule, and queries.
            </p>
          </div>
        </div>

        <button
          onClick={handleNewChat}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs sm:text-sm shadow-xs transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>New Chat</span>
        </button>
      </div>

      {/* Main Chat Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[680px]">
        {/* Left Column: Recent Chats Sidebar */}
        <div className="hidden lg:flex lg:col-span-1 saas-card p-4 flex-col justify-between overflow-hidden">
          <div className="space-y-3 overflow-hidden">
            <div className="text-xs font-bold text-slate-900 uppercase tracking-wider">
              Recent Chats
            </div>
            <div className="space-y-1.5 overflow-y-auto max-h-[540px] pr-1">
              {RECENT_CHATS.map((chat) => (
                <button
                  key={chat.id}
                  onClick={() => handleSendMessage(chat.prompt)}
                  className="w-full p-2.5 rounded-xl text-left hover:bg-slate-50 transition-colors border border-transparent hover:border-slate-200 cursor-pointer group"
                >
                  <div className="text-xs font-semibold text-slate-800 group-hover:text-indigo-600 truncate">
                    {chat.title}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                    {chat.time}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 text-xs font-semibold text-indigo-600 hover:text-indigo-700 cursor-pointer flex items-center gap-1">
            <span>View all chats →</span>
          </div>
        </div>

        {/* Right Column: Conversation Area */}
        <div className="lg:col-span-3 saas-card flex flex-col h-full overflow-hidden">
          {/* Messages Scroll Area */}
          <div className="flex-1 p-4 sm:p-5 overflow-y-auto space-y-3.5 bg-[#F8FAFC]">
            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}
                >
                  <div
                    className={`max-w-[88%] sm:max-w-[80%] rounded-xl p-3.5 text-xs sm:text-sm leading-relaxed ${
                      isUser
                        ? 'bg-[#EEF2FF] text-[#111827] border border-[#E0E7FF] rounded-tr-xs shadow-2xs'
                        : 'bg-white text-[#111827] border border-[#E5E7EB] rounded-tl-xs shadow-2xs'
                    }`}
                  >
                    {/* Message Header */}
                    <div className="flex items-center gap-2 mb-1 text-[11px] text-[#64748B]">
                      {isUser ? (
                        <span className="font-semibold text-[#4F46E5]">You</span>
                      ) : (
                        <span className="font-semibold text-[#111827] flex items-center gap-1">
                          <Bot className="w-3.5 h-3.5 text-[#4F46E5]" /> AI Assistant
                        </span>
                      )}
                      <span>&bull;</span>
                      <span className="text-[#94A3B8]">{msg.timestamp}</span>
                    </div>

                    {/* Content */}
                    <div className="whitespace-pre-wrap font-sans text-xs sm:text-sm text-[#111827]">{msg.content}</div>

                    {/* Tool Badges if executed */}
                    {msg.toolsCalled && msg.toolsCalled.length > 0 && (
                      <div className="mt-2.5 pt-2 border-t border-[#E5E7EB] space-y-1">
                        <div className="text-[10px] uppercase font-semibold text-[#64748B] flex items-center gap-1">
                          <Terminal className="w-3 h-3 text-[#4F46E5]" />
                          <span>Tools Executed ({msg.toolsCalled.length})</span>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {msg.toolsCalled.map((tool, idx) => (
                            <div
                              key={idx}
                              className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border ${
                                tool.status === 'completed'
                                  ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                  : 'bg-amber-50 border-amber-200 text-amber-700'
                              }`}
                            >
                              <Wrench className="w-3 h-3" />
                              <span className="font-medium text-[11px]">{tool.name}</span>
                              {tool.status === 'completed' ? (
                                <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                              ) : (
                                <AlertTriangle className="w-3 h-3 text-amber-600" />
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Confirmation Challenge Box */}
                    {msg.requiresConfirmation && msg.confirmation && (
                      <div className="mt-3 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-900 space-y-2">
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                          <div className="text-xs">
                            <div className="font-bold text-amber-800">Confirmation Required</div>
                            <p className="mt-0.5 text-amber-900">{msg.confirmation.message}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 pt-1">
                          <button
                            onClick={() => handleConfirmAction(msg.confirmation!)}
                            disabled={loading}
                            className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-xs transition-colors cursor-pointer"
                          >
                            Confirm & Execute
                          </button>
                          <button
                            onClick={handleCancelConfirmation}
                            disabled={loading}
                            className="px-3 py-1.5 rounded-lg bg-white border border-[#E5E7EB] text-[#111827] text-xs hover:bg-slate-50 transition-colors cursor-pointer"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Actions footer for assistant bubble */}
                    {!isUser && (
                      <div className="mt-2.5 pt-2 border-t border-[#E5E7EB] flex items-center justify-between text-[#94A3B8]">
                        <div className="flex items-center gap-2">
                          <button className="p-0.5 hover:text-[#64748B] rounded transition-colors" title="Helpful">
                            <ThumbsUp className="w-3 h-3" />
                          </button>
                          <button className="p-0.5 hover:text-[#64748B] rounded transition-colors" title="Not helpful">
                            <ThumbsDown className="w-3 h-3" />
                          </button>
                        </div>
                        <button
                          onClick={() => handleCopy(msg.content, msg.id)}
                          className="flex items-center gap-1 text-[11px] hover:text-[#4F46E5] transition-colors"
                        >
                          <Copy className="w-3 h-3" />
                          <span>{copiedId === msg.id ? 'Copied' : 'Copy'}</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {loading && (
              <div className="flex items-start gap-2">
                <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-none p-3.5 text-xs text-slate-500 flex items-center gap-2 shadow-2xs">
                  <Loader2 className="w-4 h-4 text-indigo-600 animate-spin" />
                  <span>AI Assistant is thinking...</span>
                </div>
              </div>
            )}

            {error && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-xs flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />
                  <span>{error}</span>
                </div>
                <button
                  onClick={() => handleSendMessage()}
                  className="px-2 py-0.5 bg-rose-100 hover:bg-rose-200 text-rose-800 rounded font-semibold text-xs"
                >
                  Retry
                </button>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Bottom Input Area */}
          <div className="p-4 bg-white border-t border-slate-200">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendMessage();
              }}
              className="flex items-center gap-2"
            >
              <div className="relative flex-1">
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={loading || !isAuthenticated}
                  placeholder={
                    isAuthenticated
                      ? "Ask anything... (Press Enter to send)"
                      : "Sign in to chat with the AI Assistant"
                  }
                  rows={1}
                  className="w-full bg-slate-50 border border-slate-200 rounded-xl pl-4 pr-10 py-2.5 text-xs sm:text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:bg-white focus:border-indigo-500 transition-colors resize-none"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  title="Attach file"
                >
                  <Paperclip className="w-4 h-4" />
                </button>
              </div>

              {/* Voice Controls Integration */}
              <VoiceControls
                onAudioRecorded={handleVoiceRecorded}
                disabled={loading || !isAuthenticated}
                isProcessing={Boolean(activeVoiceExecutionId)}
                onCancelProcessing={() => setLoading(false)}
                lastAudioBase64={lastAudioBase64}
                lastAudioMimeType={lastAudioMimeType}
                ttsStatus={ttsStatus}
              />

              {/* Send Button */}
              <button
                type="submit"
                disabled={loading || !inputText.trim() || !isAuthenticated}
                className="w-10 h-10 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl flex items-center justify-center transition-colors shadow-xs disabled:opacity-40 cursor-pointer flex-shrink-0"
                title="Send message"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
