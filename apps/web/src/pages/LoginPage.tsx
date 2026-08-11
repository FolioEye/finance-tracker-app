import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useOAuthLoginMutation } from "../api/auth";
import { useAuthStore } from "../store/authStore";

// Minimal shape of the bits of Google Identity Services / Apple's JS SDK
// this component actually touches -- both scripts attach a global, and
// neither ships its own TypeScript types as an npm package we depend on,
// so these are declared locally rather than pulling in a heavier
// community @types package for two function calls.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
    AppleID?: {
      auth: {
        init: (config: {
          clientId: string;
          scope: string;
          redirectURI: string;
          usePopup: boolean;
        }) => void;
        signIn: () => Promise<{ authorization: { id_token: string } }>;
      };
    };
  }
}

function useExternalScript(src: string, enabled = true): boolean {
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      setLoaded(true);
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => setLoaded(true);
    document.body.appendChild(script);
    // Deliberately not removed on unmount -- both SDKs are meant to be
    // loaded once for the page's lifetime, and re-injecting them on every
    // LoginPage mount/unmount cycle would re-run each SDK's own global
    // init side effects unnecessarily.
  }, [src, enabled]);

  return loaded;
}

export function LoginPage() {
  const navigate = useNavigate();
  const setSession = useAuthStore((state) => state.setSession);
  const googleButtonRef = useRef<HTMLDivElement>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Apple sign-in requires a paid Apple Developer Program enrollment to
  // get a real clientId -- that may not exist yet for a given deploy.
  // FINTRACK-38 incident (2026-08-09): AppleID.auth.init() throws
  // synchronously when clientId isn't a string, which an unset env var
  // produces as `undefined` -- and that throw happened inside a React
  // effect with no error boundary, taking down the ENTIRE page (blank
  // white screen, including the Google button) rather than just Apple's.
  // Treating Apple as optional-and-gracefully-hidden, rather than
  // required, means a missing Apple config can never do that again.
  const appleClientId = import.meta.env.VITE_APPLE_CLIENT_ID as string | undefined;
  const appleConfigured = Boolean(appleClientId);

  const googleScriptLoaded = useExternalScript("https://accounts.google.com/gsi/client");
  const appleScriptLoaded = useExternalScript(
    "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js",
    appleConfigured,
  );

  const googleLogin = useOAuthLoginMutation("google");
  const appleLogin = useOAuthLoginMutation("apple");

  useEffect(() => {
    if (!googleScriptLoaded || !window.google || !googleButtonRef.current) {
      return;
    }
    window.google.accounts.id.initialize({
      client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID,
      callback: (response) => {
        googleLogin.mutate(response.credential, {
          onSuccess: (data) => {
            setSession({ accessToken: data.access_token, userId: data.user_id, email: data.email });
            navigate("/dashboard", { replace: true });
          },
          onError: () => setErrorMessage("Google sign-in failed. Please try again."),
        });
      },
    });
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      theme: "outline",
      size: "large",
      width: 320,
    });
    // googleLogin/navigate/setSession are stable across renders (mutate
    // and store setters are referentially stable in React Query/Zustand);
    // only re-running this effect when the script/ref actually change
    // avoids re-initializing Google's SDK on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [googleScriptLoaded]);

  useEffect(() => {
    if (!appleConfigured || !appleScriptLoaded || !window.AppleID) {
      return;
    }
    window.AppleID.auth.init({
      clientId: appleClientId as string,
      scope: "email",
      redirectURI: import.meta.env.VITE_APPLE_REDIRECT_URI,
      usePopup: true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appleScriptLoaded, appleConfigured]);

  async function handleAppleSignIn() {
    setErrorMessage(null);
    if (!window.AppleID) {
      setErrorMessage("Apple sign-in is not available right now.");
      return;
    }
    try {
      const result = await window.AppleID.auth.signIn();
      appleLogin.mutate(result.authorization.id_token, {
        onSuccess: (data) => {
          setSession({ accessToken: data.access_token, userId: data.user_id, email: data.email });
          navigate("/dashboard", { replace: true });
        },
        onError: () => setErrorMessage("Apple sign-in failed. Please try again."),
      });
    } catch {
      // The user closing Apple's popup also lands here -- not a real
      // error worth surfacing as "sign-in failed", so this is silent.
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="w-full max-w-sm rounded-lg bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Sign in to FinTrack</h1>
        <p className="mt-1 text-sm text-slate-500">
          No password to remember -- continue with an account you already have.
        </p>

        {errorMessage ? (
          <p role="alert" className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
            {errorMessage}
          </p>
        ) : null}

        <div className="mt-6 flex flex-col gap-3">
          <div ref={googleButtonRef} data-testid="google-signin-button" />
          {appleConfigured ? (
            <button
              type="button"
              onClick={handleAppleSignIn}
              data-testid="apple-signin-button"
              className="flex w-full items-center justify-center rounded-md bg-black px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              Continue with Apple
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
