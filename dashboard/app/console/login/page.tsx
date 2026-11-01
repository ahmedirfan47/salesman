"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { consoleLogin, getAdminToken } from "@/lib/console-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

/** Sign-in for Stonic admins. Business accounts can't sign in here, and the site switches never close it. */
export default function ConsoleLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getAdminToken()) router.replace("/console");
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await consoleLogin(email, password);
      router.replace("/console");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 text-center">
          <div className="flex items-center justify-center gap-2 text-2xl font-bold tracking-tight">
            <ShieldCheck size={24} className="text-[var(--primary)]" /> Stonic Console
          </div>
          <p className="mt-1 text-sm text-slate-500">For Stonic admins only</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium">Email</label>
            <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Password</label>
            <Input type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}