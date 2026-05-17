import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchMe, logout, UnauthenticatedError, type Me } from "./api";

export function App() {
  const qc = useQueryClient();
  const meQ = useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    // Surface 401 as "logged out" rather than an error toast.
    throwOnError: (e) => !(e instanceof UnauthenticatedError),
  });

  const logoutM = useMutation({
    mutationFn: logout,
    onSuccess: () => qc.resetQueries({ queryKey: ["me"] }),
  });

  if (meQ.isLoading) {
    return <Layout>Loading…</Layout>;
  }

  const me = meQ.data;
  const loggedOut = !me || meQ.error instanceof UnauthenticatedError;

  if (loggedOut) {
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

  return (
    <Layout>
      <h1>rmr</h1>
      <p>
        Signed in as <strong>{me.discord_username ?? me.discord_id}</strong> (user
        #{me.user_id})
      </p>
      <button className="btn" onClick={() => logoutM.mutate()}>
        Sign out
      </button>
      <hr />
      <p style={{ color: "#888" }}>
        Day-1 round-trip is working. Next: characters list, then chargen wizard.
      </p>
    </Layout>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
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
        hr { border: 0; border-top: 1px solid #eee; margin: 24px 0; }
      `}</style>
      {children}
    </main>
  );
}
