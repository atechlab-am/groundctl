import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getMe, uiLogin, uiLogout, uiRefresh, type UserRead } from "@/api/auth";
import { registerAuthHooks } from "@/api/client";

// Silent-refresh cadence: access tokens expire after 15 minutes
// (jwt_expire_minutes in app/config.py) — refresh a bit early so a request
// in flight around the 15-minute mark doesn't race the expiry.
const SILENT_REFRESH_INTERVAL_MS = 12 * 60 * 1000;

interface AuthContextValue {
  user: UserRead | null;
  accessToken: string | null;
  // Undetermined until the initial silent-refresh-on-load attempt settles.
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // In-memory only — never localStorage/sessionStorage. A ref (not just
  // state) so the client.ts fetch wrapper's getAccessToken() closure always
  // reads the latest value without needing to be re-registered on every
  // render.
  const accessTokenRef = useRef<string | null>(null);
  const [accessTokenState, setAccessTokenState] = useState<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const setAccessToken = useCallback((token: string | null) => {
    accessTokenRef.current = token;
    setAccessTokenState(token);
  }, []);

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current !== null) {
      clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    clearRefreshTimer();
  }, [setAccessToken, clearRefreshTimer]);

  const refreshAccessToken = useCallback(async (): Promise<string | null> => {
    try {
      const { access_token } = await uiRefresh();
      setAccessToken(access_token);
      return access_token;
    } catch {
      clearSession();
      return null;
    }
  }, [setAccessToken, clearSession]);

  const scheduleRefresh = useCallback(() => {
    clearRefreshTimer();
    refreshTimerRef.current = setInterval(() => {
      void refreshAccessToken();
    }, SILENT_REFRESH_INTERVAL_MS);
  }, [clearRefreshTimer, refreshAccessToken]);

  const onAuthFailure = useCallback(() => {
    clearSession();
  }, [clearSession]);

  // Register the fetch wrapper's hooks once. Uses refs/callbacks that are
  // stable across renders (accessTokenRef never changes identity, and the
  // callbacks below are recreated only when their own deps change, but
  // registerAuthHooks always points at the latest closures because this
  // effect re-runs when refreshAccessToken/onAuthFailure identities change).
  useEffect(() => {
    registerAuthHooks({
      getAccessToken: () => accessTokenRef.current,
      refreshAccessToken,
      onAuthFailure,
    });
  }, [refreshAccessToken, onAuthFailure]);

  // On app load: try a silent refresh using the httpOnly cookie (if any).
  // Success means a valid refresh cookie existed — fetch /auth/me to
  // populate the user, then start the recurring refresh timer. Failure
  // (401, or no cookie present) just means "show the login page," not an
  // error to surface.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { access_token } = await uiRefresh();
        if (cancelled) return;
        setAccessToken(access_token);
        const me = await getMe();
        if (cancelled) return;
        setUser(me);
        scheduleRefresh();
      } catch {
        if (!cancelled) clearSession();
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Intentionally run once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => clearRefreshTimer, [clearRefreshTimer]);

  const login = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await uiLogin(username, password);
      setAccessToken(access_token);
      const me = await getMe();
      setUser(me);
      scheduleRefresh();
    },
    [setAccessToken, scheduleRefresh],
  );

  const logout = useCallback(async () => {
    try {
      await uiLogout();
    } finally {
      clearSession();
    }
  }, [clearSession]);

  return (
    <AuthContext.Provider
      value={{ user, accessToken: accessTokenState, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
