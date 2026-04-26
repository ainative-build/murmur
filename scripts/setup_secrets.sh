#!/bin/bash

# --- Setup Secrets in Google Cloud Secret Manager ---

# Define the specific secrets used by this application
SECRETS=(
  "GEMINI_API_KEY"
  "DEEPSEEK_API_KEY"
  "TAVILY_API_KEY"
  "TWITTER_API_IO_KEY"
  "AGENTQL_API_KEY"
  "TELEGRAM_BOT_TOKEN"
  "TELEGRAM_WEBHOOK_SECRET_TOKEN"
  "WEBHOOK_SECRET_PATH"
  "SUPABASE_URL"
  "SUPABASE_KEY"
  "TINYFISH_API_KEY"
  # NOTE: To create the MINIMAX_API_KEY secret manually in GCP Secret Manager:
  #   gcloud secrets create MINIMAX_API_KEY --replication-policy=automatic --project=<PROJECT_ID>
  #   printf "<your-key>" | gcloud secrets versions add MINIMAX_API_KEY --data-file=- --project=<PROJECT_ID>
  "MINIMAX_API_KEY"
)

# --- You shouldn't need to edit below this line --- 

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud command not found. Please install the Google Cloud SDK." >&2
    exit 1
fi

# Get PROJECT_ID if not set
if [ -z "${PROJECT_ID}" ]; then
  read -p "Enter your Google Cloud Project ID: " PROJECT_ID
  if [ -z "${PROJECT_ID}" ]; then
    echo "Error: Project ID cannot be empty." >&2
    exit 1
  fi
  export PROJECT_ID
  gcloud config set project "$PROJECT_ID"
fi

echo "Using Project ID: $PROJECT_ID"

echo "Enabling Secret Manager API (if not already enabled)..."
gcloud services enable secretmanager.googleapis.com --project="$PROJECT_ID"

# --- Grant Secret Accessor Role to Default Compute Service Account --- 
echo "Fetching Project Number for $PROJECT_ID..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

if [ -z "$PROJECT_NUMBER" ]; then
  echo "Error: Could not fetch Project Number for Project ID $PROJECT_ID." >&2
  echo "Please ensure the Project ID is correct and you have permissions." >&2
  exit 1
fi

SERVICE_ACCOUNT_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
ROLE_TO_GRANT="roles/secretmanager.secretAccessor"

echo "Checking if service account $SERVICE_ACCOUNT_EMAIL has role $ROLE_TO_GRANT..."
# Check current policy binding (suppress errors if role isn't found)
if ! gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten="bindings[].members" \
  --format='table(bindings.role)' \
  --filter="bindings.members:$SERVICE_ACCOUNT_EMAIL AND bindings.role:$ROLE_TO_GRANT" 2>/dev/null | grep -q "$ROLE_TO_GRANT"; then 

  echo "Granting '$ROLE_TO_GRANT' to service account '$SERVICE_ACCOUNT_EMAIL' on project '$PROJECT_ID'..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
      --role="$ROLE_TO_GRANT" \
      --condition=None # Explicitly setting no condition

  if [ $? -ne 0 ]; then
    echo "Error: Failed to grant IAM role $ROLE_TO_GRANT to $SERVICE_ACCOUNT_EMAIL." >&2
    echo "Please check permissions or grant the role manually via the Google Cloud Console." >&2
    # Decide if you want to exit or continue
    # exit 1 
  else
    echo "IAM role granted successfully."
  fi
else
    echo "Service account already has the required role."
fi
# --- End Grant Role ---


if [ ${#SECRETS[@]} -eq 0 ]; then
    echo "Internal Error: SECRETS array is empty in script ($0)." >&2
    exit 1
fi


for SECRET_NAME in "${SECRETS[@]}"; do
  echo "-------------------------------------"
  echo "Processing Secret: $SECRET_NAME"
  
  # Check if secret exists
  if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &> /dev/null; then
    echo "Secret '$SECRET_NAME' already exists."
    read -p "Do you want to add a new version with a new value? (y/N): " ADD_VERSION_CONFIRM
    if [[ "$ADD_VERSION_CONFIRM" =~ ^[Yy]$ ]]; then
      # Add new version
      # Prompt for the secret value without echoing to the terminal
      echo -n "Enter the new value for secret '$SECRET_NAME': "
      read -s SECRET_VALUE 
      echo # Add a newline after reading the secret
      if [ -z "$SECRET_VALUE" ]; then
         echo "Warning: Secret value is empty. Skipping adding new version for '$SECRET_NAME'." >&2
      else
         printf "%s" "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"
         echo "Added new version to secret '$SECRET_NAME'."
      fi
    else
      echo "Skipping secret '$SECRET_NAME'."
    fi
  else
    # Create secret
    echo "Secret '$SECRET_NAME' does not exist. Creating it..."
    gcloud secrets create "$SECRET_NAME" --replication-policy="automatic" --project="$PROJECT_ID"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create secret '$SECRET_NAME'." >&2
        continue # Skip to the next secret
    fi
    echo "Created secret '$SECRET_NAME'."

    # Add the first version
    # Prompt for the secret value without echoing to the terminal
    echo -n "Enter the value for secret '$SECRET_NAME': "
    read -s SECRET_VALUE
    echo 
    if [ -z "$SECRET_VALUE" ]; then
        echo "Warning: Secret value is empty. Creating secret '$SECRET_NAME' with no initial version." >&2
    else
        printf "%s" "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"
        echo "Added initial version to secret '$SECRET_NAME'."
    fi
  fi
done

echo "-------------------------------------"
echo "Secret setup process complete."
echo "Remember to grant your Cloud Run service account (PROJECT_NUMBER-compute@developer.gserviceaccount.com) the 'Secret Manager Secret Accessor' role for these secrets."
