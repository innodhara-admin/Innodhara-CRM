import { QueryClient } from "@tanstack/react-query";

/**
 * Reads may retry. **Writes never do** (D17, §4.1).
 *
 * Do not "fix" this by turning mutation retries on. The server reads no
 * `Idempotency-Key` and has no dedupe on any admin write — verified across all
 * of `app/` — so a retried POST creates a second program, vendor or approval
 * rule, and the operator is never told. A failed write surfaces the server's
 * own message and the operator decides.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      // Setup data changes only when this console changes it, so refetching on
      // every window focus would be noise against a local backend.
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
    mutations: { retry: 0 },
  },
});
