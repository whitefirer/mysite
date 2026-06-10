#!/bin/bash
# List all draft posts in a Hugo content directory
# Usage: ./scripts/list-drafts.sh [content/posts]

POSTS_DIR="${1:-content/posts}"

echo "=== Draft Posts ==="
for f in "$POSTS_DIR"/*/index.md; do
    [ -f "$f" ] || continue
    draft=$(awk '/^draft:/{print $2}' "$f")
    title=$(awk -F'"' '/^title:/{print $2}' "$f")
    slug=$(basename "$(dirname "$f")")
    date=$(awk '/^date:/{print $2}' "$f" | cut -c1-10)
    if [ "$draft" = "true" ]; then
        printf "  %-12s  %s  %s\n" "$date" "$slug" "$title"
    fi
done

echo ""
echo "=== Published Posts ==="
for f in "$POSTS_DIR"/*/index.md; do
    [ -f "$f" ] || continue
    draft=$(awk '/^draft:/{print $2}' "$f")
    if [ "$draft" != "true" ]; then
        title=$(awk -F'"' '/^title:/{print $2}' "$f")
        slug=$(basename "$(dirname "$f")")
        date=$(awk '/^date:/{print $2}' "$f" | cut -c1-10)
        printf "  %-12s  %s  %s\n" "$date" "$slug" "$title"
    fi
done
