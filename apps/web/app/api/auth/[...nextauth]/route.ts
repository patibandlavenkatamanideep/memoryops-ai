import { handlers } from "@/auth";

// Auth.js v5 route handlers (sign-in, sign-out, callback, session).
// Only mounted meaningfully in authenticated mode; in demo mode nothing calls it.
export const { GET, POST } = handlers;
