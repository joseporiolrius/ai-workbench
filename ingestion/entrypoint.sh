#!/bin/sh
# Run the MOUNTED ingestion source against the baked dependencies. Arguments go to ingest.py,
# e.g. --docs docs/study-guides --collection study_guides_<SHA> --revision <SHA>.
set -eu
W=/workspace
fail() { echo "ingest-entrypoint: ERROR: $*" >&2; exit 2; }
for f in ingestion/ingest.py ingestion/rag.py ingestion/corpus.py ingestion/uv.lock rag-settings.yaml course-artifacts.yaml; do
  [ -r "$W/$f" ] || fail "mounted bundle is missing or unreadable: $W/$f (the Job must mount the release checkout at $W)"
done
baked=$(cat /opt/deps/uv.lock.sha256)
mounted=$(sha256sum "$W/ingestion/uv.lock" | cut -d' ' -f1)
[ "$baked" = "$mounted" ] || fail "mounted ingestion/uv.lock ($mounted) differs from this image's dependencies ($baked): dependencies changed, so build and pin a new ingestion image"
echo "ingest-entrypoint: dependencies uv.lock sha256 $baked; running mounted source from $W"
cd "$W"
exec python ingestion/ingest.py "$@"
