import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './api';

/** Exported singleton QueryClient. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, err) =>
        err instanceof ApiError && err.isClient ? false : count < 2,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
  },
});
