#!/usr/bin/env bash
# demo_run.sh — end-to-end demo: upload all sample docs, poll until done, print results
set -euo pipefail

API="http://localhost:8000/api/v1"
SAMPLES="sample_docs"

echo "=== Document Intelligence Platform — Demo Run ==="
echo ""

for pdf in "$SAMPLES"/*.pdf; do
  name=$(basename "$pdf")
  echo "▶ Uploading $name ..."
  resp=$(curl -s -X POST "$API/documents/upload" -F "file=@$pdf")
  doc_id=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['document']['id'])")
  echo "  Document ID: $doc_id"

  # Poll status (up to 60 seconds)
  for i in $(seq 1 12); do
    sleep 5
    status=$(curl -s "$API/documents/$doc_id/status" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
    echo "  Status: $status"
    if [[ "$status" == "completed" || "$status" == "review_required" || "$status" == "failed" ]]; then
      break
    fi
  done

  echo "  Result:"
  curl -s "$API/documents/$doc_id/result" | python3 -m json.tool | head -40
  echo ""
done

echo "=== Pending review tasks ==="
curl -s "$API/reviews/pending" | python3 -m json.tool
