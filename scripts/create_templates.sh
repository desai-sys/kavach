#!/usr/bin/env bash
# Submit Kavach's two WhatsApp templates for Meta approval.
# Usage: ./scripts/create_templates.sh <WABA_ID>
#   <WABA_ID> is the WhatsApp Business Account ID shown in the End User Messaging Social
#   console (Business accounts > your account). Approval usually takes minutes, sometimes hours.
set -euo pipefail
WABA_ID="${1:?Pass your WhatsApp Business Account ID}"
REGION="${AWS_REGION:-ap-south-1}"
DIR="$(cd "$(dirname "$0")" && pwd)/whatsapp_templates"

for file in "$DIR"/*.json; do
  echo "Submitting $(basename "$file")..."
  aws socialmessaging create-whatsapp-message-template \
    --region "$REGION" \
    --cli-binary-format raw-in-base64-out \
    --id "$WABA_ID" \
    --template-definition "file://$file"
done

echo "Check status: aws socialmessaging list-whatsapp-message-templates --id $WABA_ID --region $REGION"
