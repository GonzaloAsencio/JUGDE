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
}

export type ErrorType = 'rate_limit' | 'timeout' | 'server' | 'network' | 'validation' | 'unknown';

export interface ApiError {
  type: ErrorType;
  message: string;
  retryAfter?: number;
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';
