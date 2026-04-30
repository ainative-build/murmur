// MiniMax client for routing/summarization (OpenAI-compatible API).
// No Gemini API key — Gemini features go through Vertex AI in src/providers/.
client<llm> MiniMaxText {
  provider openai-generic
  retry_policy Exponential
  options {
    model "MiniMax-Text-01"
    base_url "https://api.minimax.io/v1"
    api_key env.MINIMAX_API_KEY
    // MiniMax rejects requests with only a system message (error 2013).
    // Force the prompt to be sent as a user message.
    default_role "user"
  }
}

// Single-strategy fallback (kept for future expansion). BAML requires the
// fallback wrapper to allow strategy changes without touching call sites.
client<llm> LLMFallback {
  provider fallback
  options {
    strategy [MiniMaxText]
  }
}

retry_policy Constant {
  max_retries 3
  strategy {
    type constant_delay
    delay_ms 200
  }
}

retry_policy Exponential {
  max_retries 3
  strategy {
    type exponential_backoff
    delay_ms 1000
    multiplier 2
    max_delay_ms 15000
  }
}
