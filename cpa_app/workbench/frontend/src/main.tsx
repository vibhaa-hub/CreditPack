import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AppThemeProvider } from "./theme";
import { NotifyProvider } from "./notify";
import { ApiError } from "./api";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && [401, 403, 404].includes(e.status)) && n < 2,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppThemeProvider>
      <QueryClientProvider client={queryClient}>
        <NotifyProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </NotifyProvider>
      </QueryClientProvider>
    </AppThemeProvider>
  </React.StrictMode>,
);
