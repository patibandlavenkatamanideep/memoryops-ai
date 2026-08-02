import type { Metadata } from "next";
import "./globals.css";
import ModeBanner from "@/components/ModeBanner";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "MemoryOps AI — Enterprise memory governance",
  description:
    "A governed memory lifecycle for AI assistants: capture, evaluate, store, retrieve, forget, audit.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ModeBanner />
        <Nav />
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
