import React, { useState, useEffect, useCallback } from 'react';
import {
  CheckSquare,
  Square,
  Plus,
  Trash2,
  Edit2,
  Clock,
  AlertCircle,
  RefreshCw,
  X,
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
} from '../services/api';

interface TaskCardProps {
  isAuthenticated: boolean;
}

export const TaskCard: React.FC<TaskCardProps> = ({ isAuthenticated }) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [priorityFilter, setPriorityFilter] = useState<string>('');

  // New/Edit Task Modal
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [formTitle, setFormTitle] = useState<string>('');
  const [formDescription, setFormDescription] = useState<string>('');
  const [formPriority, setFormPriority] = useState<'low' | 'medium' | 'high'>('medium');
  const [formDueAt, setFormDueAt] = useState<string>('');
  const [formSaving, setFormSaving] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchTasks({
        status: statusFilter || undefined,
        priority: priorityFilter || undefined,
      });
      setTasks(res.items);
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, statusFilter, priorityFilter]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

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
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPriorityBadgeClass = (priority: string) => {
    switch (priority) {
      case 'high':
        return 'bg-red-500/10 text-red-400 border border-red-500/20';
      case 'medium':
        return 'bg-amber-500/10 text-amber-400 border border-amber-500/20';
      case 'low':
        return 'bg-blue-500/10 text-blue-400 border border-blue-500/20';
      default:
        return 'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20';
    }
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-xl flex flex-col h-full text-zinc-100">
      {/* Card Header */}
      <div className="flex items-center justify-between pb-4 border-b border-zinc-800/80 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-400">
            <CheckSquare className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Tasks</h2>
            <p className="text-xs text-zinc-400">Organize and track your daily action items</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleOpenCreate}
            disabled={!isAuthenticated}
            id="create-task-button"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" />
            New Task
          </button>
          <button
            onClick={loadTasks}
            disabled={loading || !isAuthenticated}
            title="Refresh tasks"
            className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="flex items-center gap-2 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-zinc-800/80 border border-zinc-700/60 rounded-lg px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="completed">Completed</option>
        </select>

        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value)}
          className="bg-zinc-800/80 border border-zinc-700/60 rounded-lg px-2.5 py-1 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500"
        >
          <option value="">All Priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <span className="text-xs text-zinc-500 ml-auto">
          {tasks.length} {tasks.length === 1 ? 'task' : 'tasks'}
        </span>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl flex items-center gap-2.5 text-red-400 text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Task List */}
      <div className="flex-1 overflow-y-auto space-y-2.5 min-h-[220px] max-h-[360px] pr-1">
        {!isAuthenticated ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 text-zinc-500">
            <CheckSquare className="w-8 h-8 mb-2 opacity-40" />
            <p className="text-sm">Sign in to manage tasks</p>
          </div>
        ) : loading && tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-8 text-zinc-500">
            <RefreshCw className="w-6 h-6 animate-spin mb-2 text-indigo-400" />
            <p className="text-xs">Loading tasks...</p>
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 text-zinc-500 border border-dashed border-zinc-800 rounded-xl">
            <CheckCircle2 className="w-8 h-8 mb-2 opacity-40 text-zinc-600" />
            <p className="text-sm font-medium text-zinc-400">No tasks found</p>
            <p className="text-xs text-zinc-500 mt-0.5">Click &quot;New Task&quot; to add your first item.</p>
          </div>
        ) : (
          tasks.map((task) => {
            const isCompleted = task.status === 'completed';
            return (
              <div
                key={task.id}
                className={`group flex items-start justify-between gap-3 p-3 rounded-xl border transition-all ${
                  isCompleted
                    ? 'bg-zinc-950/40 border-zinc-800/40 opacity-60'
                    : 'bg-zinc-800/40 hover:bg-zinc-800/70 border-zinc-800/80 hover:border-zinc-700/80'
                }`}
              >
                <div className="flex items-start gap-2.5 min-w-0">
                  <button
                    onClick={() => handleToggleComplete(task)}
                    className="mt-0.5 text-zinc-400 hover:text-indigo-400 transition-colors flex-shrink-0"
                    title={isCompleted ? 'Mark as pending' : 'Mark as completed'}
                  >
                    {isCompleted ? (
                      <CheckSquare className="w-4 h-4 text-emerald-400" />
                    ) : (
                      <Square className="w-4 h-4" />
                    )}
                  </button>

                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-medium ${
                          isCompleted ? 'line-through text-zinc-500' : 'text-zinc-200'
                        }`}
                      >
                        {task.title}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider ${getPriorityBadgeClass(
                          task.priority
                        )}`}
                      >
                        {task.priority}
                      </span>
                    </div>

                    {task.description && (
                      <p className="text-[11px] text-zinc-400 mt-1 line-clamp-2">
                        {task.description}
                      </p>
                    )}

                    {task.due_at && (
                      <div className="flex items-center gap-1 text-[11px] text-zinc-500 mt-1.5">
                        <Clock className="w-3 h-3" />
                        <span>Due {formatDueDate(task.due_at)}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                  <button
                    onClick={() => handleOpenEdit(task)}
                    title="Edit task"
                    className="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/50 rounded transition-colors"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(task.id)}
                    title="Delete task"
                    className="p-1 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Create / Edit Task Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl w-full max-w-md p-6 shadow-2xl relative text-zinc-100">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-800 mb-4">
              <h3 className="text-base font-semibold">
                {editingTaskId ? 'Edit Task' : 'Create New Task'}
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-zinc-400 hover:text-zinc-200 rounded-lg hover:bg-zinc-800 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              {formError && (
                <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{formError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">
                  Title <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={formTitle}
                  onChange={(e) => setFormTitle(e.target.value)}
                  placeholder="e.g., Review weekly project milestones"
                  required
                  className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Description</label>
                <textarea
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  placeholder="Optional details, bullet points, or notes..."
                  rows={3}
                  className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Priority</label>
                  <select
                    value={formPriority}
                    onChange={(e) => setFormPriority(e.target.value as any)}
                    className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Due Date</label>
                  <input
                    type="datetime-local"
                    value={formDueAt}
                    onChange={(e) => setFormDueAt(e.target.value)}
                    className="w-full bg-zinc-800/80 border border-zinc-700/80 rounded-xl px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl text-xs font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={formSaving}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5"
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
