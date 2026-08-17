/**
 * What the server tells the shell about the caller.
 *
 * A plain serialisable projection of `Identity`, because the shell is a client
 * component and only what crosses that boundary can be rendered there. Deliberately
 * carries no credential and no capability set: it is a label, and every real decision
 * is re-made server-side by the BFF.
 */
export interface ShellIdentity {
  readonly tenantId: string;
  readonly userId: string;
  readonly role: string;
  readonly isDemo: boolean;
}
