"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useDocument } from "@/lib/api/hooks";

interface TocEntry {
  depth: 2 | 3;
  text: string;
  slug: string;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function extractToc(markdown: string): TocEntry[] {
  const entries: TocEntry[] = [];
  const seen = new Map<string, number>();
  let inFence = false;
  for (const line of markdown.split("\n")) {
    if (line.trimStart().startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = /^(#{2,3})\s+(.*)$/.exec(line);
    if (!match) continue;
    const text = match[2].replace(/[#*`]/g, "").trim();
    let slug = slugify(text);
    const count = seen.get(slug) ?? 0;
    seen.set(slug, count + 1);
    if (count > 0) slug = `${slug}-${count}`;
    entries.push({ depth: match[1].length as 2 | 3, text, slug });
  }
  return entries;
}

function headingText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(headingText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return headingText((children as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

/**
 * Rendered station documents: 20px prose for comfortable reading, with a
 * sticky table of contents and anchor-linkable headings.
 */
export function MarkdownDoc({ name, title }: { name: "runbook" | "glossary"; title: string }) {
  const { data, isPending, isError } = useDocument(name);
  const toc = useMemo(() => (data ? extractToc(data.markdown) : []), [data]);

  // ReactMarkdown renders headings in document order — the same order the
  // ToC was extracted in — so slugs are assigned by position.
  let headingIndex = 0;
  const slugFor = (children: ReactNode): string =>
    toc[headingIndex++]?.slug ?? slugify(headingText(children));

  if (isPending) {
    return <p className="text-base text-muted-foreground">Opening the {title.toLowerCase()}…</p>;
  }
  if (isError || !data) {
    return (
      <p className="text-base text-muted-foreground">
        The {title.toLowerCase()} is not installed on this station yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-8 lg:flex-row lg:gap-12">
      {toc.length > 1 && (
        <aside className="lg:order-last lg:w-64 lg:shrink-0">
          <nav
            aria-label="On this page"
            className="rounded-xl border bg-card p-4 lg:sticky lg:top-6"
          >
            <p className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
              On this page
            </p>
            <ul className="mt-2 flex max-h-[70vh] flex-col gap-1 overflow-y-auto">
              {toc.map((entry) => (
                <li key={entry.slug} className={entry.depth === 3 ? "pl-4" : undefined}>
                  <a
                    href={`#${entry.slug}`}
                    className="block min-h-8 py-1 text-sm text-muted-foreground hover:text-foreground"
                  >
                    {entry.text}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>
      )}

      {/* CUSTOM_STYLE: docs prose is spec'd at 20px, above the 18px app baseline */}
      <article className="min-w-0 max-w-[70ch] flex-1 text-[20px] leading-[1.65]">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => (
              <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">{children}</h1>
            ),
            h2: ({ children }) => (
              <h2
                id={slugFor(children)}
                className="mt-10 scroll-mt-6 border-b pb-2 font-display text-2xl font-semibold"
              >
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 id={slugFor(children)} className="mt-8 scroll-mt-6 font-display text-xl font-semibold">
                {children}
              </h3>
            ),
            p: ({ children }) => <p className="mt-4">{children}</p>,
            ul: ({ children }) => <ul className="mt-4 list-disc space-y-2 pl-6">{children}</ul>,
            ol: ({ children }) => <ol className="mt-4 list-decimal space-y-2 pl-6">{children}</ol>,
            a: ({ href, children }) => (
              <a href={href} className="underline underline-offset-4 hover:text-interesting">
                {children}
              </a>
            ),
            code: ({ children, className }) =>
              className ? (
                <code className={`${className} font-mono text-[17px]`}>{children}</code>
              ) : (
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[17px]">
                  {children}
                </code>
              ),
            pre: ({ children }) => (
              <pre className="mt-4 overflow-x-auto rounded-lg bg-muted p-4">{children}</pre>
            ),
            table: ({ children }) => (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full border-collapse text-[18px]">{children}</table>
              </div>
            ),
            th: ({ children }) => (
              <th className="border-b px-3 py-2 text-left font-semibold">{children}</th>
            ),
            td: ({ children }) => <td className="border-b px-3 py-2 align-top">{children}</td>,
            blockquote: ({ children }) => (
              <blockquote className="mt-4 rounded-lg bg-muted/60 px-4 py-1 italic">
                {children}
              </blockquote>
            ),
          }}
        >
          {data.markdown}
        </ReactMarkdown>
      </article>
    </div>
  );
}
