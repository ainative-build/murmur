// Gemini 3 clients with retry + fallback chain
client<llm> Gemini3Flash {
  provider google-ai
  retry_policy Exponential
  options {
    model gemini-3-flash-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> Gemini3FlashLite {
  provider google-ai
  retry_policy Exponential
  options {
    model gemini-3.1-flash-lite-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> Gemini3Pro {
  provider google-ai
  retry_policy Exponential
  options {
    model gemini-3.1-pro-preview
    api_key env.GEMINI_API_KEY
  }
}

// Fallback: Flash → Flash-Lite (handles 503 overload gracefully)
client<llm> LLMFallback {
  provider fallback
  options {
    strategy [Gemini3Flash, Gemini3FlashLite]
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
