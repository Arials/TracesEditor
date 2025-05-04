import React, { createContext, useState, useContext, ReactNode, useCallback } from 'react';

// Define the shape of the session data we want to store
interface ActiveSession {
  id: string;
  name: string;
}

// Define the context type
interface SessionContextType {
  sessionId: string | null;
  sessionName: string | null;
  setActiveSession: (session: ActiveSession | null) => void; // Function to set/clear the active session
}

// Create the context with an initial undefined value
const SessionContext = createContext<SessionContextType | undefined>(undefined);

// Create the provider component
export const SessionProvider = ({ children }: { children: ReactNode }) => {
  const [activeSession, setActiveSessionState] = useState<ActiveSession | null>(null);

  // Use useCallback to memoize the setter function for stability
  const setActiveSession = useCallback((session: ActiveSession | null) => {
    console.log("SessionContext: Setting active session:", session); // Log context changes
    setActiveSessionState(session);
  }, []); // No dependencies, function is stable

  // Derive sessionId and sessionName from the activeSession state
  const sessionId = activeSession?.id ?? null;
  const sessionName = activeSession?.name ?? null;

  // Provide the state and the setter function to consuming components
  return (
    <SessionContext.Provider value={{ sessionId, sessionName, setActiveSession }}>
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
