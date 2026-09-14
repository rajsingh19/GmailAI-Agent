import React from 'react';
import { Mail, Calendar, Bot, Shield, Bell, CheckCircle2 } from 'lucide-react';

export const SystemOverview: React.FC = () => {
  const services = [
    {
      icon: Shield,
      title: 'OAuth 2.0 & Multi-Tenant Auth',
      description: 'Encrypted refresh tokens, user isolation, secure HTTP-only cookies.',
      status: 'Ready for Phase 2 & 3',
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      borderColor: 'border-amber-500/20',
    },
    {
      icon: Mail,
      title: 'Gmail Service',
      description: 'Inbox analysis, thread reading, AI drafting, with confirmation on send.',
      status: 'Ready for Phase 4',
      color: 'text-rose-400',
      bgColor: 'bg-rose-500/10',
      borderColor: 'border-rose-500/20',
    },
    {
      icon: Calendar,
      title: 'Google Calendar Service',
      description: 'Daily agenda reading, event creation, smart conflict resolution.',
      status: 'Ready for Phase 4',
      color: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
      borderColor: 'border-blue-500/20',
    },
    {
      icon: Bot,
      title: 'LLM Agent Orchestrator',
      description: 'Gemini API tool calling engine with pluggable model adapter layer.',
      status: 'Ready for Phase 5',
      color: 'text-purple-400',
      bgColor: 'bg-purple-500/10',
      borderColor: 'border-purple-500/20',
    },
    {
      icon: Bell,
      title: 'Reminders & APScheduler',
      description: 'Proactive background jobs for email checks and schedule reminders.',
      status: 'Ready for Phase 6',
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/20',
    },
  ];

  return (
    <div className="mt-8 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-200">System Architectural Blueprint</h3>
        <span className="text-xs font-medium text-slate-400 bg-slate-900 border border-slate-800 px-2.5 py-1 rounded-full">
          Monorepo Scaffolded
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.map((srv, idx) => {
          const Icon = srv.icon;
          return (
            <div
              key={idx}
              className="glass-panel p-5 rounded-xl border border-slate-800/90 hover:border-slate-700 transition-all group"
            >
              <div className="flex items-start justify-between">
                <div className={`p-2.5 rounded-lg ${srv.bgColor} ${srv.color} border ${srv.borderColor}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-800">
                  <CheckCircle2 className="w-3 h-3 text-blue-400" />
                  {srv.status}
                </span>
              </div>
              <h4 className="font-semibold text-slate-100 text-sm mt-3 group-hover:text-blue-400 transition-colors">
                {srv.title}
              </h4>
              <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                {srv.description}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
};
