import React from 'react';
import { Mail, ExternalLink } from 'lucide-react';

export interface EmailCardData {
  id?: string;
  subject: string;
  sender?: string;
  snippet?: string;
  date?: string;
}

interface EmailCardProps {
  data: EmailCardData;
  onOpenEmail?: (id?: string) => void;
}

export const EmailCard: React.FC<EmailCardProps> = ({ data, onOpenEmail }) => {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5 my-2 hover:border-slate-700/80 transition-all hover:bg-slate-900/80">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0 flex-1">
          <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 mt-0.5 flex-shrink-0">
            <Mail className="w-3.5 h-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <h5 className="text-xs font-semibold text-white truncate tracking-tight">
              {data.subject || '(No Subject)'}
            </h5>
            {data.sender && (
              <p className="text-[11px] text-slate-400 truncate mt-0.5">
                From: <span className="text-slate-300 font-medium">{data.sender}</span>
              </p>
            )}
          </div>
        </div>

        {data.id && onOpenEmail && (
          <button
            onClick={() => onOpenEmail(data.id)}
            className="text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 flex-shrink-0 px-2 py-0.5 rounded hover:bg-indigo-500/10 transition-colors cursor-pointer"
          >
            <span>Open</span>
            <ExternalLink className="w-3 h-3" />
          </button>
        )}
      </div>

      {data.snippet && (
        <p className="text-xs text-slate-400 mt-2 line-clamp-2 leading-relaxed font-sans bg-slate-950/40 p-2 rounded-lg border border-slate-800/60">
          {data.snippet}
        </p>
      )}
    </div>
  );
};
