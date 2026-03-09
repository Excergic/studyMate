import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata: Metadata = {
  title: "StudyBuddy",
  description: "AI study assistant for computer engineering",
};

const isPlaceholderClerkKey =
  !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY === "pk_test_placeholder";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const content = (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );

  if (isPlaceholderClerkKey) {
    return content;
  }

  return <ClerkProvider>{content}</ClerkProvider>;
}
