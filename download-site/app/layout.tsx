import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export const metadata: Metadata = {
  metadataBase: new URL('https://ai-hub-windows-download.ai-pro-myhome.chatgpt.site'),
  title: 'AI Hub — Windows 多模型 AI 工作台',
  description: '下載 AI Hub，在 Windows 本機統一使用 Codex、Gemini、ChatGPT 與開源 AI。',
  openGraph: {
    title: 'AI Hub — Windows 多模型 AI 工作台',
    description: '下載 AI Hub，在 Windows 本機統一使用 Codex、Gemini、ChatGPT 與開源 AI。',
    images: [{ url: '/og.png', width: 1733, height: 909, alt: 'AI Hub Windows 多模型 AI 工作台' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'AI Hub — Windows 多模型 AI 工作台',
    description: '下載 AI Hub，在 Windows 本機統一使用 Codex、Gemini、ChatGPT 與開源 AI。',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-Hant">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body>
    </html>
  );
}
