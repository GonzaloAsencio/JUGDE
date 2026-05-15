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
}

export interface QueryError {
  message: string;
  status?: number;
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';
