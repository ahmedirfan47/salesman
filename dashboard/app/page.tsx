"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken, isDemo } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    // signed in: the dashboard; everyone else (including a demo visitor) starts at the plans page
    router.replace(getToken() && !isDemo() ? "/overview" : "/plans");
  }, [router]);

  return null;
}