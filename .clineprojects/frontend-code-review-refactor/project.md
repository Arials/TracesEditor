# Project: Frontend Code Review and Refactoring

**Project ID:** FR-2025-001
**Creation Date:** 2025-05-09
**Owner(s):** Cline
**Overall Project Status:** PLANNING
**Priority:** HIGH
**Estimated Deadline:**

## 1. General Description and Objectives
Review and refactor the frontend codebase to address unused/deprecated code, improve documentation, unify state management patterns (especially for session data), enhance consistency in handling asynchronous jobs, and improve overall code quality and maintainability. This review excludes DICOM-related pages (`DicomPage.tsx`, `DicomAnonymizationV2Page.tsx`).

## 2. Scope
### 2.1. In Scope
-   **Core Files:** `frontend/src/App.tsx`, `frontend/src/context/SessionContext.tsx`, `frontend/src/components/Sidebar.tsx`, `frontend/src/services/api.ts`.
-   **Pages:** `frontend/src/pages/UploadPage.tsx`, `frontend/src/pages/SubnetsPage.tsx`, `frontend/src/pages/AsyncPage.tsx`, `frontend/src/pages/MacPage.tsx`, `frontend/src/pages/SettingsPage.tsx`.
-   **Focus Areas:**
    *   Unification of session state management.
    *   Consistency in asynchronous job handling (SSE, localStorage).
    *   Code clarity, readability, and documentation.
    *   Adherence to MUI conventions (as per `.clinerules/default-rules.md`).
    *   Identification and removal of redundant or unused code.
    *   Standardization of error handling and user notifications.

### 2.2. Out of Scope
-   DICOM-related pages: `frontend/src/pages/DicomPage.tsx`, `frontend/src/pages/DicomAnonymizationV2Page.tsx`.
-   Backend code modifications (unless strictly necessary to support frontend refactoring, to be discussed).
-   Major UI/UX redesigns not related to code quality or pattern adherence.

## 3. Key Milestones
-   **MILESTONE-01:** Session State Unification Completed - [STATUS: PENDING]
-   **MILESTONE-02:** Job Handling Consistency Improved - [STATUS: PENDING]
-   **MILESTONE-03:** Code Clarity and Documentation Enhanced - [STATUS: PENDING]
-   **MILESTONE-04:** Minor Issues and Optimizations Addressed - [STATUS: PENDING]
-   **MILESTONE-05:** Project Review and Completion - [STATUS: PENDING]

## 4. Detailed Phases and Tasks

### Phase 1: Session State Management Unification
  **Phase Objective:** Centralize all session list and active session management within `SessionContext.tsx` to create a single source of truth.
  **Phase Status:** [COMPLETED]

  1.  **Task 1.1:** Centralize session list fetching (`listSessions`), state (`sessions`, `isLoadingSessions`, `sessionsError`), and manipulation functions (`addSession`, `removeSession`, `updateSessionInList`, `fetchSessions`) exclusively within `frontend/src/context/SessionContext.tsx`. [STATUS: COMPLETED]
      *   **Details:** Ensure context provides all necessary data and functions for session management.
      *   **Assignee:** Cline
      *   **Estimate:** M
  2.  **Task 1.2:** Remove duplicated session list logic (state: `traces`, `listLoading`, `listError`; function: `fetchTraces`) from `frontend/src/App.tsx`. [STATUS: COMPLETED]
      *   **Details:** `App.tsx` should no longer manage or pass down this session list state.
      *   **Assignee:** Cline
      *   **Estimate:** S
  3.  **Task 1.3:** Refactor `frontend/src/pages/UploadPage.tsx` to consume all session list data and manipulation functions from `SessionContext` via the `useSession()` hook. Remove props related to session list. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** M
  4.  **Task 1.4:** Refactor `frontend/src/pages/AsyncPage.tsx` to use `addSession` from `SessionContext` for adding newly created traces. Remove `refreshSessionList` prop if solely used for this. [STATUS: COMPLETED]
      *   **Details:** Verified that AsyncPage.tsx already uses addSession from context and does not rely on refreshSessionList prop.
      *   **Assignee:** Cline
      *   **Estimate:** S
  5.  **Task 1.5:** Verify that `frontend/src/App.tsx` correctly wraps the application components with `SessionProvider` to make the context available. [STATUS: COMPLETED]
      *   **Details:** Verified in frontend/src/main.tsx that SessionProvider wraps App.
      *   **Assignee:** Cline
      *   **Estimate:** XS

### Phase 2: Asynchronous Job Handling Consistency
  **Phase Objective:** Improve consistency and reduce duplication in how asynchronous jobs (especially those involving SSE and localStorage for job ID persistence) are managed across pages.
  **Phase Status:** [COMPLETED]

  1.  **Task 2.1:** Investigate the feasibility of creating a custom React hook (e.g., `useJobTracking`) to encapsulate common job tracking logic (initiation, `localStorage` for ID, SSE subscription, status updates, error handling, cleanup). [STATUS: COMPLETED]
      *   **Details:** Analyzed patterns in `SubnetsPage.tsx`, `MacPage.tsx`, and `AsyncPage.tsx`. Determined hook is feasible for single-job tracking pages.
      *   **Assignee:** Cline
      *   **Estimate:** M
  2.  **Task 2.2:** If feasible, design and implement the `useJobTracking` hook. [STATUS: COMPLETED]
      *   **Dependencies:** Task 2.1
      *   **Assignee:** Cline
      *   **Estimate:** L
      *   **Notes:** Implemented `frontend/src/hooks/useJobTracking.ts`.
  3.  **Task 2.3:** Refactor `frontend/src/pages/SubnetsPage.tsx` to utilize the `useJobTracking` hook if implemented, or otherwise standardize its job handling logic. [STATUS: COMPLETED]
      *   **Dependencies:** Task 2.2
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Notes:** Refactored `SubnetsPage.tsx` to use the `useJobTracking` hook.
  4.  **Task 2.4:** Refactor `frontend/src/pages/MacPage.tsx` to utilize the `useJobTracking` hook if implemented, or otherwise standardize its job handling logic. [STATUS: COMPLETED]
      *   **Dependencies:** Task 2.2
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Notes:** Refactored `MacPage.tsx` to use the `useJobTracking` hook for MAC transformation jobs.
  5.  **Task 2.5:** Review job handling logic in `frontend/src/pages/AsyncPage.tsx` for potential simplifications or use of the `useJobTracking` hook for individual job monitoring aspects. [STATUS: COMPLETED]
      *   **Dependencies:** Task 2.2
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Notes:** Reviewed `AsyncPage.tsx`. Determined `useJobTracking` is not suitable for its main multi-job listing view but could be used for a hypothetical single-job detail view. No changes made to `AsyncPage.tsx` as its current logic is appropriate for listing multiple jobs.

### Phase 3: `localStorage` Usage Review
  **Phase Objective:** Consolidate and clarify the use of `localStorage`.
  **Phase Status:** [COMPLETED]

  1.  **Task 3.1:** Evaluate the necessity of the `pcapSessionsLastUpdated` `localStorage` listener in `frontend/src/pages/UploadPage.tsx` after session state unification (Phase 1). Aim to remove if redundant. [STATUS: COMPLETED]
      *   **Dependencies:** Phase 1
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Sub-Tasks (Planning):**
          *   **Task 3.1.1:** Read `frontend/src/pages/UploadPage.tsx` to identify the `localStorage.getItem('pcapSessionsLastUpdated')` listener and its associated logic (e.g., `useEffect` hook, event listener for `storage` events). [STATUS: COMPLETED]
          *   **Task 3.1.2:** Read `frontend/src/context/SessionContext.tsx` to confirm how session list updates are propagated to consumers (e.g., `UploadPage.tsx` via `useSession()`). [STATUS: COMPLETED]
          *   **Task 3.1.3:** Analyze if `SessionContext` updates are sufficient for `UploadPage.tsx` synchronization, considering if `pcapSessionsLastUpdated` served intra-app (likely redundant) or cross-tab (evaluate necessity) purposes. [STATUS: COMPLETED]
          *   **Task 3.1.4:** Document reasoning regarding the listener's necessity. Conclusion: Keep for cross-tab synchronization. [STATUS: COMPLETED]
          *   **Task 3.1.5 (Implementation):** No removal needed. [STATUS: N/A]
          *   **Task 3.1.6 (Testing):** No removal to test. [STATUS: N/A]
  2.  **Task 3.2:** If `useJobTracking` hook (Task 2.2) is implemented, ensure it handles `localStorage` for `jobId` persistence consistently. Otherwise, review direct `localStorage` usage in `SubnetsPage.tsx` and `MacPage.tsx`. [STATUS: COMPLETED]
      *   **Dependencies:** Task 2.2
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Sub-Tasks (Planning):**
          *   **Task 3.2.1:** Read `frontend/src/hooks/useJobTracking.ts`. Document its `localStorage` usage for `jobId` (key name, read/write/clear logic). [STATUS: COMPLETED]
          *   **Task 3.2.2:** Read `frontend/src/pages/SubnetsPage.tsx`. Verify `useJobTracking` usage. Identify any remaining direct `localStorage` access for `subnetJobId`. [STATUS: COMPLETED]
          *   **Task 3.2.3:** Read `frontend/src/pages/MacPage.tsx`. Verify `useJobTracking` usage. Identify any remaining direct `localStorage` access for `macJobId`. [STATUS: COMPLETED]
          *   **Task 3.2.4:** Analyze if `useJobTracking.ts`'s `localStorage` handling is comprehensive for job lifecycle (start, resume, clear). [STATUS: COMPLETED]
          *   **Task 3.2.5:** No redundant direct `localStorage` access found in `SubnetsPage.tsx` or `MacPage.tsx` for their respective job IDs. Hook usage is consistent. No refactoring needed. [STATUS: COMPLETED]
          *   **Task 3.2.6 (Implementation):** No refactoring needed. [STATUS: N/A]
          *   **Task 3.2.7 (Testing):** No refactoring to test. [STATUS: N/A]

### Phase 4: Code Clarity and Documentation Enhancement
  **Phase Objective:** Improve the readability and maintainability of complex code sections through better comments and potential minor refactoring.
  **Phase Status:** [COMPLETED]

  1.  **Task 4.1:** Add detailed comments to the subnet transformation generation algorithm in `frontend/src/pages/SubnetsPage.tsx`. Consider breaking down complex logic into smaller helper functions if it improves clarity. [STATUS: COMPLETED]
      *   **Details:** Extracted transformation logic into `generateDefaultSubnetTransformations` function with JSDoc comments.
      *   **Assignee:** Cline
      *   **Estimate:** M
  2.  **Task 4.2:** Review `frontend/src/pages/MacPage.tsx` for complex state interactions or dense logic. Add comments and explore minor refactoring for clarity (e.g., extracting small helper functions). [STATUS: COMPLETED]
      *   **Details:** Added JSDoc comments to major functions, handlers, and state variables. Clarified `DisplayMacRule` interface. No major refactoring was required.
      *   **Assignee:** Cline
      *   **Estimate:** M
  3.  **Task 4.3:** Review all modified files to ensure comments are up-to-date, clear, and accurately reflect the code's purpose and functionality. [STATUS: COMPLETED]
      *   **Details:** Reviewed and updated comments in `SessionContext.tsx`, `App.tsx`, `UploadPage.tsx`, `AsyncPage.tsx`, and `useJobTracking.ts`. `SubnetsPage.tsx` and `MacPage.tsx` were handled during Tasks 4.1 and 4.2.
      *   **Assignee:** Cline
      *   **Estimate:** M (ongoing with other tasks)
  4.  **Task 4.4:** Remove or comment out non-essential `console.log` statements from the reviewed files. Retain logs that are valuable for specific debugging scenarios, clearly marked. [STATUS: COMPLETED]
      *   **Details:** Commented out general debug `console.log` statements in `SessionContext.tsx`, `UploadPage.tsx`, `AsyncPage.tsx`, `useJobTracking.ts`, `SubnetsPage.tsx`, and `MacPage.tsx`. Retained `console.error` and specific `console.warn` messages.
      *   **Assignee:** Cline
      *   **Estimate:** S

### Phase 5: Error Handling and Notification Consistency
  **Phase Objective:** Ensure a more uniform approach to handling API errors and presenting feedback to the user.
  **Phase Status:** [COMPLETED]

  1.  **Task 5.1:** Review and standardize API error handling in `UploadPage.tsx`, `SubnetsPage.tsx`, `MacPage.tsx`, and `AsyncPage.tsx`. Ensure consistent display of error messages. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Details:** Refined error message construction in catch blocks for API calls in specified pages to provide more specific feedback.
  2.  **Task 5.2:** Ensure user-facing error messages are informative and guide the user where possible. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Details:** Integrated with Task 5.1. Fallback error messages made more user-friendly.
  3.  **Task 5.3:** (Optional Investigation) Briefly evaluate if a centralized notification context/service would offer significant benefits over individual `Snackbar` usage per page. Implement only if clear, simple win. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Details:** Evaluation completed. Decision: A centralized notification service will not be implemented in this phase as the current benefit does not outweigh the added complexity.

### Phase 6: Minor Functionality Review and Optimizations
  **Phase Objective:** Address smaller specific items identified during the review.
  **Phase Status:** [COMPLETED]

  1.  **Task 6.1:** In `frontend/src/pages/SubnetsPage.tsx`, verify the actual usage and necessity of the `maskMac` state and its associated checkbox. Remove if unused. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Details:** The `maskMac` state and its checkbox were found to be unused in `SubnetsPage.tsx` and have been removed.
  2.  **Task 6.2:** In `frontend/src/pages/AsyncPage.tsx`, review the "Legacy Download" button logic for `mac_transform` jobs. Determine if it's still required or if `output_trace_id` is always reliably available. Simplify or remove if obsolete. [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** S
      *   **Details:** The "Legacy Download" button for `mac_transform` jobs in `AsyncPage.tsx` was deemed redundant as `output_trace_id` is expected to be reliably available for completed transformation jobs, triggering the "View New Trace" functionality. The legacy button has been removed.
  3.  **Task 6.3:** Investigate and implement a mechanism for `frontend/src/pages/SettingsPage.tsx` (after a successful `clearAllData` operation) to trigger a refresh of session and job lists in other parts of the application (e.g., by calling `fetchSessions()` from `SessionContext` and `fetchJobs()` on `AsyncPage` or a global job context if developed). [STATUS: COMPLETED]
      *   **Assignee:** Cline
      *   **Estimate:** M
      *   **Details:** Implemented. `SettingsPage.tsx` now calls `fetchSessions()` from `SessionContext` and sets `localStorage.setItem('jobDataLastClearedTimestamp', Date.now().toString())` on successful `clearAllData`. `AsyncPage.tsx` now listens for the `storage` event on `jobDataLastClearedTimestamp` and calls its `fetchJobs()` function to refresh the job list.

## 5. Notes and Considerations
-   All changes should be tested to ensure no regressions in functionality.
-   Adherence to existing MUI styling and conventions (as per `.clinerules/default-rules.md`) should be maintained.
-   Priorities can be adjusted based on feedback.
