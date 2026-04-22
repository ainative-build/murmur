#!/bin/bash

# --- Deploy the Telegram Summarizer Bot to Google Cloud Run ---

set -e # Exit immediately if a command exits with a non-zero status.

# --- Configuration --- 
# You can set these environment variables or the script will prompt you.
# PROJECT_ID="your-gcp-project-id"
# REGION="your-preferred-region" # e.g., us-central1
# SERVICE_NAME="telegram-summarizer"
# REPO_NAME="my-summarizer-bot-repo" # Artifact Registry repo name

# Define the secrets to map from Secret Manager to Cloud Run environment variables.
# Format: "ENV_VAR_NAME_IN_CLOUDRUN=SECRET_NAME_IN_MANAGER:latest"
SECRETS_TO_MAP=(
  "TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest"
  "TELEGRAM_WEBHOOK_SECRET_TOKEN=TELEGRAM_WEBHOOK_SECRET_TOKEN:latest"
  "WEBHOOK_SECRET_PATH=WEBHOOK_SECRET_PATH:latest"
  "GEMINI_API_KEY=GEMINI_API_KEY:latest"
  "DEEPSEEK_API_KEY=DEEPSEEK_API_KEY:latest"
  "TAVILY_API_KEY=TAVILY_API_KEY:latest"
  "TWITTER_API_IO_KEY=TWITTER_API_IO_KEY:latest"
  "AGENTQL_API_KEY=AGENTQL_API_KEY:latest"
  "SUPABASE_URL=SUPABASE_URL:latest"
  "SUPABASE_KEY=SUPABASE_KEY:latest"
)

# --- Script Logic --- 

# Check dependencies
if ! command -v gcloud &> /dev/null; then echo "Error: gcloud not found. Please install Google Cloud SDK." >&2; exit 1; fi
if ! command -v docker &> /dev/null; then echo "Error: docker not found. Please install Docker." >&2; exit 1; fi

# Get configuration if not set via environment variables
PROJECT_ID=${PROJECT_ID:-"$(gcloud config get-value project)"}
if [ -z "${PROJECT_ID}" ]; then read -p "Enter Google Cloud Project ID: " PROJECT_ID; fi
if [ -z "${PROJECT_ID}" ]; then echo "Error: Project ID is required." >&2; exit 1; fi
gcloud config set project "$PROJECT_ID"

REGION=${REGION:-"$(gcloud config get-value run/region)"}
if [ -z "${REGION}" ]; then read -p "Enter Google Cloud Region (e.g., us-central1): " REGION; fi
if [ -z "${REGION}" ]; then echo "Error: Region is required." >&2; exit 1; fi
gcloud config set run/region "$REGION"

SERVICE_NAME=${SERVICE_NAME:-"murmur-bot"}
read -p "Enter Cloud Run Service Name [${SERVICE_NAME}]: " INPUT_SERVICE_NAME
SERVICE_NAME=${INPUT_SERVICE_NAME:-$SERVICE_NAME}

REPO_NAME=${REPO_NAME:-"murmur-bot-repo"}
read -p "Enter Artifact Registry Repository Name [${REPO_NAME}]: " INPUT_REPO_NAME
REPO_NAME=${INPUT_REPO_NAME:-$REPO_NAME}

# Construct image name
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"

echo "--- Deployment Configuration ---"
echo "Project ID:       $PROJECT_ID"
echo "Region:           $REGION"
echo "Service Name:     $SERVICE_NAME"
echo "Artifact Repo:    $REPO_NAME"
echo "Image Name:       $IMAGE_NAME"
echo "------------------------------"
read -p "Proceed with deployment? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
  echo "Deployment cancelled."
  exit 0
fi

# Get the directory of the script itself
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
PROJECT_ROOT="$SCRIPT_DIR/.."

# Enable APIs
echo "Enabling required Google Cloud APIs..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com --project="$PROJECT_ID"

# Create Artifact Registry Repository
echo "Checking/Creating Artifact Registry repository '$REPO_NAME' in region '$REGION'..."
if ! gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" --project="$PROJECT_ID" &> /dev/null; then
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker repository for $SERVICE_NAME" \
    --project="$PROJECT_ID"
  echo "Created Artifact Registry repository."
else
  echo "Artifact Registry repository already exists."
fi

# Configure Docker Authentication
echo "Configuring Docker authentication for $REGION..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --project="$PROJECT_ID"

# Build the Docker image
echo "Building Docker image '$IMAGE_NAME' from $PROJECT_ROOT..."
cd "$PROJECT_ROOT" || exit 1
# Force linux/amd64 — Cloud Run is amd64; building on Apple Silicon would
# otherwise produce arm64 binaries that fail at startup with "exec format error".
docker build --platform=linux/amd64 -t "$IMAGE_NAME" .
if [ $? -ne 0 ]; then echo "Error: Docker build failed." >&2; exit 1; fi

# Push the Docker image
echo "Pushing Docker image to Artifact Registry..."
docker push "$IMAGE_NAME"
if [ $? -ne 0 ]; then echo "Error: Docker push failed." >&2; exit 1; fi

# Construct secrets argument
if [ ${#SECRETS_TO_MAP[@]} -eq 0 ]; then
    # This case should not happen with the hardcoded list above
    echo "Internal Error: SECRETS_TO_MAP array is empty in script ($0)." >&2
    exit 1
fi
SECRETS_ARG=$(printf -- "--set-secrets=%s" "$(IFS=,; echo "${SECRETS_TO_MAP[*]}")")
echo "Will map the following secrets to environment variables in Cloud Run:" 
printf "  %s\n" "${SECRETS_TO_MAP[@]}"

# Deploy to Cloud Run
echo "Deploying service '$SERVICE_NAME' to Cloud Run in region '$REGION'..."

# You can add additional flags here as needed. Example:
# --memory=512Mi     # Specify memory
# --cpu=1            # Specify CPU
# --min-instances=0  # Allows scaling to zero (default, so not explicitly required)
# --max-instances=10 # Maximum number of instances

gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE_NAME" \
  --platform=managed \
  --region="$REGION" \
  --port=8080 \
  --allow-unauthenticated \
  --memory=1024Mi \
  --min-instances=1 \
  --cpu-throttling \
  $SECRETS_ARG \
  --project="$PROJECT_ID"

if [ $? -ne 0 ]; then echo "Error: Cloud Run deployment failed." >&2; exit 1; fi

# Get the service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --platform managed --region "$REGION" --format 'value(status.url)' --project="$PROJECT_ID")
echo "Service deployed successfully. URL: $SERVICE_URL"

# --- Set Telegram Webhook --- 
echo "Attempting to set Telegram webhook..."

# Find the secret IDs for the bot token and webhook path from the mapping
TELEGRAM_BOT_TOKEN_SECRET_ID=""
WEBHOOK_SECRET_PATH_SECRET_ID=""
WEBHOOK_SECRET_TOKEN_SECRET_ID=""

for mapping in "${SECRETS_TO_MAP[@]}"; do
  env_var_name=$(echo "$mapping" | cut -d'=' -f1)
  secret_ref=$(echo "$mapping" | cut -d'=' -f2)
  secret_id=$(echo "$secret_ref" | cut -d':' -f1)
  
  if [[ "$(echo "$env_var_name" | tr '[:upper:]' '[:lower:]')" == "telegram_bot_token" ]]; then
    TELEGRAM_BOT_TOKEN_SECRET_ID="$secret_id"
  fi
  # Use the env var name expected by bot.py (which matches the secret name here)
  if [[ "$(echo "$env_var_name" | tr '[:upper:]' '[:lower:]')" == "webhook_secret_path" ]]; then
    WEBHOOK_SECRET_PATH_SECRET_ID="$secret_id"
  fi
  if [[ "$(echo "$env_var_name" | tr '[:upper:]' '[:lower:]')" == "telegram_webhook_secret_token" ]]; then
    WEBHOOK_SECRET_TOKEN_SECRET_ID="$secret_id"
  fi
done

if [ -z "$TELEGRAM_BOT_TOKEN_SECRET_ID" ]; then
  echo "Error: Could not find TELEGRAM_BOT_TOKEN mapping in SECRETS_TO_MAP. Cannot set webhook." >&2
  exit 1
fi

if [ -z "$WEBHOOK_SECRET_PATH_SECRET_ID" ]; then
  echo "Warning: Could not find WEBHOOK_SECRET_PATH mapping in SECRETS_TO_MAP." >&2
  echo "Will attempt to set webhook using default '/webhook' path." >&2
  # Default path if not found in secrets
  WEBHOOK_PATH_VALUE="/webhook"
else
  echo "Fetching Webhook Secret Path from Secret Manager..."
  WEBHOOK_PATH_VALUE=$(gcloud secrets versions access latest --secret="$WEBHOOK_SECRET_PATH_SECRET_ID" --project="$PROJECT_ID")
  # Ensure path starts with a slash
  if [[ "$WEBHOOK_PATH_VALUE" != /* ]]; then
      WEBHOOK_PATH_VALUE="/$WEBHOOK_PATH_VALUE"
  fi
fi

# Fetch the latest version of the secrets
echo "Fetching Telegram Bot Token from Secret Manager..."
TELEGRAM_BOT_TOKEN=$(gcloud secrets versions access latest --secret="$TELEGRAM_BOT_TOKEN_SECRET_ID" --project="$PROJECT_ID")

WEBHOOK_SECRET_TOKEN=""
if [ -n "$WEBHOOK_SECRET_TOKEN_SECRET_ID" ]; then
  echo "Fetching Webhook Secret Token from Secret Manager..."
  WEBHOOK_SECRET_TOKEN=$(gcloud secrets versions access latest --secret="$WEBHOOK_SECRET_TOKEN_SECRET_ID" --project="$PROJECT_ID")
fi

# Construct webhook URL
FINAL_WEBHOOK_URL="${SERVICE_URL}${WEBHOOK_PATH_VALUE}"

echo "Setting webhook to: $FINAL_WEBHOOK_URL"

# Use curl to set the webhook
API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook"

echo "DEBUG: Preparing curl command..."

# Construct the complete JSON payload in one string
if [ -n "$WEBHOOK_SECRET_TOKEN" ]; then
  echo "Using webhook secret token."
  JSON_PAYLOAD="{\"url\": \"$FINAL_WEBHOOK_URL\", \"secret_token\": \"$WEBHOOK_SECRET_TOKEN\"}"
else
  echo "No webhook secret token found/used."
  JSON_PAYLOAD="{\"url\": \"$FINAL_WEBHOOK_URL\"}"
fi

echo "DEBUG: JSON Payload: $JSON_PAYLOAD"

# Function to make the curl request with retries
set_webhook_with_retry() {
  local max_retries=3
  local retry_count=0
  local wait_time=2

  while [ $retry_count -lt $max_retries ]; do
    echo "DEBUG: Setting webhook (attempt $((retry_count + 1))/$max_retries)..."
    
    # Make the request
    RESPONSE=$(curl -s -X POST "$API_URL" \
      -H "Content-Type: application/json" \
      -d "$JSON_PAYLOAD")
    
    CURL_EXIT_CODE=$?

    # Check for rate limit error
    if [ $CURL_EXIT_CODE -eq 0 ] && echo "$RESPONSE" | grep -q '"error_code":429'; then
      retry_after=$(echo "$RESPONSE" | grep -o '"retry_after":[0-9]*' | grep -o '[0-9]*')
      
      # If retry_after is not found or not a number, use default wait time
      if [ -z "$retry_after" ] || ! [[ "$retry_after" =~ ^[0-9]+$ ]]; then
        retry_after=$wait_time
      fi
      
      echo "Rate limited by Telegram API. Waiting ${retry_after}s before retry..."
      sleep $((retry_after + 1))  # Wait a bit longer than recommended
      retry_count=$((retry_count + 1))
      continue
    fi
    
    # If we get here, either there was no rate limit error or another error occurred
    break
  done
  
  return $CURL_EXIT_CODE
}

# Call the function to make the request with retries
set_webhook_with_retry
CURL_EXIT_CODE=$?

# For debugging, let's see the response
echo "DEBUG: Webhook response: $RESPONSE"

# Check response from Telegram API
if [ $CURL_EXIT_CODE -ne 0 ]; then
    echo "Error: curl command failed with exit code $CURL_EXIT_CODE" >&2
    exit 1
elif echo "$RESPONSE" | grep -q '"ok":true'; then
  echo "Telegram webhook set successfully!"
  echo "Result: $RESPONSE"
elif echo "$RESPONSE" | grep -q '"description":"Webhook is already set"'; then
  # This is also a success case, webhook is properly set
  echo "Telegram webhook was already set to this URL."
  echo "Result: $RESPONSE"
else
  echo "Error setting Telegram webhook." >&2
  echo "URL used: $FINAL_WEBHOOK_URL" >&2
  echo "Check TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET_PATH (if used), and ensure the service URL is correct and publicly accessible." >&2
  echo "Telegram API Response: $RESPONSE" >&2
  exit 1
fi

echo "--- Deployment Complete ---"
