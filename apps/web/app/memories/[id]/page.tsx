"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import MemoryDetailPanel from "@/components/memories/MemoryDetailPanel";

export default function MemoryDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  return (
    <div className="space-y-6">
      <Link href="/memories" className="text-sm text-slate-400 hover:text-white">
        ← Back to memories
      </Link>
      <h1 className="text-2xl font-bold text-white">Memory detail</h1>
      {id ? (
        <MemoryDetailPanel memoryId={id} />
      ) : (
        <p className="text-sm text-rose-400">Missing memory id.</p>
      )}
    </div>
  );
}
