import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEO Engine",
  description: "An agentic SEO and digital growth operating system.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
