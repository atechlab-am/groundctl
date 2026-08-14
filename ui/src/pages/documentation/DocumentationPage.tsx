import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { FileText } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { cn } from "@/lib/utils";
import { listDocs, getDoc } from "@/api/docs";

// The route param deliberately has no "." in it (slug = filename with
// .md stripped) even though every real doc filename is "name.md" — a
// hard refresh on e.g. /documentation/install.md would 404 for real
// instead of loading the SPA, because SPAStaticFiles (app/main.py)
// intentionally treats any path whose last segment contains a "." as a
// missing-asset request, not a client route (correct for real assets;
// this route would otherwise look identical to one). /documentation/install
// (no dot) avoids that check entirely rather than special-casing .md into
// the fallback logic, which would need to grow one exception per future
// feature that puts a dotted param in a route.
function slugFor(filename: string): string {
  return filename.replace(/\.md$/, "");
}

function filenameForSlug(slug: string): string {
  return `${slug}.md`;
}

export function DocumentationPage() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const filename = slug ? filenameForSlug(slug) : undefined;

  const listQuery = useQuery({ queryKey: ["docs"], queryFn: listDocs });

  // Land on the first doc (install.md if present, else whatever sorts
  // first) once the list loads and no doc is selected yet — /documentation
  // alone shouldn't show a blank pane.
  useEffect(() => {
    if (!slug && listQuery.data && listQuery.data.length > 0) {
      const preferred = listQuery.data.find((d) => d.filename === "install.md") ?? listQuery.data[0];
      if (preferred) navigate(`/documentation/${slugFor(preferred.filename)}`, { replace: true });
    }
  }, [slug, listQuery.data, navigate]);

  const docQuery = useQuery({
    queryKey: ["doc", filename],
    queryFn: () => getDoc(filename!),
    enabled: !!filename,
  });

  return (
    <div>
      <PageHeader title="Documentation" description="Installation, usage, and reference docs shipped with this groundctl install" />

      <div className="flex gap-6">
        <nav className="w-56 shrink-0">
          <QueryState isLoading={listQuery.isLoading} isError={listQuery.isError} error={listQuery.error}>
            <ul className="flex flex-col gap-0.5">
              {listQuery.data?.map((doc) => (
                <li key={doc.filename}>
                  <button
                    type="button"
                    onClick={() => navigate(`/documentation/${slugFor(doc.filename)}`)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium transition-colors",
                      filename === doc.filename
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    )}
                  >
                    <FileText className="h-4 w-4 shrink-0" />
                    <span className="truncate">{doc.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </QueryState>
        </nav>

        <div className="min-w-0 flex-1">
          <QueryState
            isLoading={docQuery.isLoading || (!filename && listQuery.isLoading)}
            isError={docQuery.isError}
            error={docQuery.error}
          >
            {docQuery.data && (
              <article className="prose prose-sm dark:prose-invert max-w-none rounded-lg border bg-card p-6">
                <ReactMarkdown>{docQuery.data.content}</ReactMarkdown>
              </article>
            )}
          </QueryState>
        </div>
      </div>
    </div>
  );
}
