"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
            // See below. A query that silently waits for the network shows a
            // spinner with nothing behind it.
            networkMode: "always",
          },
          mutations: {
            /*
              Attempt the request even when the browser says it is offline.

              The default holds a mutation unsent until the connection comes
              back, which leaves a submit button spinning with no explanation
              and no way to cancel — the browser's idea of "offline" is also
              wrong often enough that waiting on it is its own bug. Sending it
              anyway fails in milliseconds, and the client turns that into a
              message that says the server could not be reached, with
              everything the person typed still in the form.
            */
            networkMode: "always",
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
