import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useState } from "react";
import { useNavigate } from "react-router";

function stored(key: string, fallback: string) {
  return window.localStorage.getItem(key) ?? fallback;
}

export default function AuthPage() {
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState(stored("knowledgeos.workspace", "default"));
  const [user, setUser] = useState(stored("knowledgeos.user", "local"));
  const [token, setToken] = useState(stored("knowledgeos.token", ""));

  const save = () => {
    window.localStorage.setItem("knowledgeos.workspace", workspace.trim() || "default");
    window.localStorage.setItem("knowledgeos.user", user.trim() || "local");
    if (token.trim()) window.localStorage.setItem("knowledgeos.token", token.trim());
    else window.localStorage.removeItem("knowledgeos.token");
    navigate("/");
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>Workspace credentials</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-center text-sm text-muted-foreground">
            Anonymous local use is the default. If the backend sets
            <span className="font-mono"> KNOWLEDGEOS_ALLOW_ANONYMOUS=false</span>,
            paste the bearer token derived from the backend auth secret.
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="auth-workspace">Workspace ID</Label>
            <Input
              id="auth-workspace"
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auth-user">User ID</Label>
            <Input
              id="auth-user"
              value={user}
              onChange={(event) => setUser(event.target.value)}
              autoComplete="username"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auth-token">Bearer token (optional)</Label>
            <Input
              id="auth-token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="hex HMAC token"
              autoComplete="off"
            />
          </div>
          <Button className="w-full" onClick={save}>
            Save and continue
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
