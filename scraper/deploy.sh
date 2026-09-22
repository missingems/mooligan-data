#!/usr/bin/env bash
# Builds the scraper image with Cloud Build and deploys it as a Cloud Run Job
# that Cloud Scheduler starts at 02:00 and 14:00 UTC. The 4-hour task timeout
# covers the first run, which reads each archetype's whole history window.
#
#   PROJECT_ID=my-project ./deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
JOB="${JOB:-mtggoldfish-scraper}"
REPOSITORY="${REPOSITORY:-mtg-meta}"
SCHEDULE="${SCHEDULE:-0 2,14 * * *}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${JOB}:latest"
RUNNER_SA="${JOB}@${PROJECT_ID}.iam.gserviceaccount.com"
INVOKER_SA="${JOB}-invoker@${PROJECT_ID}.iam.gserviceaccount.com"

cd "$(dirname "$0")"
gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com firestore.googleapis.com

gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$REPOSITORY" --repository-format docker --location "$REGION"

# The job runs as its own account, allowed to write Firestore and nothing else.
gcloud iam service-accounts describe "$RUNNER_SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$JOB" --display-name "MTGGoldfish scraper"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${RUNNER_SA}" --role roles/datastore.user --condition None >/dev/null

gcloud builds submit --tag "$IMAGE" .

gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "$RUNNER_SA" \
  --cpu 2 --memory 2Gi \
  --task-timeout 14400s --max-retries 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},FORMATS=${FORMATS:-modern,standard,pioneer},META_DAYS=${META_DAYS:-30},EVENTS_PER_FORMAT=${EVENTS_PER_FORMAT:-10},MAX_NEW_EVENTS=${MAX_NEW_EVENTS:-60},MAX_NEW_DECKS=${MAX_NEW_DECKS:-400},HISTORY_DAYS=${HISTORY_DAYS:-30}"

# Cloud Scheduler starts the job through the Cloud Run Admin API as the invoker account.
gcloud iam service-accounts describe "$INVOKER_SA" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "${JOB}-invoker" --display-name "MTGGoldfish scraper scheduler"
gcloud run jobs add-iam-policy-binding "$JOB" --region "$REGION" \
  --member "serviceAccount:${INVOKER_SA}" --role roles/run.invoker >/dev/null

RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB}:run"
if gcloud scheduler jobs describe "$JOB" --location "$REGION" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi
gcloud scheduler jobs "$VERB" http "$JOB" \
  --location "$REGION" \
  --schedule "$SCHEDULE" --time-zone UTC \
  --uri "$RUN_URI" --http-method POST \
  --oauth-service-account-email "$INVOKER_SA"

echo "Deployed. Run it now with: gcloud run jobs execute $JOB --region $REGION"
