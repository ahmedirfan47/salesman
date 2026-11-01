"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Lock } from "lucide-react";
import { getSite, login, PREVIEW, type SiteStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [site, setSite] = useState<SiteStatus | null>(null);

  useEffect(() => {
    if (PREVIEW) {
      router.replace("/overview"); // preview mode: no sign-in
      return;
    }
    getSite().then(setSite);
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  const closed = site !== null && !site.sign_in_enabled;

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm p-8">
        <div className="mb-6 text-center">
          <div className="text-2xl font-bold tracking-tight">
            Salesman<span className="text-[var(--primary)]">.</span>
          </div>
          <p className="mt-1 text-sm text-slate-500">Sign in to your dashboard</p>
        </div>
        {closed ? (
          // Sign-in is switched off (or the server can't be reached): a form here could only fail.
          <>
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <Lock size={16} className="mt-0.5 shrink-0" />
              <span>{site.closed_message}</span>
            </div>
            <Link href="/plans"
              className="mt-5 block w-full rounded-lg bg-[var(--primary)] py-2 text-center text-sm font-medium text-white hover:opacity-90">
              See plans and pricing
            </Link>
          </>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium">Email</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@company.com"
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Password</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        )}
        {site?.sign_up_enabled !== false && (
          <p className="mt-6 text-center text-sm text-slate-500">
            New here?{" "}
            <Link href="/signup" className="font-medium text-[var(--primary)] hover:underline">
              Create an account
            </Link>
          </p>
        )}
      </Card>
    </div>
  );
}