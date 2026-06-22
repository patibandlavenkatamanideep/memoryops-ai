import Link from "next/link";

const links = [
  { href: "/", label: "Home" },
  { href: "/chat", label: "Chat" },
  { href: "/memories", label: "Memories" },
  { href: "/governance", label: "Governance" },
  { href: "/audit", label: "Audit" },
  { href: "/loops", label: "Loops" },
  { href: "/admin", label: "Admin" },
  { href: "/architecture", label: "Architecture" },
];

export default function Nav() {
  return (
    <nav className="flex flex-wrap items-center gap-4 border-b border-slate-800 px-6 py-4">
      <Link href="/" className="font-semibold text-white">
        MemoryOps<span className="text-accent"> AI</span>
      </Link>
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
        {links.slice(1).map((l) => (
          <Link key={l.href} href={l.href} className="hover:text-white">
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
