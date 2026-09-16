import React, { useState, useEffect, useCallback } from 'react';
import {
  Brain,
  Search,
  Plus,
  Trash2,
  Edit2,
  CheckCircle2,
  ShieldCheck,
  ShieldAlert,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
  Sliders,
  Tag,
  FileText,
  Workflow,
  FolderGit2,
  X,
  AlertTriangle,
} from 'lucide-react';
import {
  MemoryItem,
  MemoryCategory,
  MemoryStatsResponse,
  fetchMemories,
  createMemory,
  updateMemory,
  deactivateMemory,
  deleteMemory,
  fetchMemoryStats,
  searchMemories,
  fetchProactivePreferences,
  updateProactivePreferences,
} from '../services/api';

interface MemoryManagerProps {
  isAuthenticated: boolean;
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
}

export const MemoryManager: React.FC<MemoryManagerProps> = ({ isAuthenticated, onNotify }) => {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [stats, setStats] = useState<MemoryStatsResponse | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [toggling, setToggling] = useState<boolean>(false);

  // Filter & Search state
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [editingMemory, setEditingMemory] = useState<MemoryItem | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [deletingMemory, setDeletingMemory] = useState<MemoryItem | null>(null);

  // Form states
  const [formCategory, setFormCategory] = useState<MemoryCategory>('user_preference');
  const [formKey, setFormKey] = useState<string>('');
  const [formValue, setFormValue] = useState<string>('');
  const [formDescription, setFormDescription] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);

  const loadData = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const [statsData, prefData] = await Promise.all([
        fetchMemoryStats().catch(() => null),
        fetchProactivePreferences().catch(() => null),
      ]);

      if (prefData) {
        setMemoryEnabled(Boolean(prefData.memory_enabled));
      }
      if (statsData) {
        setStats(statsData);
      }

      if (searchQuery.trim()) {
        const searchRes = await searchMemories(
          searchQuery.trim(),
          selectedCategory !== 'all' ? selectedCategory : undefined
        );
        setMemories(searchRes.results);
      } else {
        const catParam = selectedCategory !== 'all' ? selectedCategory : undefined;
        const listRes = await fetchMemories({ category: catParam });
        setMemories(listRes.items);
      }
    } catch (err: any) {
      console.error('Failed to load memory data:', err);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, searchQuery, selectedCategory]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleToggleMemory = async () => {
    setToggling(true);
    try {
      const newStatus = !memoryEnabled;
      await updateProactivePreferences({ memory_enabled: newStatus });
      setMemoryEnabled(newStatus);
      onNotify?.(
        newStatus
          ? 'Personal Long-Term Memory has been enabled.'
          : 'Personal Memory disabled. Existing memories are preserved securely.',
        'info'
      );
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to update memory setting', 'error');
    } finally {
      setToggling(false);
    }
  };

  const handleCreateMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formKey.trim() || !formValue.trim()) {
      onNotify?.('Please provide both a key and a value.', 'error');
      return;
    }

    setSubmitting(true);
    try {
      await createMemory({
        category: formCategory,
        key: formKey.trim(),
        value: formValue.trim(),
        description: formDescription.trim() || undefined,
        confidence: 'EXPLICIT',
        source: 'user_ui',
        explicitly_confirmed: true,
      });

      onNotify?.(`Memory '${formKey.trim()}' saved successfully!`, 'success');
      setIsCreateModalOpen(false);
      setFormKey('');
      setFormValue('');
      setFormDescription('');
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to save memory', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingMemory) return;

    setSubmitting(true);
    try {
      await updateMemory(editingMemory.id, {
        value: formValue.trim(),
        description: formDescription.trim() || undefined,
        category: formCategory,
      });

      onNotify?.(`Memory '${editingMemory.key}' updated successfully!`, 'success');
      setIsEditModalOpen(false);
      setEditingMemory(null);
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to update memory', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleActive = async (mem: MemoryItem) => {
    try {
      if (mem.active) {
        await deactivateMemory(mem.id);
        onNotify?.(`Deactivated '${mem.key}'. It will not be used in chat context.`, 'info');
      } else {
        await updateMemory(mem.id, { active: true });
        onNotify?.(`Reactivated '${mem.key}'.`, 'success');
      }
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to change memory status', 'error');
    }
  };

  const handleDeleteMemory = async () => {
    if (!deletingMemory) return;
    setSubmitting(true);
    try {
      await deleteMemory(deletingMemory.id);
      onNotify?.(`Memory '${deletingMemory.key}' permanently deleted.`, 'success');
      setIsDeleteModalOpen(false);
      setDeletingMemory(null);
      loadData();
    } catch (err: any) {
      onNotify?.(err.message || 'Failed to delete memory', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const openEditModal = (mem: MemoryItem) => {
    setEditingMemory(mem);
    setFormCategory(mem.category);
    setFormKey(mem.key);
    setFormValue(mem.value);
    setFormDescription(mem.description || '');
    setIsEditModalOpen(true);
  };

  const openDeleteModal = (mem: MemoryItem) => {
    setDeletingMemory(mem);
    setIsDeleteModalOpen(true);
  };

  const categories = [
    { id: 'all', label: 'All Categories', icon: Brain },
    { id: 'user_preference', label: 'Preferences', icon: Sliders },
    { id: 'user_fact', label: 'Personal Facts', icon: FileText },
    { id: 'project_context', label: 'Project Context', icon: FolderGit2 },
    { id: 'workflow_preference', label: 'Workflows', icon: Workflow },
    { id: 'explicit_user_memory', label: 'Explicit Memory', icon: Tag },
  ];

  return (
    <div className="glass-panel rounded-2xl p-6 border border-slate-800/80 bg-slate-900/40 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20 shadow-lg shadow-purple-500/10">
            <Brain className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base sm:text-lg font-bold text-white tracking-tight">
                Long-Term Personal Memory & Personalization
              </h3>
              <span className="inline-flex items-center text-[10px] font-semibold uppercase tracking-wider bg-purple-500/15 text-purple-300 border border-purple-500/30 px-2 py-0.5 rounded-full">
                Milestone 11
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Structured user facts, coding preferences, and project context with deterministic agent personalization.
            </p>
          </div>
        </div>

        {/* Master Toggle & Add Button */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleToggleMemory}
            disabled={toggling || !isAuthenticated}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
              memoryEnabled
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20'
                : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {memoryEnabled ? (
              <>
                <ToggleRight className="w-4 h-4 text-emerald-400" />
                <span>Memory Active</span>
              </>
            ) : (
              <>
                <ToggleLeft className="w-4 h-4 text-slate-500" />
                <span>Memory Disabled (Opt-In)</span>
              </>
            )}
          </button>

          <button
            onClick={() => {
              setFormCategory('user_preference');
              setFormKey('');
              setFormValue('');
              setFormDescription('');
              setIsCreateModalOpen(true);
            }}
            disabled={!isAuthenticated}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md shadow-purple-600/25 transition-all cursor-pointer disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Memory</span>
          </button>
        </div>
      </div>

      {/* Privacy Notice Banner if Disabled */}
      {!memoryEnabled && (
        <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-start gap-3 text-xs text-amber-300">
          <ShieldAlert className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Privacy-First Mode Active:</span> Personal Memory is currently turned off.
            The assistant will not inject memories or infer new preferences in chat turns until you turn it on. Existing stored memories remain preserved safely.
          </div>
        </div>
      )}

      {/* Stats Summary Bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800/60">
            <div className="text-[11px] text-slate-400 font-medium">Total Memories</div>
            <div className="text-lg font-bold text-white mt-0.5">{stats.total_memories}</div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800/60">
            <div className="text-[11px] text-slate-400 font-medium">Active Memories</div>
            <div className="text-lg font-bold text-emerald-400 mt-0.5">{stats.active_memories}</div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800/60">
            <div className="text-[11px] text-slate-400 font-medium">Deactivated</div>
            <div className="text-lg font-bold text-slate-400 mt-0.5">{stats.inactive_memories}</div>
          </div>
          <div className="p-3 rounded-xl bg-slate-950/50 border border-slate-800/60">
            <div className="text-[11px] text-slate-400 font-medium">Secret Scanning</div>
            <div className="text-xs font-semibold text-blue-400 mt-1 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Active Heuristic</span>
            </div>
          </div>
        </div>
      )}

      {/* Category Tabs & Search Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pt-2">
        {/* Category Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0 scrollbar-none">
          {categories.map((cat) => {
            const Icon = cat.icon;
            const isSelected = selectedCategory === cat.id;
            return (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all cursor-pointer ${
                  isSelected
                    ? 'bg-purple-600/20 text-purple-300 border border-purple-500/40 shadow-sm'
                    : 'bg-slate-800/40 text-slate-400 hover:text-slate-200 hover:bg-slate-800/80 border border-transparent'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{cat.label}</span>
              </button>
            );
          })}
        </div>

        {/* Search Input */}
        <div className="relative w-full md:w-64 flex-shrink-0">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search key or value..."
            className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-slate-950/70 border border-slate-800 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
          />
        </div>
      </div>

      {/* Memories List */}
      <div className="space-y-2.5">
        {loading ? (
          <div className="py-12 flex flex-col items-center justify-center text-slate-500 text-xs gap-2">
            <RefreshCw className="w-5 h-5 animate-spin text-purple-400" />
            <span>Loading personal memories...</span>
          </div>
        ) : memories.length === 0 ? (
          <div className="py-10 text-center rounded-xl bg-slate-950/30 border border-slate-800/50 p-6 space-y-2">
            <Brain className="w-8 h-8 text-slate-600 mx-auto" />
            <div className="text-xs font-semibold text-slate-300">No personal memories found</div>
            <p className="text-[11px] text-slate-500 max-w-sm mx-auto">
              {searchQuery
                ? 'No memories matched your search query.'
                : 'Click "Add Memory" or say "Remember that I prefer..." in chat turns.'}
            </p>
          </div>
        ) : (
          memories.map((mem) => {
            const isExplicit = mem.confidence === 'EXPLICIT';
            return (
              <div
                key={mem.id}
                className={`p-3.5 rounded-xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                  mem.active
                    ? 'bg-slate-950/60 border-slate-800/80 hover:border-slate-700'
                    : 'bg-slate-950/20 border-slate-800/40 opacity-60'
                }`}
              >
                <div className="space-y-1 flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold text-purple-300">{mem.key}</span>
                    <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 border border-slate-700/60">
                      {mem.category.replace('_', ' ')}
                    </span>
                    <span
                      className={`text-[10px] font-semibold px-2 py-0.5 rounded-md border ${
                        isExplicit
                          ? 'bg-blue-500/10 text-blue-300 border-blue-500/30'
                          : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                      }`}
                    >
                      {mem.confidence} ({mem.confidence_score * 100}%)
                    </span>
                    {mem.explicitly_confirmed && (
                      <span className="text-[10px] text-emerald-400 flex items-center gap-1 font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        Confirmed
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-slate-200 font-medium break-words">
                    <span className="text-slate-400">Value:</span> {mem.value}
                  </div>

                  {mem.description && (
                    <div className="text-[11px] text-slate-400 italic break-words">{mem.description}</div>
                  )}

                  <div className="flex items-center gap-3 text-[10px] text-slate-500 pt-0.5">
                    <span>Source: {mem.source}</span>
                    <span>&bull;</span>
                    <span>Updated: {new Date(mem.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 self-end sm:self-center flex-shrink-0">
                  <button
                    onClick={() => handleToggleActive(mem)}
                    title={mem.active ? 'Deactivate Memory' : 'Reactivate Memory'}
                    className={`p-1.5 rounded-lg border text-xs font-medium transition-colors cursor-pointer ${
                      mem.active
                        ? 'bg-slate-800/80 hover:bg-slate-800 text-emerald-400 border-slate-700'
                        : 'bg-slate-800/40 hover:bg-slate-800 text-slate-500 border-slate-800'
                    }`}
                  >
                    {mem.active ? 'Active' : 'Inactive'}
                  </button>
                  <button
                    onClick={() => openEditModal(mem)}
                    className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700 transition-colors cursor-pointer"
                    title="Edit Memory"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => openDeleteModal(mem)}
                    className="p-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 transition-colors cursor-pointer"
                    title="Delete Memory"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Create Memory Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-400" />
                Add Personal Memory
              </h4>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="p-1 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateMemory} className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Category</label>
                <select
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value as MemoryCategory)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="user_preference">User Preference (Coding style, language, framework)</option>
                  <option value="user_fact">User Fact (Stable goals, roles, non-sensitive context)</option>
                  <option value="project_context">Project Context (Project name, tech stack, constraints)</option>
                  <option value="workflow_preference">Workflow Preference (Git conventions, formatting)</option>
                  <option value="explicit_user_memory">Explicit Memory (General user request)</option>
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Key Identifier</label>
                <input
                  type="text"
                  value={formKey}
                  onChange={(e) => setFormKey(e.target.value)}
                  placeholder="e.g., coding.framework or preferred_language"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Memory Value</label>
                <textarea
                  value={formValue}
                  onChange={(e) => setFormValue(e.target.value)}
                  placeholder="e.g., FastAPI with PostgreSQL and React 18"
                  rows={3}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Optional Description / Notes</label>
                <input
                  type="text"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  placeholder="e.g., Stated during architecture discussion"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-semibold text-white shadow-md shadow-purple-600/25 transition-all cursor-pointer disabled:opacity-50"
                >
                  {submitting ? 'Saving...' : 'Save Memory'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Memory Modal */}
      {isEditModalOpen && editingMemory && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Edit2 className="w-4 h-4 text-purple-400" />
                Edit Memory: {editingMemory.key}
              </h4>
              <button
                onClick={() => setIsEditModalOpen(false)}
                className="p-1 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleUpdateMemory} className="space-y-3">
              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Category</label>
                <select
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value as MemoryCategory)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="user_preference">User Preference</option>
                  <option value="user_fact">User Fact</option>
                  <option value="project_context">Project Context</option>
                  <option value="workflow_preference">Workflow Preference</option>
                  <option value="explicit_user_memory">Explicit Memory</option>
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Value</label>
                <textarea
                  value={formValue}
                  onChange={(e) => setFormValue(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-medium text-slate-400 mb-1">Description / Notes</label>
                <input
                  type="text"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-white focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-semibold text-white shadow-md shadow-purple-600/25 transition-all cursor-pointer disabled:opacity-50"
                >
                  {submitting ? 'Updating...' : 'Update Memory'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {isDeleteModalOpen && deletingMemory && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-rose-500/30 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400">
              <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <h4 className="text-sm font-bold text-white">Delete Memory?</h4>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Are you sure you want to permanently delete <strong className="text-white font-mono">{deletingMemory.key}</strong>? This action cannot be undone.
            </p>

            <div className="pt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsDeleteModalOpen(false)}
                className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteMemory}
                disabled={submitting}
                className="px-4 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-xs font-semibold text-white shadow-md shadow-rose-600/25 transition-all cursor-pointer disabled:opacity-50"
              >
                {submitting ? 'Deleting...' : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
