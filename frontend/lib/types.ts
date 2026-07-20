export interface Citation {
  section: string;
  source_type: string;
  content_preview: string;
  similarity: number;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  latency_ms: number;
  cache_hit?: boolean;
  // Retrieval confidence computed by the backend. It excludes the 0.0 lexical
  // similarity of exact tag/card matches and treats a detected card as maximal,
  // so the UI must trust this number rather than averaging citation similarities.
  confidence?: number;
}

export type ErrorType = 'rate_limit' | 'timeout' | 'server' | 'network' | 'validation' | 'unknown' | 'cold_start';

export interface ApiError {
  type: ErrorType;
  message: string;
  retryAfter?: number;
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';

// The caller's daily token meter (GET /api/usage). `tier` is "anon" | "auth";
// the anon badge nudges the user to sign in for a higher limit.
export interface UsageInfo {
  used: number;
  quota: number;
  remaining: number;
  resets_at: string;
  tier: string;
}
