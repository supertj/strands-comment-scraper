// Writes the test exports with Comment Scraper's own serialisers, and records the lines the
// extension's Markdown export prints for every comment, so the Python tools are checked
// against the extension's code rather than against themselves. The threads are made up.
//
// Needs a checkout of supertj/comment-scraper-mcp next to this repository (its src/core is
// copied from the extension). Run from this repository's root:
//
//   make fixtures

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  SCHEMA_VERSION,
  commentLines,
  commentNumbers,
  toFlatJson,
  toNestedJson,
  type ExportRecord,
  type FetchReport,
} from "../../../comment-scraper-mcp/src/core/index";

const now = "2026-10-10T12:00:00.000Z";
const ago = (hours: number) => new Date(Date.parse(now) - hours * 3_600_000).toISOString();

type Comment = { id: string; parent: string | null; score: number | null; body: string; extra?: Partial<ExportRecord> };

/** Comments must be listed in tree order (depth first, orphans last), as the extension writes them. */
function thread(
  source: "reddit" | "hn",
  id: string,
  title: string,
  postBody: string,
  comments: Comment[],
  report: Omit<FetchReport, "path" | "requests">,
) {
  const subreddit = source === "reddit" ? "smallbusiness" : null;
  const permalink = source === "reddit" ? `https://www.reddit.com/r/smallbusiness/comments/${id}/` : `https://news.ycombinator.com/item?id=${id}`;
  const base = {
    schema_version: SCHEMA_VERSION,
    source,
    thread_id: id,
    thread_title: title,
    subreddit,
    score_hidden: false,
    edited_utc: null,
    is_op: false,
    comment_state: "normal" as const,
  };
  const records: ExportRecord[] = [
    { ...base, record_type: "post", comment_id: null, parent_id: null, depth: null, score: source === "reddit" ? 50 : 120, created_utc: ago(48), body: postBody, permalink, is_op: true } as ExportRecord,
  ];
  const depth = new Map<string, number>();
  for (const comment of comments) {
    const level = comment.parent ? (depth.get(comment.parent) ?? 0) + 1 : 0;
    depth.set(comment.id, level);
    const commentLink = source === "reddit" ? `${permalink}_/${comment.id}/` : `https://news.ycombinator.com/item?id=${comment.id}`;
    records.push({
      ...base,
      record_type: "comment",
      comment_id: comment.id,
      parent_id: comment.parent ?? id,
      depth: level,
      score: comment.score,
      created_utc: ago(24),
      body: comment.body,
      permalink: commentLink,
      ...comment.extra,
    } as ExportRecord);
  }
  return { records, report: { ...report, path: source === "reddit" ? ("json" as const) : ("api" as const), requests: 3 } };
}

const crm = thread(
  "reddit",
  "crm1",
  "Which CRM do small teams actually stick with?",
  "# Which CRM?\nWe are four people.",
  [
    { id: "a1", parent: null, score: 214, body: "We left our CRM after the renewal doubled." },
    { id: "a2", parent: "a1", score: 88, body: "Ask for the year-two price in writing.", extra: { is_op: true } },
    { id: "a3", parent: "a2", score: 31, body: "The export button was the first thing they hid.", extra: { edited_utc: ago(20) } },
    { id: "a8", parent: "a1", score: 2, body: "", extra: { comment_state: "removed" } },
    { id: "a4", parent: null, score: null, body: "Email sync is what made us stay. Renewal was fine.", extra: { score_hidden: true } },
    { id: "a5", parent: null, score: 3, body: "", extra: { comment_state: "deleted" } },
    { id: "a6", parent: "a5", score: 12, body: "# Not a heading\nWe ended up on a spreadsheet.\n\nSecond paragraph." },
    // Its parent was never fetched, so the extension puts it after every complete branch.
    { id: "a7", parent: "gone1", score: 5, body: "Same here, the renewal email came with no warning.", extra: { parent_missing: true, depth: 1 } },
  ],
  { fetched: 8, knownUnfetched: 2, reported: 12, status: "partial", stopReason: "rate_limited", fetchedAt: now },
);
crm.records.find((record) => record.comment_id === "a7")!.parent_id = "gone1";

const pricing = thread(
  "reddit",
  "price1",
  "Raising prices as a freelancer",
  "",
  [
    { id: "b1", parent: null, score: 12, body: "I raised my renewal rate by 20% and nobody left." },
    { id: "b2", parent: "b1", score: 4, body: "Did you tell them in advance, or just send the new price?" },
    { id: "b3", parent: "b1", score: 7, body: "  # Also not a heading\n```\nNot a code block either.\n~~~" },
  ],
  { fetched: 3, knownUnfetched: 0, reported: 3, status: "all_known_fetched", stopReason: null, fetchedAt: ago(2) },
);

const hnPricing = thread(
  "hn",
  "40001",
  "Ask HN: How do you price a side project?",
  "I have 30 paying users and no idea what to charge.",
  [
    { id: "40011", parent: null, score: null, body: "Charge more than feels comfortable. Half my users never noticed the price change." },
    { id: "40012", parent: "40011", score: null, body: "Same experience. The ones who left were not paying much anyway." },
  ],
  { fetched: 2, knownUnfetched: 1, reported: 3, status: "limit_reached", stopReason: "comment_limit", fetchedAt: ago(5) },
);

const hnEmpty = thread("hn", "40002", "Show HN: A tiny invoice generator", "", [], {
  fetched: 0,
  knownUnfetched: 0,
  reported: null,
  status: "all_known_fetched",
  stopReason: null,
  fetchedAt: ago(6),
});

// The envelope's exported_at is the time of writing; pin it so regenerating doesn't churn git.
const pin = (json: string) => json.replace(/"exported_at": "[^"]+"/, `"exported_at": "${now}"`);

const files: Record<string, { threads: ReturnType<typeof thread>[]; write: typeof toFlatJson }> = {
  "which-crm.json": { threads: [crm], write: toFlatJson },
  "which-crm-nested.json": { threads: [crm], write: toNestedJson },
  "pricing-nested.json": { threads: [pricing], write: toNestedJson },
  "hacker-news-two-threads.json": { threads: [hnPricing, hnEmpty], write: toFlatJson },
};

// For every comment: the number the Markdown export gives it and the lines it prints for the
// comment, starting with e.g. "[c3] reply to [c2] (score 31, 1d ago, edited)".
const golden: Record<string, Array<{ thread_id: string; comments: Array<{ comment_id: string; number: number; markdown_lines: string[] }> }>> = {};

const out = join("tests", "fixtures");
mkdirSync(out, { recursive: true });
for (const [name, { threads, write }] of Object.entries(files)) {
  writeFileSync(join(out, name), pin(write(threads)) + "\n");
  golden[name] = threads.map(({ records, report }) => {
    const numbers = commentNumbers(records);
    return {
      thread_id: records[0]!.thread_id,
      comments: records
        .filter((record) => record.record_type === "comment")
        .map((record) => ({
          comment_id: record.comment_id!,
          number: numbers.get(record.comment_id!)!,
          markdown_lines: commentLines(record, numbers, report.fetchedAt),
        })),
    };
  });
}
writeFileSync(join(out, "markdown-lines.json"), JSON.stringify(golden, null, 2) + "\n");
