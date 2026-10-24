#!/usr/bin/env bash
# Puts the newest test build on the "nightly" pre-release (like Qupil): the tag "nightly" is moved to the commit that
# was built, the AppImage carries build number and commit in its name, older nightly AppImages are removed.
# Usage: bash .github/scripts/publish-nightly.sh dist/Pulsecut-nightly-*-x86_64.AppImage dist/SHA256SUMS
# Needs GH_TOKEN with contents: write, GITHUB_REPOSITORY, GITHUB_SHA, GITHUB_SERVER_URL.
set -euo pipefail
repo="$GITHUB_REPOSITORY"
tag="nightly"
app="$1"
sums="$2"
name="$(basename "$app")"

if ! gh release view "$tag" --repo "$repo" > /dev/null 2>&1; then
    gh release create "$tag" --repo "$repo" --prerelease --target "$GITHUB_SHA" \
        --title "Nightly test build" --notes "Test build of the latest commit on main." || true
fi
gh api -X PATCH "repos/$repo/git/refs/tags/$tag" -f sha="$GITHUB_SHA" -F force=true > /dev/null

for f in "$app" "$sums"; do
    for attempt in 1 2 3; do   # uploads fail now and then (GitHub 5xx)
        if gh release upload "$tag" "$f" --repo "$repo" --clobber; then break; fi
        if [ "$attempt" -eq 3 ]; then exit 1; fi
        sleep 10
    done
done
gh release view "$tag" --repo "$repo" --json assets -q '.assets[].name' | while read -r asset; do
    if [[ "$asset" == Pulsecut-nightly-*-x86_64.AppImage && "$asset" != "$name" ]]; then
        gh release delete-asset "$tag" "$asset" --repo "$repo" -y && echo "Removed $asset"
    fi
done

build="${name#Pulsecut-}"; build="${build%-x86_64.AppImage}"
gh release edit "$tag" --repo "$repo" --prerelease --title "Nightly test build ${build#nightly-}" --notes "$(cat <<NOTES
Automatic test build of the newest commit on \`main\` (commit ${GITHUB_SHA::7}, $(date -u '+%Y-%m-%d %H:%M UTC')), after all tests passed.
There is no stable release yet – the first one will be **1.0.0**.

**Linux x86-64 AppImage** (glibc 2.35+: Ubuntu/Kubuntu 22.04 and newer, Debian 12+, Fedora 36+):

\`\`\`bash
sudo apt install ffmpeg melt
chmod +x $name && ./$name
\`\`\`

The program shows the build in the window title and on the start page (nightly <build> (<commit>)).
Projects of older builds open as they are.

**SHA-256**

\`\`\`
$(cat "$sums")
\`\`\`

Deutsch: Testversion des neuesten Stands – herunterladen, ausführbar machen, starten. Anleitung: [README.de.md](${GITHUB_SERVER_URL}/${repo}/blob/main/README.de.md)
NOTES
)"
echo "Published $name"
