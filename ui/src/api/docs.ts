import { api } from "./client";

export interface DocSummary {
  filename: string;
  title: string;
}

export interface DocRead {
  filename: string;
  title: string;
  content: string;
}

export function listDocs(): Promise<DocSummary[]> {
  return api.get<DocSummary[]>("/docs");
}

export function getDoc(filename: string): Promise<DocRead> {
  return api.get<DocRead>(`/docs/${encodeURIComponent(filename)}`);
}
