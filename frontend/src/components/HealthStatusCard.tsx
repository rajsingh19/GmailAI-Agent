import React from 'react';
import { CheckCircle2, AlertCircle, RefreshCw, Activity, Server, Clock, Zap } from 'lucide-react';
import { HealthCheckResult } from '../services/api';

interface HealthStatusCardProps {
  health: HealthCheckResult | null;
  loading: boolean;
  onRefresh: () => void;
}

export const HealthStatusCard: React.FC<HealthStatusCardProps> = ({
  health,
  loading,
  onRefresh,
}) => {
  const isHealthy = health?.data?.status === 'healthy';

  return (
    <div className="glass-panel-glow rounded-2xl p-6 sm:p-8 transition-all duration-300">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className={`p-3 rounded-xl ${isHealthy ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
            <Server className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white tracking-tight flex items-center gap-2">
              FastAPI Backend Status
              <span id="backend-status-pill" className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                isHealthy
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${isHealthy ? 'bg-emerald-400 animate-ping' : 'bg-rose-400'}`}></span>
                {loading ? 'Checking...' : isHealthy ? 'OPERATIONAL' : 'OFFLINE'}
              </span>
            </h2>
            <p className="text-sm text-slate-400 mt-0.5">
              Verified connection via <code className="text-xs bg-slate-800/80 px-1.5 py-0.5 rounded text-blue-400">GET /health</code>
            </p>
          </div>
        </div>

        <button
          id="refresh-health-btn"
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-500/20 text-white cursor-pointer"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Pinging...' : 'Ping Backend'}
        </button>
      </div>

      {health?.error ? (
        <div className="mt-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 mt-0.5 flex-shrink-0 text-rose-400" />
          <div>
            <div className="font-medium text-sm">Failed to connect to backend service</div>
            <div className="text-xs text-rose-400/80 mt-1">{health.error}</div>
            <div className="text-xs text-slate-400 mt-2">
              Ensure the FastAPI backend is running on port 8000: <code className="bg-slate-900 px-1.5 py-0.5 rounded">uvicorn backend.app.main:app --reload --port 8000</code>
            </div>
          </div>
        </div>
      ) : health?.data ? (
        <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
            <div className="text-xs font-medium text-slate-400 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-blue-400" />
              Service Status
            </div>
            <div id="service-status-value" className="text-base font-semibold text-emerald-400 mt-1 capitalize flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              {health.data.status}
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
            <div className="text-xs font-medium text-slate-400 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              Response Latency
            </div>
            <div id="service-latency-value" className="text-base font-semibold text-slate-100 mt-1">
              {health.latencyMs} <span className="text-xs text-slate-400 font-normal">ms</span>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
            <div className="text-xs font-medium text-slate-400 flex items-center gap-1.5">
              <Server className="w-3.5 h-3.5 text-purple-400" />
              Environment
            </div>
            <div id="service-env-value" className="text-base font-semibold text-slate-100 mt-1 capitalize">
              {health.data.environment}
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
            <div className="text-xs font-medium text-slate-400 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-emerald-400" />
              Service Version
            </div>
            <div id="service-version-value" className="text-base font-semibold text-slate-100 mt-1">
              v{health.data.version}
            </div>
          </div>
        </div>
      ) : null}

      {health?.data && (
        <div className="mt-6 pt-5 border-t border-slate-800/80 flex flex-col sm:flex-row items-start sm:items-center justify-between text-xs text-slate-400 gap-2">
          <div>
            Service: <span className="text-slate-300 font-medium">{health.data.service}</span>
          </div>
          <div className="font-mono text-slate-500">
            Last check: {new Date(health.fetchedAt).toLocaleTimeString()} (UTC {health.data.timestamp})
          </div>
        </div>
      )}
    </div>
  );
};
