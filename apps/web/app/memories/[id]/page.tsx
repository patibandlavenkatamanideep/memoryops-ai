"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import MemoryDetailPanel from "@/components/memories/MemoryDetailPanel";
import { ErrorState, PageHeader } from "@/components/ui";

export default function MemoryDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Runtime · Memories"
        title="Memory detail"
        description="Content, provenance and the append-only audit history for a single governed memory."
        actions={
          <Link
            href="/memories"
            className="inline-flex min-h-[2.25rem] items-center rounded-md text-sm text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
          >
            ← Back to memories
          </Link>
        }
      />
      {id ? (
        <MemoryDetailPanel memoryId={id} />
      ) : (
        <ErrorState title="Missing memory id" detail="This route requires a memory id." />
      )}
    </div>
  );
}
