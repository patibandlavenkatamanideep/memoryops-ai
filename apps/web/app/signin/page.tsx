import { redirect } from "next/navigation";

import { signIn } from "@/auth";
import { webMode } from "@/lib/identity";

/**
 * Operator sign-in.
 *
 * Uses the Credentials provider from auth.ts so the authenticated flow is runnable
 * and testable with no external IdP. Swap the provider there for GitHub/Okta/Auth0
 * and this page becomes a button instead of a form — nothing downstream changes,
 * because everything reads the mapped `tenantId` / `memoryopsUserId` / `role`.
 */
export default function SignInPage({
  searchParams,
}: {
  searchParams?: { callbackUrl?: string; error?: string };
}) {
  // Nothing to sign into in demo mode.
  if (webMode() !== "authenticated") redirect("/");

  const callbackUrl = searchParams?.callbackUrl ?? "/";
  const failed = Boolean(searchParams?.error);

  return (
    <div className="mx-auto max-w-sm py-16">
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-neutral-600">
        MemoryOps control plane — operator access.
      </p>

      {failed ? (
        <p
          role="alert"
          className="mt-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          Sign-in failed. Check your operator id and password.
        </p>
      ) : null}

      <form
        action={async (formData: FormData) => {
          "use server";
          await signIn("credentials", {
            email: formData.get("email"),
            password: formData.get("password"),
            redirectTo: callbackUrl,
          });
        }}
        className="mt-6 space-y-3"
      >
        <label className="block text-sm">
          <span className="text-neutral-700">Operator</span>
          <input
            name="email"
            autoComplete="username"
            required
            placeholder="tenant:user"
            className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="text-neutral-700">Password</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className="mt-1 w-full rounded border border-neutral-300 px-3 py-2"
          />
        </label>
        <button
          type="submit"
          className="w-full rounded bg-neutral-900 px-3 py-2 text-sm font-medium text-white"
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
