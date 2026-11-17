import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Agent Regression Gate", description: "Agent 行为回归评测控制台" };
export const viewport: Viewport = { themeColor: "#0B1220", colorScheme: "dark" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
