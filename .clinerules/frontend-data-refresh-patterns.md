# Cline Rules - Frontend Data Refresh Patterns

## 1. Context: Refreshing Data After Job Completion

When a backend asynchronous job (e.g., a PCAP transformation) completes and results in new data that should be visible across different parts of the application (like an updated list of PCAP sessions in `UploadPage.tsx`), the frontend needs a reliable way to refresh its state.

This document outlines the patterns for ensuring data consistency, covering both same-tab navigation and cross-tab scenarios.

## 2. Core Pattern: `useJobTracking` Hook Enhancement

The primary mechanism involves enhancing and utilizing the `useJobTracking` hook (`frontend/src/hooks/useJobTracking.ts`).

### 2.1. `onJobSuccessTriggerRefresh` Callback (Same-Tab Updates)

-   **Purpose**: To ensure immediate data refresh when navigating within the same browser tab after a job completes.
-   **Implementation**:
    -   The `useJobTracking` hook accepts an optional callback function `onJobSuccessTriggerRefresh?: () => void;` in its configuration options.
    -   Pages that initiate jobs (e.g., `MacPage.tsx`, `SubnetsPage.tsx`) must:
        1.  Import `useSession` from `../context/SessionContext`.
        2.  Get the `fetchSessions` function from the context: `const { fetchSessions } = useSession();`.
        3.  Pass this `fetchSessions` function as the `onJobSuccessTriggerRefresh` callback when configuring `useJobTracking`.
    -   Internally, `useJobTracking` will invoke this `onJobSuccessTriggerRefresh()` callback whenever a job it's tracking completes successfully. This directly calls `fetchSessions`, updating the `SessionContext` and causing all subscribed components (like `UploadPage.tsx`) to re-render with fresh data.

    ```typescript
    // Example in a page component (e.g., MacPage.tsx)
    import { useSession } from '../context/SessionContext';
    import { useJobTracking } from '../hooks/useJobTracking';

    // ...
    const { fetchSessions } = useSession();
    const { startJob } = useJobTracking({
      // ... other options like jobIdLocalStorageKey, onJobSuccess (for local UI updates)
      onJobSuccessTriggerRefresh: fetchSessions, 
    });
    // ...
    ```

### 2.2. `localStorage` for Cross-Tab Updates

-   **Purpose**: To attempt to notify other browser tabs (if the application is open in multiple tabs) that session data has changed.
-   **Implementation**:
    -   When `useJobTracking` detects a successful job completion, in addition to calling `onJobSuccessTriggerRefresh`, it also writes to `localStorage`:
        ```javascript
        localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString());
        ```
    -   Components that display lists of sessions and need to be aware of cross-tab changes (primarily `UploadPage.tsx`) should maintain an event listener for the `storage` event on the `window` object, specifically listening for changes to the `pcapSessionsLastUpdated` key.
    -   Upon detecting a change to this key, the component should call its `fetchSessions` function.

    ```typescript
    // Example in UploadPage.tsx
    useEffect(() => {
      const handleStorageChange = (event: StorageEvent) => {
        if (event.key === 'pcapSessionsLastUpdated') {
          // console.log('UploadPage: Detected pcapSessionsLastUpdated change (cross-tab), refreshing traces.');
          fetchSessions(); 
        }
      };
      window.addEventListener('storage', handleStorageChange);
      return () => {
        window.removeEventListener('storage', handleStorageChange);
      };
    }, [fetchSessions]); // fetchSessions from SessionContext
    ```
-   **Note**: The reliability of the `storage` event for immediate cross-tab updates can vary slightly by browser, but it's the standard mechanism. The direct callback handles the more common same-tab navigation case robustly.

## 3. Pages Not Using `useJobTracking`

For pages that manage their own job lifecycle without the `useJobTracking` hook (e.g., `DicomAnonymizationV2Page.tsx`):

-   If a job on such a page results in a new `PcapSession` that should be reflected globally:
    1.  The page must import `useSession` and get `fetchSessions`.
    2.  Upon successful completion of the job (and confirmation that new data like `output_trace_id` exists), the page should directly call `fetchSessions()`.
    3.  It should also set `localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString());` to attempt cross-tab notification.

    ```typescript
    // Example in DicomAnonymizationV2Page.tsx
    import { useSession } from '../context/SessionContext';
    // ...
    const { fetchSessions } = useSession();
    // ...
    // Inside an effect监测anonymizationJob completion:
    useEffect(() => {
      if (anonymizationJob?.status === 'completed' && anonymizationJob.result_data?.output_trace_id) {
        fetchSessions(); // For same-tab updates
        localStorage.setItem('pcapSessionsLastUpdated', new Date().toISOString()); // For cross-tab
      }
    }, [anonymizationJob, fetchSessions]);
    ```

## 4. Summary of Responsibilities

-   **`useJobTracking` Hook**:
    -   Provides `onJobSuccessTriggerRefresh` callback for consumers.
    -   Calls this callback on job success.
    -   Sets `localStorage.pcapSessionsLastUpdated` on job success.
-   **Pages Initiating Transformations (using `useJobTracking`)**:
    -   Provide `fetchSessions` (from `SessionContext`) to `useJobTracking` via `onJobSuccessTriggerRefresh`.
-   **Pages Initiating Transformations (NOT using `useJobTracking`)**:
    -   Call `fetchSessions` (from `SessionContext`) directly on job success.
    -   Set `localStorage.pcapSessionsLastUpdated` on job success.
-   **`UploadPage.tsx` (and similar global list views)**:
    -   Consumes `sessions` from `SessionContext` (updated by `fetchSessions`).
    -   Listens to `storage` event for `pcapSessionsLastUpdated` as a fallback/cross-tab mechanism.

This hybrid approach ensures data is refreshed reliably for same-tab navigation and provides a standard mechanism for cross-tab updates.
