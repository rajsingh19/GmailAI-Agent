import React, { useState, useEffect } from 'react';
import {
  fetchPersonalizationConfig,
  updatePersonalizationConfig,
  previewPersonalization,
  setPersonalizationSessionOverride,
  PersonalizationConfigResponse,
  PersonalizationLevelType,
  PersonalizationPreviewItem,
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

  // Preview state
  const [previewQuery, setPreviewQuery] = useState<string>('How do I build an API endpoint for tasks?');
  const [previewItems, setPreviewItems] = useState<PersonalizationPreviewItem[]>([]);
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);

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
      setSuccessMessage(enabled ? 'Personalization enabled' : 'Personalization disabled');
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
          ? 'Personalization bypassed for this session.'
          : 'Personalization resumed for this session.'
      );
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to toggle session override');
    } finally {
      setOverrideLoading(false);
    }
  };

  const handleRunPreview = async () => {
    if (!previewQuery.trim()) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const res = await previewPersonalization(previewQuery.trim(), 10);
      setPreviewItems(res.items);
    } catch (err: any) {
      setError(err.message || 'Failed to run preview');
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="personalization-settings-panel" style={{
      background: 'rgba(255, 255, 255, 0.95)',
      borderRadius: '16px',
      padding: '24px',
      boxShadow: '0 10px 30px rgba(0,0,0,0.1)',
      border: '1px solid #e2e8f0',
      maxWidth: '780px',
      margin: '0 auto',
      color: '#1e293b',
      fontFamily: 'Inter, system-ui, sans-serif'
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>Personalization Intelligence</span>
            <span style={{ fontSize: '0.8rem', padding: '2px 8px', borderRadius: '12px', background: '#e0e7ff', color: '#4338ca', fontWeight: 500 }}>
              Milestone 12
            </span>
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: '0.9rem', color: '#64748b' }}>
            Safely modulates response style and technical context without altering permissions or security policies.
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              border: 'none',
              background: 'transparent',
              fontSize: '1.2rem',
              cursor: 'pointer',
              color: '#94a3b8',
              padding: '4px 8px',
            }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Status Alerts */}
      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.9rem' }}>
          {error}
        </div>
      )}
      {successMessage && (
        <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#15803d', padding: '10px 14px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.9rem' }}>
          ✓ {successMessage}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '30px', color: '#64748b' }}>Loading personalization configuration...</div>
      ) : config ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Master Toggle */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '16px',
            background: '#f8fafc',
            borderRadius: '12px',
            border: '1px solid #e2e8f0',
          }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '1rem' }}>Master Personalization</div>
              <div style={{ fontSize: '0.85rem', color: '#64748b' }}>
                {config.personalization_enabled ? 'Active — Personal preferences adapt responses.' : 'Disabled — Standard non-personalized assistant responses.'}
              </div>
            </div>
            <button
              onClick={() => handleToggleEnabled(!config.personalization_enabled)}
              disabled={saving}
              style={{
                padding: '8px 18px',
                borderRadius: '8px',
                border: 'none',
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                background: config.personalization_enabled ? '#4f46e5' : '#94a3b8',
                color: '#ffffff',
                transition: 'background 0.2s',
              }}
            >
              {config.personalization_enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          {/* Level Selector */}
          <div style={{
            opacity: config.personalization_enabled ? 1 : 0.5,
            pointerEvents: config.personalization_enabled ? 'auto' : 'none',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px'
          }}>
            <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>Personalization Level</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
              {(['NONE', 'LOW', 'MEDIUM', 'HIGH'] as PersonalizationLevelType[]).map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => handleLevelChange(lvl)}
                  disabled={saving}
                  style={{
                    padding: '10px',
                    borderRadius: '8px',
                    border: config.personalization_level === lvl ? '2px solid #4f46e5' : '1px solid #cbd5e1',
                    background: config.personalization_level === lvl ? '#eef2ff' : '#ffffff',
                    color: config.personalization_level === lvl ? '#4338ca' : '#475569',
                    fontWeight: config.personalization_level === lvl ? 600 : 500,
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontSize: '0.85rem',
                  }}
                >
                  <div>{lvl}</div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '2px' }}>
                    {lvl === 'NONE' ? '0 items' : lvl === 'LOW' ? 'Style only' : lvl === 'MEDIUM' ? 'Style + Project' : 'Full context'}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Categories */}
          <div style={{
            opacity: config.personalization_enabled ? 1 : 0.5,
            pointerEvents: config.personalization_enabled ? 'auto' : 'none',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            background: '#f8fafc',
            padding: '14px',
            borderRadius: '10px',
            border: '1px solid #e2e8f0',
          }}>
            <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '4px' }}>Active Scopes</div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.88rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={config.personalize_response_style}
                onChange={(e) => handleCategoryToggle('style', e.target.checked)}
                disabled={saving}
              />
              <span>Response Style (conciseness, technical depth)</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.88rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={config.personalize_project_context}
                onChange={(e) => handleCategoryToggle('project', e.target.checked)}
                disabled={saving}
              />
              <span>Project Context (frameworks, stack preferences)</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.88rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={config.personalize_workflow_habits}
                onChange={(e) => handleCategoryToggle('workflow', e.target.checked)}
                disabled={saving}
              />
              <span>Workflow Habits (task tags, reminder phrasing)</span>
            </label>
          </div>

          {/* Ephemeral Session Override */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '12px 16px',
            background: sessionBypassActive ? '#fff1f2' : '#f0fdf4',
            borderRadius: '10px',
            border: sessionBypassActive ? '1px solid #fecdd3' : '1px solid #bbf7d0',
          }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.88rem', color: sessionBypassActive ? '#9f1239' : '#166534' }}>
                Current Session Override: {sessionBypassActive ? 'Bypassed (Turn Off)' : 'Active (Standard)'}
              </div>
              <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                1-hour temporary bypass for session ({currentSessionId.slice(0, 8)}...).
              </div>
            </div>
            <button
              onClick={handleToggleSessionBypass}
              disabled={overrideLoading}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                background: '#ffffff',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: 500,
              }}
            >
              {sessionBypassActive ? 'Resume Personalization' : 'Bypass for this Session'}
            </button>
          </div>

          {/* Interactive Preview Engine */}
          <div style={{ marginTop: '10px', borderTop: '1px solid #e2e8f0', paddingTop: '16px' }}>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '8px' }}>
              Personalization Explainability Preview
            </div>
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
              <input
                type="text"
                value={previewQuery}
                onChange={(e) => setPreviewQuery(e.target.value)}
                placeholder="Enter test user query..."
                style={{
                  flex: 1,
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '0.88rem',
                }}
              />
              <button
                onClick={handleRunPreview}
                disabled={previewLoading || !previewQuery.trim()}
                style={{
                  padding: '8px 16px',
                  background: '#334155',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  fontWeight: 500,
                  fontSize: '0.85rem',
                  cursor: previewLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {previewLoading ? 'Testing...' : 'Test Relevance'}
              </button>
            </div>

            {previewItems.length > 0 ? (
              <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: '8px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', textAlign: 'left' }}>
                      <th style={{ padding: '8px 12px' }}>Category</th>
                      <th style={{ padding: '8px 12px' }}>Key</th>
                      <th style={{ padding: '8px 12px' }}>Score</th>
                      <th style={{ padding: '8px 12px' }}>Status</th>
                      <th style={{ padding: '8px 12px' }}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewItems.map((item, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '8px 12px', color: '#64748b' }}>{item.category}</td>
                        <td style={{ padding: '8px 12px', fontWeight: 500 }}>{item.key}</td>
                        <td style={{ padding: '8px 12px', fontWeight: 600 }}>{item.relevance_score}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <span style={{
                            padding: '2px 6px',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            background: item.is_selected ? '#dcfce7' : '#f1f5f9',
                            color: item.is_selected ? '#166534' : '#64748b',
                          }}>
                            {item.is_selected ? 'APPLIED' : 'FILTERED'}
                          </span>
                        </td>
                        <td style={{ padding: '8px 12px', color: '#64748b' }}>{item.selection_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontStyle: 'italic' }}>
                Click 'Test Relevance' to simulate candidate selection for the query.
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
};
