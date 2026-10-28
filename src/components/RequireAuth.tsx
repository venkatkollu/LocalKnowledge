import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";
import { Lock } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

export function RequireAuth({
  children,
  title = "Authentication required",
}: {
  children: ReactNode;
  title?: string;
  description?: string;
  redirectImmediately?: boolean;
}) {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  if (isAuthenticated) return children;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <Lock className="mb-2 size-5 text-muted-foreground" />
          <CardTitle className="text-xl">{title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-center text-sm text-muted-foreground">
          <p>Sign in with a workspace credential to continue.</p>
          <Button variant="outline" onClick={() => navigate("/")}>
            Back to home
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
