#!/usr/bin/env bash
set -Eeuo pipefail

###############################################################################
# publish-poster.sh
#
# Usage:
#     ./publish-poster.sh poster.png
###############################################################################

[[ $# -eq 1 ]] || {
    echo "Usage: $0 <poster.png>"
    exit 1
}

POSTER="$(realpath "$1")"

[[ -f "$POSTER" ]] || {
    echo "Poster not found:"
    echo "    $POSTER"
    exit 1
}

###############################################################################
# Edit these
###############################################################################

source $1.desc

###############################################################################
# Derive slug
###############################################################################

SLUG="$(
echo "$TITLE" \
| tr '[:upper:]' '[:lower:]' \
| sed 's/[^a-z0-9]/-/g' \
| tr -s '-' \
| sed 's/^-//;s/-$//'
)"

###############################################################################
# Remember where we started
###############################################################################

START_DIR="$(pwd)"

###############################################################################
# Clone if needed
###############################################################################

if [[ -d "$REPO_DIR/.git" ]]; then

    echo "[INFO] Using existing repository."

else

    echo "[INFO] Cloning $REPO"

    gh repo clone "$REPO" "$REPO_DIR"

fi

###############################################################################
# Work only inside cloned repository
###############################################################################

cd "$START_DIR/$REPO_DIR"

###############################################################################
# Create publication directory
###############################################################################

mkdir -p "$SLUG"

cd "$SLUG"

###############################################################################
# Copy poster
###############################################################################

cp "$POSTER" poster.png

###############################################################################
# README
###############################################################################

cat > README.md <<EOF
# $TITLE

$DESCRIPTION
EOF

###############################################################################
# LICENSE
###############################################################################

cat > LICENSE <<EOF
Creative Commons Attribution-NoDerivatives 4.0 International

Copyright © 1993–2026 Abhishek Choudhary

This work is licensed under the Creative Commons Attribution-NoDerivatives 4.0 International License (CC BY-ND 4.0).

You are free to:

- Share — copy and redistribute the material in any medium or format for any purpose, even commercially.

Under the following terms:

- Attribution — You must give appropriate credit, provide a link to the license, and indicate if changes were made.
- NoDerivatives — If you remix, transform, or build upon the material, you may not distribute the modified material.

Full license text:
https://creativecommons.org/licenses/by-nd/4.0/

Any associated code is distributed under
GNU General Public License v3.0; OR
other license specified in the code
EOF

###############################################################################
# CITATION
###############################################################################

cat > CITATION.cff <<EOF
cff-version: 1.2.0
title: "$TITLE"
version: "$VERSION"

authors:
  - family-names: Choudhary
    given-names: Abhishek

license: GPL-3.0
EOF

###############################################################################
# misty.json
###############################################################################

cat > misty.json <<EOF
{
  "title": "$TITLE",
  "version": "$VERSION",

  "upload_type": "$UPLOAD_TYPE",
  "publication_type": "$PUBLICATION_TYPE",

  "description": "$DESCRIPTION",

  "license": "$LICENSE",
  "access_right": "$ACCESS",

  "creators": [
    {
      "name": "$AUTHOR",
      "affiliation": "$AFFILIATION",
      "orcid": "$ORCID"
    }
  ],

  "keywords": [
$(for k in "${KEYWORDS[@]}"; do
    printf '    "%s",\n' "$k"
done | sed '$ s/,$//')
  ],

  "related_identifiers": [],

  "repository": "https://github.com/$REPO"
}
EOF

###############################################################################
# Validate
###############################################################################

echo
echo "[INFO] Validating metadata..."

misty validate -m misty.json

###############################################################################
# Commit
###############################################################################

echo
echo "[INFO] Committing..."

git add .

git commit -m "Add poster: $TITLE" || true

git push

###############################################################################
# Publish
###############################################################################

echo
echo "[INFO] Publishing..."

misty publish \
    -m misty.json \
    -f poster.png \
    --output result.json

###############################################################################
# Timestamp
###############################################################################

echo
echo "[INFO] Timestamping..."

misty ots stamp poster.png

###############################################################################
# Done
###############################################################################

echo
echo "========================================"
echo "Done."
echo
echo "Publication:"
echo "    $SLUG"
echo
echo "Repository:"
echo "    https://github.com/$REPO"
echo
echo "Poster:"
echo "    poster.png"
echo
echo "Metadata:"
echo "    misty.json"
echo
echo "DOI Result:"
echo "    result.json"
echo
echo "Timestamp:"
echo "    poster.png.ots"
echo
echo "========================================"
