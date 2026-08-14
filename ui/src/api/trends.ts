import { api } from "./client";

export interface JobTrendPoint {
  date: string;
  success: number;
  failed: number;
  running: number;
  pending: number;
}

export interface ComplianceTrendPoint {
  date: string;
  outdated: number;
  up_to_date: number;
  checks: number;
}

export function getJobTrends(days = 14): Promise<JobTrendPoint[]> {
  return api.get<JobTrendPoint[]>("/trends/jobs", { days });
}

export function getComplianceTrends(days = 14): Promise<ComplianceTrendPoint[]> {
  return api.get<ComplianceTrendPoint[]>("/trends/compliance", { days });
}
