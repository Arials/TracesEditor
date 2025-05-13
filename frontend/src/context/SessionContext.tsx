import { createContext, useState, useContext, ReactNode, useCallback, useEffect } from 'react';
import { PcapSession, listSessions } from '../services/api';

const ACTIVE_SESSION_ID_STORAGE_KEY = 'activePcapSessionId';

/**
 * Defines the shape of the SessionContext.
 * This context provides access to the list of all PCAP sessions,
 * the currently active session, and functions to manage them.
 */
interface SessionContextType {
  /** The currently selected PCAP session object, or null if no session is active. */
  activeSession: PcapSession | null;
  /** Function to set the active PCAP session. Pass null to clear the active session. */
  setActiveSession: (session: PcapSession | null) => void;
  /** An array of all available PCAP sessions. */
  sessions: PcapSession[];
  /** Asynchronously fetches or re-fetches the list of all PCAP sessions from the backend. */
  fetchSessions: () => Promise<void>;
  /** Adds a new session to the list or updates an existing one if the ID matches. Keeps the list sorted. */
  addSession: (newSession: PcapSession) => void;
  /** Removes a session from the list by its ID. Clears active session if it's the one being removed. */
  removeSession: (sessionId: string) => void;
  /** Updates an existing session in the list. Also updates the active session if it matches. */
  updateSessionInList: (updatedSession: PcapSession) => void;
  /** Boolean indicating if the session list is currently being fetched. */
  isLoadingSessions: boolean;
  /** Error message string if fetching sessions failed, otherwise null. */
  sessionsError: string | null;
  /** The ID of the currently active session, or null if no session is active. Derived for convenience. */
  activeSessionId: string | null;
  /** The name of the currently active session, or null if no session is active. Derived for convenience. */
  activeSessionName: string | null;
}

/**
 * React Context for managing PCAP session state across the application.
 * Provides access to the active session, list of all sessions, and related actions.
 */
export const SessionContext = createContext<SessionContextType | undefined>(undefined);

/**
 * Provider component for the SessionContext.
 * It manages the state for PCAP sessions and makes it available to its children.
 * @param {object} props - The component props.
 * @param {ReactNode} props.children - The child components that will have access to the context.
 */
export const SessionProvider = ({ children }: { children: ReactNode }) => {
  const [activeSession, setActiveSessionState] = useState<PcapSession | null>(null); // Internal state setter
  const [sessions, setSessions] = useState<PcapSession[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState<boolean>(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  /**
   * Fetches the list of PCAP sessions from the backend and updates the context state.
   * Sets `isLoadingSessions` during the fetch and `sessionsError` on failure.
   */
  const fetchSessions = useCallback(async () => {
    // console.log("SessionContext: Fetching sessions...");
    setIsLoadingSessions(true);
    setSessionsError(null); // Clear previous errors
    try {
      const fetchedSessions = await listSessions();
      setSessions(fetchedSessions);
      // console.log("SessionContext: Sessions fetched successfully", fetchedSessions.length);
    } catch (error: any) { // Added type any for error
      console.error("SessionContext: Error fetching sessions:", error); // Keep error logs
      const errorMessage = error?.response?.data?.detail || error?.message || "An unknown error occurred while fetching sessions.";
      setSessionsError(errorMessage);
      setSessions([]); // Clear sessions on error to prevent displaying stale data
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  // Effect to fetch sessions when the component mounts.
  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]); // fetchSessions is memoized, so this runs once on mount.

  /**
   * Sets the provided session as the active session in the context.
   * Also updates localStorage to synchronize across tabs.
   * @param session - The PCAP session to set as active, or null to clear.
   */
  const setActiveSession = useCallback((session: PcapSession | null) => {
    // console.log("SessionContext: Setting active session (and localStorage):", session);
    if (session) {
      localStorage.setItem(ACTIVE_SESSION_ID_STORAGE_KEY, session.id);
    } else {
      localStorage.removeItem(ACTIVE_SESSION_ID_STORAGE_KEY);
    }
    setActiveSessionState(session); // Update internal React state
  }, [setActiveSessionState]); // setActiveSessionState is stable

  /**
   * Adds a new session to the list or updates an existing one if an ID match is found.
   * The list of sessions is kept sorted by upload timestamp in descending order.
   * @param newSession - The PCAP session to add or update.
   */
  const addSession = useCallback((newSession: PcapSession) => {
    // console.log("SessionContext: Adding or updating session:", newSession);
    setSessions(prevSessions => {
      const sessionExists = prevSessions.find(s => s.id === newSession.id);
      if (sessionExists) {
        // Update existing session
        return prevSessions.map(s => s.id === newSession.id ? newSession : s)
                           .sort((a, b) => new Date(b.upload_timestamp).getTime() - new Date(a.upload_timestamp).getTime());
      }
      // Add new session and sort
      return [...prevSessions, newSession].sort((a, b) => 
        new Date(b.upload_timestamp).getTime() - new Date(a.upload_timestamp).getTime()
      );
    });
  }, []);

  /**
   * Removes a session from the list by its ID.
   * If the removed session was the active session, the active session is cleared.
   * @param sessionId - The ID of the session to remove.
   */
  const removeSession = useCallback((sessionId: string) => {
    // console.log("SessionContext: Removing session:", sessionId);
    setSessions(prevSessions => prevSessions.filter(s => s.id !== sessionId));
    // If the removed session was the active one, clear the active session state
    // and localStorage by calling the main setActiveSession.
    if (activeSession?.id === sessionId) {
      setActiveSession(null);
    }
  }, [activeSession?.id, setActiveSession]); // Dependency on activeSession.id and the new setActiveSession

  /**
   * Updates an existing session in the list.
   * If the updated session is the currently active session, the active session state is also updated.
   * @param updatedSession - The session object with updated information.
   */
  const updateSessionInList = useCallback((updatedSession: PcapSession) => {
    // console.log("SessionContext: Updating session in list:", updatedSession);
    setSessions(prevSessions =>
      prevSessions.map(s => (s.id === updatedSession.id ? updatedSession : s))
    );
    // If the updated session is the active one, also update the activeSession state.
    if (activeSession?.id === updatedSession.id) {
      setActiveSessionState(updatedSession);
    }
  }, [activeSession?.id]); // Dependency on activeSession.id.


  // Derived values for convenience: ID and name of the active session.
  const activeSessionId = activeSession?.id ?? null;
  const activeSessionName = activeSession?.name ?? null;

  // Effect for initializing activeSession from localStorage and syncing with the sessions list
  useEffect(() => {
    if (!isLoadingSessions) { 
      const storedActiveSessionId = localStorage.getItem(ACTIVE_SESSION_ID_STORAGE_KEY);

      if (storedActiveSessionId) {
        // If there's an ID in storage, try to find the session
        const sessionFromStorage = sessions.find(s => s.id === storedActiveSessionId);
        if (sessionFromStorage) {
          // Session found. If it's not already the active one, set it (internal state only).
          if (activeSession?.id !== sessionFromStorage.id) {
            setActiveSessionState(sessionFromStorage);
          }
        } else {
          // Session not found in the current list (stale ID in localStorage).
          // Remove the stale ID from storage.
          localStorage.removeItem(ACTIVE_SESSION_ID_STORAGE_KEY);
          // If the current active session was based on this stale ID, clear it (internal state only).
          if (activeSession?.id === storedActiveSessionId) {
            setActiveSessionState(null);
          }
        }
      } else {
        // No ID in storage. If there's an active session in state, it means
        // localStorage was cleared (e.g., by another tab or action). Clear the state.
        if (activeSession !== null) {
          setActiveSessionState(null);
        }
      }
    }
  }, [sessions, isLoadingSessions, activeSession, setActiveSessionState]);


  // Effect for cross-tab synchronization via localStorage 'storage' event
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === ACTIVE_SESSION_ID_STORAGE_KEY) {
        const newStoredId = event.newValue; // This can be null if the item was removed

        if (newStoredId) {
          // An ID was set or changed in another tab.
          // If our current active session is different, try to update (internal state only).
          if (activeSession?.id !== newStoredId) {
            const sessionToActivate = sessions.find(s => s.id === newStoredId);
            setActiveSessionState(sessionToActivate || null);
          }
        } else {
          // The item was removed from localStorage in another tab.
          // If we had an active session, clear it (internal state only).
          if (activeSession !== null) {
            setActiveSessionState(null);
          }
        }
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, [sessions, activeSession, setActiveSessionState]); // Dependencies ensure the callback has fresh data

  return (
    <SessionContext.Provider
      value={{
        activeSession,
        setActiveSession,
        sessions,
        fetchSessions, // Also exposed as refreshSessions or similar if needed
        addSession,
        removeSession,
        updateSessionInList,
        isLoadingSessions,
        sessionsError, // Expose sessionsError
        activeSessionId,
        activeSessionName,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = (): SessionContextType => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};
