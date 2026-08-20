import { redirect } from "next/navigation";

import { signIn } from "@/auth";
import { Button, ErrorState, Field, Panel, PanelBody, TextInput } from "@/components/ui";
import { webMode } from "@/lib/identity";

/**
 * Operator sign-in.
 *
 * Uses the Credentials provider from auth.ts so the authenticated flow is runnable
 * and testable with no external IdP. Swap the provider there for GitHub/Okta/Auth0
 * and this page becomes a button instead of a form — nothing downstream changes,
 * because everything reads the mapped `tenantId` / `memoryopsUserId` / `role`.
 *
 * Rendered without the control-plane chrome (see components/shell/navigation.ts): a
 * sidebar of sections the visitor cannot open yet is noise, not navigation. That is a
 * presentation choice — the redirect that brought them here is middleware's, and the
 * BFF refuses independently.
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
    <main
      id="main-content"
      className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-6 py-16"
    >
      <div className="mb-8 space-y-2">
        <span className="flex items-center gap-2.5 text-sm font-semibold tracking-tight text-fg">
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-md border border-accent/40 bg-accent/10 font-mono text-[11px] text-accent-strong"
          >
            MO
          </span>
          MemoryOps<span className="text-fg-muted"> AI</span>
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Sign in</h1>
        <p className="text-sm text-fg-secondary">
          Operator access to the memory control plane.
        </p>
      </div>

      {failed ? (
        <ErrorState
          title="Sign-in failed"
          detail="Check your operator id and password."
          className="mb-4"
        />
      ) : null}

      <Panel>
        <PanelBody>
          <form
            action={async (formData: FormData) => {
              "use server";
              await signIn("credentials", {
                email: formData.get("email"),
                password: formData.get("password"),
                redirectTo: callbackUrl,
              });
            }}
            className="space-y-4"
          >
            <Field label="Operator" hint="Formatted as tenant:user.">
              <TextInput
                name="email"
                autoComplete="username"
                required
                placeholder="tenant:user"
              />
            </Field>
            <Field label="Password">
              <TextInput name="password" type="password" autoComplete="current-password" required />
            </Field>
            <Button type="submit" variant="primary" className="w-full">
              Sign in
            </Button>
          </form>
        </PanelBody>
      </Panel>

      <p className="mt-6 text-xs leading-relaxed text-fg-muted">
        Your session determines the tenant and user every request is scoped to. The
        browser never chooses that scope — it is attached server-side on each call.
      </p>
    </main>
  );
}
