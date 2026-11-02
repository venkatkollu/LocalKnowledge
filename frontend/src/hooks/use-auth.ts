/** Anonymous local workspaces are supported; deployments can enforce bearer auth in the API. */
export function useAuth() {
  return { isAuthenticated: true };
}
