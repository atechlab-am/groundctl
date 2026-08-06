import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QueryState } from "@/components/QueryState";
import {
  getBranding,
  updateBrandingColors,
  uploadLogo,
  uploadFavicon,
  logoUrl,
  faviconUrl,
} from "@/api/branding";
import { applyBrandingColors, DEFAULT_PRIMARY_COLOR, DEFAULT_ACCENT_COLOR } from "@/lib/branding";
import { errorMessage } from "@/lib/errors";

export function AppearanceTab() {
  const queryClient = useQueryClient();
  const logoInputRef = useRef<HTMLInputElement>(null);
  const faviconInputRef = useRef<HTMLInputElement>(null);
  const [primaryColor, setPrimaryColor] = useState<string | null>(null);
  const [accentColor, setAccentColor] = useState<string | null>(null);
  const [colorError, setColorError] = useState<string | null>(null);

  const brandingQuery = useQuery({ queryKey: ["branding"], queryFn: getBranding });

  // Seed the local color inputs from the server once the query resolves —
  // afterward the inputs are the source of truth until Save, so a
  // background refetch doesn't yank the fields out from under someone
  // mid-edit. useEffect, not useQuery's onSuccess (removed in TanStack
  // Query v5 — this codebase is on ^5.101.4).
  useEffect(() => {
    if (!brandingQuery.data) return;
    setPrimaryColor((current) => current ?? brandingQuery.data.primary_color ?? DEFAULT_PRIMARY_COLOR);
    setAccentColor((current) => current ?? brandingQuery.data.accent_color ?? DEFAULT_ACCENT_COLOR);
  }, [brandingQuery.data]);

  const colorsMutation = useMutation({
    mutationFn: updateBrandingColors,
    onSuccess: (data) => {
      toast.success("Colors updated");
      void queryClient.invalidateQueries({ queryKey: ["branding"] });
      applyBrandingColors(data.primary_color, data.accent_color);
      setColorError(null);
    },
    onError: (err) => setColorError(errorMessage(err)),
  });

  const logoMutation = useMutation({
    mutationFn: uploadLogo,
    onSuccess: () => {
      toast.success("Logo updated");
      void queryClient.invalidateQueries({ queryKey: ["branding"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const faviconMutation = useMutation({
    mutationFn: uploadFavicon,
    onSuccess: () => {
      toast.success("Favicon updated");
      void queryClient.invalidateQueries({ queryKey: ["branding"] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  function handleSaveColors() {
    setColorError(null);
    colorsMutation.mutate({ primary_color: primaryColor, accent_color: accentColor });
  }

  function handleLogoChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) logoMutation.mutate(file);
    e.target.value = "";
  }

  function handleFaviconChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) faviconMutation.mutate(file);
    e.target.value = "";
  }

  return (
    <QueryState isLoading={brandingQuery.isLoading} isError={brandingQuery.isError} error={brandingQuery.error}>
      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Colors</CardTitle>
            <CardDescription>Applied instantly for every user once saved.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {colorError && <p className="text-sm text-destructive">{colorError}</p>}
            <div className="flex flex-wrap gap-6">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="primary-color">Primary color</Label>
                <div className="flex items-center gap-2">
                  <input
                    id="primary-color"
                    type="color"
                    value={primaryColor ?? DEFAULT_PRIMARY_COLOR}
                    onChange={(e) => setPrimaryColor(e.target.value)}
                    className="h-9 w-12 cursor-pointer rounded-md border border-input"
                  />
                  <Input
                    value={primaryColor ?? ""}
                    onChange={(e) => setPrimaryColor(e.target.value)}
                    placeholder={DEFAULT_PRIMARY_COLOR}
                    className="w-32 font-mono text-xs"
                  />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="accent-color">Accent color</Label>
                <div className="flex items-center gap-2">
                  <input
                    id="accent-color"
                    type="color"
                    value={accentColor ?? DEFAULT_ACCENT_COLOR}
                    onChange={(e) => setAccentColor(e.target.value)}
                    className="h-9 w-12 cursor-pointer rounded-md border border-input"
                  />
                  <Input
                    value={accentColor ?? ""}
                    onChange={(e) => setAccentColor(e.target.value)}
                    placeholder={DEFAULT_ACCENT_COLOR}
                    className="w-32 font-mono text-xs"
                  />
                </div>
              </div>
            </div>
            <Button onClick={handleSaveColors} disabled={colorsMutation.isPending} className="self-start">
              {colorsMutation.isPending ? "Saving…" : "Save colors"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Logo</CardTitle>
            <CardDescription>Shown in the sidebar. PNG, JPEG, or WebP, up to 2 MB.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-md border bg-muted">
              {brandingQuery.data?.has_logo ? (
                <img src={logoUrl(brandingQuery.data.updated_at)} alt="Current logo" className="h-full w-full object-contain" />
              ) : (
                <span className="text-xs text-muted-foreground">None</span>
              )}
            </div>
            <input
              ref={logoInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={handleLogoChange}
            />
            <Button variant="outline" onClick={() => logoInputRef.current?.click()} disabled={logoMutation.isPending}>
              <Upload className="h-4 w-4" />
              {logoMutation.isPending ? "Uploading…" : "Upload logo"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Favicon</CardTitle>
            <CardDescription>Shown in the browser tab. PNG, JPEG, WebP, or ICO, up to 2 MB.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-4">
            <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded border bg-muted">
              {brandingQuery.data?.has_favicon ? (
                <img
                  src={faviconUrl(brandingQuery.data.updated_at)}
                  alt="Current favicon"
                  className="h-full w-full object-contain"
                />
              ) : (
                <span className="text-[10px] text-muted-foreground">None</span>
              )}
            </div>
            <input
              ref={faviconInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/x-icon"
              className="hidden"
              onChange={handleFaviconChange}
            />
            <Button
              variant="outline"
              onClick={() => faviconInputRef.current?.click()}
              disabled={faviconMutation.isPending}
            >
              <Upload className="h-4 w-4" />
              {faviconMutation.isPending ? "Uploading…" : "Upload favicon"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </QueryState>
  );
}
