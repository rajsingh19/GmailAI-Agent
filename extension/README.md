# LinkedIn Job Agent Browser Extension (Manifest V3)

A privacy-first, secure browser extension for Chrome, Brave, Edge, and Firefox that captures LinkedIn job postings and posts directly into your Personal AI Assistant / Job Application Agent.

---

## 🛡️ Security & Privacy Guarantees

- **Zero Impersonation / Credential Access**: Never touches, reads, or transmits LinkedIn cookies, session tokens, or credentials.
- **Explicit User Action Only**: Never scrapes or transmits in the background. Ingestion occurs strictly upon an explicit button click.
- **Dedicated, Revocable Token**: Uses a distinct, extension-scoped API token (`ext_...`). The server stores only its cryptographic SHA-256 hash. Revoking the token in Settings immediately disconnects the extension without affecting your web login.
- **Dedicated Audit Log**: Every extension interaction is logged with timestamp, endpoint, token ID, and client IP in `extension_audit`.
- **Prompt-Injection Defense**: All extracted text is wrapped in `<untrusted_job_posting>` isolation tags before parsing by Gemini.
- **Never Auto-Submits**: Never auto-sends emails or auto-submits applications.

---

## 🚀 Installation

### In Chrome / Brave / Edge:
1. Open your browser and navigate to `chrome://extensions`.
2. Enable **Developer mode** (toggle in top right).
3. Click **Load unpacked**.
4. Select the `extension/` directory from this repository (`/path/to/AI-ASSISTANT/extension`).

### In Firefox:
1. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on...**.
3. Select the `manifest.json` file inside the `extension/` directory.

---

## ⚙️ Configuration & Token Setup

1. Open your Personal AI Assistant in the browser (`http://localhost:5173` or your production domain).
2. Go to **Settings** -> **LinkedIn Job Agent Extension**.
3. Click **Generate New Token** and copy the displayed token (`ext_...`).
4. Click the **Job Agent Extension icon** in your browser toolbar (pin it for quick access).
5. In the extension popup:
   - Ensure the **Assistant API Base URL** matches your backend (default: `http://localhost:8000`).
   - Paste your **Extension Token**.
   - Click **Save Settings & Test Connection**.

---

## 🎯 Usage Modes & Trust Tiers

### 1. Verified Job Detail Page (Automated Pipeline)
- **Applicable URL**: `https://www.linkedin.com/jobs/view/*` (single job detail posting).
- **Workflow**:
  1. Browse to any individual job detail view.
  2. A discreet floating **"Send to Job Agent"** button appears in the bottom right corner (and inside the extension popup).
  3. Click the button.
  4. The extension extracts the job title, company name, location, and visible job description text.
  5. The backend validates the URL, isolates untrusted text, structures the job posting, deduplicates against existing records, and **automatically computes an evidence-backed resume match score** against your active resume.
  6. The job appears in your Job Applications list marked with the **"via extension"** badge.

### 2. Quick Capture Mode (Unverified Posts / Arbitrary Pages)
- **Applicable URL**: Any LinkedIn page or feed post (e.g., `https://www.linkedin.com/posts/...`, feed updates, recruiter posts).
- **Workflow**:
  1. Highlight text from the post or view the page.
  2. Click the extension toolbar icon and click **"Capture Visible Post / Selection (Manual Review)"**.
  3. The text is safely staged with status `pending_manual_review`. **No AI parsing or resume matching is run automatically**, ensuring arbitrary feed text never pollutes your match records.
  4. In your Job Agent dashboard, a **"Pending Quick Captures (Manual Review Required)"** banner will appear.
  5. Click **"Review in Modal →"** to inspect the text, verify the job title and company name, and finalize it into your application pipeline.
