import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Sliders,
  CheckCircle2,
  RefreshCw,
  Clock,
  Check,
} from 'lucide-react';
import {
  fetchPersonalizationConfig,
  updatePersonalizationConfig,
  setPersonalizationSessionOverride,
  PersonalizationConfigResponse,
  PersonalizationLevelType,
} from '../services/api';

interface PersonalizationSettingsProps {
  currentSessionId?: string;
  onClose?: () => void;
}

export const PersonalizationSettings: React.FC<PersonalizationSettingsProps> = ({
  currentSessionId = 'current_session',
  onClose,
}) => {
  const [config, setConfig] = useState<PersonalizationConfigResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Session override state
  const [sessionBypassActive, setSessionBypassActive] = useState<boolean>(false);
  const [overrideLoading, setOverrideLoading] = useState<boolean>(false);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPersonalizationConfig();
      setConfig(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load personalization settings');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleEnabled = async (enabled: boolean) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePersonalizationConfig({ personalization_enabled: enabled });
      setConfig(updated);
      setSuccessMessage(enabled ? 'Personalization activated' : 'Personalization turned off');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to update personalization setting');
    } finally {
      setSaving(false);
    }
  };

  const handleLevelChange = async (level: PersonalizationLevelType) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePersonalizationConfig({ personalization_level: level });
      setConfig(updated);
      setSuccessMessage(`Personalization level updated to ${level}`);
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to update level');
    } finally {
      setSaving(false);
    }
  };

  const handleCategoryToggle = async (key: 'style' | 'project' | 'workflow', val: boolean) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        personalize_response_style: key === 'style' ? val : config.personalize_response_style,
        personalize_project_context: key === 'project' ? val : config.personalize_project_context,
        personalize_workflow_habits: key === 'workflow' ? val : config.personalize_workflow_habits,
      };
      const updated = await updatePersonalizationConfig(payload);
      setConfig(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to update category setting');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleSessionBypass = async () => {
    setOverrideLoading(true);
    setError(null);
    try {
      const nextState = !sessionBypassActive;
      await setPersonalizationSessionOverride(currentSessionId, nextState);
      setSessionBypassActive(nextState);
      setSuccessMessage(
        nextState
          ? 'Personalization temporarily bypassed for this session.'
          : 'Personalization resumed for this session.'
      );
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to toggle session override');
    } finally {
      setOverrideLoading(false);
    }
  };

  return (
    <div className="glass-panel-glow rounded-2xl p-6 sm:p-8 transition-all duration-300">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-indigo-500/20 to-purple-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-lg shadow-indigo-500/10">
            <Sliders className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white tracking-tight flex items-center gap-2.5">
              Personalization Settings
              {config?.personalization_enabled ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse"></span>
                  Personalization Active
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
                  Standard Mode
                </span>
              )}
            </h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Optionally tailor how the assistant structures responses based on your communication style and project context.
            </p>
          </div>
        </div>

        {onClose && (
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-200 bg-slate-900 hover:bg-slate-800 border border-slate-800 transition-colors cursor-pointer"
          >
            ✕
          </button>
        )}
      </div>

      {/* Permissions & Security Note */}
      <div className="mt-4 p-3 rounded-xl bg-slate-950/40 border border-slate-800/60 text-xs text-slate-400 leading-relaxed">
        <strong className="text-slate-300">Privacy Note:</strong> Personalization only affects the style and context of assistant responses. It does not grant permissions to modify your accounts or execute actions automatically.
      </div>

      {/* Status Alerts */}
      {error && (
        <div className="mt-5 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-start gap-3 text-xs">
          <span>{error}</span>
        </div>
      )}
      {successMessage && (
        <div className="mt-5 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 flex items-center gap-2 text-xs">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
          <RefreshCw className="w-4 h-4 animate-spin text-indigo-400" />
          <span>Loading personalization settings...</span>
        </div>
      ) : config ? (
        <div className="mt-6 space-y-6">
          {/* Master Toggle */}
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="text-base font-semibold text-white flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                Master Personalization
              </div>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                {config.personalization_enabled
                  ? 'Enabled — The assistant incorporates your preferred response style and workflow preferences.'
                  : 'Disabled — The assistant responds using default standard formatting.'}
              </p>
            </div>
            <button
              onClick={() => handleToggleEnabled(!config.personalization_enabled)}
              disabled={saving}
              className={`px-5 py-2.5 rounded-xl text-xs font-semibold transition-all cursor-pointer disabled:opacity-50 flex items-center gap-2 ${
                config.personalization_enabled
                  ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/25'
                  : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'
              }`}
            >
              {config.personalization_enabled ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  Personalization ON
                </>
              ) : (
                'Turn ON'
              )}
            </button>
          </div>

          {/* Personalization Level */}
          <div
            className={`space-y-3 transition-opacity ${
              config.personalization_enabled ? 'opacity-100' : 'opacity-40 pointer-events-none'
            }`}
          >
            <div className="text-sm font-semibold text-slate-200">Personalization Level</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {(['NONE', 'LOW', 'MEDIUM', 'HIGH'] as PersonalizationLevelType[]).map((lvl) => {
                const isSelected = config.personalization_level === lvl;
                return (
                  <button
                    key={lvl}
                    onClick={() => handleLevelChange(lvl)}
                    disabled={saving || !config.personalization_enabled}
                    className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-indigo-600/15 border-indigo-500/50 text-white shadow-sm ring-1 ring-indigo-500/30'
                        : 'bg-slate-900/50 hover:bg-slate-800/60 border-slate-800 text-slate-300'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold tracking-wide">{lvl}</span>
                      {isSelected && <span className="w-2 h-2 rounded-full bg-indigo-400"></span>}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-1">
                      {lvl === 'NONE'
                        ? 'Standard output'
                        : lvl === 'LOW'
                        ? 'Response style only'
                        : lvl === 'MEDIUM'
                        ? 'Style + project context'
                        : 'Full contextual awareness'}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Active Scopes */}
          <div
            className={`bg-slate-900/40 border border-slate-800/80 rounded-xl p-5 space-y-3 transition-opacity ${
              config.personalization_enabled ? 'opacity-100' : 'opacity-40 pointer-events-none'
            }`}
          >
            <div className="text-sm font-semibold text-slate-200">Active Scopes</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label className="flex items-start gap-3 p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 hover:border-slate-700 cursor-pointer transition-colors">
                <input
                  type="checkbox"
                  checked={config.personalize_response_style}
                  onChange={(e) => handleCategoryToggle('style', e.target.checked)}
                  disabled={saving || !config.personalization_enabled}
                  className="mt-0.5 rounded border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
                <div>
                  <div className="text-xs font-semibold text-slate-200">Response Style</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">Conciseness and communication tone</div>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 hover:border-slate-700 cursor-pointer transition-colors">
                <input
                  type="checkbox"
                  checked={config.personalize_project_context}
                  onChange={(e) => handleCategoryToggle('project', e.target.checked)}
                  disabled={saving || !config.personalization_enabled}
                  className="mt-0.5 rounded border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
                <div>
                  <div className="text-xs font-semibold text-slate-200">Project Context</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">Technology stacks and project domain</div>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 hover:border-slate-700 cursor-pointer transition-colors">
                <input
                  type="checkbox"
                  checked={config.personalize_workflow_habits}
                  onChange={(e) => handleCategoryToggle('workflow', e.target.checked)}
                  disabled={saving || !config.personalization_enabled}
                  className="mt-0.5 rounded border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
                <div>
                  <div className="text-xs font-semibold text-slate-200">Workflow Habits</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">Task organization and scheduling habits</div>
                </div>
              </label>
            </div>
          </div>

          {/* Session Bypass */}
          <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-slate-800 text-slate-400">
                <Clock className="w-4 h-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-slate-200">
                  Session Override: {sessionBypassActive ? 'Bypassed (Turned Off)' : 'Normal'}
                </div>
                <div className="text-[11px] text-slate-400 mt-0.5">
                  Temporarily disable personalization for this current session without changing saved settings.
                </div>
              </div>
            </div>
            <button
              onClick={handleToggleSessionBypass}
              disabled={overrideLoading}
              className="px-3.5 py-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
            >
              {sessionBypassActive ? 'Resume Personalization' : 'Bypass for this Session'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
};

