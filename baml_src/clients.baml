// Gemini 3 clients (v1 choice — model swaps are a config change)
client<llm> Gemini3Flash {
  provider google-ai
  options {
    model gemini-3-flash-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> Gemini3Pro {
  provider google-ai
  options {
    model gemini-3.1-pro-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> DeepSeekV3 {
  provider "openai"
  options {
    api_key env.DEEPSEEK_API_KEY
    base_url "https://api.deepseek.com"
    model "deepseek-chat"
    temperature 0.1
  }
}

// Use Gemini 3 Flash directly — DeepSeek removed (no valid key in production)
client<llm> LLMFallback {
  provider google-ai
  options {
    model gemini-3-flash-preview
    api_key env.GEMINI_API_KEY
  }
}

// https://docs.boundaryml.com/docs/snippets/clients/retry
retry_policy Constant {
  max_retries 3
  strategy {
    type constant_delay
    delay_ms 200
  }
}

retry_policy Exponential {
  max_retries 2
  strategy {
    type exponential_backoff
    delay_ms 300
    multiplier 1.5
    max_delay_ms 10000
  }
}
