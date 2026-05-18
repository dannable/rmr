import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

import { fetchMe, logout, UnauthenticatedError, type Me } from "./api";
import { CharacterDetailPage } from "./pages/CharacterDetail";
import { CharacterListPage } from "./pages/CharacterList";
import { NewCharacterPage } from "./pages/NewCharacter";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RequireAuth><CharacterListPage /></RequireAuth>} />
        <Route path="/characters/new" element={<RequireAuth><NewCharacterPage /></RequireAuth>} />
        <Route path="/characters/:id" element={<RequireAuth><CharacterDetailPage /></RequireAuth>} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

/**
 * Gate that:
 *   - shows "loading" while we resolve the session
 *   - redirects to /login on 401
 *   - renders children with the current user available
 *
 * Wrapping each protected Route keeps the redirect logic in one place.
 */
function RequireAuth({ children }: { children: ReactNode }) {
  const meQ = useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    throwOnError: (e) => !(e instanceof UnauthenticatedError),
    retry: false,
  });

  if (meQ.isLoading) return <Layout><p>Loading…</p></Layout>;
  if (meQ.error instanceof UnauthenticatedError || !meQ.data) {
    return <Navigate to="/login" replace />;
  }
  return <AppShell me={meQ.data}>{children}</AppShell>;
}

function LoginPage() {
  const meQ = useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    throwOnError: (e) => !(e instanceof UnauthenticatedError),
    retry: false,
  });
  // If already signed in, bounce to the home view.
  if (meQ.data) return <Navigate to="/" replace />;

  return (
    <Layout>
      <h1>rmr — RMSS character builder</h1>
      <p>Sign in with Discord to start a character.</p>
      <a className="btn" href="/auth/discord/login">
        Sign in with Discord
      </a>
    </Layout>
  );
}

function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logoutM = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      qc.resetQueries({ queryKey: ["me"] });
      navigate("/login", { replace: true });
    },
  });

  return (
    <Layout>
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 24,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 20 }}>
          <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
            rmr
          </Link>
        </h1>
        <div style={{ fontSize: 13, color: "#666" }}>
          <span style={{ marginRight: 12 }}>
            {me.discord_username ?? me.discord_id}
          </span>
          <button className="btn-link" onClick={() => logoutM.mutate()}>
            Sign out
          </button>
        </div>
      </header>
      {children}
    </Layout>
  );
}

function Layout({ children }: { children: ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 720,
        margin: "40px auto",
        padding: "0 20px",
        fontFamily: "system-ui, sans-serif",
        lineHeight: 1.5,
      }}
    >
      <style>{`
        .btn {
          display: inline-block;
          padding: 8px 16px;
          background: #5865F2;
          color: white;
          border-radius: 6px;
          text-decoration: none;
          border: none;
          font-size: 14px;
          cursor: pointer;
        }
        .btn:hover { background: #4752C4; }
        .btn-secondary {
          background: #6b7280;
        }
        .btn-secondary:hover { background: #4b5563; }
        .btn-danger {
          background: #dc2626;
        }
        .btn-danger:hover { background: #b91c1c; }
        .btn-link {
          background: none;
          border: none;
          color: #5865F2;
          cursor: pointer;
          padding: 0;
          font-size: inherit;
          font-family: inherit;
        }
        .btn-link:hover { text-decoration: underline; }
        hr { border: 0; border-top: 1px solid #eee; margin: 24px 0; }
        input[type=text] {
          padding: 8px 10px;
          border: 1px solid #ccc;
          border-radius: 4px;
          font-size: 14px;
          width: 100%;
          box-sizing: border-box;
        }
        label {
          display: block;
          font-size: 13px;
          color: #444;
          margin-bottom: 4px;
        }
        .character-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 0;
          border-bottom: 1px solid #eee;
        }
        .character-row:last-child { border-bottom: 0; }
        .character-row a { color: #111; text-decoration: none; font-weight: 500; }
        .character-row a:hover { text-decoration: underline; }
      `}</style>
      {children}
    </main>
  );
}
