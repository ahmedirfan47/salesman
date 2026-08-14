import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Salesman Dashboard",
  description: "AI Sales & Order Management",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}