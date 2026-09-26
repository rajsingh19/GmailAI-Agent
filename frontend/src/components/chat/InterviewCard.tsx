import React from 'react';
import {
  Briefcase,
  Mail,
  ExternalLink,
  AlertCircle,
  Clock3,
  CalendarClock,
} from 'lucide-react';

export interface InterviewCardData {
  id?: string;
  status: 'UPCOMING' | 'PENDING_ACTION' | 'EXPIRED_PAST' | 'HISTORICAL' | string;
  subject: string;
  scheduledTime?: string;
  sender?: string;
  snippet?: string;
  url?: string;
}

interface InterviewCardProps {
  data: InterviewCardData;
  onOpenEmail?: (id?: string) => void;
}

export const InterviewCard: React.FC<InterviewCardProps> = ({ data, onOpenEmail }) => {
  const normStatus = (data.status || 'UPCOMING').toUpperCase();
  const isUpcoming = normStatus === 'UPCOMING';
  const isPending = normStatus === 'PENDING_ACTION' || normStatus === 'ACTION_REQUIRED';

  const getStatusBadge = () => {
    if (isUpcoming) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shadow-2xs">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          Upcoming Interview
        </span>
      );
    }
    if (isPending) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30 shadow-2xs">
          <AlertCircle className="w-3 h-3 text-amber-400" />
          Action Required
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-400 border border-slate-700">
        <Clock3 className="w-3 h-3 text-slate-400" />
        Past / Completed
      </span>
    );
  };

  const getBorderColor = () => {
    if (isUpcoming) return 'border-emerald-500/40 bg-gradient-to-br from-slate-900/90 via-slate-900/80 to-emerald-950/20';
    if (isPending) return 'border-amber-500/40 bg-gradient-to-br from-slate-900/90 via-slate-900/80 to-amber-950/20';
    return 'border-slate-800 bg-slate-900/60';
  };

  return (
    <div
      className={`rounded-xl border p-4 my-2.5 transition-all duration-200 hover:shadow-lg shadow-sm ${getBorderColor()}`}
    >
      {/* Top Header: Badge + Actions */}
      <div className="flex items-center justify-between gap-3 mb-2.5">
        <div className="flex items-center gap-2">
          <div
            className={`p-1.5 rounded-lg border ${
              isUpcoming
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                : isPending
                ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                : 'bg-slate-800 border-slate-700 text-slate-400'
            }`}
          >
            <Briefcase className="w-4 h-4" />
          </div>
          {getStatusBadge()}
        </div>

        {data.id && onOpenEmail && (
          <button
            onClick={() => onOpenEmail(data.id)}
            className="text-[11px] font-medium text-indigo-400 hover:text-indigo-300 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-indigo-500/10 transition-colors cursor-pointer"
            title="View message in Gmail inbox"
          >
            <span>View Email</span>
            <ExternalLink className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* Subject / Title */}
      <h4 className="text-sm font-semibold text-white tracking-tight mb-2 flex items-start gap-1.5">
        <span>{data.subject}</span>
      </h4>

      {/* Details Grid: Date/Time + Sender */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-300 mb-2.5">
        {data.scheduledTime && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-slate-950/40 border border-slate-800/80">
            <CalendarClock className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
            <div className="truncate">
              <span className="text-[10px] text-slate-400 block font-medium">Scheduled / Deadline</span>
              <span className="font-semibold text-slate-200">{data.scheduledTime}</span>
            </div>
          </div>
        )}

        {data.sender && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-slate-950/40 border border-slate-800/80">
            <Mail className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
            <div className="truncate">
              <span className="text-[10px] text-slate-400 block font-medium">From / Recruiter</span>
              <span className="text-slate-300 truncate block" title={data.sender}>
                {data.sender}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Snippet / Notes if available */}
      {data.snippet && (
        <div className="text-xs text-slate-400 bg-slate-950/30 p-2.5 rounded-lg border border-slate-800/50 leading-relaxed font-sans">
          {data.snippet}
        </div>
      )}
    </div>
  );
};
