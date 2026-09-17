import React, { useState, useEffect, useCallback } from 'react';
import {
  CheckSquare,
  Square,
  Plus,
  Trash2,
  Edit2,
  Calendar,
  AlertCircle,
  RefreshCw,
  X,
  Search,
  CheckCircle2,
} from 'lucide-react';
import {
  Task,
  TaskCreateInput,
  TaskUpdateInput,
  fetchTasks,
  createTask,
  updateTask,
  completeTask,
  deleteTask,
} from '../../services/api';

interface TasksPageProps {
  isAuthenticated: boolean;
}

export const TasksPage: React.FC<TasksPageProps> = ({ isAuthenticated }) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Tab & Filters
  const [activeTab, setActiveTab] = useState<'my_tasks' | 'completed' | 'all'>('my_tasks');
  const [priorityFilter, setPriorityFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [formTitle, setFormTitle] = useState<string>('');
  const [formDescription, setFormDescription] = useState<string>('');
  const [formPriority, setFormPriority] = useState<'low' | 'medium' | 'high'>('medium');
  const [formDueAt, setFormDueAt] = useState<string>('');
  const [formSaving, setFormSaving] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      let statusParam: string | undefined = undefined;
      if (activeTab === 'my_tasks') statusParam = 'pending';
      if (activeTab === 'completed') statusParam = 'completed';

      const res = await fetchTasks({
        status: statusParam,
        priority: priorityFilter || undefined,
      });
      setTasks(res.items || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [activeTab, priorityFilter, isAuthenticated]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isModalOpen) {
        setIsModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isModalOpen]);

  const handleOpenCreate = () => {
    setEditingTaskId(null);
    setFormTitle('');
    setFormDescription('');
    setFormPriority('medium');
    setFormDueAt('');
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleOpenEdit = (task: Task) => {
    setEditingTaskId(task.id);
    setFormTitle(task.title);
    setFormDescription(task.description || '');
    setFormPriority(task.priority);
    setFormDueAt(task.due_at ? new Date(task.due_at).toISOString().slice(0, 16) : '');
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTitle.trim()) {
      setFormError('Task title is required');
      return;
    }

    setFormSaving(true);
    setFormError(null);

    const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const dueAtIso = formDueAt ? new Date(formDueAt).toISOString() : null;

    try {
      if (editingTaskId) {
        const updateInput: TaskUpdateInput = {
          title: formTitle.trim(),
          description: formDescription.trim() || undefined,
          priority: formPriority,
          due_at: dueAtIso,
          timezone: userTz,
        };
        await updateTask(editingTaskId, updateInput);
      } else {
        const createInput: TaskCreateInput = {
          title: formTitle.trim(),
          description: formDescription.trim() || undefined,
          priority: formPriority,
          due_at: dueAtIso,
          timezone: userTz,
        };
        await createTask(createInput);
      }
      setIsModalOpen(false);
      await loadTasks();
    } catch (err: any) {
      setFormError(err.message || 'Failed to save task');
    } finally {
      setFormSaving(false);
    }
  };

  const handleToggleComplete = async (task: Task) => {
    try {
      if (task.status === 'completed') {
        await updateTask(task.id, { status: 'pending' });
      } else {
        await completeTask(task.id);
      }
      await loadTasks();
    } catch (err: any) {
      setError(err.message || 'Failed to update task status');
    }
  };

  const handleDelete = async (taskId: string) => {
    if (!confirm('Are you sure you want to delete this task?')) return;
    try {
      await deleteTask(taskId);
      await loadTasks();
    } catch (err: any) {
      setError(err.message || 'Failed to delete task');
    }
  };

  const formatDueDate = (dueAtStr: string | null | undefined) => {
    if (!dueAtStr) return null;
    const date = new Date(dueAtStr);
    const today = new Date();
    const isToday =
      date.getDate() === today.getDate() &&
      date.getMonth() === today.getMonth() &&
      date.getFullYear() === today.getFullYear();

    const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (isToday) return `Today, ${timeStr}`;

    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPriorityBadge = (priority: string) => {
    switch (priority.toLowerCase()) {
      case 'high':
        return (
          <span className="px-1.5 py-0.2 rounded text-[10px] font-bold tracking-wide bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]">
            HIGH
          </span>
        );
      case 'medium':
        return (
          <span className="px-1.5 py-0.2 rounded text-[10px] font-bold tracking-wide bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
            MED
          </span>
        );
      case 'low':
        return (
          <span className="px-1.5 py-0.2 rounded text-[10px] font-bold tracking-wide bg-[#ECFDF5] text-[#059669] border border-[#059669]/20">
            LOW
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.2 rounded text-[10px] font-bold tracking-wide bg-slate-100 text-slate-600 border border-[#E5E7EB]">
            {priority}
          </span>
        );
    }
  };

  const filteredTasks = tasks.filter((t) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      t.title.toLowerCase().includes(query) ||
      (t.description && t.description.toLowerCase().includes(query))
    );
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-semibold text-[#111827] tracking-tight">
            Tasks
          </h1>
          <p className="text-xs sm:text-sm text-[#64748B] mt-0.5">
            Organize, track, and get things done with AI.
          </p>
        </div>

        <button
          onClick={handleOpenCreate}
          className="inline-flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-[#4F46E5] hover:bg-[#4338CA] text-white font-medium text-xs sm:text-sm shadow-2xs transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>New Task</span>
        </button>
      </div>

      {/* Main SaaS Card */}
      <div className="saas-card overflow-hidden">
        {/* Tabs Bar */}
        <div className="flex items-center gap-5 px-5 pt-3.5 border-b border-[#E5E7EB]">
          <button
            onClick={() => setActiveTab('my_tasks')}
            className={`pb-2.5 text-xs sm:text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === 'my_tasks'
                ? 'border-[#4F46E5] text-[#4F46E5]'
                : 'border-transparent text-[#64748B] hover:text-[#111827]'
            }`}
          >
            My Tasks
          </button>
          <button
            onClick={() => setActiveTab('completed')}
            className={`pb-2.5 text-xs sm:text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === 'completed'
                ? 'border-[#4F46E5] text-[#4F46E5]'
                : 'border-transparent text-[#64748B] hover:text-[#111827]'
            }`}
          >
            Completed
          </button>
          <button
            onClick={() => setActiveTab('all')}
            className={`pb-2.5 text-xs sm:text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
              activeTab === 'all'
                ? 'border-[#4F46E5] text-[#4F46E5]'
                : 'border-transparent text-[#64748B] hover:text-[#111827]'
            }`}
          >
            All Tasks
          </button>
        </div>

        {/* Filters & Search Row */}
        <div className="p-4 sm:p-5 bg-slate-50/50 border-b border-slate-200 flex flex-col md:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 w-full md:w-auto">
            {/* Priority filter */}
            <select
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              className="bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 focus:outline-none focus:border-indigo-500 cursor-pointer shadow-2xs"
            >
              <option value="">All Priorities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          {/* Search Bar */}
          <div className="relative w-full md:w-72">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tasks..."
              className="w-full pl-9 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-indigo-500 transition-colors shadow-2xs"
            />
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="m-4 p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-500 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Tasks List */}
        <div className="divide-y divide-slate-100">
          {loading ? (
            <div className="py-16 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
              <RefreshCw className="w-5 h-5 animate-spin text-indigo-500" />
              <span>Loading tasks...</span>
            </div>
          ) : filteredTasks.length === 0 ? (
            <div className="py-16 text-center space-y-2">
              <CheckCircle2 className="w-8 h-8 text-slate-300 mx-auto" />
              <div className="text-sm font-semibold text-slate-700">No tasks found</div>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                {searchQuery
                  ? 'No tasks matched your search query.'
                  : 'Click "New Task" above to add your first task.'}
              </p>
            </div>
          ) : (
            filteredTasks.map((task) => {
              const isCompleted = task.status === 'completed';
              return (
                <div
                  key={task.id}
                  className="p-4 sm:p-5 flex items-start justify-between gap-4 hover:bg-slate-50/70 transition-colors group"
                >
                  <div className="flex items-start gap-3.5 min-w-0 flex-1">
                    {/* Checkbox */}
                    <button
                      onClick={() => handleToggleComplete(task)}
                      className="mt-0.5 text-slate-400 hover:text-indigo-600 transition-colors flex-shrink-0 cursor-pointer"
                      title={isCompleted ? 'Mark as pending' : 'Mark as completed'}
                    >
                      {isCompleted ? (
                        <CheckSquare className="w-5 h-5 text-indigo-600" />
                      ) : (
                        <Square className="w-5 h-5 text-slate-300 hover:text-slate-500" />
                      )}
                    </button>

                    {/* Priority & Content */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        {getPriorityBadge(task.priority)}
                        <span
                          className={`text-xs sm:text-sm font-semibold ${
                            isCompleted ? 'line-through text-slate-400' : 'text-slate-900'
                          }`}
                        >
                          {task.title}
                        </span>
                      </div>

                      {task.description && (
                        <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                          {task.description}
                        </p>
                      )}

                      {task.due_at && (
                        <div className="flex items-center gap-1.5 text-xs text-slate-500 mt-2 font-medium">
                          <Calendar className="w-3.5 h-3.5 text-slate-400" />
                          <span>{formatDueDate(task.due_at)}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    <button
                      onClick={() => handleOpenEdit(task)}
                      className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                      title="Edit task"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(task.id)}
                      className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors cursor-pointer"
                      title="Delete task"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* New / Edit Task Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white border border-slate-200 rounded-2xl w-full max-w-md p-6 shadow-2xl relative text-slate-900">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-4">
              <h3 className="text-base font-semibold text-slate-900">
                {editingTaskId ? 'Edit Task' : 'Create New Task'}
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              {formError && (
                <div className="p-2.5 bg-rose-50 border border-rose-200 rounded-lg text-rose-700 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Title <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  placeholder="e.g., Prepare for interview"
                  required
                  className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-xs sm:text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:border-indigo-500 shadow-2xs"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Description
                </label>
                <textarea
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  placeholder="Optional details, notes, or bullet points..."
                  rows={3}
                  className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-xs sm:text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:border-indigo-500 shadow-2xs"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Priority
                  </label>
                  <select
                    value={formPriority}
                    onChange={(e) => setFormPriority(e.target.value as any)}
                    className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-xs sm:text-sm text-slate-900 focus:outline-none focus:border-indigo-500 shadow-2xs cursor-pointer"
                  >
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Due Date
                  </label>
                  <input
                    type="datetime-local"
                    value={formDueAt}
                    onChange={(e) => setFormDueAt(e.target.value)}
                    className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-xs sm:text-sm text-slate-900 focus:outline-none focus:border-indigo-500 shadow-2xs"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-medium transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={formSaving}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5 cursor-pointer shadow-xs"
                >
                  {formSaving && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                  {editingTaskId ? 'Save Changes' : 'Create Task'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
