import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/api/events";

export function useHealthCheck(intervalMs = 10000) {
  const q = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: intervalMs,
    retry: false,
  });
  return { isOnline: q.isSuccess && !q.isError, data: q.data, error: q.error, isLoading: q.isLoading };
}
