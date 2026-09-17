import React, { useState, useEffect } from 'react';
import {
  BookOpen,
  Search,
  RefreshCw,
  Mail,
  Calendar,
  CheckSquare,
  Bell,
  Sparkles,
  ShieldCheck,
  Database,
  Layers,
} from 'lucide-react';
import {
  KnowledgeStatusResponse,
  KnowledgeResultItem,
  fetchKnowledgeStatus,
  searchKnowledge,
  reindexKnowledge,
} from '../services/api';

interface PersonalKnowledgeCardProps {
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
}

export const PersonalKnowledgeCard: React.FC<PersonalKnowledgeCardProps> = ({ onNotify }) => {
  const [status, setStatus] = useState<KnowledgeStatusResponse | null>(null);
  const [reindexing, setReindexing] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSource, setSelectedSource] = useState<string>('all');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<KnowledgeResultItem[]>([]);
  const [hasSearched, setHasSearched] = useState(false);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const data = await fetchKnowledgeStatus();
      setStatus(data);
    } catch (err: any) {
      // Don't show toast on initial mount if unauthenticated
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    try {
      const res = await reindexKnowledge();
      await loadStatus();
      onNotify?.(
        `Knowledge synced: ${res.documents_indexed} indexed, ${res.documents_skipped} up to date (${res.chunks_created} chunks)`,
        'success'
      );
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to sync knowledge', 'error');
    } finally {
      setReindexing(false);
    }
  };

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearching(true);
    setHasSearched(true);
    try {
      const res = await searchKnowledge({
        query: searchQuery,
        source_type: selectedSource === 'all' ? null : selectedSource,
        top_k: 6,
      });
      setSearchResults(res.results);
    } catch (err: any) {
      onNotify?.(err.message || 'Semantic search failed', 'error');
    } finally {
      setSearching(false);
    }
  };

  const getSourceIcon = (sourceType: string) => {
    switch (sourceType) {
      case 'gmail':
        return <Mail className="w-4 h-4 text-rose-400" />;
      case 'calendar':
        return <Calendar className="w-4 h-4 text-sky-400" />;
      case 'task':
        return <CheckSquare className="w-4 h-4 text-emerald-400" />;
      case 'reminder':
        return <Bell className="w-4 h-4 text-amber-400" />;
      default:
        return <BookOpen className="w-4 h-4 text-indigo-400" />;
    }
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 backdrop-blur-xl shadow-xl flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 text-indigo-400 shadow-inner">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
              Personal Knowledge
            </h2>
            <p className="text-xs text-slate-400">
              Search and retrieve information across your connected emails, calendar events, tasks, and reminders
            </p>
          </div>
        </div>

        <button
          onClick={handleReindex}
          disabled={reindexing}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-indigo-600/20 border border-indigo-500/30 hover:bg-indigo-600/30 text-indigo-300 text-xs font-medium transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-sm hover:shadow"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${reindexing ? 'animate-spin' : ''}`} />
          {reindexing ? 'Syncing...' : 'Sync Knowledge'}
        </button>
      </div>

      {/* Indexing Stats Banner */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-950/40 border border-slate-800/60 rounded-xl p-3">
        <div className="flex items-center gap-2.5">
          <Database className="w-4 h-4 text-indigo-400" />
          <div>
            <div className="text-[11px] text-slate-400">Saved Items</div>
            <div className="text-sm font-semibold text-slate-200">
              {status ? status.total_documents : 0}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <Layers className="w-4 h-4 text-purple-400" />
          <div>
            <div className="text-[11px] text-slate-400">Knowledge Index</div>
            <div className="text-sm font-semibold text-slate-200">
              {status ? status.total_chunks : 0}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          <div>
            <div className="text-[11px] text-slate-400">AI Search</div>
            <div className="text-sm font-semibold text-emerald-400">Active</div>
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="w-4 h-4 text-sky-400" />
          <div>
            <div className="text-[11px] text-slate-400">Privacy</div>
            <div className="text-sm font-semibold text-sky-400">User Isolated</div>
          </div>
        </div>
      </div>

      {/* Semantic Search Bar */}
      <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search topics (e.g., 'What did Alex say about the project timeline?')..."
            className="w-full bg-slate-950/60 border border-slate-800/80 rounded-xl pl-10 pr-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/50 transition-all shadow-inner"
          />
        </div>
        <button
          type="submit"
          disabled={searching || !searchQuery.trim()}
          className="flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-sm font-medium transition-all shadow-md shadow-indigo-900/20 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {searching ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          Search
        </button>
      </form>

      {/* Source Filters */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        <span className="text-[11px] text-slate-500 mr-1">Filter:</span>
        {['all', 'gmail', 'calendar', 'task', 'reminder'].map((src) => (
          <button
            key={src}
            type="button"
            onClick={() => setSelectedSource(src)}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium capitalize transition-all cursor-pointer ${
              selectedSource === src
                ? 'bg-indigo-500/20 border border-indigo-500/40 text-indigo-300'
                : 'bg-slate-950/30 border border-slate-800/50 text-slate-400 hover:text-slate-200'
            }`}
          >
            {src}
          </button>
        ))}
      </div>

      {/* Search Results */}
      {hasSearched && (
        <div className="flex flex-col gap-3 mt-1">
          <div className="flex items-center justify-between text-xs text-slate-400 font-medium px-1">
            <span>Search Results ({searchResults.length} excerpts found)</span>
            <span className="text-[11px] text-slate-500">Sorted by Cosine Similarity</span>
          </div>

          {searchResults.length === 0 ? (
            <div className="text-center py-8 rounded-xl bg-slate-950/20 border border-slate-800/40 text-slate-400 text-xs">
              No matching knowledge excerpts found. Try syncing knowledge or broadening your query.
            </div>
          ) : (
            <div className="flex flex-col gap-2.5 max-h-[380px] overflow-y-auto pr-1">
              {searchResults.map((item) => (
                <div
                  key={item.citation_id}
                  className="bg-slate-950/40 border border-slate-800/60 rounded-xl p-3.5 hover:border-slate-700/60 transition-all flex flex-col gap-2 shadow-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      {getSourceIcon(item.source_type)}
                      <span className="text-xs font-semibold text-slate-200 truncate">
                        {item.title}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                        {item.citation_id}
                      </span>
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400">
                        {Math.round(item.similarity_score * 100)}% match
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-300 line-clamp-3 leading-relaxed font-sans bg-slate-900/30 p-2 rounded-lg border border-slate-800/40 whitespace-pre-line">
                    {item.snippet}
                  </p>

                  <div className="flex items-center justify-between text-[10px] text-slate-500 pt-0.5">
                    <span className="capitalize">{item.source_type}</span>
                    <span>{item.timestamp ? new Date(item.timestamp).toLocaleString() : ''}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
