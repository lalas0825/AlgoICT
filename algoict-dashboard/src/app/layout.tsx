import type { Metadata } from 'next';
import { DM_Sans, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-dm-sans',
  display: 'swap',
});

const ibmPlexMono = IBM_Plex_Mono({
  weight: ['400', '500', '600'],
  subsets: ['latin'],
  variable: '--font-ibm-plex-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'AlgoICT Dashboard',
  description: '6-layer AI trading intelligence — ICT + SWC + GEX + VPIN + Strategy Lab + Post-Mortem',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${dmSans.variable} ${ibmPlexMono.variable} antialiased`}
    >
      <body
        className="bg-zinc-950 text-zinc-50 font-sans min-h-screen"
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
