import React, { useState, useEffect, useCallback } from 'react';
import {
  Briefcase,
  Upload,
  Link,
  Sparkles,
  FileText,
  Mail,
  AlertTriangle,
  AlertCircle,
  ExternalLink,
  Trash2,
  RefreshCw,
  Building,
  MapPin,
  ShieldCheck,
  Search,
  Plus,
  Check,
  X,
  FileUp,
} from 'lucide-react';
import {
  AuthStatusResponse,
  ResumeItem,
  JobApplicationItem,
  JobMatchAnalysis,
  JobEmailDraft,
  JobApplicationStatus,
  JobGmailSyncStatus,
  fetchUserResumes,
  uploadUserResume,
  createUserResumeFromText,
  deleteUserResume,
  fetchJobApplications,
  fetchJobApplication,
  createJobApplication,
  deleteJobApplication,
  resolveJobUrl,
  parseJobDescription,
  matchResumeToJob,
  fetchJobMatchAnalysis,
  generateJobEmailDraft,
  fetchJobEmailDraft,
  updateJobEmailDraft,
  saveJobToGmailDraft,
  updateJobStatus,
  getGoogleOAuthUrl,
  fetchPendingQuickCaptures,
  deletePendingQuickCapture,
} from '../../services/api';

interface JobsPageProps {
  authStatus: AuthStatusResponse | null;
  onNotify?: (message: string, type: 'success' | 'error' | 'info') => void;
}

// Helper to derive a clean Job Title from JD text instead of tab/page titles (e.g. "Post | LinkedIn")
export function extractJobTitleFromJd(rawText?: string, existingTitle?: string | null): string {
  const isJunkOrPageTitle = (t?: string | null) => {
    if (!t) return true;
    const lower = t.trim().toLowerCase();
    return (
      lower.includes('| linkedin') ||
      lower.includes('on linkedin:') ||
      lower === 'post | linkedin' ||
      lower === 'search | linkedin' ||
      lower === 'feed | linkedin' ||
      lower === 'linkedin post' ||
      lower === 'unreviewed linkedin post' ||
      lower === 'linkedin' ||
      lower === 'open position'
    );
  };

  if (rawText) {
    const lines = rawText
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    // Priority 1: Line containing hiring or job role patterns
    for (const line of lines) {
      if (/^(hello|hi|dear|hey|greetings)\b/i.test(line)) continue;
      if (/^https?:\/\//i.test(line)) continue;
      if (/^#\w+/i.test(line)) continue;

      if (
        /(hiring|role|position|job|intern|engineer|developer|manager|lead|specialist|designer|analyst|associate|consultant|architect)/i.test(
          line
        ) &&
        line.length <= 120
      ) {
        return line.replace(/^we\s+are\s+hiring[:\s-]*/i, '').slice(0, 100).trim();
      }
    }

    // Priority 2: First concise line that is not a link or hashtag
    for (const line of lines) {
      if (!/^https?:\/\//i.test(line) && !/^#\w+/i.test(line) && line.length >= 5 && line.length <= 90) {
        return line.slice(0, 100).trim();
      }
    }
  }

  if (existingTitle && !isJunkOrPageTitle(existingTitle)) {
    return existingTitle.trim();
  }

  return '';
}

// Helper to derive Company Name from email domain or non-generic company in JD text
export function extractCompanyFromJd(rawText?: string, existingCompany?: string | null): string {
  const isGeneric = (c?: string | null) => {
    if (!c) return true;
    const lower = c.trim().toLowerCase();
    return lower === 'linkedin post' || lower === 'target company' || lower === 'linkedin';
  };

  if (rawText) {
    const emailMatch = rawText.match(/[\w.-]+@([a-zA-Z0-9-]+)\.([a-zA-Z]{2,})/);
    if (emailMatch) {
      const domain = emailMatch[1].toLowerCase();
      const genericWebmails = ['gmail', 'yahoo', 'outlook', 'hotmail', 'icloud', 'proton', 'protonmail', 'zoho'];
      if (!genericWebmails.includes(domain)) {
        if (domain === 'thevertical') {
          return 'The Vertical';
        }
        return domain
          .replace(/[-_]+/g, ' ')
          .replace(/([a-z])([A-Z])/g, '$1 $2')
          .split(' ')
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ');
      }
    }
  }

  if (existingCompany && !isGeneric(existingCompany)) {
    return existingCompany.trim();
  }

  return '';
}

export const JobsPage: React.FC<JobsPageProps> = ({ authStatus: _authStatus, onNotify }) => {
  // Navigation sub-views
  const [activeView, setActiveView] = useState<'applications' | 'resumes'>('applications');

  // Resumes State
  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [resumesLoading, setResumesLoading] = useState<boolean>(false);
  const [selectedResumeId, setSelectedResumeId] = useState<string>('');
  const [uploadModalOpen, setUploadModalOpen] = useState<boolean>(false);
  const [resumeUploadFile, setResumeUploadFile] = useState<File | null>(null);
  const [resumeUploadText, setResumeUploadText] = useState<string>('');
  const [resumeUploadMode, setResumeUploadMode] = useState<'file' | 'text'>('file');
  const [resumeUploading, setResumeUploading] = useState<boolean>(false);

  // Job Applications State
  const [jobs, setJobs] = useState<JobApplicationItem[]>([]);
  const [jobsLoading, setJobsLoading] = useState<boolean>(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Selected / Active Job Detail
  const [selectedJob, setSelectedJob] = useState<JobApplicationItem | null>(null);
  const [activeJobMatch, setActiveJobMatch] = useState<JobMatchAnalysis | null>(null);
  const [activeJobDraft, setActiveJobDraft] = useState<JobEmailDraft | null>(null);
  const [jobDetailLoading, setJobDetailLoading] = useState<boolean>(false);

  // Ingestion Modal State
  const [ingestModalOpen, setIngestModalOpen] = useState<boolean>(false);
  const [jobUrlInput, setJobUrlInput] = useState<string>('');
  const [resolvingUrl, setResolvingUrl] = useState<boolean>(false);
  const [manualPasteRequired, setManualPasteRequired] = useState<boolean>(false);
  const [manualPasteReason, setManualPasteReason] = useState<string>('');
  const [rawJdText, setRawJdText] = useState<string>('');
  const [jobTitleInput, setJobTitleInput] = useState<string>('');
  const [companyNameInput, setCompanyNameInput] = useState<string>('');
  const [parsingJd, setParsingJd] = useState<boolean>(false);
  const [pendingCaptures, setPendingCaptures] = useState<JobApplicationItem[]>([]);
  const [activePendingCaptureId, setActivePendingCaptureId] = useState<string | null>(null);

  // Actions Loading State
  const [matchingLoading, setMatchingLoading] = useState<boolean>(false);
  const [generatingDraft, setGeneratingDraft] = useState<boolean>(false);
  const [savingDraftToGmail, setSavingDraftToGmail] = useState<boolean>(false);
  const [reconnectNotice, setReconnectNotice] = useState<{ message: string; url?: string } | null>(null);

  // Draft Editing State
  const [draftRecipient, setDraftRecipient] = useState<string>('');
  const [draftSubject, setDraftSubject] = useState<string>('');
  const [draftBody, setDraftBody] = useState<string>('');
  const [draftModified, setDraftModified] = useState<boolean>(false);

  // Safe Delete Modal
  const [deleteModalJob, setDeleteModalJob] = useState<JobApplicationItem | null>(null);
  const [deleteAlsoGmailDraft, setDeleteAlsoGmailDraft] = useState<boolean>(false);
  const [deletingJob, setDeletingJob] = useState<boolean>(false);

  const notify = (msg: string, type: 'success' | 'error' | 'info' = 'info') => {
    if (onNotify) onNotify(msg, type);
  };

  // Load Resumes
  const loadResumes = useCallback(async () => {
    setResumesLoading(true);
    try {
      const res = await fetchUserResumes();
      const list = Array.isArray(res) ? res : (res?.resumes || []);
      setResumes(list);
      if (list.length > 0 && !selectedResumeId) {
        setSelectedResumeId(list[0].id);
      }
    } catch (err: any) {
      console.error('Error fetching resumes:', err);
      setResumes([]);
    } finally {
      setResumesLoading(false);
    }
  }, [selectedResumeId]);

  // Load Job Applications
  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const res = await fetchJobApplications({
        status: statusFilter === 'all' ? undefined : statusFilter,
      });
      const list = Array.isArray(res) ? res : (res?.jobs || []);
      setJobs(list);
    } catch (err: any) {
      console.error('Error fetching jobs:', err);
      setJobs([]);
    } finally {
      setJobsLoading(false);
    }
  }, [statusFilter]);

  // Load Pending Quick Captures
  const loadPendingCaptures = useCallback(async () => {
    try {
      const pending = await fetchPendingQuickCaptures();
      setPendingCaptures(pending || []);
    } catch (err: any) {
      console.warn('Could not load pending quick captures:', err);
      setPendingCaptures([]);
    }
  }, []);

  const handleReviewPendingCapture = (item: JobApplicationItem) => {
    setActivePendingCaptureId(item.id);
    const rawText = item.job_description_raw || (item as any).raw_jd_text || '';
    setRawJdText(rawText);
    setJobUrlInput(item.job_url || item.source_url || '');

    // Extract sensible Job Title from the captured post/JD text instead of page/tab title ("Post | LinkedIn")
    const resolvedTitle = extractJobTitleFromJd(rawText, item.job_title);
    setJobTitleInput(resolvedTitle);

    // Extract sensible Company Name from JD text or existing company/author
    const resolvedCompany = extractCompanyFromJd(rawText, item.company_name);
    setCompanyNameInput(resolvedCompany);

    setManualPasteRequired(true);
    setManualPasteReason(
      'Staged via Quick Capture (Unverified LinkedIn post/page). Please review the raw text below, verify or enter the Job Title and Company Name, and click "Parse & Save Application" to run prompt-injection isolation and resume matching.'
    );
    setIngestModalOpen(true);
  };

  const handleDismissPendingCapture = async (id: string) => {
    // Optimistic removal from UI
    setPendingCaptures((prev) => prev.filter((p) => p.id !== id));
    try {
      await deletePendingQuickCapture(id);
      notify('Dismissed pending quick capture and deleted from database.', 'info');
      await loadPendingCaptures();
    } catch (err: any) {
      notify(err.message || 'Failed to dismiss quick capture.', 'error');
      await loadPendingCaptures();
    }
  };

  useEffect(() => {
    loadResumes();
    loadJobs();
    loadPendingCaptures();
  }, [loadResumes, loadJobs, loadPendingCaptures]);

  // Select a Job and Load Details
  const handleSelectJob = async (job: JobApplicationItem) => {
    setSelectedJob(job);
    setJobDetailLoading(true);
    setActiveJobMatch(null);
    setActiveJobDraft(null);
    setReconnectNotice(null);

    try {
      const [jobData, matchData, draftData] = await Promise.all([
        fetchJobApplication(job.id).catch(() => job),
        fetchJobMatchAnalysis(job.id).catch(() => null),
        fetchJobEmailDraft(job.id).catch(() => null),
      ]);

      setSelectedJob(jobData);
      setActiveJobMatch(matchData);
      if (draftData) {
        setActiveJobDraft(draftData);
        setDraftRecipient(draftData.recipient_email || draftData.recipient || jobData.recruiter_email || (jobData.structured_jd as any)?.recruiter_email || '');
        setDraftSubject(draftData.subject || '');
        setDraftBody(draftData.body || '');
        setDraftModified(false);
      } else {
        setDraftRecipient(jobData.recruiter_email || (jobData.structured_jd as any)?.recruiter_email || '');
        setDraftSubject(`Application for ${jobData.job_title} at ${jobData.company_name}`);
        setDraftBody('');
      }
    } catch (err: any) {
      console.error('Error loading job details:', err);
    } finally {
      setJobDetailLoading(false);
    }
  };

  // Upload Resume
  const handleUploadResume = async (e: React.FormEvent) => {
    e.preventDefault();
    setResumeUploading(true);
    try {
      if (resumeUploadMode === 'file' && resumeUploadFile) {
        const item = await uploadUserResume(resumeUploadFile);
        notify(`Resume "${item.filename}" uploaded & encrypted securely.`, 'success');
      } else if (resumeUploadMode === 'text' && resumeUploadText.trim()) {
        const item = await createUserResumeFromText(resumeUploadText.trim());
        notify(`Resume profile "${item.filename}" created.`, 'success');
      }
      setUploadModalOpen(false);
      setResumeUploadFile(null);
      setResumeUploadText('');
      await loadResumes();
    } catch (err: any) {
      notify(err.message || 'Failed to save resume.', 'error');
    } finally {
      setResumeUploading(false);
    }
  };

  // Delete Resume
  const handleDeleteResume = async (resumeId: string) => {
    if (!window.confirm('Are you sure you want to permanently delete this resume?')) return;
    try {
      await deleteUserResume(resumeId);
      notify('Resume deleted securely.', 'success');
      await loadResumes();
    } catch (err: any) {
      notify(err.message || 'Failed to delete resume.', 'error');
    }
  };

  // Step 1: Ingest URL & Botwall Fallback
  const handleResolveUrl = async () => {
    if (!jobUrlInput.trim()) return;
    setResolvingUrl(true);
    setManualPasteRequired(false);
    setManualPasteReason('');

    try {
      const res = await resolveJobUrl(jobUrlInput.trim());
      if (res.accessible && res.extracted_text && !res.requires_manual_paste) {
        setRawJdText(res.extracted_text);
        if (res.detected_title) setJobTitleInput(res.detected_title);
        if (res.detected_company) setCompanyNameInput(res.detected_company);
        notify('Job description extracted successfully.', 'success');
      } else {
        setManualPasteRequired(true);
        setManualPasteReason(
          res.reason ||
            'Job details are behind a LinkedIn login wall or protected page. Please paste the job description below.'
        );
        if (res.detected_title) setJobTitleInput(res.detected_title);
        if (res.detected_company) setCompanyNameInput(res.detected_company);
      }
    } catch (err: any) {
      setManualPasteRequired(true);
      setManualPasteReason(
        'Could not fetch automatically. Please paste the job description text manually.'
      );
    } finally {
      setResolvingUrl(false);
    }
  };

  // Step 2: Parse & Create Job Application
  const handleParseAndCreateJob = async () => {
    if (!rawJdText.trim()) {
      notify('Please enter or paste the job description text.', 'error');
      return;
    }
    setParsingJd(true);
    try {
      const parsed = await parseJobDescription({
        raw_text: rawJdText,
        source_url: jobUrlInput || undefined,
        job_title: jobTitleInput || undefined,
        company_name: companyNameInput || undefined,
      });

      const details = parsed?.structured_jd || (parsed as any) || {};

      // Defensive skill extraction guarding against undefined / non-array fields
      const reqSkills: string[] = Array.isArray(details.required_skills)
        ? details.required_skills
        : Array.isArray((parsed as any)?.skills_required)
        ? (parsed as any).skills_required
        : [];

      const prefSkills: string[] = Array.isArray(details.preferred_skills)
        ? details.preferred_skills
        : Array.isArray((parsed as any)?.skills_preferred)
        ? (parsed as any).skills_preferred
        : [];

      const combinedSkills = Array.from(new Set([...reqSkills, ...prefSkills].filter(Boolean)));

      const extractedTitle =
        details.job_title || (parsed as any)?.job_title || jobTitleInput || 'Open Position';
      const extractedCompany =
        details.company_name || (parsed as any)?.company_name || companyNameInput || 'Target Company';
      const extractedLocation =
        details.location || (parsed as any)?.location || undefined;
      const extractedEmail =
        details.recruiter_email || (parsed as any)?.recruiter_email || undefined;

      const newJob = await createJobApplication({
        source_url: jobUrlInput || undefined,
        company_name: extractedCompany,
        job_title: extractedTitle,
        location: extractedLocation,
        recruiter_email: extractedEmail,
        job_description_raw: rawJdText,
        skills_extracted: combinedSkills,
        status: 'draft_local',
        source: activePendingCaptureId ? 'extension_quick_capture' : 'manual_paste',
        pending_capture_id: activePendingCaptureId || undefined,
      });

      notify(`Job created for ${newJob.job_title} at ${newJob.company_name}.`, 'success');
      setIngestModalOpen(false);
      setJobUrlInput('');
      setRawJdText('');
      setJobTitleInput('');
      setCompanyNameInput('');
      setManualPasteRequired(false);
      setActivePendingCaptureId(null);
      await loadJobs();
      await loadPendingCaptures();
      await handleSelectJob(newJob);
    } catch (err: any) {
      notify(err.message || 'Failed to parse and save job.', 'error');
    } finally {
      setParsingJd(false);
    }
  };

  // Run Match Analysis
  const handleRunMatch = async () => {
    if (!selectedJob) return;
    const resumeId = selectedResumeId || (resumes.length > 0 ? resumes[0].id : null);
    if (!resumeId) {
      notify('Please upload or select a resume first.', 'error');
      return;
    }
    setMatchingLoading(true);
    try {
      const match = await matchResumeToJob(selectedJob.id, resumeId);
      setActiveJobMatch(match);
      const score = Math.round(match.evidence_coverage_percentage ?? match.coverage_score ?? 0);
      notify(`Match analysis complete (${score}% verified coverage).`, 'success');
      await loadJobs();
    } catch (err: any) {
      notify(err.message || 'Failed to match resume.', 'error');
    } finally {
      setMatchingLoading(false);
    }
  };

  // Generate Email Draft
  const handleGenerateDraft = async () => {
    if (!selectedJob) return;
    const resumeId = selectedResumeId || (resumes.length > 0 ? resumes[0].id : null);
    setGeneratingDraft(true);
    try {
      const draft = await generateJobEmailDraft(selectedJob.id, {
        resume_id: resumeId || undefined,
      });
      setActiveJobDraft(draft);
      setDraftRecipient(draft.recipient_email || draft.recipient || selectedJob.recruiter_email || (selectedJob.structured_jd as any)?.recruiter_email || '');
      setDraftSubject(draft.subject || '');
      setDraftBody(draft.body || '');
      setDraftModified(false);
      notify('Personalized application draft generated.', 'success');
      await loadJobs();
    } catch (err: any) {
      notify(err.message || 'Failed to generate email draft.', 'error');
    } finally {
      setGeneratingDraft(false);
    }
  };

  // Save Local Changes to Draft
  const handleSaveLocalDraft = async () => {
    if (!selectedJob) return;
    try {
      const updated = await updateJobEmailDraft(selectedJob.id, {
        recipient: draftRecipient,
        recipient_email: draftRecipient,
        subject: draftSubject,
        body: draftBody,
      });
      setActiveJobDraft(updated);
      setDraftRecipient(updated.recipient_email || updated.recipient || draftRecipient);
      setDraftModified(false);
      notify('Draft changes saved locally.', 'success');
    } catch (err: any) {
      notify(err.message || 'Failed to update draft.', 'error');
    }
  };

  // Save to Gmail Drafts
  const handleSaveToGmail = async () => {
    if (!selectedJob) return;
    const resumeId = selectedResumeId || (resumes.length > 0 ? resumes[0].id : undefined);
    setSavingDraftToGmail(true);
    setReconnectNotice(null);

    // Save local text changes first if any
    if (draftModified) {
      await updateJobEmailDraft(selectedJob.id, {
        recipient: draftRecipient,
        subject: draftSubject,
        body: draftBody,
      }).catch(() => null);
    }

    try {
      const res = await saveJobToGmailDraft(selectedJob.id, {
        resume_id: resumeId,
      });

      notify(
        `Gmail Draft saved successfully! ${res.attachment_filename ? `Attached ${res.attachment_filename}` : ''}`,
        'success'
      );

      // Refresh job data
      const [updatedJob, updatedDraft] = await Promise.all([
        fetchJobApplication(selectedJob.id),
        fetchJobEmailDraft(selectedJob.id),
      ]);
      setSelectedJob(updatedJob);
      setActiveJobDraft(updatedDraft);
      setDraftModified(false);
      await loadJobs();
    } catch (err: any) {
      console.error('Save to Gmail draft error:', err);
      if (err.status === 403 || err.code === 'MISSING_COMPOSE_SCOPE' || err.message?.includes('permission')) {
        setReconnectNotice({
          message: 'Gmail Compose permissions are required to create drafts. Please reconnect your Google account.',
          url: err.reconnectUrl || getGoogleOAuthUrl(true),
        });
        notify('Gmail permissions required. Please reconnect.', 'error');
      } else {
        notify(err.message || 'Failed to save draft to Gmail.', 'error');
      }
    } finally {
      setSavingDraftToGmail(false);
    }
  };

  // Update Application Pipeline Status
  const handleStatusChange = async (newStatus: JobApplicationStatus) => {
    if (!selectedJob) return;
    try {
      const updated = await updateJobStatus(selectedJob.id, newStatus);
      setSelectedJob(updated);
      notify(`Application status marked as "${newStatus.replace('_', ' ')}".`, 'success');
      await loadJobs();
    } catch (err: any) {
      notify(err.message || 'Failed to update status.', 'error');
    }
  };

  // Confirm and Execute Safe Delete
  const handleExecuteDelete = async () => {
    if (!deleteModalJob) return;
    setDeletingJob(true);
    try {
      const res = await deleteJobApplication(deleteModalJob.id, deleteAlsoGmailDraft);
      notify(
        `Application deleted.${res.gmail_draft_deleted ? ' Corresponding Gmail draft was also deleted.' : ''}`,
        'success'
      );
      if (selectedJob?.id === deleteModalJob.id) {
        setSelectedJob(null);
        setActiveJobMatch(null);
        setActiveJobDraft(null);
      }
      setDeleteModalJob(null);
      setDeleteAlsoGmailDraft(false);
      await loadJobs();
    } catch (err: any) {
      notify(err.message || 'Failed to delete application.', 'error');
    } finally {
      setDeletingJob(false);
    }
  };

  const getStatusBadge = (status: JobApplicationStatus) => {
    switch (status) {
      case 'saved':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-700">Saved</span>;
      case 'draft_local':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-blue-50 text-blue-700 border border-blue-200">Local Draft</span>;
      case 'draft_saved_to_gmail':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">Draft in Gmail</span>;
      case 'applied_manually':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">Applied Manually</span>;
      case 'interview':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-purple-50 text-purple-700 border border-purple-200">Interviewing</span>;
      case 'offer':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-amber-50 text-amber-700 border border-amber-200">Offer Received</span>;
      case 'rejected':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-red-50 text-red-700 border border-red-200">Rejected</span>;
      case 'archived':
        return <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-500">Archived</span>;
      default:
        return null;
    }
  };

  const getSourceBadge = (source?: string | null, status?: JobApplicationStatus) => {
    if (status === 'pending_manual_review') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded-md bg-amber-50 text-amber-800 border border-amber-300">
          <AlertTriangle className="w-2.5 h-2.5 text-amber-600" />
          Quick Capture — Needs Review
        </span>
      );
    }
    if (source === 'extension_quick_capture') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded-md bg-sky-50 text-sky-700 border border-sky-200">
          <Sparkles className="w-2.5 h-2.5 text-sky-500" />
          Quick Capture (Reviewed)
        </span>
      );
    }
    if (source === 'linkedin_extension') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded-md bg-indigo-50 text-indigo-700 border border-indigo-200">
          <Sparkles className="w-2.5 h-2.5 text-indigo-500" />
          via extension
        </span>
      );
    }
    return null;
  };

  const getGmailSyncBadge = (sync: JobGmailSyncStatus) => {
    switch (sync) {
      case 'synced':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-emerald-100 text-emerald-800">
            <Check className="w-3.5 h-3.5" /> Gmail Synced
          </span>
        );
      case 'draft_deleted_in_gmail':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-amber-100 text-amber-800">
            <AlertCircle className="w-3.5 h-3.5" /> Draft Removed in Gmail
          </span>
        );
      case 'sync_error':
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-red-100 text-red-800">
            <AlertTriangle className="w-3.5 h-3.5" /> Sync Error
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-600">
            Not Synced to Gmail
          </span>
        );
    }
  };

  const filteredJobs = jobs.filter((j) => {
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchText = (j.company_name + ' ' + j.job_title + ' ' + (j.location || '')).toLowerCase();
      if (!matchText.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-white p-6 rounded-2xl border border-gray-200/80 shadow-sm">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white shadow-sm">
              <Briefcase className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">Job Application Agent</h1>
              <p className="text-xs text-gray-500">
                LinkedIn ingestion • Evidence-backed resume matching • Gmail draft integration
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="inline-flex p-1 bg-gray-100 rounded-xl">
            <button
              onClick={() => setActiveView('applications')}
              className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
                activeView === 'applications'
                  ? 'bg-white text-indigo-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Applications ({(jobs || []).length})
            </button>
            <button
              onClick={() => setActiveView('resumes')}
              className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
                activeView === 'resumes'
                  ? 'bg-white text-indigo-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Resumes ({(resumes || []).length})
            </button>
          </div>

          <button
            onClick={() => setIngestModalOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-xl shadow-sm hover:shadow transition-all"
          >
            <Plus className="w-4 h-4" />
            New Job Application
          </button>
        </div>
      </div>

      {/* OAuth Reconnect Warning Banner if present */}
      {reconnectNotice && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl flex items-center justify-between gap-3 text-amber-900 text-xs">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span>{reconnectNotice.message}</span>
          </div>
          {reconnectNotice.url && (
            <a
              href={reconnectNotice.url}
              className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white font-medium rounded-lg transition-colors whitespace-nowrap"
            >
              Grant Compose Permission
            </a>
          )}
        </div>
      )}

      {/* VIEW: RESUMES MANAGEMENT */}
      {activeView === 'resumes' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Your Encrypted Resumes</h2>
              <p className="text-xs text-gray-500">
                All resume files and parsed profiles are encrypted at rest with AES-128 Fernet. Decrypted in memory only when matching or attaching.
              </p>
            </div>
            <button
              onClick={() => setUploadModalOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 hover:bg-black text-white text-xs font-semibold rounded-xl transition-all"
            >
              <FileUp className="w-4 h-4" /> Upload Resume
            </button>
          </div>

          {resumesLoading ? (
            <div className="p-12 text-center text-gray-400">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
              <p className="text-xs">Loading resumes...</p>
            </div>
          ) : (resumes || []).length === 0 ? (
            <div className="p-12 bg-white rounded-2xl border border-dashed border-gray-300 text-center space-y-3">
              <FileText className="w-10 h-10 text-gray-400 mx-auto" />
              <p className="text-sm font-medium text-gray-700">No resumes uploaded yet</p>
              <p className="text-xs text-gray-500 max-w-sm mx-auto">
                Upload your PDF or DOCX resume to enable evidence-backed job matching and automated email attachments.
              </p>
              <button
                onClick={() => setUploadModalOpen(true)}
                className="px-4 py-2 bg-indigo-600 text-white text-xs font-semibold rounded-xl"
              >
                Upload First Resume
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {(resumes || []).map((r) => (
                <div
                  key={r.id}
                  className={`p-5 bg-white rounded-2xl border transition-all ${
                    selectedResumeId === r.id ? 'border-indigo-500 ring-2 ring-indigo-100 shadow-sm' : 'border-gray-200/80 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold text-xs uppercase">
                        {r.file_type && r.file_type.includes('pdf') ? 'PDF' : r.file_type && r.file_type.includes('docx') ? 'DOCX' : 'TXT'}
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-gray-900 truncate max-w-[160px]">{r.filename}</h3>
                        <p className="text-[11px] text-gray-500">{r.file_size_bytes ? (r.file_size_bytes / 1024).toFixed(1) : '0'} KB</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteResume(r.id)}
                      className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Delete Resume"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  {r.structured_data && (
                    <div className="mt-4 pt-3 border-t border-gray-100 space-y-2 text-xs">
                      {r.structured_data.candidate_name && (
                        <div className="text-gray-700 font-medium">{r.structured_data.candidate_name}</div>
                      )}
                      {r.structured_data.skills && r.structured_data.skills.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {r.structured_data.skills.slice(0, 5).map((s, idx) => (
                            <span key={idx} className="px-2 py-0.5 bg-gray-100 text-gray-700 text-[10px] rounded-md">
                              {s}
                            </span>
                          ))}
                          {r.structured_data.skills.length > 5 && (
                            <span className="text-[10px] text-gray-400">+{r.structured_data.skills.length - 5} more</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                    <span className="text-emerald-700 flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5" /> AES Encrypted
                    </span>
                    <button
                      onClick={() => setSelectedResumeId(r.id)}
                      className={`font-semibold ${selectedResumeId === r.id ? 'text-indigo-600' : 'text-gray-500 hover:text-gray-900'}`}
                    >
                      {selectedResumeId === r.id ? 'Active Profile' : 'Select'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* VIEW: JOB APPLICATIONS & WORKFLOW */}
      {activeView === 'applications' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Job Applications List */}
          <div className="lg:col-span-4 space-y-4">
            {/* Pending Quick Captures (Manual Review Required) Banner */}
            {pendingCaptures.length > 0 && (
              <div className="p-4 bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/80 rounded-2xl space-y-3 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="p-1 bg-amber-100 rounded-lg text-amber-700">
                      <AlertTriangle className="w-4 h-4" />
                    </div>
                    <span className="text-xs font-bold text-amber-950">
                      Pending Quick Captures ({pendingCaptures.length})
                    </span>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-200/80 text-amber-900 border border-amber-300">
                    Needs Review
                  </span>
                </div>
                <p className="text-[11px] text-amber-900/80 leading-relaxed">
                  Captured from unverified LinkedIn posts/pages. These items are <strong>not auto-matched</strong>. Review and finalize in the manual modal before matching.
                </p>
                <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                  {pendingCaptures.map((pc) => (
                    <div key={pc.id} className="p-2.5 bg-white/95 border border-amber-200 rounded-xl space-y-1.5 shadow-xs">
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-semibold text-xs text-gray-900 line-clamp-1">
                          {pc.company_name && pc.company_name !== 'LinkedIn Post' ? pc.company_name : (pc.job_title || 'Unreviewed Post')}
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDismissPendingCapture(pc.id);
                          }}
                          className="text-gray-400 hover:text-red-500 p-0.5 rounded transition-colors"
                          title="Dismiss and delete capture"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <p className="text-[11px] text-gray-600 line-clamp-2 italic">
                        "{pc.job_description_raw || (pc as any).raw_jd_text || ''}"
                      </p>
                      <div className="pt-1 flex items-center justify-between gap-2">
                        <span className="text-[10px] text-gray-400">
                          {new Date(pc.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                        <button
                          onClick={() => handleReviewPendingCapture(pc)}
                          className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold rounded-lg flex items-center gap-1 shadow-xs transition-all"
                        >
                          Review in Modal →
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Search & Filter Bar */}
            <div className="bg-white p-4 rounded-2xl border border-gray-200/80 space-y-3">
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search jobs or companies..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-[11px]">
                {['all', 'draft_local', 'draft_saved_to_gmail', 'applied_manually', 'interview', 'offer', 'rejected'].map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={`px-2.5 py-1 rounded-lg font-medium whitespace-nowrap transition-colors ${
                      statusFilter === s ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {s === 'all' ? 'All' : s.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
            </div>

            {/* List */}
            <div className="space-y-2">
              {jobsLoading ? (
                <div className="p-8 text-center text-gray-400 bg-white rounded-2xl border border-gray-200">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                  <p className="text-xs">Loading applications...</p>
                </div>
              ) : (filteredJobs || []).length === 0 ? (
                <div className="p-8 text-center text-gray-400 bg-white rounded-2xl border border-dashed border-gray-200">
                  <Briefcase className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                  <p className="text-xs">No job applications found</p>
                </div>
              ) : (
                (filteredJobs || []).map((j) => (
                  <div
                    key={j.id}
                    onClick={() => handleSelectJob(j)}
                    className={`p-4 bg-white rounded-2xl border cursor-pointer transition-all ${
                      selectedJob?.id === j.id
                        ? 'border-indigo-500 ring-2 ring-indigo-100 shadow-sm'
                        : 'border-gray-200/80 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h4 className="text-sm font-semibold text-gray-900 truncate">{j.job_title}</h4>
                        <p className="text-xs text-gray-600 font-medium flex items-center gap-1.5 mt-0.5">
                          <Building className="w-3.5 h-3.5 text-gray-400" />
                          <span className="truncate">{j.company_name}</span>
                        </p>
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteModalJob(j);
                        }}
                        className="p-1 text-gray-300 hover:text-red-500 rounded transition-colors"
                        title="Delete application"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {getStatusBadge(j.status)}
                        {getSourceBadge(j.source, j.status)}
                      </div>
                      <span className="text-[10px] text-gray-400">
                        {new Date(j.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Right Column: Workflow Workspace */}
          <div className="lg:col-span-8">
            {!selectedJob ? (
              <div className="p-12 bg-white rounded-2xl border border-gray-200/80 text-center space-y-3">
                <Briefcase className="w-12 h-12 text-indigo-400 mx-auto" />
                <h3 className="text-base font-semibold text-gray-900">Select a Job Application</h3>
                <p className="text-xs text-gray-500 max-w-md mx-auto">
                  Select an application from the left or click "New Job Application" to ingest a LinkedIn URL or JD text.
                </p>
              </div>
            ) : jobDetailLoading ? (
              <div className="p-16 text-center text-gray-400 bg-white rounded-2xl border border-gray-200">
                <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                <p className="text-xs">Loading application details...</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Active Job Header & Status Controller */}
                <div className="bg-white p-6 rounded-2xl border border-gray-200/80 shadow-sm space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h2 className="text-lg font-bold text-gray-900">{selectedJob.job_title}</h2>
                        {getSourceBadge(selectedJob.source, selectedJob.status)}
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 mt-1">
                        <span className="font-semibold text-indigo-600 flex items-center gap-1">
                          <Building className="w-3.5 h-3.5" /> {selectedJob.company_name}
                        </span>
                        {selectedJob.location && (
                          <span className="flex items-center gap-1 text-gray-500">
                            <MapPin className="w-3.5 h-3.5" /> {selectedJob.location}
                          </span>
                        )}
                        {selectedJob.source_url && (
                          <a
                            href={selectedJob.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-gray-400 hover:text-indigo-600 flex items-center gap-1"
                          >
                            <ExternalLink className="w-3.5 h-3.5" /> Source Link
                          </a>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="text-xs text-gray-500 font-medium">Pipeline Status:</label>
                      <select
                        value={selectedJob.status}
                        onChange={(e) => handleStatusChange(e.target.value as JobApplicationStatus)}
                        className="px-3 py-1.5 text-xs font-semibold bg-gray-50 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      >
                        <option value="saved">Saved</option>
                        <option value="draft_local">Draft (Local)</option>
                        <option value="draft_saved_to_gmail">Draft (Gmail Synced)</option>
                        <option value="applied_manually">Applied Manually</option>
                        <option value="interview">Interviewing</option>
                        <option value="offer">Offer</option>
                        <option value="rejected">Rejected</option>
                        <option value="archived">Archived</option>
                      </select>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 pt-3 border-t border-gray-100 text-xs">
                    {getGmailSyncBadge(selectedJob.gmail_sync_status)}
                    {selectedJob.recruiter_email && (
                      <span className="text-gray-500 flex items-center gap-1">
                        <Mail className="w-3.5 h-3.5" /> {selectedJob.recruiter_email}
                      </span>
                    )}
                  </div>
                </div>

                {/* Section 1: Transparent Resume Match Analysis */}
                <div className="bg-white p-6 rounded-2xl border border-gray-200/80 shadow-sm space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-indigo-600" /> Evidence-Backed Resume Match
                      </h3>
                      <p className="text-xs text-gray-500">
                        Cites exact quotes from your selected resume without guessing or making up hiring probability.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <select
                        value={selectedResumeId}
                        onChange={(e) => setSelectedResumeId(e.target.value)}
                        className="px-3 py-1.5 text-xs bg-gray-50 border border-gray-200 rounded-xl"
                      >
                        {(resumes || []).map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.filename}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={handleRunMatch}
                        disabled={matchingLoading || (resumes || []).length === 0}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5 transition-all"
                      >
                        {matchingLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                        {activeJobMatch ? 'Re-Analyze Match' : 'Analyze Match'}
                      </button>
                    </div>
                  </div>

                  {activeJobMatch ? (() => {
                    const matched = activeJobMatch.matched_requirements || activeJobMatch.matched_skills || [];
                    const missing = activeJobMatch.missing_requirements || activeJobMatch.missing_skills || [];
                    const coverage = Math.round(activeJobMatch.evidence_coverage_percentage ?? activeJobMatch.coverage_score ?? 0);
                    const explanation = activeJobMatch.calculation_explanation || activeJobMatch.scoring_breakdown?.limitations || 'Coverage represents verified skills directly evidenced in your resume. It is not an arbitrary hiring probability.';

                    return (
                    <div className="space-y-4 pt-2">
                      {/* Score Card */}
                      <div className="p-4 bg-indigo-50/70 border border-indigo-100 rounded-xl flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-2xl font-black text-indigo-900">
                              {coverage}%
                            </span>
                            <span className="text-xs font-bold text-indigo-700 uppercase tracking-wider">
                              Verified Requirement Coverage
                            </span>
                          </div>
                          <p className="text-[11px] text-indigo-800/80 mt-1 max-w-xl">
                            {explanation}
                          </p>
                        </div>

                        <div className="text-right text-xs text-indigo-900/80">
                          <span className="font-semibold">
                            {matched.length} / {matched.length + missing.length} requirements evidenced
                          </span>
                        </div>
                      </div>

                      {/* Evidence Citations */}
                      <div className="space-y-3">
                        <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                          Matched Requirements with Resume Evidence ({matched.length})
                        </h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                          {matched.map((m, idx) => (
                            <div key={idx} className="p-3 bg-emerald-50/50 border border-emerald-200/70 rounded-xl space-y-1 text-xs">
                              <div className="flex items-center justify-between">
                                <span className="font-semibold text-emerald-900">{m.requirement}</span>
                                <span className="text-[10px] px-1.5 py-0.5 bg-emerald-100 text-emerald-800 font-bold rounded">
                                  {m.confidence || 'high'}
                                </span>
                              </div>
                              <p className="text-[11px] text-emerald-800 italic bg-white/70 p-1.5 rounded border border-emerald-100">
                                "{m.evidence || (m as any).evidence_quote || ''}"
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Missing Requirements */}
                      {missing.length > 0 && (
                        <div className="space-y-3 pt-2">
                          <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                            Missing / Unverified Requirements ({missing.length})
                          </h4>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                            {missing.map((ms, idx) => (
                              <div key={idx} className="p-3 bg-amber-50/60 border border-amber-200/70 rounded-xl space-y-1 text-xs">
                                <span className="font-semibold text-amber-900">{ms.requirement}</span>
                                <p className="text-[11px] text-amber-700">
                                  Category: {ms.category} • Status: {ms.status || 'not_found_in_resume'}
                                  {ms.recommendation && ` — ${ms.recommendation}`}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                    );
                  })() : (
                    <div className="p-6 bg-gray-50 rounded-xl text-center text-xs text-gray-500">
                      Click "Analyze Match" to verify requirements against your resume with exact supporting citations.
                    </div>
                  )}
                </div>

                {/* Section 2: AI Application Email Draft & Gmail Sync */}
                <div className="bg-white p-6 rounded-2xl border border-gray-200/80 shadow-sm space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                        <Mail className="w-4 h-4 text-indigo-600" /> Application Email Draft & Resume Attachment
                      </h3>
                      <p className="text-xs text-gray-500">
                        Synthesizes job requirements with verified resume facts. Attached resume is decrypted in-memory and synced directly to Gmail drafts.
                      </p>
                    </div>

                    <button
                      onClick={handleGenerateDraft}
                      disabled={generatingDraft}
                      className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5 transition-all"
                    >
                      {generatingDraft ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                      {activeJobDraft ? 'Regenerate Draft' : 'Generate Application Draft'}
                    </button>
                  </div>

                  {/* Composer Fields */}
                  <div className="space-y-3 pt-2">
                    {/* Recipient & Subject */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">Recipient Email:</label>
                        <input
                          type="email"
                          value={draftRecipient}
                          onChange={(e) => {
                            setDraftRecipient(e.target.value);
                            setDraftModified(true);
                          }}
                          placeholder="recruiter@company.com"
                          className="w-full px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">Subject Line:</label>
                        <input
                          type="text"
                          value={draftSubject}
                          onChange={(e) => {
                            setDraftSubject(e.target.value);
                            setDraftModified(true);
                          }}
                          placeholder="Application for..."
                          className="w-full px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                    </div>

                    {/* Email Body */}
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-medium text-gray-700">Email Body:</label>
                        {draftModified && (
                          <span className="text-[11px] text-amber-600 font-medium">Unsaved local edits</span>
                        )}
                      </div>
                      <textarea
                        rows={8}
                        value={draftBody}
                        onChange={(e) => {
                          setDraftBody(e.target.value);
                          setDraftModified(true);
                        }}
                        placeholder="Generate or write your application email..."
                        className="w-full p-3 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-sans leading-relaxed"
                      />
                    </div>

                    {/* Attachment Selection & Status */}
                    <div className="p-3 bg-gray-50 border border-gray-200/80 rounded-xl flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-indigo-600 flex-shrink-0" />
                        <span className="font-semibold text-gray-800">Resume Attachment:</span>
                        <select
                          value={selectedResumeId}
                          onChange={(e) => setSelectedResumeId(e.target.value)}
                          className="px-2.5 py-1 text-xs bg-white border border-gray-300 rounded-lg"
                        >
                          {(resumes || []).map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.filename} ({r.file_size_bytes ? (r.file_size_bytes / 1024).toFixed(0) : '0'} KB)
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="text-[11px] text-gray-500 flex items-center gap-1">
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                        Decrypted in-memory on save
                      </div>
                    </div>

                    {/* Action Bar */}
                    <div className="pt-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                      <div className="flex items-center gap-2">
                        {draftModified && (
                          <button
                            onClick={handleSaveLocalDraft}
                            className="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl transition-all"
                          >
                            Save Locally
                          </button>
                        )}
                      </div>

                      <div className="flex items-center gap-3">
                        <button
                          onClick={handleSaveToGmail}
                          disabled={savingDraftToGmail || !draftBody.trim()}
                          className="px-4 py-2.5 bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-700 hover:to-rose-700 disabled:opacity-50 text-white text-xs font-bold rounded-xl shadow-sm flex items-center gap-2 transition-all"
                        >
                          {savingDraftToGmail ? (
                            <RefreshCw className="w-4 h-4 animate-spin" />
                          ) : (
                            <Mail className="w-4 h-4" />
                          )}
                          Save to Gmail Drafts
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* MODAL: Ingest Job URL or Manual Paste */}
      {ingestModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
                <Briefcase className="w-5 h-5 text-indigo-600" /> New Job Application
              </h3>
              <button
                onClick={() => setIngestModalOpen(false)}
                className="p-1 text-gray-400 hover:text-gray-600 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* URL Input */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-gray-700">LinkedIn / Public Job URL:</label>
              <div className="flex gap-2">
                <input
                  type="url"
                  value={jobUrlInput}
                  onChange={(e) => setJobUrlInput(e.target.value)}
                  placeholder="https://www.linkedin.com/jobs/view/... or lnkd.in/..."
                  className="flex-1 px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500"
                />
                <button
                  onClick={handleResolveUrl}
                  disabled={resolvingUrl || !jobUrlInput.trim()}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5"
                >
                  {resolvingUrl ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Link className="w-3.5 h-3.5" />}
                  Fetch JD
                </button>
              </div>
            </div>

            {/* Botwall or Fallback Notice */}
            {manualPasteRequired && (
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800 space-y-1">
                <div className="font-semibold flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4 text-amber-600" /> LinkedIn Protected Page Detected
                </div>
                <p>{manualPasteReason}</p>
              </div>
            )}

            {/* Structured Inputs */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-700">Job Title:</label>
                <input
                  type="text"
                  value={jobTitleInput}
                  onChange={(e) => setJobTitleInput(e.target.value)}
                  placeholder="e.g. Senior Software Engineer"
                  className="w-full px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl mt-1"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-700">Company Name:</label>
                <input
                  type="text"
                  value={companyNameInput}
                  onChange={(e) => setCompanyNameInput(e.target.value)}
                  placeholder="e.g. Google"
                  className="w-full px-3 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl mt-1"
                />
              </div>
            </div>

            {/* Job Description Textarea */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-gray-700">Job Description Text:</label>
              <textarea
                rows={6}
                value={rawJdText}
                onChange={(e) => setRawJdText(e.target.value)}
                placeholder="Paste the full job description, requirements, and qualifications here..."
                className="w-full p-3 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 font-sans"
              />
            </div>

            <div className="pt-2 flex justify-end gap-2">
              <button
                onClick={() => {
                  setIngestModalOpen(false);
                  setActivePendingCaptureId(null);
                }}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handleParseAndCreateJob}
                disabled={parsingJd || !rawJdText.trim()}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5"
              >
                {parsingJd ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                Parse & Save Application
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Upload Resume */}
      {uploadModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleUploadResume}
            className="bg-white rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-xl"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
                <FileUp className="w-5 h-5 text-indigo-600" /> Upload Resume
              </h3>
              <button
                type="button"
                onClick={() => setUploadModalOpen(false)}
                className="p-1 text-gray-400 hover:text-gray-600 rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex gap-2 p-1 bg-gray-100 rounded-xl text-xs font-medium">
              <button
                type="button"
                onClick={() => setResumeUploadMode('file')}
                className={`flex-1 py-1.5 rounded-lg transition-all ${
                  resumeUploadMode === 'file' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'
                }`}
              >
                PDF / DOCX File
              </button>
              <button
                type="button"
                onClick={() => setResumeUploadMode('text')}
                className={`flex-1 py-1.5 rounded-lg transition-all ${
                  resumeUploadMode === 'text' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600'
                }`}
              >
                Paste Text
              </button>
            </div>

            {resumeUploadMode === 'file' ? (
              <div className="border-2 border-dashed border-gray-200 p-6 rounded-2xl text-center space-y-2">
                <Upload className="w-8 h-8 text-gray-400 mx-auto" />
                <label className="cursor-pointer block">
                  <span className="text-xs font-semibold text-indigo-600 hover:text-indigo-700">
                    Choose a PDF or DOCX file
                  </span>
                  <input
                    type="file"
                    accept=".pdf,.docx,.txt"
                    onChange={(e) => setResumeUploadFile(e.target.files ? e.target.files[0] : null)}
                    className="hidden"
                  />
                </label>
                {resumeUploadFile && (
                  <p className="text-xs font-medium text-gray-900 mt-2">
                    Selected: {resumeUploadFile.name} ({(resumeUploadFile.size / 1024).toFixed(1)} KB)
                  </p>
                )}
                <p className="text-[11px] text-gray-400">Encrypted at rest with AES-128 Fernet</p>
              </div>
            ) : (
              <div>
                <textarea
                  rows={8}
                  value={resumeUploadText}
                  onChange={(e) => setResumeUploadText(e.target.value)}
                  placeholder="Paste your raw resume text here..."
                  className="w-full p-3 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 font-sans"
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setUploadModalOpen(false)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={resumeUploading || (resumeUploadMode === 'file' && !resumeUploadFile) || (resumeUploadMode === 'text' && !resumeUploadText.trim())}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5"
              >
                {resumeUploading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                Upload & Encrypt
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: Safe Job Delete with Gmail Option */}
      {deleteModalJob && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="w-6 h-6 flex-shrink-0" />
              <h3 className="text-base font-bold text-gray-900">Delete Job Application?</h3>
            </div>

            <p className="text-xs text-gray-600">
              Are you sure you want to delete the application for{' '}
              <strong className="text-gray-900">{deleteModalJob.job_title}</strong> at{' '}
              <strong className="text-gray-900">{deleteModalJob.company_name}</strong>?
            </p>

            {deleteModalJob.gmail_draft_id && (
              <div className="p-3.5 bg-gray-50 border border-gray-200 rounded-xl space-y-2">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={deleteAlsoGmailDraft}
                    onChange={(e) => setDeleteAlsoGmailDraft(e.target.checked)}
                    className="mt-0.5 rounded text-indigo-600 focus:ring-indigo-500"
                  />
                  <div className="text-xs">
                    <span className="font-semibold text-gray-900">Also delete corresponding Gmail draft</span>
                    <p className="text-gray-500 text-[11px]">
                      If unchecked, the draft will remain saved in your Gmail Drafts folder.
                    </p>
                  </div>
                </label>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setDeleteModalJob(null);
                  setDeleteAlsoGmailDraft(false);
                }}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteDelete}
                disabled={deletingJob}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl flex items-center gap-1.5"
              >
                {deletingJob ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default JobsPage;
