'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/shared/lib/supabase';

export default function LogoutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    setBusy(true);
    await supabase.auth.signOut();
    router.replace('/login');
    router.refresh();
  };

  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800 rounded transition font-mono uppercase tracking-wider disabled:opacity-50"
      aria-label="Sign out"
    >
      {busy ? '…' : 'Logout'}
    </button>
  );
}
